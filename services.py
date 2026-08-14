"""Application services shared by HTTP route modules."""

import json
import base64
import glob
import multiprocessing
import os
import re
import subprocess
import threading
import time
import uuid
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import boto3
import redis
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key


AWS_REGION = os.environ.get("AWS_REGION", "us-east-2").strip()
redis_client = redis.Redis(
    host=os.environ.get("REDIS_HOST", "localhost"),
    port=int(os.environ.get("REDIS_PORT", 6379)),
    decode_responses=True,
)
s3_client = boto3.client("s3", region_name=AWS_REGION)
S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME", "").strip()
DYNAMODB_TABLE_NAME = os.environ.get("DYNAMODB_TABLE_NAME", "").strip()
ABSTRACT_FILTER_NAMES = {
    "none", "wave", "voronoi", "shear", "spiral", "mosaic",
    "crystal", "ripple", "centerline", "glitch", "shattered", "deep_fryer",
}
ABSTRACT_PRESET_PREFIX = "abstract_"
HISTORY_SESSION_RE = re.compile(r"^[a-f0-9-]{32,36}$")
HISTORY_TTL_SECONDS = 7 * 24 * 60 * 60
DAILY_JOB_LIMIT = max(1, int(os.environ.get("DAILY_JOB_LIMIT", "3")))
manager = multiprocessing.Manager()
tasks = manager.dict()


def account_table():
    """Return the optional durable account-data table without affecting guests."""
    if not DYNAMODB_TABLE_NAME:
        return None
    return boto3.resource("dynamodb", region_name=AWS_REGION).Table(DYNAMODB_TABLE_NAME)


