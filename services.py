"""Application services shared by HTTP route modules."""

import json
import multiprocessing
import os
import re
import subprocess
import threading
import time

import boto3
import redis
from botocore.exceptions import ClientError


redis_client = redis.Redis(
    host=os.environ.get("REDIS_HOST", "localhost"),
    port=int(os.environ.get("REDIS_PORT", 6379)),
    decode_responses=True,
)
s3_client = boto3.client("s3")
BUCKET_NAME = "mopa-laser-rasterizer.com"
ABSTRACT_FILTER_NAMES = {
    "none", "wave", "voronoi", "shear", "spiral", "mosaic",
    "crystal", "ripple", "centerline", "tumbler", "shattered",
}
ABSTRACT_PRESET_PREFIX = "abstract_"
HISTORY_SESSION_RE = re.compile(r"^[a-f0-9-]{32,36}$")
HISTORY_TTL_SECONDS = 7 * 24 * 60 * 60
manager = multiprocessing.Manager()
tasks = manager.dict()


def valid_history_session(value):
    value = str(value or "").strip().lower()
    return value if HISTORY_SESSION_RE.fullmatch(value) else None


def normalize_dimension(value, default=0):
    if value is None or str(value).strip() == "":
        return default
    try:
        return max(0, min(1600, int(float(value))))
    except (TypeError, ValueError):
        return default


def add_history_entry(session_id, task_id, source_name, image_preset, abstract_filter):
    if not session_id:
        return
    key = f"history:{session_id}"
    entry = json.dumps({
        "task_id": task_id, "source_name": source_name,
        "image_preset": image_preset,
        # Abstract styles are now submitted as named presets (for example,
        # ``abstract_wave``), so retain their resolved filter name in history.
        "abstract_filter": abstract_filter,
        "created_at": int(time.time()),
    }, separators=(",", ":"))
    pipeline = redis_client.pipeline()
    pipeline.lpush(key, entry)
    pipeline.ltrim(key, 0, 98)
    pipeline.expire(key, HISTORY_TTL_SECONDS)
    pipeline.execute()


def get_history_entries(session_id):
    if not session_id:
        return []
    history_key = f"history:{session_id}"
    entries, stale_records = [], []
    for raw_entry in redis_client.lrange(history_key, 0, 98):
        try:
            entry = json.loads(raw_entry)
        except (TypeError, json.JSONDecodeError):
            stale_records.append(raw_entry)
            continue
        task_id = entry.get("task_id")
        if not task_id or redis_client.get(f"task:{task_id}:status") is None:
            stale_records.append(raw_entry)
            continue
        entries.append({
            "task_id": task_id, "source_name": entry.get("source_name", "processed image"),
            "image_preset": entry.get("image_preset"), "abstract_filter": entry.get("abstract_filter"),
            "created_at": entry.get("created_at"), "status": redis_client.get(f"task:{task_id}:status"),
            "svg_url": f"/download/{task_id}", "lightburn_url": f"/download-lbrn2/{task_id}",
        })
    if stale_records:
        pipeline = redis_client.pipeline()
        for raw_entry in stale_records:
            pipeline.lrem(history_key, 0, raw_entry)
        pipeline.execute()
    return entries


def parse_abstract_filter_parameters(raw_value):
    if not raw_value:
        return {}
    try:
        parameters = json.loads(raw_value)
    except json.JSONDecodeError as error:
        raise ValueError("Abstract filter settings are not valid JSON") from error
    if not isinstance(parameters, dict) or len(parameters) > 20:
        raise ValueError("Abstract filter settings must be a small object")
    clean = {}
    for key, value in parameters.items():
        if not isinstance(key, str) or not key.replace("_", "").isalnum():
            raise ValueError("An abstract filter setting has an invalid name")
        if key == "material" and value in ("metal", "powdercoat"):
            clean[key] = value
        elif key == "transparent" and isinstance(value, bool):
            clean[key] = value
        elif isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Abstract filter setting '{key}' must be numeric")
        else:
            clean[key] = value
    return clean


