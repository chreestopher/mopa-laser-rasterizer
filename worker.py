"""Dedicated Redis-backed raster worker for Kubernetes deployments."""

import json
import os
import signal
import threading
import time

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from services import (
    HISTORY_TTL_SECONDS,
    RASTER_JOB_PROCESSING_QUEUE,
    RASTER_JOB_QUEUE,
    download_task_artifact,
    long_running_script,
    redis_client,
    secure_artifact_name,
)


stop_requested = False
WORKER_ID = f"{os.environ.get('HOSTNAME', 'raster-worker')}:{os.getpid()}"
LEASE_SECONDS = max(30, int(os.environ.get("RASTER_JOB_LEASE_SECONDS", "90")))
HEARTBEAT_SECONDS = max(
    5,
    min(int(os.environ.get("RASTER_JOB_HEARTBEAT_SECONDS", "20")), LEASE_SECONDS // 2),
)
RECOVERY_INTERVAL_SECONDS = max(
    5, int(os.environ.get("RASTER_JOB_RECOVERY_INTERVAL_SECONDS", "15"))
)
RECOVERY_LOCK_SECONDS = max(
    5, int(os.environ.get("RASTER_JOB_RECOVERY_LOCK_SECONDS", "10"))
)
RECOVERY_LOCK_KEY = "rasterizer:jobs:recovery-lock"

REFRESH_LEASE = redis_client.register_script(
    """
    if redis.call('GET', KEYS[1]) == ARGV[1] then
        return redis.call('EXPIRE', KEYS[1], ARGV[2])
    end
    return 0
    """
)

ACKNOWLEDGE_JOB = redis_client.register_script(
    """
    if redis.call('GET', KEYS[3]) ~= ARGV[2] then
        return 0
    end
    local removed = redis.call('LREM', KEYS[1], 1, ARGV[1])
    redis.call('DEL', KEYS[3])
    return removed
    """
)

RECOVER_STALE_JOB = redis_client.register_script(
    """
    if redis.call('EXISTS', KEYS[3]) == 1 then
        return 0
    end
    local removed = redis.call('LREM', KEYS[1], 1, ARGV[1])
    if removed == 0 then
        return -1
    end
    local status = redis.call('GET', KEYS[4])
    if status == 'completed' or status == 'failed' then
        return 2
    end
    redis.call('RPUSH', KEYS[2], ARGV[1])
    redis.call('SET', KEYS[4], 'pending', 'EX', ARGV[2])
    redis.call('RPUSH', KEYS[5], ARGV[3])
    redis.call('EXPIRE', KEYS[5], ARGV[2])
    return 1
    """
)


def request_stop(_signal_number, _frame):
    global stop_requested
    stop_requested = True
    print("[Raster-Worker] Shutdown requested; finishing the active job.", flush=True)


def lease_key(task_id):
    return f"rasterizer:job:{task_id}:lease"


def payload_task_id(raw_payload):
    try:
        return str(json.loads(raw_payload).get("task_id", ""))
    except (TypeError, json.JSONDecodeError):
        return ""


def recover_stale_jobs():
    """Requeue only processing entries whose owning worker lease expired."""
    if not redis_client.set(
        RECOVERY_LOCK_KEY, WORKER_ID, nx=True, ex=RECOVERY_LOCK_SECONDS
    ):
        return
    recovered = 0
    terminal = 0
    for raw_payload in redis_client.lrange(RASTER_JOB_PROCESSING_QUEUE, 0, -1):
        task_id = payload_task_id(raw_payload)
        if not task_id:
            continue
        result = int(RECOVER_STALE_JOB(
            keys=[
                RASTER_JOB_PROCESSING_QUEUE,
                RASTER_JOB_QUEUE,
                lease_key(task_id),
                f"task:{task_id}:status",
                f"task:{task_id}:log",
            ],
            args=[
                raw_payload,
                HISTORY_TTL_SECONDS,
                "Worker lease expired; job safely returned to the queue.",
            ],
        ))
        recovered += result == 1
        terminal += result == 2
    if recovered:
        print(f"[Raster-Worker] Requeued {recovered} stale job(s).", flush=True)
    if terminal:
        print(
            f"[Raster-Worker] Removed {terminal} completed/failed stale queue entry(s).",
            flush=True,
        )


def maintain_lease(task_id, heartbeat_stop):
    """Renew one claimed job lease until processing or ownership ends."""
    key = lease_key(task_id)
    while not heartbeat_stop.wait(HEARTBEAT_SECONDS):
        try:
            renewed = REFRESH_LEASE(
                keys=[key], args=[WORKER_ID, LEASE_SECONDS]
            )
            if not renewed:
                print(
                    f"[Raster-Worker] Lost lease ownership for job {task_id}.",
                    flush=True,
                )
                return
        except (RedisTimeoutError, RedisConnectionError) as error:
            print(
                f"[Raster-Worker] Lease heartbeat interrupted for {task_id}: {error}",
                flush=True,
            )


def acknowledge_job(raw_payload, task_id):
    while True:
        try:
            return bool(ACKNOWLEDGE_JOB(
                keys=[
                    RASTER_JOB_PROCESSING_QUEUE,
                    RASTER_JOB_QUEUE,
                    lease_key(task_id),
                ],
                args=[raw_payload, WORKER_ID],
            ))
        except (RedisTimeoutError, RedisConnectionError) as error:
            print(
                f"[Raster-Worker] Redis acknowledgement interrupted; retrying: {error}",
                flush=True,
            )
            time.sleep(1)


def record_job_failure(task_id, error):
    """Persist a terminal failure without letting a Redis blip kill the worker."""
    for attempt in range(1, 4):
        try:
            pipeline = redis_client.pipeline()
            pipeline.set(
                f"task:{task_id}:status", "failed", ex=HISTORY_TTL_SECONDS
            )
            pipeline.rpush(f"task:{task_id}:log", f"Raster worker failed: {error}")
            pipeline.expire(f"task:{task_id}:log", HISTORY_TTL_SECONDS)
            pipeline.execute()
            return
        except (RedisTimeoutError, RedisConnectionError) as redis_error:
            print(
                f"[Raster-Worker] Could not persist failure for {task_id} "
                f"(attempt {attempt}/3): {redis_error}",
                flush=True,
            )
            time.sleep(1)


def run_job(raw_payload, upload_folder):
    payload = json.loads(raw_payload)
    task_id = str(payload["task_id"])
    if payload.get("job_type") == "holographic_artwork":
        return run_holographic_artwork_job(payload, upload_folder)
    image_name = secure_artifact_name(payload.get("image_name"), "image")
    material_name = secure_artifact_name(payload.get("material_name"), "materials.clb")
    image_path = os.path.join(upload_folder, f"{task_id}_{image_name}")
    material_path = os.path.join(upload_folder, f"{task_id}_material_{material_name}")
    os.makedirs(upload_folder, exist_ok=True)
    redis_client.rpush(f"task:{task_id}:log", "Dedicated raster worker claimed the job.")
    download_task_artifact(payload["image_key"], image_path)
    download_task_artifact(payload["material_key"], material_path)
    long_running_script(
        task_id,
        payload.get("data") or {},
        image_path,
        material_path,
        upload_folder,
        payload.get("user_id"),
        payload.get("output_name"),
    )


def run_holographic_artwork_job(payload, upload_folder):
    """Materialize a queued Holographic Artwork export outside the web pod."""
    from werkzeug.datastructures import FileStorage
    from routes.holographic import _build_holographic_exports

    task_id = str(payload["task_id"])
    log_key = f"task:{task_id}:log"
    redis_client.set(f"task:{task_id}:status", "processing", ex=HISTORY_TTL_SECONDS)
    redis_client.rpush(log_key, "Dedicated worker claimed the Holographic Artwork job.")
    names = {
        "artwork": secure_artifact_name(payload.get("artwork_name"), "artwork.png"),
        "recipe": secure_artifact_name(payload.get("recipe_name"), "recipe.json"),
        "material": secure_artifact_name(payload.get("material_name"), "materials.clb"),
    }
    paths = {name: os.path.join(upload_folder, f"{task_id}_{filename}") for name, filename in names.items()}
    os.makedirs(upload_folder, exist_ok=True)
    redis_client.rpush(log_key, "Downloading artwork, Holographic Recipe, and Material Library inputs.")
    download_task_artifact(payload["artwork_key"], paths["artwork"])
    download_task_artifact(payload["recipe_key"], paths["recipe"])
    download_task_artifact(payload["material_key"], paths["material"])
    redis_client.rpush(log_key, "Building calibrated holographic grating layers.")
    redis_client.rpush(log_key, f"Cut mode: {payload.get('cut_mode', 'setting')}.")
    with open(paths["artwork"], "rb") as artwork_stream, open(paths["recipe"], encoding="utf-8") as recipe_file:
        artwork = FileStorage(stream=artwork_stream, filename=names["artwork"])
        svg_name, lbrn_name, metadata_name, width, height, rectangle_count = _build_holographic_exports(
            upload_folder, artwork, recipe_file, paths["material"],
            int(payload.get("max_dimension", 96)), float(payload.get("pixel_mm", .5)),
            preserve_black_outlines=bool(payload.get("preserve_black_outlines")), task_id=task_id,
            cut_mode=str(payload.get("cut_mode", "setting")),
        )
    result = {
        "source_width": width, "source_height": height, "rectangle_count": rectangle_count,
        "svg_url": f"/holographic-etching/download/{svg_name}",
        "lightburn_url": f"/holographic-etching/download/{lbrn_name}",
        "metadata_url": f"/holographic-etching/download/{metadata_name}",
    }
    redis_client.set(f"holographic-artwork-result:{task_id}", json.dumps(result), ex=HISTORY_TTL_SECONDS)
    redis_client.set(f"task:{task_id}:status", "completed", ex=HISTORY_TTL_SECONDS)
    redis_client.rpush(log_key, f"Holographic Artwork complete: {rectangle_count} vector rectangles ready.")
    redis_client.expire(log_key, HISTORY_TTL_SECONDS)


def main():
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    upload_folder = os.environ.get("UPLOAD_FOLDER", "/tmp/uploads")
    last_recovery = 0.0
    print("[Raster-Worker] Waiting for jobs.", flush=True)
    while not stop_requested:
        if time.monotonic() - last_recovery >= RECOVERY_INTERVAL_SECONDS:
            try:
                recover_stale_jobs()
            except (RedisTimeoutError, RedisConnectionError) as error:
                print(f"[Raster-Worker] Stale-job recovery interrupted: {error}", flush=True)
            last_recovery = time.monotonic()
        try:
            raw_payload = redis_client.brpoplpush(
                RASTER_JOB_QUEUE, RASTER_JOB_PROCESSING_QUEUE, timeout=5
            )
        except RedisTimeoutError:
            # Some Redis/socket configurations surface an expired blocking
            # queue read as a socket timeout instead of returning ``None``.
            # This is a normal idle poll; reconnect on the next iteration
            # without filling the worker log with non-actionable warnings.
            continue
        except RedisConnectionError as error:
            print(f"[Raster-Worker] Redis queue wait interrupted; retrying: {error}", flush=True)
            time.sleep(1)
            continue
        if raw_payload is None:
            continue
        task_id = payload_task_id(raw_payload)
        if not task_id:
            print("[Raster-Worker] Discarding malformed queue payload.", flush=True)
            redis_client.lrem(RASTER_JOB_PROCESSING_QUEUE, 1, raw_payload)
            continue
        try:
            owns_job = redis_client.set(
                lease_key(task_id), WORKER_ID, nx=True, ex=LEASE_SECONDS
            )
        except (RedisTimeoutError, RedisConnectionError) as error:
            print(f"[Raster-Worker] Could not acquire lease for {task_id}: {error}", flush=True)
            time.sleep(1)
            continue
        if not owns_job:
            # A duplicate payload may exist, but another live worker owns the
            # task ID. Remove only this claimed list entry and do not run it.
            redis_client.lrem(RASTER_JOB_PROCESSING_QUEUE, 1, raw_payload)
            print(f"[Raster-Worker] Skipped duplicate live job {task_id}.", flush=True)
            continue
        heartbeat_stop = threading.Event()
        heartbeat = threading.Thread(
            target=maintain_lease,
            args=(task_id, heartbeat_stop),
            name=f"lease-{task_id}",
            daemon=True,
        )
        heartbeat.start()
        try:
            run_job(raw_payload, upload_folder)
        except Exception as error:
            print(f"[Raster-Worker] Job {task_id or '(unknown)'} failed: {error}", flush=True)
            record_job_failure(task_id, error)
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=HEARTBEAT_SECONDS + 1)
            if not acknowledge_job(raw_payload, task_id):
                print(
                    f"[Raster-Worker] Did not acknowledge {task_id}: lease ownership was lost.",
                    flush=True,
                )
    print("[Raster-Worker] Shutdown complete.", flush=True)


if __name__ == "__main__":
    main()
