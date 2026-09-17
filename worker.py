"""Dedicated Redis-backed raster worker for Kubernetes deployments."""

import argparse
import json
import os
import signal
import threading
import time
from datetime import datetime
from urllib.request import urlopen

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from job_runtime import DynamoJobRuntime, RedisJobRuntime

from services import (
    HISTORY_TTL_SECONDS,
    RASTER_JOB_PROCESSING_QUEUE,
    RASTER_JOB_PAYLOAD_PREFIX,
    RASTER_JOB_QUEUE,
    download_task_artifact,
    long_running_script,
    job_runtime,
    sync_job_runtime,
    redis_client,
    secure_artifact_name,
    summarize_job_failure,
    update_user_job,
    upload_task_artifact,
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


def register_cloudwatch_log_stream(runtime, task_id):
    """Record this one-shot ECS task's awslogs stream for authenticated reads."""
    if not isinstance(runtime, DynamoJobRuntime):
        return
    metadata_uri = os.environ.get("ECS_CONTAINER_METADATA_URI_V4", "").rstrip("/")
    log_group = os.environ.get("CLOUDWATCH_LOG_GROUP", "").strip()
    if not metadata_uri or not log_group:
        print(f"[Raster-Worker] CloudWatch stream metadata is unavailable for {task_id}.", flush=True)
        return
    try:
        with urlopen(f"{metadata_uri}/task", timeout=3) as response:
            metadata = json.load(response)
        ecs_task_id = str(metadata.get("TaskARN") or "").rsplit("/", 1)[-1]
        if not ecs_task_id:
            raise ValueError("ECS task metadata did not contain a TaskARN")
        prefix = os.environ.get("CLOUDWATCH_LOG_STREAM_PREFIX", "worker").strip("/") or "worker"
        container = os.environ.get("CLOUDWATCH_LOG_CONTAINER_NAME", "raster-worker").strip("/") or "raster-worker"
        runtime.set_cloudwatch_log_stream(task_id, log_group, f"{prefix}/{container}/{ecs_task_id}")
    except Exception as error:
        print(f"[Raster-Worker] Could not register CloudWatch logs for {task_id}: {error}", flush=True)

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
    message = summarize_job_failure(error)
    try:
        update_user_job(task_id, "failed", error_message=message)
    except Exception as durable_error:
        print(f"[Raster-Worker] Could not persist durable failure for {task_id}: {durable_error}", flush=True)
    try:
        job_runtime.append_log(task_id, f"ERROR: Raster worker failed: {error}")
    except Exception as log_error:
        print(f"[Raster-Worker] Could not persist failure log for {task_id}: {log_error}", flush=True)
    job_runtime.set_status(task_id, "failed", error=message)


def run_job(raw_payload, upload_folder):
    payload = json.loads(raw_payload)
    task_id = str(payload["task_id"])
    if payload.get("job_type") == "holographic_artwork":
        return run_holographic_artwork_job(payload, upload_folder)
    image_name = secure_artifact_name(payload.get("image_name"), "image")
    svg_only = str((payload.get("data") or {}).get("svg_only", "false")).lower() in ("true", "1", "yes", "on")
    material_name = secure_artifact_name(payload.get("material_name"), "materials.clb")
    image_path = os.path.join(upload_folder, f"{task_id}_{image_name}")
    material_path = os.path.join(upload_folder, f"{task_id}_material_{material_name}")
    os.makedirs(upload_folder, exist_ok=True)
    job_runtime.append_log(task_id, "Dedicated raster worker claimed the job.")
    job_runtime.append_log(task_id, "Downloading the source image from durable storage.")
    download_task_artifact(payload["image_key"], image_path)
    job_runtime.append_log(task_id, "Source image download complete.")
    if not svg_only:
        job_runtime.append_log(task_id, "Downloading the selected Material Library.")
        download_task_artifact(payload["material_key"], material_path)
        job_runtime.append_log(task_id, "Material Library download complete.")
    long_running_script(
        task_id,
        payload.get("data") or {},
        image_path,
        None if svg_only else material_path,
        upload_folder,
        payload.get("user_id"),
        payload.get("output_name"),
        guest_job=payload.get("guest_job") is True,
        guest_quota_visitor=str(payload.get("guest_quota_visitor") or ""),
        guest_quota_day=str(payload.get("guest_quota_day") or ""),
        guest_daily_job_limit=int(payload.get("guest_daily_job_limit") or 0),
    )


def run_holographic_artwork_job(payload, upload_folder):
    """Materialize a queued Fauxlographic Artwork export outside the web pod."""
    from werkzeug.datastructures import FileStorage
    from routes.fauxlographic import _build_holographic_exports

    task_id = str(payload["task_id"])
    def progress(message):
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
        job_runtime.append_log(task_id, line)

    job_runtime.set_status(task_id, "processing")
    progress("Dedicated worker claimed the Fauxlographic Artwork job.")
    names = {
        "artwork": secure_artifact_name(payload.get("artwork_name"), "artwork.png"),
        "recipe": secure_artifact_name(payload.get("recipe_name"), "recipe.json"),
        "material": secure_artifact_name(payload.get("material_name"), "materials.clb"),
    }
    paths = {name: os.path.join(upload_folder, f"{task_id}_{filename}") for name, filename in names.items()}
    os.makedirs(upload_folder, exist_ok=True)
    progress("[Input download 1/3] START: downloading artwork.")
    download_task_artifact(payload["artwork_key"], paths["artwork"])
    progress("[Input download 1/3] DONE: downloaded artwork.")
    progress("[Input download 2/3] START: downloading Fauxlographic Palette.")
    download_task_artifact(payload["recipe_key"], paths["recipe"])
    progress("[Input download 2/3] DONE: downloaded Fauxlographic Palette.")
    progress("[Input download 3/3] START: downloading Material Library.")
    download_task_artifact(payload["material_key"], paths["material"])
    progress("[Input download 3/3] DONE: downloaded Material Library.")
    progress(f"Building calibrated fauxlographic grating layers; cut mode {payload.get('cut_mode', 'setting')}.")
    with open(paths["artwork"], "rb") as artwork_stream, open(paths["recipe"], encoding="utf-8") as recipe_file:
        artwork = FileStorage(stream=artwork_stream, filename=names["artwork"])
        svg_name, lbrn_name, width, height, rectangle_count = _build_holographic_exports(
            upload_folder, artwork, recipe_file, paths["material"],
            int(payload.get("max_dimension", 96)), float(payload.get("pixel_mm", .5)),
            preserve_black_outlines=bool(payload.get("preserve_black_outlines")), task_id=task_id,
            cut_mode=str(payload.get("cut_mode", "setting")),
            progress=progress, store_artifacts=False,
            selected_recipe_indexes=payload.get("selected_recipe_indexes"),
            embedded_material_name=payload.get("embedded_material_name"),
            embedded_black_setting_name=payload.get("embedded_black_setting_name"),
        )
    result = {
        "source_width": width, "source_height": height, "rectangle_count": rectangle_count,
        "svg_url": f"/holographic-etching/download/{svg_name}",
        "lightburn_url": f"/holographic-etching/download/{lbrn_name}",
    }
    output_names = (svg_name, lbrn_name)
    output_keys = []
    progress("[Durable output upload 1/1] START: registering 2/2 outputs with job history.")
    for output_name in output_names:
        output_key = upload_task_artifact(
            task_id, os.path.join(upload_folder, output_name), category="outputs",
            user_id=payload.get("user_id"),
        )
        if output_key:
            output_keys.append(output_key)
    progress(f"[Durable output upload 1/1] DONE: registered {len(output_keys)}/2 outputs with job history.")
    update_user_job(task_id, "completed", output_keys=output_keys)
    if isinstance(job_runtime, RedisJobRuntime):
        redis_client.set(f"holographic-artwork-result:{task_id}", json.dumps(result), ex=HISTORY_TTL_SECONDS)
    job_runtime.set_status(task_id, "completed")
    progress(f"Fauxlographic Artwork complete: {rectangle_count}/{rectangle_count} vector rectangles ready.")


def process_owned_job(raw_payload, task_id, upload_folder):
    """Run and acknowledge one job whose lease is already owned by this process."""
    heartbeat_stop = threading.Event()
    heartbeat = threading.Thread(
        target=maintain_lease,
        args=(task_id, heartbeat_stop),
        name=f"lease-{task_id}",
        daemon=True,
    )
    heartbeat.start()
    succeeded = True
    try:
        run_job(raw_payload, upload_folder)
    except Exception as error:
        succeeded = False
        print(f"[Raster-Worker] Job {task_id} failed: {error}", flush=True)
        record_job_failure(task_id, error)
    finally:
        heartbeat_stop.set()
        heartbeat.join(timeout=HEARTBEAT_SECONDS + 1)
        if not acknowledge_job(raw_payload, task_id):
            print(
                f"[Raster-Worker] Did not acknowledge {task_id}: lease ownership was lost.",
                flush=True,
            )
    return succeeded


def run_task_by_id(task_id, upload_folder):
    """Process exactly one persisted job envelope and return a process exit code."""
    runtime = sync_job_runtime(redis_client)
    register_cloudwatch_log_stream(runtime, task_id)
    if isinstance(runtime, RedisJobRuntime):
        if redis_client.get(f"task:{task_id}:status") == "completed":
            print(f"[Raster-Worker] Task {task_id} is already complete; nothing to do.", flush=True)
            return 0
        raw_payload = redis_client.get(f"{RASTER_JOB_PAYLOAD_PREFIX}{task_id}")
        if raw_payload is None or payload_task_id(raw_payload) != task_id:
            print(f"[Raster-Worker] No valid persisted payload exists for task {task_id}.", flush=True)
            return 2
        if not redis_client.set(lease_key(task_id), WORKER_ID, nx=True, ex=LEASE_SECONDS):
            print(f"[Raster-Worker] Task {task_id} is already owned by another worker.", flush=True)
            return 3
        pipeline = redis_client.pipeline()
        pipeline.lrem(RASTER_JOB_QUEUE, 0, raw_payload)
        pipeline.lrem(RASTER_JOB_PROCESSING_QUEUE, 0, raw_payload)
        pipeline.rpush(RASTER_JOB_PROCESSING_QUEUE, raw_payload)
        pipeline.execute()
        print(f"[Raster-Worker] Running one-shot task {task_id}.", flush=True)
        return 0 if process_owned_job(raw_payload, task_id, upload_folder) else 1
    durable_status = str(runtime.status(task_id) or "").lower()
    if durable_status in {"completed", "failed", "cancelled"}:
        print(
            f"[Raster-Worker] Task {task_id} is already {durable_status}; nothing to do.",
            flush=True,
        )
        return 0
    payload = runtime.payload(task_id)
    if payload is None:
        print(f"[Raster-Worker] No persisted payload exists for task {task_id}.", flush=True)
        return 2
    if str(payload.get("task_id", "")) != task_id:
        print(f"[Raster-Worker] Persisted payload does not match task {task_id}.", flush=True)
        return 2
    if not runtime.acquire_lease(task_id, WORKER_ID, LEASE_SECONDS):
        print(f"[Raster-Worker] Task {task_id} is already owned by another worker.", flush=True)
        return 3

    print(f"[Raster-Worker] Running one-shot task {task_id}.", flush=True)
    heartbeat_stop = threading.Event()
    def refresh_runtime_lease():
        while not heartbeat_stop.wait(HEARTBEAT_SECONDS):
            if not runtime.refresh_lease(task_id, WORKER_ID, LEASE_SECONDS):
                print(f"[Raster-Worker] Lost lease ownership for job {task_id}.", flush=True)
                return
    heartbeat = threading.Thread(target=refresh_runtime_lease, daemon=True)
    heartbeat.start()
    succeeded = True
    try:
        run_job(json.dumps(payload, separators=(",", ":"), default=str), upload_folder)
    except Exception as error:
        succeeded = False
        print(f"[Raster-Worker] Job {task_id} failed: {error}", flush=True)
        record_job_failure(task_id, error)
    finally:
        heartbeat_stop.set()
        heartbeat.join(timeout=HEARTBEAT_SECONDS + 1)
        runtime.release_lease(task_id, WORKER_ID)
    return 0 if succeeded else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run raster jobs from Redis.")
    parser.add_argument(
        "--task-id",
        help="Process exactly one persisted task envelope and exit (for ECS/Fargate).",
    )
    args = parser.parse_args(argv)
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    upload_folder = os.environ.get("UPLOAD_FOLDER", "/tmp/uploads")
    if args.task_id:
        return run_task_by_id(str(args.task_id), upload_folder)
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
        process_owned_job(raw_payload, task_id, upload_folder)
    print("[Raster-Worker] Shutdown complete.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