def upload_local_file(local_file_path, object_key):
    try:
        s3_client.upload_file(local_file_path, BUCKET_NAME, object_key)
    except ClientError as error:
        print(f"Error uploading file: {error}")


def download_s3_file(object_key, local_download_path):
    try:
        s3_client.download_file(BUCKET_NAME, object_key, local_download_path)
    except ClientError as error:
        print(f"Error downloading file: {error}")


def start_disk_cleanup_worker(app, interval_seconds=3600):
    def cleanup_loop():
        time.sleep(10)
        while True:
            try:
                upload_folder = app.config.get("UPLOAD_FOLDER")
                if upload_folder and os.path.exists(upload_folder):
                    for filename in os.listdir(upload_folder):
                        if filename.startswith("."):
                            continue
                        task_id = filename.split("_")[0]
                        if not redis_client.exists(f"task:{task_id}:status"):
                            file_path = os.path.join(upload_folder, filename)
                            if os.path.isfile(file_path):
                                os.remove(file_path)
                                print(f"[Disk-Cleanup] Purged orphaned file: {filename}", flush=True)
            except Exception as error:
                print(f"[Disk-Cleanup] Worker exception: {error}", flush=True)
            time.sleep(interval_seconds)
    threading.Thread(target=cleanup_loop, daemon=True).start()


def long_running_script(task_id, data, image_path, material_settings_path, upload_folder):
    try:
        log_key, status_key = f"task:{task_id}:log", f"task:{task_id}:status"
        redis_client.set(status_key, "processing")
        redis_client.expire(status_key, HISTORY_TTL_SECONDS)
        redis_client.expire(log_key, HISTORY_TTL_SECONDS)
        image_preset = str(data.get("image_preset", "cartoon")).strip().lower()
        abstract_filter = str(data.get("abstract_filter", "none")).strip().lower()
        if image_preset.startswith(ABSTRACT_PRESET_PREFIX):
            abstract_filter = image_preset.removeprefix(ABSTRACT_PRESET_PREFIX)
            image_preset = "abstract"
        if image_preset != "abstract" or abstract_filter not in ABSTRACT_FILTER_NAMES:
            abstract_filter = "none"
        process = subprocess.Popen([
            "python", "-u", "lib/Material_Library.py", image_path,
            os.path.join(upload_folder, tasks[f"{task_id}_filename"]),
            str(data.get("pixel_square_mm", "1")), str(normalize_dimension(data.get("new_width"))),
            str(normalize_dimension(data.get("new_height"))), material_settings_path,
            str(data.get("colors", "")), image_preset, abstract_filter,
            json.dumps(parse_abstract_filter_parameters(data.get("abstract_filter_parameters", "{}")), separators=(",", ":")),
        ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        current_line = []
        while True:
            char = process.stdout.read(1)
            if not char and process.poll() is not None:
                break
            if char:
                if char in ("\n", "\r"):
                    line = "".join(current_line).strip()
                    if line:
                        print(f"[Task {task_id}] {line}", flush=True)
                        redis_client.rpush(log_key, line)
                    current_line = []
                else:
                    current_line.append(char)
        line = "".join(current_line).strip()
        if line:
            print(f"[Task {task_id}] {line}", flush=True)
            redis_client.rpush(log_key, line)
        redis_client.set(status_key, "completed" if process.wait() == 0 else "failed")
    except Exception as error:
        print(f"[Thread-{task_id}] Exception: {error}", flush=True)
        tasks[f"{task_id}_status"] = "failed"
        tasks[f"{task_id}_error"] = str(error)


def cleanup_redis_inflight(task_id):
    download_key = f"task:{task_id}:downloads"
    if redis_client.incr(download_key) == 1:
        redis_client.expire(download_key, HISTORY_TTL_SECONDS)
    redis_client.expire(f"task:{task_id}:status", HISTORY_TTL_SECONDS)
    redis_client.expire(f"task:{task_id}:log", HISTORY_TTL_SECONDS)