def _dynamodb_values(value):
    """DynamoDB resources require Decimal rather than Python float values."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {key: _dynamodb_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_dynamodb_values(item) for item in value]
    return value


def _json_values(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _json_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_values(item) for item in value]
    return value


def get_user_preferences(user_id):
    table = account_table()
    if not table or not user_id:
        return {}
    try:
        item = table.get_item(Key={"pk": f"USER#{user_id}", "sk": "PREFERENCES"}).get("Item", {})
    except ClientError as error:
        raise RuntimeError("Could not load account preferences.") from error
    preferences = item.get("preferences", {})
    return _json_values(preferences) if isinstance(preferences, dict) else {}


def save_user_preferences(user_id, preferences):
    table = account_table()
    if not table:
        raise RuntimeError("Account storage is not configured.")
    if not user_id:
        raise ValueError("An authenticated account is required.")
    table.put_item(Item={
        "pk": f"USER#{user_id}",
        "sk": "PREFERENCES",
        "preferences": _dynamodb_values(preferences),
        "updated_at": int(time.time()),
    })


def list_user_material_libraries(user_id):
    table = account_table()
    if not table or not user_id:
        return []
    try:
        response = table.query(
            KeyConditionExpression=Key("pk").eq(f"USER#{user_id}") & Key("sk").begins_with("MATERIAL#"),
            ScanIndexForward=False,
        )
    except ClientError as error:
        raise RuntimeError("Could not load saved Material Libraries.") from error
    return [_json_values(item) for item in response.get("Items", [])]


def get_user_material_library(user_id, library_id):
    table = account_table()
    if not table or not user_id or not library_id:
        return None
    try:
        item = table.get_item(Key={"pk": f"USER#{user_id}", "sk": f"MATERIAL#{library_id}"}).get("Item")
    except ClientError as error:
        raise RuntimeError("Could not load the saved Material Library.") from error
    return _json_values(item) if item else None


def save_user_material_library(user_id, local_file_path, material_name=""):
    """Store an uploaded LightBurn library once under its Cognito owner."""
    table = account_table()
    if not table or not S3_BUCKET_NAME:
        raise RuntimeError("Account Material Library storage is not configured.")
    library_id = str(uuid.uuid4())
    filename = os.path.basename(local_file_path)
    s3_key = f"users/{user_id}/materials/{library_id}/{filename}"
    try:
        s3_client.upload_file(local_file_path, S3_BUCKET_NAME, s3_key)
        table.put_item(Item={
            "pk": f"USER#{user_id}",
            "sk": f"MATERIAL#{library_id}",
            "library_id": library_id,
            "name": filename,
            "material_name": str(material_name or "").strip()[:160],
            "s3_key": s3_key,
            "created_at": int(time.time()),
        })
    except ClientError as error:
        raise RuntimeError("Could not save the Material Library to this account.") from error
    return {"library_id": library_id, "name": filename, "material_name": str(material_name or "").strip()}


def download_user_material_library(library, local_path):
    if not library or not library.get("s3_key"):
        raise RuntimeError("Saved Material Library is unavailable.")
    try:
        s3_client.download_file(S3_BUCKET_NAME, library["s3_key"], local_path)
    except ClientError as error:
        raise RuntimeError("Could not retrieve the saved Material Library.") from error


def record_user_job(user_id, task_id, source_name, image_preset, abstract_filter, material_name, run_parameters):
    """Write both an ordered user-history record and a direct owner lookup."""
    table = account_table()
    if not table or not user_id:
        return
    created_at = int(time.time())
    history_item = {
        "pk": f"USER#{user_id}", "sk": f"JOB#{created_at:010d}#{task_id}",
        "task_id": task_id, "source_name": source_name,
        "image_preset": image_preset, "abstract_filter": abstract_filter,
        "material_name": material_name, "run_parameters": _dynamodb_values(run_parameters or {}),
        "created_at": created_at,
    }
    owner_item = {"pk": f"JOB#{task_id}", "sk": "OWNER", "user_id": user_id, "created_at": created_at}
    try:
        with table.batch_writer() as batch:
            batch.put_item(Item=history_item)
            batch.put_item(Item=owner_item)
    except ClientError as error:
        raise RuntimeError("Could not record this job in the account history.") from error


def get_user_job_history(user_id, limit=100):
    table = account_table()
    if not table or not user_id:
        return []
    try:
        response = table.query(
            KeyConditionExpression=Key("pk").eq(f"USER#{user_id}") & Key("sk").begins_with("JOB#"),
            ScanIndexForward=False, Limit=limit,
        )
    except ClientError as error:
        raise RuntimeError("Could not load account job history.") from error
    entries = []
    for item in response.get("Items", []):
        entry = _json_values(item)
        task_id = entry.get("task_id")
        if not task_id:
            continue
        stored_status = redis_client.get(f"task:{task_id}:status")
        # Keep account history consistent with S3 lifecycle/manual cleanup,
        # just as the guest history panel already does.
        if not stored_status and not task_artifacts_exist(task_id):
            continue
        entry.update({
            "status": stored_status or "expired",
            "svg_url": f"/download/{task_id}", "lightburn_url": f"/download-lbrn2/{task_id}",
        })
        entry["reuse_url"] = reuse_settings_url(entry)
        entries.append(entry)
    return entries


def get_job_owner(task_id):
    table = account_table()
    if not table or not task_id:
        return None
    try:
        item = table.get_item(Key={"pk": f"JOB#{task_id}", "sk": "OWNER"}).get("Item") or {}
    except ClientError as error:
        raise RuntimeError("Could not verify job ownership.") from error
    return item.get("user_id")


def valid_history_session(value):
    value = str(value or "").strip().lower()
    return value if HISTORY_SESSION_RE.fullmatch(value) else None


def claim_daily_job(user_id):
    """Atomically claim one authenticated user's daily job allowance."""
    now = datetime.now(timezone.utc)
    day_key = now.strftime("%Y-%m-%d")
    key = f"quota:{user_id}:{day_key}"
    used = redis_client.incr(key)
    if used == 1:
        next_day = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        redis_client.expire(key, max(1, int((next_day - now).total_seconds())))
    if used > DAILY_JOB_LIMIT:
        return False, DAILY_JOB_LIMIT
    return True, DAILY_JOB_LIMIT - used


def normalize_dimension(value, default=0):
    if value is None or str(value).strip() == "":
        return default
    try:
        return max(0, min(1600, int(float(value))))
    except (TypeError, ValueError):
        return default


