"""Application services shared by HTTP route modules."""

import json
import base64
import glob
import hashlib
import multiprocessing
import os
import re
import subprocess
import threading
import time
import uuid
from decimal import Decimal
from numbers import Integral, Real
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import boto3
import redis
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key
from lib.lightburn import Lightburn


AWS_REGION = os.environ.get("AWS_REGION", "us-east-2").strip()
redis_client = redis.Redis(
    host=os.environ.get("REDIS_HOST", "localhost"),
    port=int(os.environ.get("REDIS_PORT", 6379)),
    decode_responses=True,
)
s3_client = boto3.client("s3", region_name=AWS_REGION)
S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME", "").strip()
DYNAMODB_TABLE_NAME = os.environ.get("DYNAMODB_TABLE_NAME", "").strip()
LIGHTBURN_PALETTE_NAMES = {
    "#B4B4B4": "Light-Gray", "#000000": "Black", "#0000FF": "Blue",
    "#FF0000": "Red", "#00E000": "Green", "#D0D000": "Yellow",
    "#FF8000": "Orange", "#00E0E0": "Cyan", "#FF00FF": "Magenta",
    "#0000A0": "Dark-Blue", "#A00000": "Dark-Red", "#00A000": "Dark-Green",
    "#A0A000": "Dark-Yellow", "#C08000": "Dark-Orange", "#00A0FF": "Light-Blue",
    "#A000A0": "Dark-Magenta", "#808080": "Medium-Gray", "#7D87B9": "Slate-Blue",
    "#BB7784": "Rose", "#4A6FE3": "Periwinkle-Blue", "#D33F6A": "Raspberry",
    "#8CD78C": "Sage-Green", "#F0B98D": "Peach", "#F6C4E1": "Light-Pink",
    "#FA9ED4": "Orchid-Pink", "#500A78": "Deep-Purple", "#B45A00": "Rust-Brown",
    "#004754": "Teal", "#86FA88": "Bright-Mint-Green", "#FFDB66": "Light-Gold",
}
ABSTRACT_FILTER_NAMES = {
    "none", "wave", "voronoi", "shear", "spiral", "mosaic",
    "crystal", "ripple", "centerline", "glitch", "shattered", "deep_fryer",
}
ABSTRACT_PRESET_PREFIX = "abstract_"
RASTER_JOB_QUEUE = "rasterizer:jobs"
RASTER_JOB_PROCESSING_QUEUE = "rasterizer:jobs:processing"
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
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    # LightBurn and NumPy occasionally expose numeric scalar subclasses. They
    # look like ordinary values in Python but boto3 will not serialize them.
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
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


def _setting_values(setting):
    """Keep the actual LightBurn controls, including Offset Fill sublayers."""
    hidden = {"materialName", "entryDesc", "entryThickness", "entryNoThickTitle", "subLayers"}
    values = {}
    for key, value in vars(setting).items():
        if key not in hidden and value is not None and isinstance(value, (str, int, float, bool)):
            values[key] = value
    if getattr(setting, "subLayers", None):
        values["subLayers"] = [_setting_values(layer) for layer in setting.subLayers]
    return values


def resolve_material_setting_usage(material_settings_path, material_name, selected_colors,
                                   color_name_overrides=None):
    """Resolve the exact settings a raster job will map to each palette swatch.

    This deliberately mirrors the production parser's exact, case-insensitive
    material and Description/cut-setting matching rules.  It is telemetry only:
    a malformed or unusual library must never prevent the actual job from running.
    """
    names = dict(LIGHTBURN_PALETTE_NAMES)
    for swatch, name in (color_name_overrides or {}).items():
        swatch = str(swatch).upper().strip()
        if swatch in names and str(name).strip():
            names[swatch] = str(name).strip()
    chosen = {str(name).strip().casefold() for name in selected_colors if str(name).strip()}
    if not chosen:
        chosen = {name.casefold() for name in names.values()}
    chosen.update({names["#000000"].casefold(), names["#B4B4B4"].casefold()})
    requested_material = str(material_name or "").strip().casefold()
    matched = {}
    for setting in Lightburn().parse_material_library(material_settings_path):
        if str(getattr(setting, "materialName", "") or "").strip().casefold() != requested_material:
            continue
        labels = {
            str(getattr(setting, "entryDesc", "") or "").strip().casefold(),
            str(getattr(setting, "name", "") or "").strip().casefold(),
        }
        for swatch, swatch_name in names.items():
            if swatch_name.casefold() in chosen and swatch_name.casefold() in labels and swatch not in matched:
                matched[swatch] = {
                    "swatch_hex": swatch,
                    "swatch_name": swatch_name,
                    "material": str(getattr(setting, "materialName", "") or "").strip(),
                    "description": str(getattr(setting, "entryDesc", "") or "").strip(),
                    "type": str(getattr(setting, "type", "") or "").strip(),
                    "setting_values": _setting_values(setting),
                }
                break
    return list(matched.values())


