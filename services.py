"""Application services shared by HTTP route modules."""

import json
import base64
import glob
import hashlib
import hmac
import math
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
from urllib.parse import quote, urlencode

import boto3
from botocore.config import Config
import redis
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key
from lib.lightburn import Lightburn
from job_runtime import DynamoJobRuntime, RedisJobRuntime, create_job_runtime


AWS_REGION = os.environ.get("AWS_REGION", "us-east-2").strip()


def _environment_flag(name, default="false"):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def create_redis_client():
    """Create a Redis client usable by local, Kubernetes, and ECS workloads."""
    redis_url = os.environ.get("REDIS_URL", "").strip()
    common_options = {
        "decode_responses": True,
        "socket_connect_timeout": int(os.environ.get("REDIS_CONNECT_TIMEOUT_SECONDS", "5")),
        "socket_timeout": int(os.environ.get("REDIS_SOCKET_TIMEOUT_SECONDS", "10")),
        "health_check_interval": int(os.environ.get("REDIS_HEALTH_CHECK_SECONDS", "30")),
    }
    if redis_url:
        return redis.Redis.from_url(redis_url, **common_options)

    password = os.environ.get("REDIS_PASSWORD", "")
    username = os.environ.get("REDIS_USERNAME", "")
    return redis.Redis(
        host=os.environ.get("REDIS_HOST", "localhost"),
        port=int(os.environ.get("REDIS_PORT", 6379)),
        ssl=_environment_flag("REDIS_SSL"),
        password=password or None,
        username=username or None,
        **common_options,
    )


redis_client = create_redis_client()
s3_client = boto3.client(
    "s3",
    region_name=AWS_REGION,
    config=Config(
        connect_timeout=10,
        read_timeout=60,
        retries={"max_attempts": 3, "mode": "standard"},
    ),
)
sqs_client = boto3.client(
    "sqs",
    region_name=AWS_REGION,
    config=Config(
        connect_timeout=5,
        read_timeout=10,
        retries={"max_attempts": 3, "mode": "standard"},
    ),
)
S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME", "").strip()
DYNAMODB_TABLE_NAME = os.environ.get("DYNAMODB_TABLE_NAME", "").strip()
SQS_QUEUE_URL = os.environ.get("SQS_QUEUE_URL", "").strip()
FARGATE_DISPATCH_VIA_S3 = _environment_flag("FARGATE_DISPATCH_VIA_S3")
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
    "crystal", "ripple", "glitch", "shattered", "deep_fryer",
    "optical_color_mix",
    "structure_tensor_flow",
}
ABSTRACT_PRESET_PREFIX = "abstract_"
RASTER_JOB_QUEUE = "rasterizer:jobs"
RASTER_JOB_PROCESSING_QUEUE = "rasterizer:jobs:processing"
RASTER_JOB_PAYLOAD_PREFIX = "rasterizer:job-payload:"
HISTORY_SESSION_RE = re.compile(r"^[a-f0-9-]{32,36}$")
HISTORY_TTL_SECONDS = 7 * 24 * 60 * 60
GUEST_MATERIAL_LIBRARY_LIMIT = 12
DAILY_JOB_LIMIT = max(1, int(os.environ.get("DAILY_JOB_LIMIT", "3")))
manager = multiprocessing.Manager()
tasks = manager.dict()
job_runtime = create_job_runtime(redis_client, HISTORY_TTL_SECONDS, RASTER_JOB_PAYLOAD_PREFIX)


def sync_job_runtime(client=None):
    """Keep test/legacy Redis monkey-patches attached to the runtime adapter."""
    if isinstance(job_runtime, RedisJobRuntime):
        job_runtime.client = client or redis_client
    return job_runtime


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
    material and Entry Description matching rules.  It is telemetry only:
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
        description = str(getattr(setting, "entryDesc", "") or "").strip()
        description_key = description.casefold()
        for swatch, swatch_name in names.items():
            if (
                swatch_name.casefold() in chosen
                and swatch_name.casefold() == description_key
                and swatch not in matched
            ):
                matched[swatch] = {
                    "swatch_hex": swatch,
                    "swatch_name": swatch_name,
                    "material": str(getattr(setting, "materialName", "") or "").strip(),
                    "description": description,
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


def record_setting_usage_async(task_id, resolved_settings, library=None):
    """Record optional aggregate telemetry without delaying job submission.

    A palette can resolve dozens of swatches, and each swatch updates several
    aggregate dimensions. Those remote DynamoDB writes must never sit inside
    the user-facing /upload request or delay queueing the raster job.
    """
    if not resolved_settings:
        return None

    def record_in_background():
        try:
            record_setting_usage(task_id, resolved_settings, library)
        except RuntimeError as error:
            print(
                f"Could not record Material Library usage for {task_id}: {error}",
                flush=True,
            )

    usage_thread = threading.Thread(
        target=record_in_background,
        name=f"setting-usage-{task_id}",
        daemon=True,
    )
    usage_thread.start()
    return usage_thread


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
                               display_name=None, source_filename=None,
                               library_intent="color_palette"):
    """Store an uploaded LightBurn library once under its Cognito owner."""
    table = account_table()
    if not table or not S3_BUCKET_NAME:
        raise RuntimeError("Account Material Library storage is not configured.")
    library_id = str(uuid.uuid4())
    filename = os.path.basename(source_filename or local_file_path)
    library_name = str(display_name or filename).strip()[:160] or filename
    library_intent = "hatch_palette" if library_intent == "hatch_palette" else "color_palette"
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
            "library_intent": library_intent,
            "s3_key": s3_key,
            "created_at": int(time.time()),
        }
        if summary:
            item["summary"] = _dynamodb_values(summary)
        table.put_item(Item=item)
    except ClientError as error:
        raise RuntimeError("Could not save the Material Library to this account.") from error
    return {"library_id": library_id, "name": library_name, "original_name": filename,
            "material_name": str(material_name or "").strip(),
            "library_intent": library_intent}


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


def list_user_depth_palettes(user_id):
    """Return account-owned depth palettes stored directly in DynamoDB."""
    table = account_table()
    if not table or not user_id:
        return []
    try:
        response = table.query(
            KeyConditionExpression=Key("pk").eq(f"USER#{user_id}") & Key("sk").begins_with("DEPTHPALETTE#"),
            ScanIndexForward=False,
        )
    except ClientError as error:
        raise RuntimeError("Could not load saved Depth Palettes.") from error
    return [_json_values(item) for item in response.get("Items", [])]


def get_user_depth_palette(user_id, palette_id):
    table = account_table()
    if not table or not user_id or not palette_id:
        return None
    try:
        item = table.get_item(
            Key={"pk": f"USER#{user_id}", "sk": f"DEPTHPALETTE#{palette_id}"}
        ).get("Item")
    except ClientError as error:
        raise RuntimeError("Could not load the saved Depth Palette.") from error
    return _json_values(item) if item else None


def save_user_depth_palette(user_id, name, entries, palette_id=None):
    table = account_table()
    if not table:
        raise RuntimeError("Account Depth Palette storage is not configured.")
    if not user_id:
        raise ValueError("An authenticated account is required.")
    palette_id = palette_id or str(uuid.uuid4())
    existing = get_user_depth_palette(user_id, palette_id) if palette_id else None
    item = {
        "pk": f"USER#{user_id}",
        "sk": f"DEPTHPALETTE#{palette_id}",
        "palette_id": palette_id,
        "name": str(name).strip()[:160],
        "entries": _dynamodb_values(entries),
        "created_at": (existing or {}).get("created_at", int(time.time())),
        "updated_at": int(time.time()),
    }
    try:
        # Existing DynamoDB numeric values are converted to ordinary Python
        # numbers when read for JSON responses. Normalize the complete item on
        # every write so an existing Decimal timestamp cannot return as a float
        # and trigger boto3's unsupported-float serializer error on updates.
        table.put_item(Item=_dynamodb_values(item))
    except (ClientError, TypeError, ValueError) as error:
        raise RuntimeError("Could not save the Depth Palette.") from error
    return _json_values(item)


def delete_user_depth_palette(user_id, palette_id):
    table = account_table()
    if not table or not get_user_depth_palette(user_id, palette_id):
        return False
    try:
        table.delete_item(Key={"pk": f"USER#{user_id}", "sk": f"DEPTHPALETTE#{palette_id}"})
    except ClientError as error:
        raise RuntimeError("Could not delete the Depth Palette.") from error
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
        raise RuntimeError("Could not load saved Fauxlographic Palettes.") from error
    return [_json_values(item) for item in response.get("Items", [])]


def get_user_holographic_recipe(user_id, recipe_id):
    table = account_table()
    if not table or not user_id or not recipe_id:
        return None
    try:
        item = table.get_item(Key={"pk": f"USER#{user_id}", "sk": f"HOLORECIPE#{recipe_id}"}).get("Item")
    except ClientError as error:
        raise RuntimeError("Could not load the saved Fauxlographic Palette.") from error
    return _json_values(item) if item else None


