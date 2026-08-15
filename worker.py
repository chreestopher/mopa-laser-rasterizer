"""Dedicated Redis-backed raster worker for Kubernetes deployments."""

import json
import os
import signal
import time

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from services import (
    RASTER_JOB_PROCESSING_QUEUE,
    RASTER_JOB_QUEUE,
    download_task_artifact,
    long_running_script,
    redis_client,
    secure_artifact_name,
)


stop_requested = False


def request_stop(_signal_number, _frame):
    global stop_requested
    stop_requested = True
    print("[Raster-Worker] Shutdown requested; finishing the active job.", flush=True)


def recover_interrupted_jobs():
    recovered = 0
    while True:
        payload = redis_client.rpoplpush(RASTER_JOB_PROCESSING_QUEUE, RASTER_JOB_QUEUE)
        if payload is None:
            break
        recovered += 1
    if recovered:
        print(f"[Raster-Worker] Requeued {recovered} interrupted job(s).", flush=True)


def run_job(raw_payload, upload_folder):
    payload = json.loads(raw_payload)
    task_id = str(payload["task_id"])
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


def main():
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    upload_folder = os.environ.get("UPLOAD_FOLDER", "/tmp/uploads")
    recover_interrupted_jobs()
    print("[Raster-Worker] Waiting for jobs.", flush=True)
    while not stop_requested:
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
        try:
            run_job(raw_payload, upload_folder)
        except Exception as error:
            try:
                task_id = str(json.loads(raw_payload).get("task_id", ""))
            except (TypeError, json.JSONDecodeError):
                task_id = ""
            print(f"[Raster-Worker] Job {task_id or '(unknown)'} failed: {error}", flush=True)
            if task_id:
                redis_client.set(f"task:{task_id}:status", "failed", ex=7 * 24 * 60 * 60)
                redis_client.rpush(f"task:{task_id}:log", f"Raster worker failed: {error}")
        finally:
            while True:
                try:
                    redis_client.lrem(RASTER_JOB_PROCESSING_QUEUE, 1, raw_payload)
                    break
                except (RedisTimeoutError, RedisConnectionError) as error:
                    print(
                        f"[Raster-Worker] Redis acknowledgement interrupted; retrying: {error}",
                        flush=True,
                    )
                    time.sleep(1)
    print("[Raster-Worker] Shutdown complete.", flush=True)


if __name__ == "__main__":
    main()