def _usage_dimension_key(kind, value):
    normalized = str(value or "Unspecified").strip() or "Unspecified"
    digest = hashlib.sha256(normalized.casefold().encode("utf-8")).hexdigest()[:24]
    return f"USAGE#{kind}#{digest}", normalized


def record_setting_usage(task_id, resolved_settings, library=None):
    """Atomically increment setting-use counters for future recommendations.

    One compact aggregate is written for every individual lookup dimension and
    for their full combination. No artwork, user identity, or uploaded file
    name is stored in these shared aggregates.
    """
    table = account_table()
    if not table or not resolved_settings:
        return
    laser_source = str((library or {}).get("laser_source") or "").strip() or "Unspecified"
    lens_field_of_view = str((library or {}).get("lens_field_of_view") or "").strip() or "Unspecified"
    now = int(time.time())
    try:
        for setting in resolved_settings:
            material = str(setting.get("material") or "Unspecified").strip() or "Unspecified"
            swatch = f"{setting.get('swatch_hex', '')} {setting.get('swatch_name', '')}".strip()
            fingerprint_source = {
                "material": material, "swatch_hex": setting.get("swatch_hex", ""),
                "description": setting.get("description", ""), "type": setting.get("type", ""),
                "setting_values": setting.get("setting_values", {}),
            }
            fingerprint = hashlib.sha256(
                json.dumps(fingerprint_source, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
            dimensions = (
                ("LASER", laser_source),
                ("LENS", lens_field_of_view),
                ("MATERIAL", material),
                ("SWATCH", swatch),
                ("COMBINATION", json.dumps({"laser_source": laser_source, "lens_field_of_view": lens_field_of_view, "material": material, "swatch": swatch}, sort_keys=True)),
            )
            for dimension, value in dimensions:
                pk, display_value = _usage_dimension_key(dimension, value)
                table.update_item(
                    Key={"pk": pk, "sk": f"SETTING#{fingerprint}"},
                    UpdateExpression=("SET #count = if_not_exists(#count, :zero) + :one, "
                                      "#dimension = :dimension, #dimension_value = :dimension_value, "
                                      "#laser = :laser_source, #lens = :lens_field_of_view, "
                                      "#material = :material, #swatch_hex = :swatch_hex, #swatch_name = :swatch_name, "
                                      "#description = :description, #setting_type = :setting_type, #setting_values = :setting_values, "
                                      "#last_used = :now, #last_task = :task_id"),
                    ExpressionAttributeNames={
                        "#count": "usage_count", "#dimension": "dimension",
                        "#dimension_value": "dimension_value", "#laser": "laser_source",
                        "#lens": "lens_field_of_view", "#material": "material",
                        "#swatch_hex": "swatch_hex", "#swatch_name": "swatch_name",
                        "#description": "description", "#setting_type": "setting_type",
                        "#setting_values": "setting_values", "#last_used": "last_used_at",
                        "#last_task": "last_task_id",
                    },
                    ExpressionAttributeValues=_dynamodb_values({
                        ":zero": 0, ":one": 1, ":dimension": dimension,
                        ":dimension_value": display_value, ":laser_source": laser_source,
                        ":lens_field_of_view": lens_field_of_view, ":material": material,
                        ":swatch_hex": setting.get("swatch_hex", ""), ":swatch_name": setting.get("swatch_name", ""),
                        ":description": setting.get("description", ""), ":setting_type": setting.get("type", ""),
                        ":setting_values": setting.get("setting_values", {}), ":now": now, ":task_id": task_id,
                    }),
                )
    except Exception as error:
        raise RuntimeError("Could not record Material Library setting usage.") from error


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


def save_user_material_library(user_id, local_file_path, material_name="", summary=None,
                               display_name=None, source_filename=None):
    """Store an uploaded LightBurn library once under its Cognito owner."""
    table = account_table()
    if not table or not S3_BUCKET_NAME:
        raise RuntimeError("Account Material Library storage is not configured.")
    library_id = str(uuid.uuid4())
    filename = os.path.basename(source_filename or local_file_path)
    library_name = str(display_name or filename).strip()[:160] or filename
    s3_key = f"users/{user_id}/materials/{library_id}/{filename}"
    try:
        # Material libraries are outside the S3 lifecycle rules, so they do
        # not need a retention tag (and this avoids requiring PutObjectTagging).
        s3_client.upload_file(local_file_path, S3_BUCKET_NAME, s3_key)
        item = {
            "pk": f"USER#{user_id}",
            "sk": f"MATERIAL#{library_id}",
            "library_id": library_id,
            "name": library_name,
            "original_name": filename,
            "material_name": str(material_name or "").strip()[:160],
            "s3_key": s3_key,
            "created_at": int(time.time()),
        }
        if summary:
            item["summary"] = _dynamodb_values(summary)
        table.put_item(Item=item)
    except ClientError as error:
        raise RuntimeError("Could not save the Material Library to this account.") from error
    return {"library_id": library_id, "name": library_name, "original_name": filename,
            "material_name": str(material_name or "").strip()}


def download_user_material_library(library, local_path):
    if not library or not library.get("s3_key"):
        raise RuntimeError("Saved Material Library is unavailable.")
    try:
        s3_client.download_file(S3_BUCKET_NAME, library["s3_key"], local_path)
    except ClientError as error:
        raise RuntimeError("Could not retrieve the saved Material Library.") from error


def delete_user_material_library(user_id, library_id):
    """Delete one account-owned library from S3 and its DynamoDB index."""
    table = account_table()
    library = get_user_material_library(user_id, library_id)
    if not table or not library:
        return False
    try:
        if library.get("s3_key"):
            s3_client.delete_object(Bucket=S3_BUCKET_NAME, Key=library["s3_key"])
        table.delete_item(Key={"pk": f"USER#{user_id}", "sk": f"MATERIAL#{library_id}"})
    except ClientError as error:
        raise RuntimeError("Could not delete the saved Material Library.") from error
    return True


def list_user_holographic_recipes(user_id):
    table = account_table()
    if not table or not user_id:
        return []
    try:
        response = table.query(
            KeyConditionExpression=Key("pk").eq(f"USER#{user_id}") & Key("sk").begins_with("HOLORECIPE#"),
            ScanIndexForward=False,
        )
    except ClientError as error:
        raise RuntimeError("Could not load saved Holographic Recipes.") from error
    return [_json_values(item) for item in response.get("Items", [])]


def get_user_holographic_recipe(user_id, recipe_id):
    table = account_table()
    if not table or not user_id or not recipe_id:
        return None
    try:
        item = table.get_item(Key={"pk": f"USER#{user_id}", "sk": f"HOLORECIPE#{recipe_id}"}).get("Item")
    except ClientError as error:
        raise RuntimeError("Could not load the saved Holographic Recipe.") from error
    return _json_values(item) if item else None


def save_user_holographic_recipe(user_id, local_file_path, display_name=None, metadata=None,
                                 source_filename=None):
    table = account_table()
    if not table or not S3_BUCKET_NAME:
        raise RuntimeError("Account Holographic Recipe storage is not configured.")
    recipe_id = str(uuid.uuid4())
    filename = os.path.basename(source_filename or local_file_path)
    name = str(display_name or os.path.splitext(filename)[0]).strip()[:160] or "Holographic Recipe"
    s3_key = f"users/{user_id}/holographic-recipes/{recipe_id}/{filename}"
    try:
        s3_client.upload_file(local_file_path, S3_BUCKET_NAME, s3_key)
        item = {
            "pk": f"USER#{user_id}", "sk": f"HOLORECIPE#{recipe_id}",
            "recipe_id": recipe_id, "name": name, "original_name": filename,
            "s3_key": s3_key, "created_at": int(time.time()),
            "metadata": _dynamodb_values(metadata or {}),
        }
        table.put_item(Item=item)
    except ClientError as error:
        raise RuntimeError("Could not save the Holographic Recipe to this account.") from error
    return _json_values(item)


def download_user_holographic_recipe(recipe, local_path):
    if not recipe or not recipe.get("s3_key"):
        raise RuntimeError("Saved Holographic Recipe is unavailable.")
    try:
        s3_client.download_file(S3_BUCKET_NAME, recipe["s3_key"], local_path)
    except ClientError as error:
        raise RuntimeError("Could not retrieve the saved Holographic Recipe.") from error


def delete_user_holographic_recipe(user_id, recipe_id):
    table = account_table()
    recipe = get_user_holographic_recipe(user_id, recipe_id)
    if not table or not recipe:
        return False
    try:
        if recipe.get("s3_key"):
            s3_client.delete_object(Bucket=S3_BUCKET_NAME, Key=recipe["s3_key"])
        table.delete_item(Key={"pk": f"USER#{user_id}", "sk": f"HOLORECIPE#{recipe_id}"})
    except ClientError as error:
        raise RuntimeError("Could not delete the saved Holographic Recipe.") from error
    return True


def rename_user_material_library(user_id, library_id, display_name, laser_source=None, lens_field_of_view=None, notes=None):
    table = account_table()
    if not table or not get_user_material_library(user_id, library_id):
        return False
    display_name = str(display_name or "").strip()
    if not display_name or len(display_name) > 160:
        raise ValueError("Library names must be between 1 and 160 characters.")
    laser_source = str(laser_source or "").strip()
    lens_field_of_view = str(lens_field_of_view or "").strip()
    notes = str(notes or "").strip()
    if len(laser_source) > 160 or len(lens_field_of_view) > 160 or len(notes) > 1000:
        raise ValueError("Laser Source and Lens Field of View must be 160 characters or fewer, and Notes 1000 characters or fewer.")
    try:
        table.update_item(
            Key={"pk": f"USER#{user_id}", "sk": f"MATERIAL#{library_id}"},
            UpdateExpression="SET #name = :name, laser_source = :laser_source, lens_field_of_view = :lens_field_of_view, notes = :notes, updated_at = :updated_at",
            ExpressionAttributeNames={"#name": "name"},
            ExpressionAttributeValues={
                ":name": display_name,
                ":laser_source": laser_source,
                ":lens_field_of_view": lens_field_of_view,
                ":notes": notes,
                ":updated_at": int(time.time()),
            },
        )
    except ClientError as error:
        raise RuntimeError("Could not rename the saved Material Library.") from error
    return True


def update_user_material_library_file(user_id, library_id, local_file_path, summary):
    """Replace an account library's S3 XML and refresh its display summary."""
    table = account_table()
    library = get_user_material_library(user_id, library_id)
    if not table or not library or not library.get("s3_key"):
        return False
    try:
        s3_client.upload_file(local_file_path, S3_BUCKET_NAME, library["s3_key"])
        table.update_item(
            Key={"pk": f"USER#{user_id}", "sk": f"MATERIAL#{library_id}"},
            UpdateExpression="SET summary = :summary, material_name = :material_name, updated_at = :updated_at",
            ExpressionAttributeValues={
                ":summary": _dynamodb_values(summary),
                ":material_name": ", ".join(summary.get("material_names", []))[:160],
                ":updated_at": int(time.time()),
            },
        )
    except ClientError as error:
        raise RuntimeError("Could not save Material Library changes.") from error
    return True


def record_user_job(user_id, task_id, source_name, image_preset, abstract_filter, material_name,
                    run_parameters, input_keys=None):
    """Write both an ordered user-history record and a direct owner lookup."""
    table = account_table()
    if not table or not user_id:
        return
    created_at = int(time.time())
    history_sk = f"JOB#{created_at:010d}#{task_id}"
    artifact_prefix = f"users/{user_id}/jobs/{task_id}/"
    history_item = {
        "pk": f"USER#{user_id}", "sk": history_sk,
        "task_id": task_id, "source_name": source_name,
        "image_preset": image_preset, "abstract_filter": abstract_filter,
        "material_name": material_name, "run_parameters": _dynamodb_values(run_parameters or {}),
        "created_at": created_at, "updated_at": created_at, "status": "pending",
        "artifact_prefix": artifact_prefix, "input_keys": list(input_keys or []),
    }
    owner_item = {
        "pk": f"JOB#{task_id}", "sk": "OWNER", "user_id": user_id,
        "created_at": created_at, "updated_at": created_at, "history_sk": history_sk,
        "status": "pending", "artifact_prefix": artifact_prefix,
        "input_keys": list(input_keys or []),
    }
    try:
        with table.batch_writer() as batch:
            batch.put_item(Item=history_item)
            batch.put_item(Item=owner_item)
    except ClientError as error:
        raise RuntimeError("Could not record this job in the account history.") from error


def get_job_record(task_id):
    """Return the direct durable record for an account-owned job, if any."""
    table = account_table()
    if not table or not task_id:
        return None
    try:
        item = table.get_item(Key={"pk": f"JOB#{task_id}", "sk": "OWNER"}).get("Item")
    except ClientError as error:
        raise RuntimeError("Could not retrieve durable job information.") from error
    return _json_values(item) if item else None


def update_user_job(task_id, status, output_keys=None, error_message=None):
    """Mirror worker completion/failure into both DynamoDB job records."""
    table = account_table()
    if not table:
        return
    record = get_job_record(task_id)
    if not record:
        return
    user_id, history_sk = record.get("user_id"), record.get("history_sk")
    if not user_id or not history_sk:
        return
    now = int(time.time())
    values = {":status": status, ":updated_at": now}
    sets = ["#status = :status", "updated_at = :updated_at"]
    if status == "completed":
        values[":completed_at"] = now
        sets.append("completed_at = :completed_at")
    if output_keys is not None:
        values[":output_keys"] = list(output_keys)
        sets.append("output_keys = :output_keys")
    if error_message:
        values[":error_message"] = str(error_message)[:2000]
        sets.append("error_message = :error_message")
    try:
        for key in (
            {"pk": f"JOB#{task_id}", "sk": "OWNER"},
            {"pk": f"USER#{user_id}", "sk": history_sk},
        ):
            table.update_item(
                Key=key,
                UpdateExpression="SET " + ", ".join(sets),
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues=_dynamodb_values(values),
            )
    except ClientError as error:
        raise RuntimeError("Could not save durable job status.") from error


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
        durable_status = entry.get("status", "pending")
        # Keep account history consistent with S3 lifecycle/manual cleanup,
        # just as the guest history panel already does.
        if not stored_status and not task_artifacts_exist(task_id):
            continue
        entry["status"] = stored_status or durable_status
        entry.update(job_history_links(entry))
        entries.append(entry)
    return entries


def get_job_owner(task_id):
    record = get_job_record(task_id)
    return record.get("user_id") if record else None


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


def job_history_links(entry):
    """Return job-type-aware actions for the shared processing history."""
    task_id = entry.get("task_id", "")
    parameters = entry.get("run_parameters") or {}
    if parameters.get("job_type") == "holographic_artwork":
        return {
            "svg_url": f"/download-svg/{task_id}",
            "lightburn_url": f"/download-lbrn2/{task_id}",
            "reuse_url": "/holographic-etching",
            "reuse_label": "Open Lab",
        }
    return {
        "svg_url": f"/download/{task_id}",
        "lightburn_url": f"/download-lbrn2/{task_id}",
        "reuse_url": reuse_settings_url(entry),
        "reuse_label": "Reuse Settings",
    }


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
        }
        history_entry.update(job_history_links(history_entry))
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
        elif key == "setting_name" and isinstance(value, str) and 1 <= len(value.strip()) <= 80:
            clean[key] = value.strip()
        elif key == "fill_mode" and value in {"from_setting", "fill", "offset_fill", "line"}:
            clean[key] = value
        elif key in {"transparent", "invert_threshold", "keep_black"} and isinstance(value, bool):
            clean[key] = value
        elif key in {"transparent", "invert_threshold", "keep_black"} and isinstance(value, str) and value.lower() in ("true", "false"):
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
    if not isinstance(overrides, dict) or len(overrides) > 64:
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


def task_artifact_key(task_id, filename, category="outputs", user_id=None):
    """Return the durable S3 key for a guest or account-owned job artifact."""
    filename = os.path.basename(filename)
    if user_id:
        return f"users/{user_id}/jobs/{task_id}/{category}/{filename}"
    return f"jobs/{task_id}/{category}/{filename}"


def upload_task_artifact(task_id, local_file_path, category="outputs", user_id=None):
    if not s3_artifacts_enabled():
        return None
    filename = os.path.basename(local_file_path)
    key = task_artifact_key(task_id, filename, category, user_id=user_id)
    try:
        upload_args = {}
        if user_id:
            # Account job keys sit below users/<sub>/jobs/, which cannot be
            # targeted by a single S3 prefix rule. A lifecycle tag keeps them
            # on the same seven-day retention schedule as guest jobs.
            upload_args["ExtraArgs"] = {"Tagging": "mopa-retention=job"}
        s3_client.upload_file(local_file_path, S3_BUCKET_NAME, key, **upload_args)
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


def _task_artifact_prefix(task_id, user_id=None):
    if user_id:
        return f"users/{user_id}/jobs/{task_id}/"
    record = get_job_record(task_id)
    if record and record.get("artifact_prefix"):
        return record["artifact_prefix"]
    return f"jobs/{task_id}/"


def find_task_artifact(task_id, extension=None, user_id=None):
    """Find a generated output even when the request lands on another pod."""
    if not s3_artifacts_enabled():
        return None
    prefix = _task_artifact_prefix(task_id, user_id=user_id) + "outputs/"
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
            Prefix=_task_artifact_prefix(task_id),
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


def long_running_script(task_id, data, image_path, material_settings_path, upload_folder,
                        user_id=None, output_name=None):
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
            os.path.join(
                upload_folder,
                output_name or tasks.get(f"{task_id}_filename")
                or f"output_{task_id}_{os.path.basename(image_path)}",
            ),
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
            output_keys = []
            for output_path in output_paths:
                if os.path.isfile(output_path):
                    key = upload_task_artifact(task_id, output_path, user_id=user_id)
                    if key:
                        output_keys.append(key)
            redis_client.set(status_key, "completed")
            try:
                update_user_job(task_id, "completed", output_keys=output_keys)
            except RuntimeError as status_error:
                print(f"[Thread-{task_id}] Could not save durable completion state: {status_error}", flush=True)
        else:
            redis_client.set(status_key, "failed")
            failure_message = f"Rasterizer exited with code {exit_code}"
            if exit_code in (-9, 137):
                failure_message += " (the worker may have been killed or exceeded its memory limit)"
            redis_client.rpush(log_key, failure_message)
            try:
                update_user_job(task_id, "failed", error_message=failure_message)
            except RuntimeError as status_error:
                print(f"[Thread-{task_id}] Could not save durable failure state: {status_error}", flush=True)
    except Exception as error:
        print(f"[Thread-{task_id}] Exception: {error}", flush=True)
        redis_client.set(f"task:{task_id}:status", "failed", ex=HISTORY_TTL_SECONDS)
        redis_client.rpush(f"task:{task_id}:log", f"Artifact processing failed: {error}")
        tasks[f"{task_id}_status"] = "failed"
        tasks[f"{task_id}_error"] = str(error)
        try:
            update_user_job(task_id, "failed", error_message=str(error))
        except RuntimeError as status_error:
            print(f"[Thread-{task_id}] Could not save durable failure state: {status_error}", flush=True)


def enqueue_raster_job(task_id, data, image_key, material_key, output_name,
                       image_name, material_name, user_id=None):
    """Place a portable raster job on Redis for the dedicated worker pod."""
    if not image_key or not material_key:
        raise RuntimeError("Queued raster jobs require durable image and material artifacts")
    payload = {
        "task_id": task_id,
        "data": data,
        "image_key": image_key,
        "material_key": material_key,
        "output_name": output_name,
        "image_name": secure_artifact_name(image_name, "image"),
        "material_name": secure_artifact_name(material_name, "materials.clb"),
        "user_id": user_id,
    }
    redis_client.lpush(RASTER_JOB_QUEUE, json.dumps(payload, separators=(",", ":")))
    redis_client.rpush(f"task:{task_id}:log", "Job queued for a dedicated raster worker.")


def raster_queue_position(task_id):
    """Return a pending task's position including currently active worker jobs."""
    queued_payloads = redis_client.lrange(RASTER_JOB_QUEUE, 0, -1)
    waiting_position = None
    # Jobs are LPUSHed and workers BRPOP from the opposite end, so the
    # rightmost entry is next. Iterate in worker-consumption order.
    for position, raw_payload in enumerate(reversed(queued_payloads), 1):
        try:
            queued_task_id = str(json.loads(raw_payload).get("task_id", ""))
        except (TypeError, json.JSONDecodeError):
            continue
        if queued_task_id == str(task_id):
            waiting_position = position
            break
    if waiting_position is None:
        return None
    active_jobs = redis_client.llen(RASTER_JOB_PROCESSING_QUEUE)
    overall_position = active_jobs + waiting_position
    return {
        "position": overall_position,
        "jobs_ahead": max(0, overall_position - 1),
        "active_jobs": active_jobs,
    }


def secure_artifact_name(value, fallback):
    """Keep queued artifact basenames portable without importing Flask helpers."""
    name = os.path.basename(str(value or "")).strip()
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._")
    return name or fallback


def cleanup_redis_inflight(task_id):
    download_key = f"task:{task_id}:downloads"
    if redis_client.incr(download_key) == 1:
        redis_client.expire(download_key, HISTORY_TTL_SECONDS)
    redis_client.expire(f"task:{task_id}:status", HISTORY_TTL_SECONDS)
    redis_client.expire(f"task:{task_id}:log", HISTORY_TTL_SECONDS)