def save_user_holographic_recipe(user_id, local_file_path, display_name=None, metadata=None,
                                 source_filename=None):
    table = account_table()
    if not table or not S3_BUCKET_NAME:
        raise RuntimeError("Account Fauxlographic Palette storage is not configured.")
    recipe_id = str(uuid.uuid4())
    filename = os.path.basename(source_filename or local_file_path)
    name = str(display_name or os.path.splitext(filename)[0]).strip()[:160] or "Fauxlographic Palette"
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
        raise RuntimeError("Could not save the Fauxlographic Palette to this account.") from error
    return _json_values(item)


def download_user_holographic_recipe(recipe, local_path):
    if not recipe or not recipe.get("s3_key"):
        raise RuntimeError("Saved Fauxlographic Palette is unavailable.")
    try:
        s3_client.download_file(S3_BUCKET_NAME, recipe["s3_key"], local_path)
    except ClientError as error:
        raise RuntimeError("Could not retrieve the saved Fauxlographic Palette.") from error


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
        raise RuntimeError("Could not delete the saved Fauxlographic Palette.") from error
    return True


def _community_normalized_value(value):
    normalized = " ".join(str(value or "").strip().casefold().replace("×", "x").split())
    normalized = re.sub(r"\s*x\s*", "x", normalized)
    normalized = re.sub(r"\s*mm\b", "mm", normalized)
    return normalized


def _community_filter_value(value):
    """Create a stable exact-match value for community lookup partitions."""
    return quote(_community_normalized_value(value), safe="")


def _community_substring_match(value, query):
    return not query or _community_normalized_value(query) in _community_normalized_value(value)


def _community_exact_match(value, query):
    return not query or _community_normalized_value(value) == _community_normalized_value(query)


COMMUNITY_PUBLIC_SETTING_FIELDS = (
    "speed", "minPower", "maxPower", "frequency", "QPulseWidth", "interval",
    "angle", "numPasses", "anglePerPass", "bidir", "crossHatch", "type",
)


def _community_public_settings(settings):
    """Strip private LightBurn metadata before a setting enters Community Set."""
    settings = settings if isinstance(settings, dict) else {}
    return {
        field: settings[field]
        for field in COMMUNITY_PUBLIC_SETTING_FIELDS
        if field in settings and not isinstance(settings[field], (dict, list))
    }


def _community_filter_partitions(laser_source, lens_field_of_view, materials):
    dimensions = {
        "laser": _community_filter_value(laser_source),
        "lens": _community_filter_value(lens_field_of_view),
    }
    partitions = set()
    for material in materials or [""]:
        values = {**dimensions, "material": _community_filter_value(material)}
        populated = [key for key in ("laser", "lens", "material") if values[key]]
        for mask in range(1, 1 << len(populated)):
            chosen = [key for index, key in enumerate(populated) if mask & (1 << index)]
            signature = "#".join(f"{key}={values[key]}" for key in chosen)
            partitions.add(f"LASER_COMMUNITY_INDEX#{signature}")
    return sorted(partitions)


def _community_query_partition(laser_source="", lens_field_of_view="", material=""):
    values = {
        "laser": _community_filter_value(laser_source),
        "lens": _community_filter_value(lens_field_of_view),
        "material": _community_filter_value(material),
    }
    signature = "#".join(
        f"{key}={values[key]}" for key in ("laser", "lens", "material") if values[key]
    )
    return f"LASER_COMMUNITY_INDEX#{signature}" if signature else ""


def _official_community_swatch(entry):
    color_hex = str(entry.get("swatch_hex", "") or "").upper()
    if color_hex in LIGHTBURN_PALETTE_NAMES:
        return color_hex, LIGHTBURN_PALETTE_NAMES[color_hex]
    description = str(entry.get("source_description", entry.get("description", "")) or "").strip()
    color_hex = next((candidate for candidate, official_name in LIGHTBURN_PALETTE_NAMES.items()
                      if official_name.casefold() == description.casefold()), "")
    return color_hex, LIGHTBURN_PALETTE_NAMES.get(color_hex, "Unassigned")


def _annotate_community_swatches(user_id, summary):
    """Resolve editable setting descriptions back to account palette hexes."""
    preferences = get_user_preferences(user_id)
    overrides = preferences.get("color_name_overrides", {}) if isinstance(preferences, dict) else {}
    override_lookup = {
        str(label).strip().casefold(): str(color_hex).upper()
        for color_hex, label in overrides.items()
        if str(color_hex).upper() in LIGHTBURN_PALETTE_NAMES and str(label).strip()
    }
    official_lookup = {name.casefold(): color_hex for color_hex, name in LIGHTBURN_PALETTE_NAMES.items()}
    for entry in summary.get("entries", []):
        description = str(entry.get("description", "") or "").strip()
        color_hex = override_lookup.get(description.casefold()) or official_lookup.get(description.casefold(), "")
        entry["swatch_hex"] = color_hex
        entry["official_color"] = LIGHTBURN_PALETTE_NAMES.get(color_hex, "Unassigned")
    return summary


def _laser_community_row(community, entry):
    settings = _json_values(entry.get("settings", {}))
    swatch, official_color = _official_community_swatch(entry)
    return {
        "laser_source": community.get("laser_source", ""),
        "lens": community.get("lens_field_of_view", ""),
        "material": entry.get("material", ""),
        "color": official_color,
        "swatch": swatch,
        "operation": entry.get("type", ""),
        "settings": settings,
        "notes": community.get("notes", ""),
    }


def query_laser_community(laser_source="", lens_field_of_view="", material="", color="", limit=300):
    """Return anonymous settings with a substring match for Material."""
    table = account_table()
    if not table:
        raise RuntimeError("Comunity Set storage is not configured.")
    if not any((laser_source, lens_field_of_view, material, color)):
        raise ValueError("Enter a laser model/source, lens, material, or color.")
    try:
        rows = []
        query_args = {
            "KeyConditionExpression": Key("pk").eq("LASER_COMMUNITY"),
            "ScanIndexForward": False,
        }
        while True:
            response = table.query(**query_args)
            for community in response.get("Items", []):
                if not _community_exact_match(community.get("laser_source", ""), laser_source):
                    continue
                if not _community_exact_match(community.get("lens_field_of_view", ""), lens_field_of_view):
                    continue
                for entry in community.get("summary", {}).get("entries", []):
                    if not _community_substring_match(entry.get("material", ""), material):
                        continue
                    _, resolved_color = _official_community_swatch(entry)
                    if resolved_color == "Unassigned":
                        continue
                    if not _community_exact_match(resolved_color, color):
                        continue
                    rows.append(_laser_community_row(community, entry))
                    if len(rows) >= limit:
                        return rows
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            query_args["ExclusiveStartKey"] = last_key
        return rows
    except ClientError as error:
        raise RuntimeError("Could not query Comunity Set settings.") from error


def _write_laser_community_record(table, user_id, library_id, summary, laser_source,
                                  lens_field_of_view, notes):
    """Write the anonymous canonical record and all seven possible filter indexes."""
    summary = dict(summary or {})
    summary["entries"] = [
        {**entry, "settings": _community_public_settings(entry.get("settings"))}
        for entry in summary.get("entries", [])
        if isinstance(entry, dict)
    ]
    summary = _annotate_community_swatches(user_id, summary)
    canonical_key = {"pk": "LASER_COMMUNITY", "sk": f"MATERIAL#{library_id}"}
    old_item = table.get_item(Key=canonical_key).get("Item") or {}
    updated_at = int(time.time())
    index_sk = f"UPDATED#{time.time_ns():019d}#MATERIAL#{library_id}"
    partitions = _community_filter_partitions(
        laser_source, lens_field_of_view, summary.get("material_names", []),
    )
    index_keys = [{"pk": partition, "sk": index_sk} for partition in partitions]
    canonical_item = {
        **canonical_key,
        "material_name": ", ".join(summary.get("material_names", []))[:160],
        "laser_source": laser_source,
        "lens_field_of_view": lens_field_of_view,
        "notes": notes,
        "summary": _dynamodb_values(summary),
        "index_keys": index_keys,
        "updated_at": updated_at,
    }
    with table.batch_writer() as batch:
        for old_key in old_item.get("index_keys", []):
            if isinstance(old_key, dict) and old_key.get("pk") and old_key.get("sk"):
                batch.delete_item(Key={"pk": old_key["pk"], "sk": old_key["sk"]})
        batch.put_item(Item=canonical_item)
        for index_key in index_keys:
            batch.put_item(Item={
                **index_key,
                "community_pk": canonical_key["pk"],
                "community_sk": canonical_key["sk"],
                "laser_source": laser_source,
                "lens_field_of_view": lens_field_of_view,
                "material_names": summary.get("material_names", []),
                "updated_at": updated_at,
            })