def add_history_entry(session_id, task_id, source_name, image_preset, abstract_filter, material_name,
                      run_parameters=None):
    if not session_id:
        return
    key = f"history:{session_id}"
    entry = json.dumps({
        "task_id": task_id, "source_name": source_name,
        "image_preset": image_preset,
        # Abstract styles are now submitted as named presets (for example,
        # ``abstract_wave``), so retain their resolved filter name in history.
        "abstract_filter": abstract_filter,
        "material_name": material_name,
        "run_parameters": run_parameters or {},
        "created_at": int(time.time()),
    }, separators=(",", ":"))
    pipeline = redis_client.pipeline()
    pipeline.lpush(key, entry)
    pipeline.ltrim(key, 0, 98)
    pipeline.expire(key, HISTORY_TTL_SECONDS)
    pipeline.execute()


def reuse_settings_url(entry):
    """Return a self-contained upload URL, with no task-history lookup."""
    parameters = entry.get("run_parameters") or {}
    settings = {
        "material": entry.get("material_name", ""),
        "pixel_square_mm": parameters.get("pixel_size_mm", "1"),
        "new_width": parameters.get("processing_width_px", "0"),
        "new_height": parameters.get("processing_height_px", "0"),
        "image_preset": entry.get("image_preset", "cartoon"),
        "colors": parameters.get("colors", []),
        "selected_color_hexes": parameters.get("selected_color_hexes", []),
        "color_name_overrides": parameters.get("color_name_overrides", {}),
        "abstract_filter_parameters": parameters.get("filter_parameters", {}),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(settings, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    return f"/?{urlencode({'settings': encoded})}"


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
        if not task_id:
            stale_records.append(raw_entry)
            continue
        stored_status = redis_client.get(f"task:{task_id}:status")
        # A manually purged or lifecycle-expired S3 job must not leave a dead
        # download row behind just because its browser-history record remains.
        if not stored_status and not task_artifacts_exist(task_id):
            stale_records.append(raw_entry)
            continue
        status = stored_status or "expired"
        history_entry = {
            "task_id": task_id, "source_name": entry.get("source_name", "processed image"),
            "image_preset": entry.get("image_preset"), "abstract_filter": entry.get("abstract_filter"),
            "material_name": entry.get("material_name"),
            "run_parameters": entry.get("run_parameters") or {},
            "created_at": entry.get("created_at"), "status": status,
            "svg_url": f"/download/{task_id}", "lightburn_url": f"/download-lbrn2/{task_id}",
        }
        history_entry["reuse_url"] = reuse_settings_url(history_entry)
        entries.append(history_entry)
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
        elif key == "transparent" and isinstance(value, str) and value.lower() in ("true", "false"):
            # Form submissions from an older cached page can serialize a
            # checkbox as text. Normalize it to the same boolean used by the
            # current JSON-producing UI.
            clean[key] = value.lower() == "true"
        elif isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Abstract filter setting '{key}' must be numeric")
        else:
            clean[key] = value
    return clean


def parse_color_name_overrides(raw_value):
    if not raw_value:
        return {}
    try:
        overrides = json.loads(raw_value)
    except json.JSONDecodeError as error:
        raise ValueError("Palette names are not valid JSON") from error
    if not isinstance(overrides, dict) or len(overrides) > 30:
        raise ValueError("Palette names must be a small object")
    clean, seen_names = {}, set()
    for color_hex, name in overrides.items():
        normalized_hex = str(color_hex).strip().upper()
        normalized_name = str(name).strip()
        if not re.fullmatch(r"#[0-9A-F]{6}", normalized_hex):
            raise ValueError("A palette color has an invalid hex value")
        if not normalized_name or len(normalized_name) > 80 or "," in normalized_name:
            raise ValueError("Each palette name must be 1-80 characters and cannot contain commas")
        name_key = normalized_name.casefold()
        if name_key in seen_names:
            raise ValueError("Each palette color needs a unique Material Library name")
        seen_names.add(name_key)
        clean[normalized_hex] = normalized_name
    return clean


def s3_artifacts_enabled():
    return bool(S3_BUCKET_NAME)


def task_artifact_key(task_id, filename, category="outputs"):
    """Keep every job's private artifacts under one predictable S3 prefix."""
    return f"jobs/{task_id}/{category}/{os.path.basename(filename)}"


def upload_task_artifact(task_id, local_file_path, category="outputs"):
    if not s3_artifacts_enabled():
        return None
    filename = os.path.basename(local_file_path)
    key = task_artifact_key(task_id, filename, category)
    try:
        s3_client.upload_file(local_file_path, S3_BUCKET_NAME, key)
    except ClientError as error:
        raise RuntimeError(f"Could not store job artifact in S3: {error}") from error
    return key


def download_task_artifact(key, local_path):
    if not s3_artifacts_enabled():
        raise RuntimeError("S3 artifact storage is not configured.")
    try:
        s3_client.download_file(S3_BUCKET_NAME, key, local_path)
    except ClientError as error:
        raise RuntimeError(f"Could not retrieve job artifact from S3: {error}") from error


def find_task_artifact(task_id, extension=None):
    """Find a generated output even when the request lands on another pod."""
    if not s3_artifacts_enabled():
        return None
    prefix = f"jobs/{task_id}/outputs/"
    try:
        response = s3_client.list_objects_v2(Bucket=S3_BUCKET_NAME, Prefix=prefix)
    except ClientError as error:
        raise RuntimeError(f"Could not list job artifacts in S3: {error}") from error
    keys = [item["Key"] for item in response.get("Contents", [])]
    if extension:
        keys = [key for key in keys if key.lower().endswith(extension.lower())]
    else:
        keys = [key for key in keys if not key.lower().endswith(".lbrn2")]
    return sorted(keys)[0] if keys else None


def task_artifacts_exist(task_id):
    """Return whether a task still has any durable S3 object.

    On an S3 error, preserve history rather than incorrectly hiding a job due
    to a temporary AWS outage.  Local-only deployments retain their existing
    Redis-based history behavior.
    """
    if not s3_artifacts_enabled():
        return True
    try:
        response = s3_client.list_objects_v2(
            Bucket=S3_BUCKET_NAME,
            Prefix=f"jobs/{task_id}/",
            MaxKeys=1,
        )
        return bool(response.get("Contents"))
    except ClientError as error:
        print(f"Unable to verify S3 history artifact for {task_id}: {error}", flush=True)
        return True


def get_s3_artifact(key):
    if not s3_artifacts_enabled():
        return None
    try:
        return s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=key)
    except ClientError as error:
        raise RuntimeError(f"Could not retrieve job artifact from S3: {error}") from error


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
                        task_match = re.search(
                            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                            filename.lower(),
                        )
                        task_id = task_match.group(0) if task_match else None
                        if task_id and not redis_client.exists(f"task:{task_id}:status"):
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
        material_name = str(data.get("material", "stainless - steel")).strip().lower()
        if not material_name:
            raise ValueError("Choose or enter a material name")
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
            material_name, str(data.get("colors", "")), image_preset, abstract_filter,
            json.dumps(parse_abstract_filter_parameters(data.get("abstract_filter_parameters", "{}")), separators=(",", ":")),
            json.dumps(parse_color_name_overrides(data.get("color_name_overrides", "{}")), separators=(",", ":")),
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
        exit_code = process.wait()
        if exit_code == 0:
            output_paths = glob.glob(os.path.join(upload_folder, f"output_{task_id}_*"))
            for output_path in output_paths:
                if os.path.isfile(output_path):
                    upload_task_artifact(task_id, output_path)
            redis_client.set(status_key, "completed")
        else:
            redis_client.set(status_key, "failed")
    except Exception as error:
        print(f"[Thread-{task_id}] Exception: {error}", flush=True)
        redis_client.set(f"task:{task_id}:status", "failed", ex=HISTORY_TTL_SECONDS)
        redis_client.rpush(f"task:{task_id}:log", f"Artifact processing failed: {error}")
        tasks[f"{task_id}_status"] = "failed"
        tasks[f"{task_id}_error"] = str(error)


def cleanup_redis_inflight(task_id):
    download_key = f"task:{task_id}:downloads"
    if redis_client.incr(download_key) == 1:
        redis_client.expire(download_key, HISTORY_TTL_SECONDS)
    redis_client.expire(f"task:{task_id}:status", HISTORY_TTL_SECONDS)
    redis_client.expire(f"task:{task_id}:log", HISTORY_TTL_SECONDS)