def rename_user_material_library(user_id, library_id, display_name, laser_source=None,
                                 lens_field_of_view=None, notes=None, laser_community=False,
                                 community_summary=None, library_intent=None):
    table = account_table()
    library = get_user_material_library(user_id, library_id) if table else None
    if not table or not library:
        return False
    display_name = str(display_name or "").strip()
    if not display_name or len(display_name) > 160:
        raise ValueError("Library names must be between 1 and 160 characters.")
    laser_source = str(laser_source or "").strip()
    lens_field_of_view = str(lens_field_of_view or "").strip()
    notes = str(notes or "").strip()
    library_intent = (
        library.get("library_intent", "color_palette")
        if library_intent is None
        else ("hatch_palette" if library_intent == "hatch_palette" else "color_palette")
    )
    # Community contribution is permanent once accepted for this library.
    laser_community = library.get("laser_community") is True or laser_community is True
    if len(laser_source) > 160 or len(lens_field_of_view) > 160 or len(notes) > 1000:
        raise ValueError("Laser Source and Lens Field of View must be 160 characters or fewer, and Notes 1000 characters or fewer.")
    try:
        table.update_item(
            Key={"pk": f"USER#{user_id}", "sk": f"MATERIAL#{library_id}"},
            UpdateExpression="SET #name = :name, laser_source = :laser_source, lens_field_of_view = :lens_field_of_view, notes = :notes, laser_community = :laser_community, library_intent = :library_intent, updated_at = :updated_at",
            ExpressionAttributeNames={"#name": "name"},
            ExpressionAttributeValues={
                ":name": display_name,
                ":laser_source": laser_source,
                ":lens_field_of_view": lens_field_of_view,
                ":notes": notes,
                ":laser_community": laser_community,
                ":library_intent": library_intent,
                ":updated_at": int(time.time()),
            },
        )
        if laser_community:
            # Community records contain useful machine context and settings, but
            # never the owner ID, private object key, filename, or personal name.
            _write_laser_community_record(
                table, user_id, library_id, community_summary or library.get("summary", {}), laser_source,
                lens_field_of_view, notes,
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
        if library.get("laser_community") is True:
            _write_laser_community_record(
                table, user_id, library_id, summary, library.get("laser_source", ""),
                library.get("lens_field_of_view", ""), library.get("notes", ""),
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
        "expires_at": created_at + HISTORY_TTL_SECONDS,
    }
    owner_item = {
        "pk": f"JOB#{task_id}", "sk": "OWNER", "user_id": user_id,
        "created_at": created_at, "updated_at": created_at, "history_sk": history_sk,
        "status": "pending", "artifact_prefix": artifact_prefix,
        "input_keys": list(input_keys or []),
        "expires_at": created_at + HISTORY_TTL_SECONDS,
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
    retention_cutoff = int(time.time()) - HISTORY_TTL_SECONDS
    for item in response.get("Items", []):
        entry = _json_values(item)
        task_id = entry.get("task_id")
        if not task_id:
            continue
        stored_status = sync_job_runtime().status(task_id)
        durable_status = entry.get("status", "pending")
        # Keep account history consistent with S3 lifecycle/manual cleanup,
        # just as the guest history panel already does. Jobs older than the
        # retention window are known to have expired and need no remote S3
        # request. Only an unusual recent row missing Redis status needs an
        # S3 existence check, using the already-known owner prefix directly.
        if not stored_status:
            if int(entry.get("created_at") or 0) <= retention_cutoff:
                continue
            if not task_artifacts_exist(task_id, user_id=user_id):
                continue
        entry["status"] = stored_status or durable_status
        entry.update(job_history_links(entry))
        entries.append(entry)
    return entries


def record_admin_job(payload):
    """Record a global seven-day operational index without artwork or secrets."""
    table = account_table()
    if not table:
        return
    task_id = str(payload.get("task_id") or "")
    if not task_id:
        return
    created_at = int(time.time())
    data = payload.get("data") or {}
    item = {
        "pk": "ADMIN#JOBS",
        "sk": f"JOB#{created_at:010d}#{task_id}",
        "task_id": task_id,
        "created_at": created_at,
        "user_id": str(payload.get("user_id") or "guest"),
        "source_name": str(payload.get("image_name") or "")[:255],
        "material_name": str(data.get("material") or "")[:160],
        "image_preset": str(data.get("image_preset") or "")[:100],
        "status": "pending",
    }
    try:
        table.put_item(Item=item)
    except ClientError as error:
        raise RuntimeError("Could not record the administrative job index.") from error


def list_admin_jobs(days=7):
    """Return indexed jobs and live pre-index jobs, newest first."""
    table = account_table()
    cutoff = int(time.time()) - max(1, int(days)) * 86400
    jobs_by_id = {}
    if table:
        try:
            response = table.query(
                KeyConditionExpression=Key("pk").eq("ADMIN#JOBS") &
                Key("sk").gte(f"JOB#{cutoff:010d}"),
                ScanIndexForward=False,
            )
        except ClientError as error:
            raise RuntimeError("Could not load the administrative job index.") from error
        for raw in response.get("Items", []):
            job = _json_values(raw)
            if job.get("task_id"):
                jobs_by_id[job["task_id"]] = job

    # Backfill the current seven-day window from browser/account history lists
    # created before the global admin index existed. Access-token keys share
    # the prefix but are strings, so inspect list keys only.
    for history_key in redis_client.scan_iter(match="history:*"):
        if history_key.endswith(":access") or redis_client.type(history_key) != "list":
            continue
        for raw_entry in redis_client.lrange(history_key, 0, -1):
            try:
                entry = json.loads(raw_entry)
            except (TypeError, json.JSONDecodeError):
                continue
            task_id = str(entry.get("task_id") or "")
            created_at = int(entry.get("created_at") or 0)
            if not task_id or created_at < cutoff or task_id in jobs_by_id:
                continue
            binding = _job_access_binding(task_id)
            operator = binding[1] if binding and binding[0] == "account" else "guest"
            jobs_by_id[task_id] = {
                "task_id": task_id, "created_at": created_at,
                "user_id": operator,
                "source_name": str(entry.get("source_name") or "")[:255],
                "material_name": str(entry.get("material_name") or "")[:160],
                "image_preset": str(entry.get("image_preset") or "")[:100],
                "status": "pending",
            }

    for queue_name, queue_state in (
        (RASTER_JOB_QUEUE, "pending"),
        (RASTER_JOB_PROCESSING_QUEUE, "processing"),
    ):
        for raw_payload in redis_client.lrange(queue_name, 0, -1):
            try:
                payload = json.loads(raw_payload)
            except (TypeError, json.JSONDecodeError):
                continue
            task_id = str(payload.get("task_id") or "")
            if not task_id or task_id in jobs_by_id:
                continue
            data = payload.get("data") or {}
            jobs_by_id[task_id] = {
                "task_id": task_id, "created_at": 0,
                "user_id": str(payload.get("user_id") or "guest"),
                "source_name": str(payload.get("image_name") or "")[:255],
                "material_name": str(data.get("material") or "")[:160],
                "image_preset": str(data.get("image_preset") or "")[:100],
                "status": queue_state,
            }
    jobs = []
    for job in jobs_by_id.values():
        task_id = job["task_id"]
        job["status"] = sync_job_runtime().status(task_id) or job.get("status", "pending")
        job["queued"] = raster_queue_position(task_id) is not None
        jobs.append(job)
    return sorted(jobs, key=lambda item: int(item.get("created_at") or 0), reverse=True)


def delete_queued_admin_job(task_id):
    """Remove only a waiting job; running jobs require a separate workflow."""
    task_id = str(task_id or "")
    removed = 0
    for raw_payload in redis_client.lrange(RASTER_JOB_QUEUE, 0, -1):
        try:
            matches = str(json.loads(raw_payload).get("task_id") or "") == task_id
        except (TypeError, json.JSONDecodeError):
            matches = False
        if matches:
            removed += redis_client.lrem(RASTER_JOB_QUEUE, 0, raw_payload)
    if not removed:
        return False
    message = "Removed from the waiting queue by an administrator."
    redis_client.set(f"task:{task_id}:status", "failed", ex=HISTORY_TTL_SECONDS)
    redis_client.rpush(f"task:{task_id}:log", message)
    redis_client.expire(f"task:{task_id}:log", HISTORY_TTL_SECONDS)
    update_user_job(task_id, "failed", error_message=message)
    return True


def get_job_owner(task_id):
    record = get_job_record(task_id)
    return record.get("user_id") if record else None


def valid_history_session(value):
    value = str(value or "").strip().lower()
    return value if HISTORY_SESSION_RE.fullmatch(value) else None


def _guest_material_library_entry(payload):
    if not isinstance(payload, dict):
        return None
    filename = os.path.basename(str(payload.get("filename") or "").strip())
    artifact_key = str(payload.get("key") or "").strip()
    local_path = str(payload.get("path") or "").strip()
    if not filename or not (artifact_key or local_path):
        return None
    identifier_seed = artifact_key or local_path
    library_id = str(payload.get("library_id") or uuid.uuid5(
        uuid.NAMESPACE_URL, f"mopa-guest-material:{identifier_seed}",
    ))
    return {
        "library_id": library_id,
        "filename": filename,
        "key": artifact_key,
        "path": local_path,
        "created_at": int(payload.get("created_at") or time.time()),
    }


def _guest_material_library_registry(session_id):
    session_id = valid_history_session(session_id)
    if not session_id:
        return []
    try:
        stored = json.loads(redis_client.get(f"material-libraries:{session_id}") or "[]")
    except (TypeError, json.JSONDecodeError):
        stored = []
    entries, seen = [], set()
    for payload in stored if isinstance(stored, list) else []:
        entry = _guest_material_library_entry(payload)
        if not entry or entry["library_id"] in seen:
            continue
        seen.add(entry["library_id"])
        entries.append(entry)

    # Preserve the pre-registry single remembered library as the first entry
    # so existing guest browser sessions continue working after deployment.
    try:
        legacy = json.loads(redis_client.get(f"material-library:{session_id}") or "{}")
    except (TypeError, json.JSONDecodeError):
        legacy = {}
    legacy_entry = _guest_material_library_entry(legacy)
    if legacy_entry and legacy_entry["library_id"] not in seen:
        entries.insert(0, legacy_entry)
    return entries[:GUEST_MATERIAL_LIBRARY_LIMIT]


def remember_guest_material_library(session_id, payload):
    """Retain a guest upload in the private browser-session library registry."""
    session_id = valid_history_session(session_id)
    entry = _guest_material_library_entry(payload)
    if not session_id or not entry:
        raise ValueError("A valid guest Material Library session and artifact are required.")
    entries = [
        existing for existing in _guest_material_library_registry(session_id)
        if existing["library_id"] != entry["library_id"]
    ]
    entries.insert(0, entry)
    redis_client.set(
        f"material-libraries:{session_id}",
        json.dumps(entries[:GUEST_MATERIAL_LIBRARY_LIMIT], separators=(",", ":")),
        ex=HISTORY_TTL_SECONDS,
    )
    redis_client.set(
        f"material-library:{session_id}",
        json.dumps(entry, separators=(",", ":")),
        ex=HISTORY_TTL_SECONDS,
    )
    return entry


def list_guest_material_libraries(session_id):
    """Return browser-safe metadata for every retained guest library."""
    entries = _guest_material_library_registry(session_id)
    return [{
        "library_id": entry["library_id"],
        "filename": entry["filename"],
        "created_at": entry["created_at"],
    } for entry in entries]


def select_guest_material_library(session_id, library_id):
    """Select one retained guest library and make it the compatibility default."""
    library_id = str(library_id or "").strip()
    for entry in _guest_material_library_registry(session_id):
        if hmac.compare_digest(entry["library_id"], library_id):
            redis_client.set(
                f"material-library:{session_id}",
                json.dumps(entry, separators=(",", ":")),
                ex=HISTORY_TTL_SECONDS,
            )
            return entry
    return None


def claim_history_session(history_session, browser_session):
    """Claim a client history ID for one signed Flask browser session."""
    browser_session = valid_history_session(browser_session)
    if not browser_session:
        raise ValueError("A valid browser session is required for job history.")
    candidate = valid_history_session(history_session) or str(uuid.uuid4())
    runtime = sync_job_runtime()
    if isinstance(runtime, DynamoJobRuntime):
        for _attempt in range(2):
            key = {"pk": f"HISTORY#{candidate}", "sk": "ACCESS"}
            try:
                runtime.table.put_item(
                    Item={**key, "browser_session": browser_session,
                          "expires_at": int(time.time()) + HISTORY_TTL_SECONDS},
                    ConditionExpression="attribute_not_exists(pk)",
                )
                return candidate
            except ClientError as error:
                if error.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                    raise RuntimeError("Could not create a private job-history session.") from error
                item = runtime.table.get_item(Key=key, ConsistentRead=True).get("Item") or {}
                if hmac.compare_digest(str(item.get("browser_session", "")), browser_session):
                    runtime.table.update_item(Key=key, UpdateExpression="SET expires_at=:expiry",
                                              ExpressionAttributeValues={":expiry": int(time.time()) + HISTORY_TTL_SECONDS})
                    return candidate
                candidate = str(uuid.uuid4())
        raise RuntimeError("Could not create a private job-history session.")
    for _attempt in range(2):
        access_key = f"history:{candidate}:access"
        if redis_client.set(access_key, browser_session, ex=HISTORY_TTL_SECONDS, nx=True):
            return candidate
        existing = valid_history_session(redis_client.get(access_key))
        if existing and hmac.compare_digest(existing, browser_session):
            redis_client.expire(access_key, HISTORY_TTL_SECONDS)
            return candidate
        candidate = str(uuid.uuid4())
    raise RuntimeError("Could not create a private job-history session.")


def history_access_allowed(history_session, browser_session):
    history_session = valid_history_session(history_session)
    browser_session = valid_history_session(browser_session)
    if not history_session or not browser_session:
        return False
    runtime = sync_job_runtime()
    if isinstance(runtime, DynamoJobRuntime):
        item = runtime.table.get_item(
            Key={"pk": f"HISTORY#{history_session}", "sk": "ACCESS"}
        ).get("Item") or {}
        expected = valid_history_session(item.get("browser_session"))
    else:
        expected = valid_history_session(redis_client.get(f"history:{history_session}:access"))
    return bool(expected) and hmac.compare_digest(expected, browser_session)


def bind_job_access(task_id, user_id=None, browser_session=None):
    """Bind a job to either its signed-in account or its guest browser session."""
    task_id = valid_history_session(task_id)
    if not task_id:
        raise ValueError("A valid task ID is required for job ownership.")
    user_id = str(user_id or "").strip()
    if user_id:
        binding = {"kind": "account", "value": user_id}
    else:
        browser_session = valid_history_session(browser_session)
        if not browser_session:
            raise ValueError("A valid guest browser session is required for job ownership.")
        binding = {"kind": "guest", "value": browser_session}
    sync_job_runtime().bind_access(task_id, binding["kind"], binding["value"])


def _job_access_binding(task_id):
    binding = sync_job_runtime().access(task_id) or {}
    kind, value = binding.get("kind"), str(binding.get("value") or "").strip()
    if kind == "account" and value:
        return kind, value
    if kind == "guest" and valid_history_session(value):
        return kind, value
    return None


def job_access_allowed(task_id, user_id=None, browser_session=None):
    """Return whether the supplied account or guest session owns a job."""
    task_id = valid_history_session(task_id)
    if not task_id:
        return False
    user_id = str(user_id or "").strip()
    browser_session = valid_history_session(browser_session)

    binding = _job_access_binding(task_id)
    if binding:
        kind, expected_identity = binding
        if kind == "account":
            # This server-issued binding is written when the account job is
            # accepted and expires with its Redis history. Avoid a DynamoDB
            # owner read for every row rendered immediately after submission.
            return bool(user_id) and hmac.compare_digest(expected_identity, user_id)

    # Durable ownership remains authoritative when the binding is absent or
    # claims guest access. An account job must never fall back to guest access.
    owner_id = get_job_owner(task_id)
    if owner_id:
        return bool(user_id) and hmac.compare_digest(str(owner_id), user_id)
    if not binding:
        return False
    _kind, expected_identity = binding
    return bool(browser_session) and hmac.compare_digest(expected_identity, browser_session)


def claim_daily_job(user_id):
    """Atomically claim one authenticated user's daily job allowance."""
    now = datetime.now(timezone.utc)
    day_key = now.strftime("%Y-%m-%d")
    key = f"quota:{user_id}:{day_key}"
    runtime = sync_job_runtime()
    if isinstance(runtime, DynamoJobRuntime):
        expiry = int(((now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0) - datetime(1970, 1, 1, tzinfo=timezone.utc)).total_seconds())
        result = runtime.table.update_item(
            Key={"pk": f"QUOTA#{user_id}#{day_key}", "sk": "USAGE"},
            UpdateExpression="SET used=if_not_exists(used,:zero)+:one, expires_at=:expiry",
            ExpressionAttributeValues={":zero": 0, ":one": 1, ":expiry": expiry},
            ReturnValues="UPDATED_NEW",
        )
        used = int(result["Attributes"]["used"])
        return used <= DAILY_JOB_LIMIT, max(0, DAILY_JOB_LIMIT - used)
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
    runtime = sync_job_runtime()
    if isinstance(runtime, DynamoJobRuntime):
        created_at = int(time.time())
        runtime.table.put_item(Item=_dynamodb_values({
            "pk": f"HISTORY#{session_id}", "sk": f"JOB#{created_at:010d}#{task_id}",
            "task_id": task_id, "source_name": source_name,
            "image_preset": image_preset, "abstract_filter": abstract_filter,
            "material_name": material_name, "run_parameters": run_parameters or {},
            "created_at": created_at, "expires_at": created_at + HISTORY_TTL_SECONDS,
        }))
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
        "white_is": parameters.get("white_is", "engraved"),
        "image_preset": entry.get("image_preset", "cartoon"),
        "colors": parameters.get("colors", []),
        "selected_color_hexes": parameters.get("selected_color_hexes", []),
        "color_name_overrides": parameters.get("color_name_overrides", {}),
        "abstract_filter_parameters": parameters.get("filter_parameters", {}),
        "geometry_style": parameters.get("geometry_style", "vectors"),
        "geometry_style_parameters": parameters.get("geometry_style_parameters", {}),
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
            "reuse_url": "/fauxlographic-etching",
            "reuse_label": "Open Lab",
        }
    return {
        "svg_url": f"/download/{task_id}",
        "lightburn_url": None if parameters.get("svg_only") else f"/download-lbrn2/{task_id}",
        "reuse_url": reuse_settings_url(entry),
        "reuse_label": "Reuse Settings",
    }


def get_history_entries(session_id):
    if not session_id:
        return []
    runtime = sync_job_runtime()
    if isinstance(runtime, DynamoJobRuntime):
        response = runtime.table.query(
            KeyConditionExpression=Key("pk").eq(f"HISTORY#{session_id}") & Key("sk").begins_with("JOB#"),
            ScanIndexForward=False, Limit=99,
        )
        raw_entries = [_json_values(item) for item in response.get("Items", [])]
    else:
        raw_entries = redis_client.lrange(f"history:{session_id}", 0, 98)
    history_key = f"history:{session_id}"
    entries, stale_records = [], []
    for raw_entry in raw_entries:
        try:
            entry = raw_entry if isinstance(raw_entry, dict) else json.loads(raw_entry)
        except (TypeError, json.JSONDecodeError):
            stale_records.append(raw_entry)
            continue
        task_id = entry.get("task_id")
        if not task_id:
            stale_records.append(raw_entry)
            continue
        stored_status = runtime.status(task_id)
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
    if stale_records and isinstance(runtime, RedisJobRuntime):
        pipeline = redis_client.pipeline()
        for raw_entry in stale_records:
            pipeline.lrem(history_key, 0, raw_entry)
        pipeline.execute()
    return entries


def get_accessible_history_entries(session_id, user_id=None, browser_session=None):
    """Return only browser-history rows whose jobs the requester still owns."""
    return [
        entry for entry in get_history_entries(session_id)
        if job_access_allowed(
            entry.get("task_id"), user_id=user_id, browser_session=browser_session,
        )
    ]


def parse_abstract_filter_parameters(raw_value):
    if not raw_value:
        return {}
    try:
        parameters = json.loads(raw_value)
    except json.JSONDecodeError as error:
        raise ValueError("We couldn't read the Image Style settings. Reload Rasterizer, choose the style again, and submit the job again.") from error
    if not isinstance(parameters, dict) or len(parameters) > 20:
        raise ValueError("The Image Style settings could not be read or contain too many controls. Reload Rasterizer, choose the style again, and submit the job again.")
    clean = {}
    for key, value in parameters.items():
        if not isinstance(key, str) or not key.replace("_", "").isalnum():
            raise ValueError("An Image Style control name could not be read. Use Reset settings under Image Style, configure it again, and submit the job again.")
        if key == "material" and value in ("metal", "powdercoat"):
            clean[key] = value
        elif key == "setting_name" and isinstance(value, str) and 1 <= len(value.strip()) <= 80:
            clean[key] = value.strip()
        elif key == "fill_mode" and value in {"from_setting", "fill", "offset_fill", "line"}:
            clean[key] = value
        elif key == "mixing_model" and value in {"lab", "rgb", "hsv"}:
            clean[key] = value
        elif key == "glyph_shape" and value in {
            "circle", "square", "diamond", "triangle", "hexagon", "octagon",
            "star", "cross", "bar", "skull", "heart", "space_invader",
            "ghost", "bat", "alien_head", "paw_print", "fish_scale",
            "puzzle_piece", "mixed",
        }:
            clean[key] = value
        elif key == "cell_shape" and value in {
            "square", "hexagon", "triangle", "diamond", "skull", "heart",
            "space_invader", "ghost", "bat", "alien_head", "paw_print",
            "fish_scale", "puzzle_piece",
        }:
            clean[key] = value
        elif key == "grating_render_mode" and value in {"line", "fill"}:
            clean[key] = value
        elif key in {"transparent", "invert_threshold", "keep_black"} and isinstance(value, bool):
            clean[key] = value
        elif key in {"transparent", "invert_threshold", "keep_black"} and isinstance(value, str) and value.lower() in ("true", "false"):
            # Form submissions from an older cached page can serialize a
            # checkbox as text. Normalize it to the same boolean used by the
            # current JSON-producing UI.
            clean[key] = value.lower() == "true"
        elif key in {"square_dots", "invert", "black_only", "keep_available_colors_as_vectors", "preserve_black", "tight_pack_geometry", "random_rotation"} and isinstance(value, str) and value.lower() in ("true", "false"):
            clean[key] = int(value.lower() == "true")
        elif key in {"transparent", "invert_threshold", "keep_black", "square_dots", "invert", "black_only", "keep_available_colors_as_vectors", "preserve_black", "tight_pack_geometry", "random_rotation"} and isinstance(value, bool):
            clean[key] = int(value)
        elif isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Image Style control '{key[:60]}' needs a number. Adjust that control or use Reset settings, then submit the job again.")
        else:
            clean[key] = value
    return clean


def parse_geometry_style_parameters(raw_value):
    if not raw_value:
        return {}
    try:
        parameters = json.loads(raw_value) if isinstance(raw_value, str) else raw_value
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("We couldn't read the Geometry Style settings. Reload Rasterizer, choose the geometry again, and submit the job again.") from error
    if not isinstance(parameters, dict):
        raise ValueError("The Geometry Style settings could not be read. Use Reset geometry settings, configure the geometry again, and submit the job again.")
    # Compatibility with the short-lived Krasnow Geometry posterization
    # control. Cached staging pages and persisted form snapshots can continue
    # sending it after removal; it no longer changes processing and must not
    # make an otherwise valid job fail.
    parameters = dict(parameters)
    parameters.pop("posterize_colors", None)
    if len(parameters) > 24:
        raise ValueError("The Geometry Style settings contain too many controls. Use Reset geometry settings, configure the geometry again, and submit the job again.")
    if any(key in parameters for key in ("assignments", "glyphs", "halftone_newsprint", "krasnow_grating")):
        if set(parameters) - {"assignments", "glyphs", "halftone_newsprint", "krasnow_grating"}:
            raise ValueError("Choose-by-Swatch geometry settings could not be read. Use Reset geometry settings, review the swatch routing, and submit again.")
        assignments = parameters.get("assignments") or {}
        if not isinstance(assignments, dict) or len(assignments) > 64:
            raise ValueError("Choose-by-Swatch routing could not be read or has too many assignments. Reload Rasterizer, review the swatch routing, and submit again.")
        clean_assignments = {}
        for color_hex, style in assignments.items():
            color_hex = str(color_hex).strip().upper()
            style = str(style).strip().lower()
            if not re.fullmatch(r"#[0-9A-F]{6}", color_hex):
                raise ValueError("A Choose-by-Swatch color could not be read. Reload Rasterizer, review the swatch routing, and submit again.")
            if style not in {"vectors", "glyphs", "halftone_newsprint", "krasnow_grating"}:
                raise ValueError(f"Choose-by-Swatch routing for {color_hex} has an unsupported geometry. Choose Vectors, Glyphs, Halftone Newsprint, or Krasnow and submit again.")
            clean_assignments[color_hex] = style
        clean_assignments["#000000"] = "vectors"
        used_styles = set(clean_assignments.values())
        clean = {"assignments": clean_assignments}
        if "glyphs" in used_styles:
            clean["glyphs"] = parse_geometry_style_parameters(
                parameters.get("glyphs") or {}
            )
        if "halftone_newsprint" in used_styles:
            clean["halftone_newsprint"] = parse_geometry_style_parameters(
                parameters.get("halftone_newsprint") or {}
            )
        if "krasnow_grating" in used_styles:
            clean["krasnow_grating"] = parse_geometry_style_parameters(
                parameters.get("krasnow_grating") or {}
            )
        return clean
    numeric = {
        "cell_size_mm", "minimum_glyph_ratio", "maximum_glyph_ratio",
        "non_black_glyph_density", "minimum_dot_ratio", "maximum_dot_ratio",
        "non_black_dot_density", "tone_curve", "contrast", "grid_angle",
        "glyph_rotation", "seed", "speed_spread", "gradient_top",
        "gradient_bottom", "gradient_curve", "hue_rotation",
        "saturation_cutoff", "patch_size_mm", "line_spacing_mm",
        "hue_line_spacing_minimum_mm", "hue_line_spacing_maximum_mm",
        "angle_min", "angle_max", "custom_glyph_threshold",
        "custom_glyph_padding", "custom_cell_padding",
    }
    toggles = {
        "invert", "invert_fill", "black_only", "square_dots", "preserve_black",
        "custom_glyph_invert", "tight_pack_geometry", "random_rotation",
    }
    shapes = {
        "circle", "square", "diamond", "triangle", "hexagon", "octagon",
        "star", "cross", "bar", "skull", "heart", "space_invader",
        "ghost", "bat", "alien_head", "paw_print", "fish_scale",
        "puzzle_piece", "mixed", "custom",
    }
    cell_shapes = {
        "square", "hexagon", "triangle", "diamond", "skull", "heart",
        "space_invader", "ghost", "bat", "alien_head", "paw_print",
        "fish_scale", "puzzle_piece", "custom",
    }
    gradient_scopes = {"entire_artwork", "each_shape"}
    glyph_size_sources = {"source_brightness", "seeded_variation"}
    grating_render_modes = {"line", "fill"}
    gradient_directions = {
        "top_to_bottom", "bottom_to_top", "left_to_right", "right_to_left",
        "center_to_edge", "edge_to_center",
    }
    clean = {}
    def compact_mask(candidate, *, flow_region_number=None):
        message = (
            f"Fauxlogram Flow Painter region {flow_region_number}'s image mask couldn't be used. "
            "Remove the mask and add a PNG, JPEG, or WebP image again."
            if flow_region_number is not None else
            "The custom glyph image couldn't be used. Remove it and choose a PNG, "
            "JPEG, or WebP image again."
        )
        if not isinstance(candidate, dict) or set(candidate) != {"width", "height", "data"}:
            raise ValueError(message)
        width = candidate.get("width")
        height = candidate.get("height")
        encoded = candidate.get("data")
        if (
            isinstance(width, bool) or not isinstance(width, int) or not 8 <= width <= 128
            or isinstance(height, bool) or not isinstance(height, int) or not 8 <= height <= 128
            or not isinstance(encoded, str) or len(encoded) > 21856
        ):
            raise ValueError(message)
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except Exception as error:
            raise ValueError(message) from error
        if len(decoded) != width * height:
            raise ValueError(message)
        return {"width": width, "height": height, "data": encoded}
    def compact_svg(candidate, label):
        message = (
            f"The custom {label} SVG couldn't be used. Choose a plain SVG "
            "containing one or more closed vector shapes."
        )
        if not isinstance(candidate, dict) or set(candidate) - {"name", "svg"}:
            raise ValueError(message)
        svg_text = candidate.get("svg")
        if not isinstance(svg_text, str) or not svg_text.strip() or len(svg_text) > 65_536:
            raise ValueError(message)
        lowered = svg_text.lower()
        if not re.search(r"<svg(?:\s|>)", lowered) or any(token in lowered for token in (
            "<!doctype", "<!entity", "<script", "<foreignobject", "<image",
            "<use", "javascript:", "data:", "url(", "href=", "xlink:href=",
        )):
            raise ValueError(message)
        return {
            "name": str(candidate.get("name") or f"custom-{label}.svg")[:120],
            "svg": svg_text,
        }
    for key, value in parameters.items():
        if key == "glyph_shape" and value in shapes:
            clean[key] = value
        elif key == "glyph_size_source" and value in glyph_size_sources:
            clean[key] = value
        elif key == "dot_size_source" and value in glyph_size_sources:
            clean[key] = value
        elif key == "cell_shape" and value in cell_shapes:
            clean[key] = value
        elif key == "grating_render_mode" and value in grating_render_modes:
            clean[key] = value
        elif key == "fauxlogram_gradient_scope" and value in gradient_scopes:
            clean[key] = value
        elif key == "fauxlogram_gradient_direction" and value in gradient_directions:
            clean[key] = value
        elif key == "fauxlogram_flow":
            if not isinstance(value, dict):
                raise ValueError("Fauxlogram Flow Painter settings could not be read. Use Reset geometry settings and rebuild the flow setup.")
            regions = value.get("regions") or []
            strokes = value.get("strokes") or []
            if not isinstance(regions, list) or not 1 <= len(regions) <= 8:
                raise ValueError("Fauxlogram Flow Painter needs 1 to 8 regions. Reopen the painter and adjust the regions, or use Reset geometry settings if it won't open.")
            if not isinstance(strokes, list) or len(strokes) > 256:
                raise ValueError("Fauxlogram Flow Painter supports at most 256 brush strokes. Reopen the painter and clear or simplify painted regions.")
            def flow_number(candidate, default, minimum, maximum):
                try:
                    candidate = float(candidate)
                except (TypeError, ValueError):
                    candidate = default
                if not math.isfinite(candidate):
                    candidate = default
                return min(maximum, max(minimum, candidate))
            clean_regions = []
            for region_number, region in enumerate(regions, start=1):
                if not isinstance(region, dict):
                    raise ValueError(
                        f"Fauxlogram Flow Painter region {region_number} could not be read. "
                        "Reopen the painter and recreate that region. If the painter won't open, "
                        "use Reset geometry settings and rebuild the flow setup."
                    )
                scope = str(region.get("scope") or "combined_region")
                region_type = str(region.get("region_type") or "painted")
                guide_type = str(region.get("guide_type") or "linear")
                orientation = str(region.get("orientation") or "parallel")
                if region_type not in {"painted", "image_mask"}:
                    raise ValueError(
                        f"Fauxlogram Flow Painter region {region_number} has an unsupported region type. "
                        "Reopen the painter and recreate that region. If the painter won't open, "
                        "use Reset geometry settings and rebuild the flow setup."
                    )
                if scope not in {"combined_region", "each_shape", "entire_artwork"}:
                    raise ValueError(
                        f"Fauxlogram Flow Painter region {region_number} has an invalid Gradient scope. "
                        "Reopen the painter and choose a valid Gradient scope for that region. "
                        "If the painter won't open, use Reset geometry settings and rebuild the flow setup."
                    )
                if guide_type not in {"linear", "radial"}:
                    raise ValueError(
                        f"Fauxlogram Flow Painter region {region_number} has an invalid Guide type. "
                        "Reopen the painter and choose Linear or Radial for that region. "
                        "If the painter won't open, use Reset geometry settings and rebuild the flow setup."
                    )
                if orientation not in {"parallel", "perpendicular", "fixed", "offset"}:
                    raise ValueError(
                        f"Fauxlogram Flow Painter region {region_number} has an invalid Grating orientation. "
                        "Reopen the painter and choose a Grating orientation for that region. "
                        "If the painter won't open, use Reset geometry settings and rebuild the flow setup."
                    )
                def point(name, fallback):
                    candidate = region.get(name, fallback)
                    message = (
                        f"Fauxlogram Flow Painter region {region_number} has an invalid guide position. "
                        "Reopen the painter and redraw that region's guide. If the painter won't open, "
                        "use Reset geometry settings and rebuild the flow setup."
                    )
                    if not isinstance(candidate, list) or len(candidate) != 2:
                        raise ValueError(message)
                    try:
                        numbers = [float(item) for item in candidate]
                    except (TypeError, ValueError) as error:
                        raise ValueError(message) from error
                    if any(not math.isfinite(item) or not 0 <= item <= 1 for item in numbers):
                        raise ValueError(message)
                    return numbers
                clean_region = {
                    "name": str(region.get("name") or f"Region {len(clean_regions)+1}")[:40],
                    "region_type": region_type, "scope": scope, "guide_type": guide_type,
                    "orientation": orientation,
                    "start": point("start", [.25, .5]), "end": point("end", [.75, .5]),
                    "gradient_start": flow_number(region.get("gradient_start"), 165, 0, 255),
                    "gradient_end": flow_number(region.get("gradient_end"), 90, 0, 255),
                    "curve": flow_number(region.get("curve"), 1, .2, 5),
                    "fixed_angle": flow_number(region.get("fixed_angle"), 0, -180, 180),
                    "angle_offset": flow_number(region.get("angle_offset"), 0, -180, 180),
                    "reverse": bool(region.get("reverse")),
                }
                if region.get("mask") is not None:
                    mode = str(region.get("mask_mode") or "silhouette")
                    if mode not in {"silhouette", "grayscale"}:
                        raise ValueError(
                            f"Fauxlogram Flow Painter region {region_number} has an invalid mask Interpretation. "
                            "Reopen the painter and choose Grayscale gradient map or Silhouette for that region."
                        )
                    offset = region.get("mask_offset", [0, 0])
                    if not isinstance(offset, list) or len(offset) != 2:
                        raise ValueError(
                            f"Fauxlogram Flow Painter region {region_number} has an invalid mask position. "
                            "Reopen the painter and reposition that region's mask, or remove and add the mask again."
                        )
                    clean_region.update({
                        "mask": compact_mask(region.get("mask"), flow_region_number=region_number),
                        "mask_name": str(region.get("mask_name") or "")[:120],
                        "mask_mode": mode,
                        "mask_threshold": flow_number(region.get("mask_threshold"), .5, 0, 1),
                        "mask_invert": bool(region.get("mask_invert")),
                        "mask_offset": [
                            flow_number(offset[0], 0, -1, 1),
                            flow_number(offset[1], 0, -1, 1),
                        ],
                    })
                clean_regions.append(clean_region)
            clean_strokes, point_count = [], 0
            for stroke_number, stroke in enumerate(strokes, start=1):
                if not isinstance(stroke, dict):
                    raise ValueError(
                        f"Fauxlogram Flow Painter brush stroke {stroke_number} could not be read. "
                        "Reopen the painter and clear the affected region, then paint it again."
                    )
                region_index = stroke.get("region")
                points = stroke.get("points") or []
                if not isinstance(region_index, int) or not 0 <= region_index < len(clean_regions):
                    raise ValueError(
                        f"Fauxlogram Flow Painter brush stroke {stroke_number} refers to a region that is no longer available. "
                        "Use Reset geometry settings and rebuild the flow setup."
                    )
                if not isinstance(points, list) or not 1 <= len(points) <= 512:
                    raise ValueError(
                        f"Fauxlogram Flow Painter brush stroke {stroke_number} could not be read. "
                        "Reopen the painter and clear the affected region, then paint it again."
                    )
                clean_points = []
                for candidate in points:
                    message = (
                        f"Fauxlogram Flow Painter brush stroke {stroke_number} has an invalid point. "
                        "Reopen the painter and clear the affected region, then paint it again."
                    )
                    if not isinstance(candidate, list) or len(candidate) != 2:
                        raise ValueError(message)
                    try:
                        coordinates = [float(item) for item in candidate]
                    except (TypeError, ValueError) as error:
                        raise ValueError(message) from error
                    if any(not math.isfinite(item) or not 0 <= item <= 1 for item in coordinates):
                        raise ValueError(message)
                    clean_points.append(coordinates)
                point_count += len(clean_points)
                if point_count > 4000:
                    raise ValueError("Fauxlogram Flow Painter supports at most 4,000 brush points. Reopen the painter and clear or simplify painted regions.")
                clean_strokes.append({
                    "region": region_index,
                    "erase": bool(stroke.get("erase")),
                    "width": flow_number(stroke.get("width"), .08, .002, .5),
                    "points": clean_points,
                })
            clean[key] = {
                "enabled": bool(value.get("enabled", True)),
                "regions": clean_regions,
                "strokes": clean_strokes,
            }
        elif key == "custom_glyph_mask":
            clean[key] = compact_mask(value)
        elif key == "custom_glyph_svg":
            clean[key] = compact_svg(value, "glyph")
        elif key == "custom_cell_svg":
            clean[key] = compact_svg(value, "cell")
        elif key in toggles and isinstance(value, bool):
            clean[key] = int(value)
        elif key in toggles and isinstance(value, int) and value in {0, 1}:
            clean[key] = value
        elif key in toggles and isinstance(value, str) and value.lower() in {"true", "false"}:
            clean[key] = int(value.lower() == "true")
        elif key in numeric and not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value):
            clean[key] = value
        else:
            raise ValueError(f"Geometry Style control '{str(key)[:60]}' has an invalid value. Use Reset geometry settings, configure it again, and submit the job again.")
    if clean.get("invert_fill") and clean.get("black_only"):
        raise ValueError("Invert Fill and Black Only cannot be used together. Turn off one of those Geometry Style controls and submit again.")
    if clean.get("glyph_shape") == "custom" and not (
        clean.get("custom_glyph_mask") or clean.get("custom_glyph_svg")
    ):
        raise ValueError("Upload a custom glyph image or SVG before submitting the job.")
    if clean.get("cell_shape") == "custom" and not clean.get("custom_cell_svg"):
        raise ValueError("Upload a custom cell SVG before submitting the job.")
    return clean


def parse_color_name_overrides(raw_value):
    if not raw_value:
        return {}
    try:
        overrides = json.loads(raw_value)
    except json.JSONDecodeError as error:
        raise ValueError("We couldn't read the selected swatch names. Reload Rasterizer, review the swatch assignments, and submit the job again.") from error
    if not isinstance(overrides, dict) or len(overrides) > 64:
        raise ValueError("The selected swatch names could not be read or exceed the supported limit. Reload Rasterizer, review the swatch assignments, and submit the job again.")
    clean, seen_names = {}, set()
    for color_hex, name in overrides.items():
        normalized_hex = str(color_hex).strip().upper()
        normalized_name = str(name).strip()
        if not re.fullmatch(r"#[0-9A-F]{6}", normalized_hex):
            raise ValueError(f"Swatch color '{str(color_hex)[:40]}' is invalid. Reload Rasterizer and select the swatch again.")
        if not normalized_name or len(normalized_name) > 80 or "," in normalized_name:
            raise ValueError(f"The name for swatch {normalized_hex} must be 1–80 characters without commas. Edit that swatch name and submit again.")
        name_key = normalized_name.casefold()
        if name_key in seen_names:
            raise ValueError(f"More than one swatch uses the Material Library name '{normalized_name}'. Give each swatch a distinct name and submit again.")
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


def upload_task_artifact(task_id, local_file_path, category="outputs", user_id=None, guest=False):
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
        elif guest:
            upload_args["ExtraArgs"] = {"Tagging": "mopa-retention=guest"}
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


def task_artifacts_exist(task_id, user_id=None):
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
            Prefix=_task_artifact_prefix(task_id, user_id=user_id),
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


def summarize_job_failure(error, exit_code=None):
    """Keep actionable validation errors, but summarize unexpected worker failures."""
    if exit_code in (-9, 137):
        return (
            "The job stopped unexpectedly, possibly because the worker ran out of memory. "
            "Try a smaller output size or a larger pixel size. If it happens again, report the job ID."
        )
    message = str(error or "").strip()
    validation = re.fullmatch(r"ValueError:\s*(.+)", message)
    if validation:
        message = validation.group(1)
    if message.startswith("source-derived Black residual-overlap correction failed"):
        return (
            "We couldn't safely separate the Black layer from the other engraved layers. "
            "Try the job again. If it happens again, report the job ID; the technical details remain in the logs."
        )
    if message.startswith((
        "Krasnow reserved Black mask does not match",
        "Artwork transparency mask does not match",
        "Source and quantized palette images must have matching dimensions",
    )):
        return (
            "Image processing stopped unexpectedly. Try the job again. "
            "If it happens again, report the job ID; the technical details remain in the logs."
        )
    if isinstance(error, ValueError) and message:
        return message
    if exit_code == 2 and message:
        return message
    if validation:
        return message
    return (
        "We couldn't finish this job because processing stopped unexpectedly. "
        "Try again. If it happens again, report the job ID."
    )


def long_running_script(task_id, data, image_path, material_settings_path, upload_folder,
                        user_id=None, output_name=None, guest_job=False,
                        guest_quota_visitor="", guest_quota_day="",
                        guest_daily_job_limit=0):
    try:
        job_runtime.set_status(task_id, "processing")
        image_preset = str(data.get("image_preset", "cartoon")).strip().lower()
        svg_only = str(data.get("svg_only", "false")).strip().lower() in ("true", "1", "yes", "on")
        material_name = str(data.get("material", "stainless - steel")).strip().lower()
        if not material_name and not svg_only:
            raise ValueError("Choose or enter a material name")
        abstract_filter = str(data.get("abstract_filter", "none")).strip().lower()
        if image_preset.startswith(ABSTRACT_PRESET_PREFIX):
            abstract_filter = image_preset.removeprefix(ABSTRACT_PRESET_PREFIX)
            image_preset = "abstract"
        if image_preset != "abstract" or abstract_filter not in ABSTRACT_FILTER_NAMES:
            abstract_filter = "none"
        geometry_style = str(data.get("geometry_style", "vectors")).strip().lower()
        if geometry_style not in {"vectors", "glyphs", "halftone_newsprint", "krasnow_grating", "by_swatch"}:
            raise ValueError("Choose a valid geometry style")
        if geometry_style in {"glyphs", "halftone_newsprint", "krasnow_grating", "by_swatch"} and abstract_filter in {
            "optical_color_mix",
        }:
            raise ValueError("This Geometry Style is not available with the selected specialized image style")
        geometry_parameters = parse_geometry_style_parameters(
            data.get("geometry_style_parameters", "{}")
        )
        command = [
            "python", "-u", "lib/Material_Library.py", image_path,
            os.path.join(
                upload_folder,
                output_name or tasks.get(f"{task_id}_filename")
                or f"output_{task_id}_{os.path.basename(image_path)}",
            ),
            str(data.get("pixel_square_mm", "1")), str(normalize_dimension(data.get("new_width"))),
            str(normalize_dimension(data.get("new_height"))), material_settings_path or "-",
            material_name, str(data.get("colors", "")), image_preset, abstract_filter,
            json.dumps(parse_abstract_filter_parameters(data.get("abstract_filter_parameters", "{}")), separators=(",", ":")),
            json.dumps(parse_color_name_overrides(data.get("color_name_overrides", "{}")), separators=(",", ":")),
            "true" if svg_only else "false",
            json.dumps({
                "color_matching_mode": data.get("color_matching_mode", "balanced"),
                "color_matching_hue_weight": data.get("color_matching_hue_weight", 4.0),
                "color_matching_saturation_weight": data.get("color_matching_saturation_weight", 1.0),
                "color_matching_lightness_weight": data.get("color_matching_lightness_weight", 1.0),
            }, separators=(",", ":")),
            "false",
            geometry_style,
            json.dumps(geometry_parameters, separators=(",", ":")),
            str(data.get("crop_shape", "")).strip().lower(),
            str(data.get("white_is", "engraved")).strip().lower(),
            json.dumps(data.get("panel_tiling") or {"enabled": False}, separators=(",", ":")),
        ]

        def run_process(arguments):
            process = subprocess.Popen(
                arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            current_line, last_line = [], ""
            while True:
                char = process.stdout.read(1)
                if not char and process.poll() is not None:
                    break
                if char:
                    if char in ("\n", "\r"):
                        line = "".join(current_line).strip()
                        if line:
                            last_line = line
                            job_runtime.append_log(task_id, line)
                        current_line = []
                    else:
                        current_line.append(char)
            line = "".join(current_line).strip()
            if line:
                last_line = line
                job_runtime.append_log(task_id, line)
            return process.wait(), last_line

        if guest_job:
            job_runtime.append_log(
                task_id,
                "Validating artwork, parameters, Material Library, and material before counting this guest job.",
            )
            validation_command = list(command)
            validation_command[17] = "true"
            validation_exit, validation_message = run_process(validation_command)
            if validation_exit != 0:
                failure_message = summarize_job_failure(validation_message, validation_exit)
                job_runtime.set_status(task_id, "failed", error=failure_message)
                job_runtime.append_log(
                    task_id,
                    f"ERROR: Guest input validation exited with code {validation_exit}: {validation_message}",
                )
                return
            quota_context_present = bool(
                guest_quota_visitor and guest_quota_day and int(guest_daily_job_limit or 0) > 0
            )
            if not quota_context_present:
                # Jobs accepted by the immediately preceding API revision were
                # already charged at submission time. Let those in-flight jobs
                # finish without charging or rejecting them a second time.
                job_runtime.append_log(
                    task_id,
                    "Input validation passed. This pre-update guest job retains its original quota claim.",
                )
            elif not job_runtime.claim_guest_quota(
                task_id, guest_quota_visitor, guest_quota_day, guest_daily_job_limit,
            ):
                failure_message = (
                    f"Guest limit reached ({int(guest_daily_job_limit or 0)} validated jobs per day). "
                    "Sign in to continue."
                )
                job_runtime.set_status(task_id, "failed", error=failure_message)
                job_runtime.append_log(task_id, f"ERROR: {failure_message}")
                return
            else:
                job_runtime.append_log(task_id, "Input validation passed. This guest job now counts toward today's limit.")

        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        current_line = []
        last_process_line = ""
        while True:
            char = process.stdout.read(1)
            if not char and process.poll() is not None:
                break
            if char:
                if char in ("\n", "\r"):
                    line = "".join(current_line).strip()
                    if line:
                        last_process_line = line
                        job_runtime.append_log(task_id, line)
                    current_line = []
                else:
                    current_line.append(char)
        line = "".join(current_line).strip()
        if line:
            last_process_line = line
            job_runtime.append_log(task_id, line)
        exit_code = process.wait()
        if exit_code == 0:
            output_paths = glob.glob(os.path.join(upload_folder, f"output_{task_id}_*"))
            output_keys = []
            for output_path in output_paths:
                if os.path.isfile(output_path):
                    key = upload_task_artifact(
                        task_id, output_path, user_id=user_id, guest=guest_job,
                    )
                    if key:
                        output_keys.append(key)
            job_runtime.set_status(task_id, "completed")
            try:
                update_user_job(task_id, "completed", output_keys=output_keys)
            except RuntimeError as status_error:
                print(f"[Thread-{task_id}] Could not save durable completion state: {status_error}", flush=True)
        else:
            failure_message = summarize_job_failure(last_process_line, exit_code)
            job_runtime.set_status(task_id, "failed", error=failure_message)
            job_runtime.append_log(
                task_id,
                f"ERROR: Rasterizer exited with code {exit_code}: {last_process_line}",
            )
            try:
                update_user_job(task_id, "failed", error_message=failure_message)
            except RuntimeError as status_error:
                print(f"[Thread-{task_id}] Could not save durable failure state: {status_error}", flush=True)
    except Exception as error:
        print(f"[Thread-{task_id}] Exception: {error}", flush=True)
        failure_message = summarize_job_failure(error)
        job_runtime.set_status(task_id, "failed", error=failure_message)
        job_runtime.append_log(task_id, f"ERROR: Artifact processing failed: {error}")
        tasks[f"{task_id}_status"] = "failed"
        tasks[f"{task_id}_error"] = str(error)
        try:
            update_user_job(task_id, "failed", error_message=failure_message)
        except RuntimeError as status_error:
            print(f"[Thread-{task_id}] Could not save durable failure state: {status_error}", flush=True)
    finally:
        pass


def store_and_enqueue_job(payload):
    """Persist a task-addressable envelope, then publish its task ID."""
    task_id = str(payload["task_id"])
    runtime = sync_job_runtime()
    raw_payload = json.dumps(payload, separators=(",", ":"))
    if isinstance(runtime, RedisJobRuntime):
        # Preserve the production Redis transaction and its established tests.
        pipeline = redis_client.pipeline()
        pipeline.set(f"{RASTER_JOB_PAYLOAD_PREFIX}{task_id}", raw_payload, ex=HISTORY_TTL_SECONDS)
        if not SQS_QUEUE_URL and not FARGATE_DISPATCH_VIA_S3:
            pipeline.lpush(RASTER_JOB_QUEUE, raw_payload)
        pipeline.execute()
    else:
        runtime.put_payload(task_id, payload)
    if FARGATE_DISPATCH_VIA_S3:
        try:
            s3_client.put_object(
                Bucket=S3_BUCKET_NAME,
                Key=f"jobs/{task_id}/dispatch.ready",
                Body=b"",
                ContentType="application/x-mopa-raster-dispatch",
            )
        except Exception as error:
            raise RuntimeError("Could not publish the raster task through S3") from error
    elif SQS_QUEUE_URL:
        try:
            message_body = (
                task_id if isinstance(runtime, RedisJobRuntime)
                else json.dumps({"task_id": task_id}, separators=(",", ":"))
            )
            sqs_client.send_message(
                QueueUrl=SQS_QUEUE_URL,
                MessageBody=message_body,
            )
        except Exception as error:
            raise RuntimeError("Could not publish the raster task to SQS") from error
    return raw_payload


def enqueue_raster_job(task_id, data, image_key, material_key, output_name,
                       image_name, material_name, user_id=None):
    """Place a portable raster job on Redis for the dedicated worker pod."""
    svg_only = str(data.get("svg_only", "false")).strip().lower() in ("true", "1", "yes", "on")
    if not image_key or (not svg_only and not material_key):
        raise RuntimeError("Queued raster jobs require their durable input artifacts")
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
    try:
        record_admin_job(payload)
    except RuntimeError as error:
        # Administrative indexing must never prevent an otherwise valid job
        # from reaching a worker.
        print(f"[Task {task_id}] Could not update admin job index: {error}", flush=True)
    store_and_enqueue_job(payload)
    sync_job_runtime().append_log(task_id, "Job accepted. Starting a raster worker...")


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
    redis_client.expire(f"task:{task_id}:access", HISTORY_TTL_SECONDS)
