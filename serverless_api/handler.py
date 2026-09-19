"""Account and capability-authorized staging API for direct browser-to-S3 jobs."""

import base64
import hashlib
import json
import math
import mimetypes
import os
import secrets
import time
import uuid
import re
from copy import deepcopy
from decimal import Decimal
from urllib.parse import unquote
from xml.etree import ElementTree as ET

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config
from botocore.exceptions import ClientError


REGION = os.environ.get("AWS_REGION", "us-east-2")
BUCKET = os.environ["S3_BUCKET_NAME"]
TABLE_NAME = os.environ["JOB_RUNTIME_TABLE_NAME"]
QUEUE_URL = os.environ["SQS_QUEUE_URL"]
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "").strip().casefold()
COGNITO_USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "").strip()
TTL_SECONDS = int(os.environ.get("JOB_TTL_SECONDS", "604800"))
MAX_ARTWORK_BYTES = int(os.environ.get("MAX_ARTWORK_BYTES", str(100 * 1024 * 1024)))
MAX_MATERIAL_BYTES = int(os.environ.get("MAX_MATERIAL_BYTES", str(10 * 1024 * 1024)))
MATERIAL_LIMIT_MB = f"{MAX_MATERIAL_BYTES / (1024 * 1024):g} MB"
MAX_RECIPE_BYTES = int(os.environ.get("MAX_RECIPE_BYTES", str(10 * 1024 * 1024)))
UPLOAD_CAPABILITY_SECONDS = 600
GUEST_JOB_SECONDS = int(os.environ.get("GUEST_JOB_SECONDS", str(24 * 3600)))
GUEST_DAILY_JOB_LIMIT = int(os.environ.get("GUEST_DAILY_JOB_LIMIT", "5"))
GUEST_ACCESS_ENABLED = os.environ.get("GUEST_ACCESS_ENABLED", "true").strip().casefold() == "true"
ALLOWED_USER_SUB = os.environ.get("ALLOWED_USER_SUB", "").strip()
GUEST_QUOTA_SALT = os.environ.get("GUEST_QUOTA_SALT", TABLE_NAME)
ARTWORK_TELEMETRY_SECONDS = int(os.environ.get("ARTWORK_TELEMETRY_SECONDS", str(30 * 86400)))
WORKER_LOG_GROUP_NAME = os.environ.get("WORKER_LOG_GROUP_NAME", "").strip()
PIPE_NAME = os.environ.get("WORKER_PIPE_NAME", "").strip()
MAX_JOB_LOG_EVENTS = max(1, min(10000, int(os.environ.get("MAX_JOB_LOG_EVENTS", "10000"))))

s3 = boto3.client(
    "s3", region_name=REGION,
    endpoint_url=f"https://s3.{REGION}.amazonaws.com",
    config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
)
sqs = boto3.client("sqs", region_name=REGION)
cognito = boto3.client("cognito-idp", region_name=REGION)
cloudwatch_logs = boto3.client("logs", region_name=REGION)
pipes = boto3.client("pipes", region_name=REGION)
table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)

SERVICE_CONTROL_KEY = {"pk": "SYSTEM#SERVICE", "sk": "CONTROL"}

PALETTE = [
    ("Black", "#000000"), ("Blue", "#0000FF"), ("Red", "#FF0000"),
    ("Green", "#00E000"), ("Yellow", "#D0D000"), ("Orange", "#FF8000"),
    ("Cyan", "#00E0E0"), ("Magenta", "#FF00FF"), ("Light-Gray", "#B4B4B4"),
    ("Dark-Blue", "#0000A0"), ("Dark-Red", "#A00000"), ("Dark-Green", "#00A000"),
    ("Dark-Yellow", "#A0A000"), ("Dark-Orange", "#C08000"), ("Light-Blue", "#00A0FF"),
    ("Dark-Magenta", "#A000A0"), ("Medium-Gray", "#808080"), ("Slate-Blue", "#7D87B9"),
    ("Rose", "#BB7784"), ("Periwinkle-Blue", "#4A6FE3"), ("Raspberry", "#D33F6A"),
    ("Sage-Green", "#8CD78C"), ("Peach", "#F0B98D"), ("Light-Pink", "#F6C4E1"),
    ("Orchid-Pink", "#FA9ED4"), ("Deep-Purple", "#500A78"), ("Rust-Brown", "#B45A00"),
    ("Teal", "#004754"), ("Bright-Mint-Green", "#86FA88"), ("Light-Gold", "#FFDB66"),
]
MAX_LIGHTBURN_LAYERS = len(PALETTE)
PALETTE_HEX = {name.casefold(): color for name, color in PALETTE}
PALETTE_NAMES = {color.upper(): name for name, color in PALETTE}
RASTER_PRESETS = {"cartoon", "color_photograph", "bw_dither_photograph"}
ABSTRACT_FILTERS = {
    "wave", "voronoi", "shear", "spiral", "mosaic", "crystal", "ripple",
    "glitch", "deep_fryer", "shattered", "halftone_newsprint", "optical_color_mix",
    "krasnow_grating", "structure_tensor_flow", "none",
}


def response(status, body):
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", "cache-control": "no-store"},
        "body": json.dumps(body, separators=(",", ":"), default=str),
    }


def visible_job_logs(items, error_message=""):
    """Return retained logs with a terminal failure reason visible exactly once."""
    messages = [
        str(item.get("message") or "") if isinstance(item, dict) else str(item or "")
        for item in items
    ]
    failure = str(error_message or "").strip()
    if failure and not any(failure in message for message in messages):
        messages.append(f"ERROR: {failure}")
    return messages


def job_logs(task_id, live):
    """Read new serverless logs from CloudWatch, retaining DynamoDB compatibility."""
    stream = str((live or {}).get("cloudwatch_log_stream") or "").strip()
    item_group = str((live or {}).get("cloudwatch_log_group") or "").strip()
    if stream and WORKER_LOG_GROUP_NAME and item_group == WORKER_LOG_GROUP_NAME:
        messages = []
        token = None
        pages = 0
        prefix = f"[Task {task_id}] "
        try:
            while len(messages) < MAX_JOB_LOG_EVENTS and pages < 20:
                options = {
                    "logGroupName": WORKER_LOG_GROUP_NAME,
                    "logStreamName": stream,
                    "startFromHead": True,
                    "limit": MAX_JOB_LOG_EVENTS - len(messages),
                }
                if token:
                    options["nextToken"] = token
                result = cloudwatch_logs.get_log_events(**options)
                pages += 1
                for event in result.get("events", []):
                    message = str(event.get("message") or "")
                    if message.startswith(prefix):
                        messages.append(message[len(prefix):])
                next_token = result.get("nextForwardToken")
                if not next_token or next_token == token:
                    break
                token = next_token
            return messages
        except ClientError as error:
            print(json.dumps({
                "event": "cloudwatch_job_logs_unavailable", "task_id": task_id,
                "error": error.response.get("Error", {}).get("Code", "ClientError"),
            }, separators=(",", ":")), flush=True)
    return table.query(
        KeyConditionExpression=(
            Key("pk").eq(f"JOB#{task_id}") & Key("sk").begins_with("LOG#")
        ),
        ScanIndexForward=True,
    ).get("Items", [])


def file_response(contents, filename, content_type="application/xml"):
    return {
        "statusCode": 200,
        "headers": {
            "content-type": content_type,
            "content-disposition": f'attachment; filename="{safe_name(filename, "download.xml")}"',
            "cache-control": "no-store",
        },
        "isBase64Encoded": True,
        "body": base64.b64encode(contents).decode("ascii"),
    }


def body_json(event):
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("JSON body must be an object")
    return value


def jwt_claims(event):
    return (((event.get("requestContext") or {}).get("authorizer") or {}).get("jwt") or {}).get("claims") or {}


def user_id(event):
    claims = jwt_claims(event)
    return str(claims.get("sub") or "").strip()


def request_header(event, name):
    headers = event.get("headers") or {}
    wanted = name.casefold()
    return next((str(value) for key, value in headers.items() if str(key).casefold() == wanted), "")


def source_ip(event):
    return str((((event.get("requestContext") or {}).get("http") or {}).get("sourceIp") or "unknown"))


def is_admin(event):
    claims = jwt_claims(event)
    email = str(claims.get("email") or "").strip().casefold()
    verified = claims.get("email_verified") in (True, "true", "True")
    return bool(ADMIN_EMAIL and verified and email and secrets.compare_digest(email, ADMIN_EMAIL))


def require_admin(event):
    if not is_admin(event):
        return response(404, {"message": "Not found"})
    return None


def next_billing_cycle_start(now=None):
    """Return the first instant of the next UTC calendar month as epoch seconds."""
    from datetime import datetime, timezone
    current = datetime.fromtimestamp(now or time.time(), tz=timezone.utc)
    year, month = (current.year + 1, 1) if current.month == 12 else (current.year, current.month + 1)
    return int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp())


def ensure_pipe_running(running):
    if not PIPE_NAME:
        return
    state = str(pipes.describe_pipe(Name=PIPE_NAME).get("CurrentState") or "")
    if running and state not in {"RUNNING", "STARTING"}:
        pipes.start_pipe(Name=PIPE_NAME)
    elif not running and state not in {"STOPPED", "STOPPING"}:
        pipes.stop_pipe(Name=PIPE_NAME)


def service_control(refresh_expired=True):
    item = table.get_item(Key=SERVICE_CONTROL_KEY, ConsistentRead=True).get("Item") or {}
    paused = str(item.get("status") or "active") == "paused"
    resumes_at = int(item.get("resumes_at") or 0)
    if paused and refresh_expired and resumes_at and resumes_at <= int(time.time()):
        ensure_pipe_running(True)
        now = int(time.time())
        table.update_item(
            Key=SERVICE_CONTROL_KEY,
            UpdateExpression="SET #status=:active, updated_at=:now, updated_by=:actor REMOVE pause_reason, resumes_at",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":active": "active", ":now": now, ":actor": "automatic-monthly-reset"},
        )
        item = {"status": "active", "updated_at": now, "updated_by": "automatic-monthly-reset"}
    return item


def public_service_status():
    item = service_control()
    paused = str(item.get("status") or "active") == "paused"
    resumes_at = int(item.get("resumes_at") or 0)
    body = {"status": "paused" if paused else "active", "processing_available": not paused}
    if paused:
        body.update({
            "reason": str(item.get("pause_reason") or "overspending"),
            "resumes_at": resumes_at,
            "message": (
                "Processing is temporarily unavailable because this month's AWS spending limit was exceeded. "
                "Service is scheduled to resume automatically on the first day of the next billing cycle, "
                "but it may return sooner. Please check back soon."
            ),
        })
    return response(200, body)


def service_paused_response():
    item = service_control()
    if str(item.get("status") or "active") != "paused":
        return None
    return response(503, {
        "message": (
            "Processing is temporarily unavailable because this month's AWS spending limit was exceeded. "
            "Service is scheduled to resume automatically on the first day of the next billing cycle, "
            "but it may return sooner. Please check back soon."
        ),
        "code": "SERVICE_PAUSED_FOR_COST",
        "resumes_at": int(item.get("resumes_at") or 0),
    })


def admin_service_control(event):
    denied = require_admin(event)
    if denied:
        return denied
    method = ((event.get("requestContext") or {}).get("http") or {}).get("method", "GET")
    if method == "GET":
        return response(200, json_value(service_control()))
    data = body_json(event)
    action = str(data.get("action") or "").strip().casefold()
    if action == "pause":
        now = int(time.time())
        resumes_at = next_billing_cycle_start(now)
        table.update_item(
            Key=SERVICE_CONTROL_KEY,
            UpdateExpression=("SET #status=:paused, pause_reason=:reason, resumes_at=:resumes, "
                              "updated_at=:now, updated_by=:actor"),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":paused": "paused", ":reason": "overspending", ":resumes": resumes_at,
                ":now": now, ":actor": str(jwt_claims(event).get("email") or "administrator"),
            },
        )
        ensure_pipe_running(False)
        return response(200, {"status": "paused", "processing_available": False, "resumes_at": resumes_at})
    if action in {"continue", "resume"}:
        ensure_pipe_running(True)
        now = int(time.time())
        table.update_item(
            Key=SERVICE_CONTROL_KEY,
            UpdateExpression="SET #status=:active, updated_at=:now, updated_by=:actor REMOVE pause_reason, resumes_at",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":active": "active", ":now": now,
                ":actor": str(jwt_claims(event).get("email") or "administrator"),
            },
        )
        return response(200, {"status": "active", "processing_available": True})
    return response(400, {"message": "Choose pause, continue, or resume"})


def safe_name(value, fallback):
    value = os.path.basename(str(value or "")).strip()
    clean = "".join(char if char.isalnum() or char in "._-" else "_" for char in value).strip("._")
    return clean[:180] or fallback


def rasterized_download_name(task_id, source_name, object_key):
    """Return a friendly raster export name while retaining UUID-safe S3 keys."""
    stored_name = str(object_key).rsplit("/", 1)[-1]
    if not stored_name.startswith(f"output_{task_id}_"):
        return stored_name
    source_name = safe_name(source_name, "artwork")
    if stored_name.lower().endswith(".lbrn2"):
        return f"{source_name}.rasterized.lbrn2"
    if stored_name.lower().endswith(".svg"):
        return f"{source_name}.rasterized.svg"
    return stored_name


def output_descriptor(task_id, source_name, obj):
    key = str(obj["Key"])
    name = rasterized_download_name(task_id, source_name, key)
    params = {"Bucket": BUCKET, "Key": key}
    if name != key.rsplit("/", 1)[-1]:
        params["ResponseContentDisposition"] = f'attachment; filename="{name}"'
    return {
        "name": name,
        "bytes": int(obj["Size"]),
        "download_url": s3.generate_presigned_url("get_object", Params=params, ExpiresIn=900),
    }


def raster_output_sort_key(obj):
    """Keep every Rasterizer download list in user-facing workflow order."""
    key = str(obj.get("Key") or "").casefold()
    if key.endswith(".svg"):
        return (0, key)
    if key.endswith(".lbrn2"):
        return (1, key)
    return (2, key)


def ordered_output_descriptors(task_id, source_name, objects):
    return [
        output_descriptor(task_id, source_name, obj)
        for obj in sorted(objects, key=raster_output_sort_key)
    ]


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def valid_upload_capability(item, token):
    return bool(token) and int(item.get("upload_expires_at") or 0) >= int(time.time()) and secrets.compare_digest(
        token_hash(token), str(item.get("upload_capability") or "")
    )


def valid_guest_capability(item, token):
    return bool(item and item.get("guest") is True and token) and int(
        item.get("guest_access_expires_at") or 0
    ) >= int(time.time()) and secrets.compare_digest(
        token_hash(token), str(item.get("guest_access_capability") or "")
    )


def guest_quota_context(event):
    """Return the privacy-preserving identity and UTC day used by the worker quota."""
    now = int(time.time())
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    visitor = hashlib.sha256(f"{GUEST_QUOTA_SALT}:{source_ip(event)}".encode("utf-8")).hexdigest()
    return visitor, day


def runtime_key(task_id):
    return {"pk": f"JOB#{task_id}", "sk": "RUNTIME"}


def runtime(task_id):
    return table.get_item(Key=runtime_key(task_id), ConsistentRead=True).get("Item")


def authorize_task(event, item):
    return bool(item) and item.get("user_id") == user_id(event)


def user_items(owner, prefix, limit=None):
    options = {
        "KeyConditionExpression": Key("pk").eq(f"USER#{owner}") & Key("sk").begins_with(prefix),
        "ScanIndexForward": False,
    }
    if limit:
        options["Limit"] = limit
    return table.query(**options).get("Items", [])


def owned_material(owner, library_id):
    if not library_id:
        return None
    item = table.get_item(
        Key={"pk": f"USER#{owner}", "sk": f"MATERIAL#{library_id}"},
        ConsistentRead=True,
    ).get("Item")
    expected_prefix = f"users/{owner}/materials/{library_id}/"
    return item if item and str(item.get("s3_key") or "").startswith(expected_prefix) else None


def owned_recipe(owner, recipe_id):
    if not recipe_id:
        return None
    item = table.get_item(
        Key={"pk": f"USER#{owner}", "sk": f"HOLORECIPE#{recipe_id}"},
        ConsistentRead=True,
    ).get("Item")
    expected_prefix = f"users/{owner}/holographic-recipes/{recipe_id}/"
    return item if item and str(item.get("s3_key") or "").startswith(expected_prefix) else None


def public_library_summary(summary):
    summary = summary if isinstance(summary, dict) else {}
    entries = []
    for item in summary.get("entries") or []:
        description = str(item.get("description") or "Unnamed setting")
        settings = item.get("settings") if isinstance(item.get("settings"), dict) else {}
        entries.append({
            "entry_id": int(item.get("entry_id") if item.get("entry_id") is not None else len(entries)),
            "description": description,
            "material": str(item.get("material") or ""),
            "type": str(item.get("type") or "Setting"),
            "hex": PALETTE_HEX.get(description.casefold(), ""),
            "angle": str(settings.get("angle") or "0"),
            "interval": str(settings.get("interval") or ""),
            "settings": settings,
        })
    return {
        "entry_count": int(summary.get("entry_count") or len(entries)),
        "material_names": [str(name) for name in summary.get("material_names") or []],
        "entries": entries,
    }


def community_normalized(value):
    normalized = " ".join(str(value or "").strip().casefold().replace("×", "x").split())
    normalized = re.sub(r"\s*x\s*", "x", normalized)
    return re.sub(r"\s*mm\b", "mm", normalized)


def community_exact(value, query):
    return not query or community_normalized(value) == community_normalized(query)


def community_contains(value, query):
    return not query or community_normalized(query) in community_normalized(value)


def community_swatch(entry):
    color_hex = str(entry.get("swatch_hex") or "").upper()
    if color_hex in PALETTE_NAMES:
        return color_hex, PALETTE_NAMES[color_hex]
    description = str(entry.get("source_description", entry.get("description", "")) or "").strip()
    for official_hex, official_name in PALETTE_NAMES.items():
        if official_name.casefold() == description.casefold():
            return official_hex, official_name
    return "", "Unassigned"


COMMUNITY_PUBLIC_SETTING_FIELDS = (
    "speed", "minPower", "maxPower", "frequency", "QPulseWidth", "interval",
    "angle", "numPasses", "anglePerPass", "bidir", "crossHatch", "type",
)


def community_public_settings(settings):
    """Keep only fields represented by the intentionally compact public table."""
    settings = settings if isinstance(settings, dict) else {}
    return {
        field: str(settings[field])[:160]
        for field in COMMUNITY_PUBLIC_SETTING_FIELDS
        if field in settings and not isinstance(settings[field], (dict, list))
    }


def community_setting_identity(laser_source, lens, entry):
    """Identify a Community Set entry solely by machine context and public cut parameters."""
    return (
        community_normalized(laser_source),
        community_normalized(lens),
        community_normalized(entry.get("material")),
        community_normalized(entry.get("type")),
        json.dumps(community_public_settings(entry.get("settings")), sort_keys=True, separators=(",", ":")),
    )


def existing_community_setting_identities():
    identities = set()
    options = {"KeyConditionExpression": Key("pk").eq("LASER_COMMUNITY")}
    while True:
        result = table.query(**options)
        for community in result.get("Items", []):
            summary = community.get("summary") if isinstance(community.get("summary"), dict) else {}
            for entry in summary.get("entries") or []:
                if isinstance(entry, dict):
                    identities.add(community_setting_identity(
                        community.get("laser_source"), community.get("lens_field_of_view"), entry,
                    ))
        last_key = result.get("LastEvaluatedKey")
        if not last_key:
            return identities
        options["ExclusiveStartKey"] = last_key


def community_material_swatch(preferences, library_id, entry):
    assignments = preferences.get("material_library_color_assignments") if isinstance(preferences, dict) else {}
    mapping = assignments.get(library_id) if isinstance(assignments, dict) else {}
    description = str(entry.get("description") or "").strip()
    assigned = next((
        str(color).upper() for color, name in (mapping.items() if isinstance(mapping, dict) else [])
        if str(color).upper() in PALETTE_NAMES and str(name).strip().casefold() == description.casefold()
    ), "")
    fallback = str(entry.get("hex") or PALETTE_HEX.get(description.casefold(), "")).upper()
    return assigned or (fallback if fallback in PALETTE_NAMES else "")


def publish_community_palette(event):
    owner, data = user_id(event), body_json(event)
    source_kind = str(data.get("source_kind") or "").strip()
    source_id = str(data.get("source_id") or "").strip()
    laser_source = str(data.get("laser_source") or "").strip()
    lens = str(data.get("lens") or "").strip()
    notes = str(data.get("notes") or "").strip()
    selected = data.get("selected_indexes")
    if source_kind != "material":
        raise ValueError("Only Color Palettes can be added to Community Set")
    try:
        uuid.UUID(source_id)
    except (TypeError, ValueError) as error:
        raise ValueError("Choose a valid saved palette") from error
    if not laser_source or len(laser_source) > 160:
        raise ValueError("Laser Model / Source is required and must be 160 characters or fewer")
    if not lens or len(lens) > 160:
        raise ValueError("Lens is required and must be 160 characters or fewer")
    if len(notes) > 1000:
        raise ValueError("Notes must be 1,000 characters or fewer")
    if not isinstance(selected, list) or not 1 <= len(selected) <= 500:
        raise ValueError("Select between 1 and 500 swatches to add to Community Set")
    if any(not isinstance(index, int) or isinstance(index, bool) or index < 0 for index in selected):
        raise ValueError("One or more Community Set swatch selections could not be read. Reload the Vault, select the swatches again, and retry publishing.")
    selected = sorted(set(selected))

    entries, palette_name, palette_type = [], "", ""
    if source_kind == "material":
        source = owned_material(owner, source_id)
        if not source:
            return response(404, {"message": "Saved palette not found"})
        if source.get("library_intent") == "hatch_palette":
            raise ValueError("Only Color Palettes can be added to Community Set")
        summary = public_library_summary(source.get("summary"))
        available = {int(entry["entry_id"]): entry for entry in summary["entries"]}
        preferences_item = table.get_item(
            Key={"pk": f"USER#{owner}", "sk": "PREFERENCES"}, ConsistentRead=True,
        ).get("Item") or {}
        preferences = preferences_item.get("preferences") or {}
        palette_name = str(source.get("name") or source.get("original_name") or "Swatch Palette")[:160]
        palette_type = "color_palette"
        for index in selected:
            entry = available.get(index)
            if entry is None:
                raise ValueError("One of the selected swatches no longer exists")
            swatch_hex = community_material_swatch(preferences, source_id, entry)
            if not swatch_hex:
                raise ValueError(
                    f"'{entry['description']}' is not assigned to an official Rasterizer swatch. "
                    "Assign it on the Rasterizer page before publishing."
                )
            entries.append({
                "entry_id": index,
                "description": str(entry.get("description") or "Unnamed setting")[:160],
                "source_description": str(entry.get("description") or "")[:160],
                "material": str(entry.get("material") or "")[:160],
                "type": str(entry.get("type") or "Setting")[:40],
                "swatch_hex": swatch_hex,
                "official_color": PALETTE_NAMES[swatch_hex],
                "settings": community_public_settings(entry.get("settings")),
            })
    else:
        source = owned_recipe(owner, source_id)
        if not source:
            return response(404, {"message": "Saved Fauxlographic Palette not found"})
        profile = json.loads(s3.get_object(Bucket=BUCKET, Key=source["s3_key"])["Body"].read(MAX_RECIPE_BYTES + 1))
        measured = profile.get("recipes") if isinstance(profile, dict) else None
        if fauxlographic_schema_version(profile) < 2 or not isinstance(measured, list):
            raise ValueError("Only self-contained Fauxlographic Palettes can be added to Community Set")
        palette_name = str(source.get("name") or profile.get("profile_name") or "Fauxlographic Palette")[:160]
        palette_type = "holographic_palette"
        material = str((profile.get("grid") or {}).get("material") or (source.get("metadata") or {}).get("material") or "")[:160]
        for index in selected:
            if index >= len(measured) or not isinstance(measured[index], dict):
                raise ValueError("One of the selected Fauxlographic swatches no longer exists")
            swatch = measured[index]
            snapshot = swatch.get("laser_settings")
            validate_lightburn_setting_snapshot(snapshot)
            official_index = nearest_lightburn_palette_index(swatch.get("observed_hex"))
            swatch_hex = PALETTE[official_index][1].upper()
            entries.append({
                "entry_id": index,
                "description": str(swatch.get("name") or f"Fauxlographic swatch {index + 1}")[:160],
                "source_description": str(swatch.get("name") or "")[:160],
                "material": material,
                "type": str(snapshot.get("type") or "Setting")[:40],
                "swatch_hex": swatch_hex,
                "official_color": PALETTE_NAMES[swatch_hex],
                "settings": community_public_settings(snapshot.get("settings")),
            })

    existing_identities = existing_community_setting_identities()
    submitted_identities = set()
    unique_entries = []
    for entry in entries:
        identity = community_setting_identity(laser_source, lens, entry)
        if identity in existing_identities or identity in submitted_identities:
            continue
        submitted_identities.add(identity)
        unique_entries.append(entry)
    duplicate_count = len(entries) - len(unique_entries)
    entries = unique_entries

    materials = []
    for entry in entries:
        if entry["material"] and entry["material"] not in materials:
            materials.append(entry["material"])
    # The public record intentionally has no owner-derived or source-palette-derived
    # identifier. It cannot be joined back to the private account record in DynamoDB.
    if not entries:
        return response(200, {
            "published": False, "palette_name": palette_name, "palette_type": palette_type,
            "setting_count": 0, "duplicate_count": duplicate_count,
        })

    publication_id = str(uuid.uuid4())
    now = int(time.time())
    table.put_item(Item={
        "pk": "LASER_COMMUNITY", "sk": f"PALETTE#{publication_id}",
        "laser_source": laser_source, "lens_field_of_view": lens, "notes": notes,
        "palette_type": palette_type,
        "summary": dynamo_value({
            "entry_count": len(entries), "material_names": materials, "entries": entries,
        }),
        "updated_at": now,
    })
    private_key = {
        "pk": f"USER#{owner}",
        "sk": f"{'MATERIAL' if source_kind == 'material' else 'HOLORECIPE'}#{source_id}",
    }
    table.update_item(
        Key=private_key,
        UpdateExpression="SET laser_source=:laser, lens_field_of_view=:lens, notes=:notes, updated_at=:now",
        ExpressionAttributeValues={
            ":laser": laser_source, ":lens": lens, ":notes": notes, ":now": now,
        },
    )
    return response(201, {
        "published": True, "palette_name": palette_name, "palette_type": palette_type,
        "setting_count": len(entries), "duplicate_count": duplicate_count,
    })


def community_settings(event):
    query = event.get("queryStringParameters") or {}
    filters = {name: str(query.get(name) or "").strip() for name in ("laser", "lens", "material", "color")}
    if any(len(value) > 160 for value in filters.values()):
        return response(400, {"message": "Filter values must be 160 characters or fewer."})
    if not any(filters.values()):
        return response(400, {"message": "Enter a laser model/source, lens, material, or color."})
    rows = []
    options = {
        "KeyConditionExpression": Key("pk").eq("LASER_COMMUNITY"),
        "ScanIndexForward": False,
    }
    while True:
        result = table.query(**options)
        for community in result.get("Items", []):
            if not community_exact(community.get("laser_source"), filters["laser"]):
                continue
            if not community_exact(community.get("lens_field_of_view"), filters["lens"]):
                continue
            summary = community.get("summary") if isinstance(community.get("summary"), dict) else {}
            for entry in summary.get("entries") or []:
                if not community_contains(entry.get("material"), filters["material"]):
                    continue
                swatch, color = community_swatch(entry)
                if color == "Unassigned" or not community_exact(color, filters["color"]):
                    continue
                rows.append({
                    "laser_source": str(community.get("laser_source") or ""),
                    "lens": str(community.get("lens_field_of_view") or ""),
                    "material": str(entry.get("material") or ""),
                    "color": color,
                    "swatch": swatch,
                    "operation": str(entry.get("type") or ""),
                    "settings": entry.get("settings") if isinstance(entry.get("settings"), dict) else {},
                    "notes": str(community.get("notes") or ""),
                })
                if len(rows) >= 300:
                    return response(200, {"status": "ok", "count": len(rows), "settings": rows})
        last_key = result.get("LastEvaluatedKey")
        if not last_key:
            break
        options["ExclusiveStartKey"] = last_key
    return response(200, {"status": "ok", "count": len(rows), "settings": rows})


def account_resources(event):
    owner = user_id(event)
    preferences = table.get_item(
        Key={"pk": f"USER#{owner}", "sk": "PREFERENCES"}, ConsistentRead=True,
    ).get("Item") or {}
    materials = user_items(owner, "MATERIAL#")
    depth_palettes = user_items(owner, "DEPTHPALETTE#")
    recipes = user_items(owner, "HOLORECIPE#")
    jobs = []
    for history in user_items(owner, "JOB#", limit=20):
        task_id = str(history.get("task_id") or "")
        live = runtime(task_id) if task_id else None
        if live and live.get("user_id") == owner:
            history["status"] = live.get("status", history.get("status", "unknown"))
            jobs.append(history)
        if len(jobs) == 10:
            break
    return response(200, {
        "material_libraries": [{
            "library_id": str(item.get("library_id") or ""),
            "name": str(item.get("name") or item.get("original_name") or "Material Library"),
            "original_name": str(item.get("original_name") or "library.clb"),
            "material_name": str(item.get("material_name") or ""),
            "laser_source": str(item.get("laser_source") or ""),
            "lens_field_of_view": str(item.get("lens_field_of_view") or ""),
            "notes": str(item.get("notes") or ""),
            "library_intent": "hatch_palette" if item.get("library_intent") == "hatch_palette" else "color_palette",
            "summary": public_library_summary(item.get("summary")),
        } for item in materials],
        "depth_palettes": [{
            "palette_id": str(item.get("palette_id") or ""),
            "name": str(item.get("name") or "Depth Palette"),
            "entries": item.get("entries") or [],
        } for item in depth_palettes],
        "holographic_recipes": [{
            "recipe_id": str(item.get("recipe_id") or ""),
            "name": str(item.get("name") or item.get("original_name") or "Fauxlographic Palette"),
            "original_name": str(item.get("original_name") or "recipe.json"),
            "metadata": item.get("metadata") or {},
            "laser_source": str(item.get("laser_source") or ""),
            "lens_field_of_view": str(item.get("lens_field_of_view") or ""),
            "notes": str(item.get("notes") or ""),
        } for item in recipes],
        "palette": [{"name": name, "hex": color} for name, color in PALETTE],
        "preferences": clean_account_preferences(preferences.get("preferences") or {}),
        "jobs": [{
            "task_id": str(item.get("task_id") or ""),
            "status": str(item.get("status") or "unknown"),
            "source_name": str(item.get("source_name") or "Artwork"),
            "material_name": str(item.get("material_name") or ""),
            "created_at": int(item.get("created_at") or 0),
        } for item in jobs if item.get("task_id")],
    })


LAST_USED_FORM_FIELDS = {
    "last_rasterizer_form": {
        "material_choice", "material_name", "pixel_square_mm", "new_width", "new_height",
        "image_preset", "filter_parameters", "cut_mode", "preserve_black_outlines",
        "geometry_style", "geometry_style_parameters",
        "color_matching_mode", "color_matching_hue_weight",
        "color_matching_saturation_weight", "color_matching_lightness_weight",
    },
    "last_holographic_artwork_form": {
        "recipe_id", "material_library_id", "max_dimension", "pixel_mm", "cut_mode",
        "preserve_black_outlines",
    },
    "last_holographic_lab_form": {
        "calibration_source", "library_id", "entry_id", "material_name", "cut_mode",
        "laser_source", "lens_field_mm", "columns", "rows", "cell_mm", "interval_low",
        "interval_high", "sweep_parameter", "sweep_low", "sweep_high", "profile_name",
        "capture_camera", "capture_distance", "capture_angle", "capture_lighting", "capture_notes",
    },
    "last_color_lab_form": {
        "library_source", "library_id", "entry_id", "x_parameter", "x_low", "x_high",
        "y_parameter", "y_low", "y_high", "grid_width_mm", "grid_length_mm",
        "white_background", "review_action", "palette_name", "palette_material",
        "measurement_grid_id",
    },
}


def clean_last_used_form(name, snapshot):
    def clean_number(value):
        if isinstance(value, bool):
            return value
        if not isinstance(value, (int, float, Decimal)) or isinstance(value, complex):
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(numeric):
            return None
        if isinstance(value, Decimal):
            return int(value) if value == value.to_integral_value() else numeric
        return value

    if not isinstance(snapshot, dict):
        return None
    try:
        saved_at = int(snapshot.get("saved_at") or 0)
    except (TypeError, ValueError):
        return None
    if saved_at < int(time.time()) - TTL_SECONDS:
        return None
    values = snapshot.get("values")
    if not isinstance(values, dict):
        return None
    def clean_parameter_map(parameters, geometry=False):
        cleaned = {}
        for parameter, parameter_value in list(parameters.items())[:64]:
            parameter = str(parameter)[:80]
            if geometry and parameter == "posterize_colors":
                continue
            number = clean_number(parameter_value)
            if number is not None:
                cleaned[parameter] = number
            elif parameter == "mixing_model" and parameter_value in {"lab", "rgb", "hsv"}:
                cleaned[parameter] = parameter_value
            elif parameter == "cell_shape" and parameter_value in {
                "square", "hexagon", "triangle", "diamond", "skull",
                "heart", "space_invader", "ghost", "bat",
                "alien_head", "paw_print", "fish_scale", "puzzle_piece",
            }:
                cleaned[parameter] = parameter_value
            elif parameter == "grating_render_mode" and parameter_value in {
                "line", "fill",
            }:
                cleaned[parameter] = parameter_value
            elif parameter == "glyph_shape" and parameter_value in {
                "circle", "square", "diamond", "triangle", "hexagon",
                "octagon", "star", "cross", "bar", "skull", "heart",
                "space_invader", "ghost", "bat", "alien_head",
                "paw_print", "fish_scale", "puzzle_piece", "mixed",
            }:
                cleaned[parameter] = parameter_value
            elif parameter == "fauxlogram_gradient_scope" and parameter_value in {
                "entire_artwork", "each_shape",
            }:
                cleaned[parameter] = parameter_value
            elif parameter == "fauxlogram_gradient_direction" and parameter_value in {
                "top_to_bottom", "bottom_to_top", "left_to_right",
                "right_to_left", "center_to_edge", "edge_to_center",
            }:
                cleaned[parameter] = parameter_value
        return cleaned

    allowed, clean_values = LAST_USED_FORM_FIELDS[name], {}
    for key, value in values.items():
        if key not in allowed:
            continue
        if key in {"filter_parameters", "geometry_style_parameters"} and isinstance(value, dict):
            if key == "geometry_style_parameters" and isinstance(value.get("assignments"), dict):
                clean_assignments = {
                    str(color_hex).upper(): assigned_style
                    for color_hex, assigned_style in list(value["assignments"].items())[:64]
                    if len(str(color_hex)) == 7
                    and str(color_hex).startswith("#")
                    and all(
                        character in "0123456789ABCDEF"
                        for character in str(color_hex).upper()[1:]
                    )
                    and assigned_style in {"vectors", "glyphs", "krasnow_grating"}
                }
                clean_assignments["#000000"] = "vectors"
                clean_parameters = {
                    "assignments": clean_assignments,
                    "glyphs": clean_parameter_map(value.get("glyphs") or {}, geometry=True),
                    "krasnow_grating": clean_parameter_map(
                        value.get("krasnow_grating") or {}, geometry=True
                    ),
                }
            else:
                clean_parameters = clean_parameter_map(
                    value, geometry=key == "geometry_style_parameters"
                )
            clean_values[key] = clean_parameters
        elif key == "geometry_style" and value in {"vectors", "glyphs", "krasnow_grating", "by_swatch"}:
            clean_values[key] = value
        elif isinstance(value, bool):
            clean_values[key] = value
        elif clean_number(value) is not None:
            clean_values[key] = clean_number(value)
        elif isinstance(value, str):
            clean_values[key] = value[:2000 if key == "capture_notes" else 320]
    return {"saved_at": saved_at, "values": clean_values}


def clean_account_preferences(data):
    clean = {}
    colors = data.get("selected_color_hexes")
    if isinstance(colors, list):
        clean["selected_color_hexes"] = [
            str(color).upper() for color in colors[:64]
            if str(color).upper() in PALETTE_NAMES
        ]
    overrides = data.get("color_name_overrides")
    if isinstance(overrides, dict):
        clean["color_name_overrides"] = {
            str(color).upper(): str(name).strip()[:80]
            for color, name in list(overrides.items())[:64]
            if str(color).upper() in PALETTE_NAMES and str(name).strip()
        }
    assignments = data.get("material_library_color_assignments")
    if isinstance(assignments, dict):
        clean["material_library_color_assignments"] = {
            str(library_id)[:80]: {
                str(color).upper(): str(name).strip()[:80]
                for color, name in list(mapping.items())[:64]
                if str(color).upper() in PALETTE_NAMES and str(name).strip()
            }
            for library_id, mapping in list(assignments.items())[:100]
            if str(library_id).strip() and isinstance(mapping, dict)
        }
    for name in LAST_USED_FORM_FIELDS:
        snapshot = clean_last_used_form(name, data.get(name))
        if snapshot:
            clean[name] = snapshot
    return clean


def account_preferences(event):
    owner = user_id(event)
    key = {"pk": f"USER#{owner}", "sk": "PREFERENCES"}
    method = ((event.get("requestContext") or {}).get("http") or {}).get("method", "GET")
    if method == "GET":
        item = table.get_item(Key=key, ConsistentRead=True).get("Item") or {}
        return response(200, {"preferences": clean_account_preferences(item.get("preferences") or {})})
    incoming = body_json(event)
    if method == "PATCH":
        item = table.get_item(Key=key, ConsistentRead=True).get("Item") or {}
        merged = dict(item.get("preferences") or {})
        now = int(time.time())
        for name, value in incoming.items():
            if name in LAST_USED_FORM_FIELDS and isinstance(value, dict):
                merged[name] = {"saved_at": now, "values": value.get("values", value)}
            else:
                merged[name] = value
        incoming = merged
    preferences = clean_account_preferences(incoming)
    table.put_item(Item={**key, "preferences": dynamo_value(preferences), "updated_at": int(time.time())})
    return response(200, {"preferences": preferences})


def preserve_material_assignment_names(owner, library_id, old_description, new_description):
    """Keep explicit Rasterizer swatch assignments attached when a setting is renamed."""
    if not old_description or old_description == new_description:
        return
    key = {"pk": f"USER#{owner}", "sk": "PREFERENCES"}
    item = table.get_item(Key=key, ConsistentRead=True).get("Item") or {}
    preferences = dict(item.get("preferences") or {})
    assignments = dict(preferences.get("material_library_color_assignments") or {})
    mapping = dict(assignments.get(library_id) or {})
    changed = False
    for color, description in list(mapping.items()):
        if str(description).strip().casefold() == str(old_description).strip().casefold():
            mapping[color] = new_description
            changed = True
    if not changed:
        return
    assignments[library_id] = mapping
    preferences["material_library_color_assignments"] = assignments
    preferences = clean_account_preferences(preferences)
    table.put_item(Item={**key, "preferences": dynamo_value(preferences), "updated_at": int(time.time())})


def history_job_type(item):
    parameters = item.get("run_parameters") if isinstance(item.get("run_parameters"), dict) else {}
    explicit = str(item.get("job_type") or parameters.get("job_type") or "").strip()
    if explicit:
        return explicit
    if str(item.get("image_preset") or "").strip() == "holographic_artwork":
        return "holographic_artwork"
    return "rasterizer"


def admin_job_index_item(event, history):
    """Build the private seven-day operations index without artwork or settings."""
    task_id = str(history.get("task_id") or "")
    created_at = int(history.get("created_at") or time.time())
    claims = jwt_claims(event)
    return {
        "pk": "ADMIN#JOBS", "sk": f"JOB#{created_at:010d}#{task_id}",
        "task_id": task_id, "created_at": created_at,
        "user_id": user_id(event),
        "user_email": str(claims.get("email") or "")[:320],
        "source_name": str(history.get("source_name") or "Artwork")[:255],
        "material_name": str(history.get("material_name") or "")[:160],
        "image_preset": str(history.get("image_preset") or "")[:100],
        "abstract_filter": str(history.get("abstract_filter") or "none")[:100],
        "job_type": str(history.get("job_type") or "rasterizer")[:80],
        "status": "pending", "expires_at": created_at + TTL_SECONDS,
    }


def admin_jobs(event):
    denied = require_admin(event)
    if denied:
        return denied
    cutoff = int(time.time()) - min(TTL_SECONDS, 7 * 86400)
    options = {
        "KeyConditionExpression": Key("pk").eq("ADMIN#JOBS") & Key("sk").gte(f"JOB#{cutoff:010d}"),
        "ScanIndexForward": False,
    }
    indexed = []
    while True:
        result = table.query(**options)
        indexed.extend(result.get("Items", []))
        if not result.get("LastEvaluatedKey") or len(indexed) >= 500:
            break
        options["ExclusiveStartKey"] = result["LastEvaluatedKey"]
    jobs = []
    for item in indexed[:500]:
        task_id = str(item.get("task_id") or "")
        if not task_id:
            continue
        live = runtime(task_id) or {}
        status = str(live.get("status") or item.get("status") or "unknown")
        jobs.append({
            "task_id": task_id, "status": status,
            "queued": status.lower() == "pending" and bool(live.get("payload")),
            "job_type": str(item.get("job_type") or "rasterizer"),
            "source_name": str(item.get("source_name") or "Artwork"),
            "material_name": str(item.get("material_name") or ""),
            "image_preset": str(item.get("image_preset") or ""),
            "abstract_filter": str(item.get("abstract_filter") or "none"),
            "user_id": str(item.get("user_id") or ""),
            "user_email": str(item.get("user_email") or ""),
            "created_at": int(item.get("created_at") or 0),
            "updated_at": int(live.get("updated_at") or item.get("created_at") or 0),
            "error": str(live.get("error_message") or ""),
        })
    return response(200, {
        "jobs": jobs,
        "admin_email": str(jwt_claims(event).get("email") or ""),
        "retention_days": 7,
    })


def admin_job(event, task_id):
    denied = require_admin(event)
    if denied:
        return denied
    record = table.get_item(
        Key={"pk": f"JOB#{task_id}", "sk": "OWNER"}, ConsistentRead=True,
    ).get("Item")
    if not record:
        return response(404, {"message": "Job not found"})
    owner = str(record.get("user_id") or "")
    history_sk = str(record.get("history_sk") or "")
    history = table.get_item(
        Key={"pk": f"USER#{owner}", "sk": history_sk}, ConsistentRead=True,
    ).get("Item") if owner and history_sk else {}
    history = history or {}
    live = runtime(task_id) or {}
    logs = job_logs(task_id, live)
    error_message = str(live.get("error_message") or history.get("error_message") or "")
    return response(200, {
        "task_id": task_id,
        "status": str(live.get("status") or record.get("status") or history.get("status") or "unknown"),
        "job_type": history_job_type(history or record),
        "source_name": str(history.get("source_name") or record.get("source_name") or "Artwork"),
        "material_name": str(history.get("material_name") or record.get("material_name") or ""),
        "image_preset": str(history.get("image_preset") or record.get("image_preset") or ""),
        "abstract_filter": str(history.get("abstract_filter") or record.get("abstract_filter") or "none"),
        "run_parameters": history.get("run_parameters") or {},
        "user_id": owner,
        "guest": record.get("guest") is True,
        "created_at": int(history.get("created_at") or record.get("created_at") or 0),
        "updated_at": int(live.get("updated_at") or history.get("updated_at") or record.get("updated_at") or 0),
        "error": error_message,
        "logs": visible_job_logs(logs, error_message),
        "queued": str(live.get("status") or "").lower() == "pending" and bool(live.get("payload")),
    })


def admin_users(event):
    denied = require_admin(event)
    if denied:
        return denied
    if not COGNITO_USER_POOL_ID:
        return response(503, {"message": "The Cognito directory is not configured"})
    users, pagination = [], None
    while True:
        options = {"UserPoolId": COGNITO_USER_POOL_ID, "Limit": 60}
        if pagination:
            options["PaginationToken"] = pagination
        result = cognito.list_users(**options)
        for user in result.get("Users", []):
            attributes = {entry["Name"]: entry["Value"] for entry in user.get("Attributes", [])}
            users.append({
                "email": str(attributes.get("email") or ""),
                "status": str(user.get("UserStatus") or ""),
                "enabled": bool(user.get("Enabled")),
                "created_at": int(user["UserCreateDate"].timestamp()) if user.get("UserCreateDate") else 0,
                "updated_at": int(user["UserLastModifiedDate"].timestamp()) if user.get("UserLastModifiedDate") else 0,
            })
        pagination = result.get("PaginationToken")
        if not pagination or len(users) >= 1000:
            break
    users.sort(key=lambda item: item["created_at"], reverse=True)
    return response(200, {"count": len(users), "users": users})


def cancel_admin_job(event, task_id):
    denied = require_admin(event)
    if denied:
        return denied
    now = int(time.time())
    message = "Cancelled while waiting in the queue by an administrator."
    try:
        result = table.update_item(
            Key=runtime_key(task_id),
            UpdateExpression=(
                "SET #status=:failed, error_message=:message, updated_at=:now, "
                "expires_at=:expiry, log_count=if_not_exists(log_count,:zero)+:one"
            ),
            ConditionExpression="#status=:pending AND attribute_exists(payload)",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":failed": "failed", ":pending": "pending", ":message": message,
                ":now": now, ":expiry": now + TTL_SECONDS, ":zero": 0, ":one": 1,
            },
            ReturnValues="UPDATED_NEW",
        )
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return response(409, {"message": "Only jobs still waiting in the queue can be cancelled"})
        raise
    sequence = int(result["Attributes"].get("log_count") or 1)
    table.put_item(Item={
        "pk": f"JOB#{task_id}", "sk": f"LOG#{sequence:09d}",
        "message": message, "expires_at": now + TTL_SECONDS,
    })
    record = table.get_item(Key={"pk": f"JOB#{task_id}", "sk": "OWNER"}).get("Item") or {}
    history_sk, owner = str(record.get("history_sk") or ""), str(record.get("user_id") or "")
    for key in (
        {"pk": f"JOB#{task_id}", "sk": "OWNER"},
        {"pk": f"USER#{owner}", "sk": history_sk} if owner and history_sk else None,
    ):
        if not key:
            continue
        table.update_item(
            Key=key,
            UpdateExpression="SET #status=:failed, error_message=:message, updated_at=:now",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":failed": "failed", ":message": message, ":now": now},
        )
    return response(200, {"task_id": task_id, "status": "failed", "message": message})


def delete_job_assets_and_records(task_id, owner, record):
    """Delete only task-scoped S3 objects and every durable record for one job."""
    deleted_assets = 0
    for prefix in (f"users/{owner}/jobs/{task_id}/", f"jobs/{task_id}/"):
        continuation = None
        while True:
            options = {"Bucket": BUCKET, "Prefix": prefix}
            if continuation:
                options["ContinuationToken"] = continuation
            listed = s3.list_objects_v2(**options)
            keys = [{"Key": str(item["Key"])} for item in listed.get("Contents", [])]
            if keys:
                result = s3.delete_objects(Bucket=BUCKET, Delete={"Objects": keys, "Quiet": True})
                errors = result.get("Errors") or []
                if errors:
                    raise RuntimeError(f"Could not delete {len(errors)} retained job asset(s)")
                deleted_assets += len(keys)
            if not listed.get("IsTruncated"):
                break
            continuation = listed.get("NextContinuationToken")

    partition_items = table.query(
        KeyConditionExpression=Key("pk").eq(f"JOB#{task_id}"),
        ProjectionExpression="pk, sk",
    ).get("Items", [])
    history_sk = str(record.get("history_sk") or "")
    with table.batch_writer() as batch:
        for item in partition_items:
            batch.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
        if history_sk.startswith("JOB#") and history_sk.endswith(f"#{task_id}"):
            batch.delete_item(Key={"pk": f"USER#{owner}", "sk": history_sk})
            batch.delete_item(Key={"pk": "ADMIN#JOBS", "sk": history_sk})
    return deleted_assets, len(partition_items)


def delete_admin_job(event, task_id):
    """Administratively remove a non-processing job and all task-only assets."""
    denied = require_admin(event)
    if denied:
        return denied
    owner_key = {"pk": f"JOB#{task_id}", "sk": "OWNER"}
    record = table.get_item(Key=owner_key, ConsistentRead=True).get("Item")
    if not record:
        print(json.dumps({
            "event": "admin_job_delete_not_found", "task_id": task_id,
        }, separators=(",", ":")), flush=True)
        return response(404, {"message": "Job not found"})
    owner = str(record.get("user_id") or "")
    live = runtime(task_id) or {}
    status = str(live.get("status") or record.get("status") or "").lower()
    print(json.dumps({
        "event": "admin_job_delete_requested", "task_id": task_id,
        "owner_id": owner, "status": status or "unknown",
    }, separators=(",", ":")), flush=True)
    if status == "processing":
        print(json.dumps({
            "event": "admin_job_delete_blocked", "task_id": task_id,
            "reason": "processing",
        }, separators=(",", ":")), flush=True)
        return response(409, {"message": "Wait for this processing job to finish before deleting it"})
    if status == "pending" and live.get("payload"):
        try:
            table.update_item(
                Key=runtime_key(task_id),
                UpdateExpression="SET #status=:cancelled, updated_at=:now REMOVE payload",
                ConditionExpression="#status=:pending AND attribute_exists(payload)",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":cancelled": "cancelled", ":pending": "pending", ":now": int(time.time()),
                },
            )
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            current = runtime(task_id) or {}
            if str(current.get("status") or "").lower() == "processing":
                print(json.dumps({
                    "event": "admin_job_delete_blocked", "task_id": task_id,
                    "reason": "processing_race",
                }, separators=(",", ":")), flush=True)
                return response(409, {"message": "The job began processing; wait for it to finish before deleting it"})
    deleted_assets, deleted_records = delete_job_assets_and_records(task_id, owner, record)
    print(json.dumps({
        "event": "admin_job_delete_succeeded", "task_id": task_id,
        "owner_id": owner, "deleted_assets": deleted_assets,
        "deleted_records": deleted_records,
    }, separators=(",", ":")), flush=True)
    return response(200, {
        "task_id": task_id, "deleted": True, "deleted_assets": deleted_assets,
        "deleted_records": deleted_records,
    })


def account_jobs(event):
    owner = user_id(event)
    jobs = []
    for item in user_items(owner, "JOB#", limit=50):
        task_id = str(item.get("task_id") or "")
        if not task_id:
            continue
        live = runtime(task_id)
        status = (live.get("status") if live and live.get("user_id") == owner else None) or item.get("status") or "unknown"
        jobs.append({
            "task_id": task_id, "status": str(status), "job_type": history_job_type(item),
            "source_name": str(item.get("source_name") or "Artwork"),
            "material_name": str(item.get("material_name") or ""),
            "image_preset": str(item.get("image_preset") or ""),
            "abstract_filter": str(item.get("abstract_filter") or "none"),
            "run_parameters": item.get("run_parameters") or {},
            "created_at": int(item.get("created_at") or 0),
            "updated_at": int(item.get("updated_at") or 0),
            "error": str((live or {}).get("error_message") or item.get("error_message") or ""),
        })
    return response(200, {"jobs": jobs})


def account_job(event, task_id):
    owner = user_id(event)
    query = event.get("queryStringParameters") or {}
    include_logs = str(query.get("include_logs") or "").lower() in {"1", "true", "yes"}
    record = table.get_item(
        Key={"pk": f"JOB#{task_id}", "sk": "OWNER"}, ConsistentRead=True,
    ).get("Item")
    if not record or record.get("user_id") != owner:
        return response(404, {"message": "Job not found"})
    history = table.get_item(
        Key={"pk": f"USER#{owner}", "sk": str(record.get("history_sk") or "")},
        ConsistentRead=True,
    ).get("Item") or {}
    live = runtime(task_id)
    logs = []
    if include_logs and live and live.get("user_id") == owner:
        logs = job_logs(task_id, live)
    prefix = str(record.get("artifact_prefix") or f"users/{owner}/jobs/{task_id}/") + "outputs/"
    objects = s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix).get("Contents", [])
    source_name = str(history.get("source_name") or "Artwork")
    outputs = ordered_output_descriptors(task_id, source_name, objects)
    status = (live.get("status") if live and live.get("user_id") == owner else None) or record.get("status") or history.get("status") or "unknown"
    terminal_status = str(status).lower() in {"completed", "failed"}
    ended_at = 0
    if terminal_status:
        ended_at = int(
            history.get("completed_at") or record.get("completed_at")
            or history.get("failed_at") or record.get("failed_at")
            or history.get("updated_at") or record.get("updated_at")
            or ((live or {}).get("updated_at") if (live or {}).get("user_id") == owner else 0)
            or 0
        )
    error_message = str((live or {}).get("error_message") or record.get("error_message") or history.get("error_message") or "")
    return response(200, {
        "task_id": task_id, "status": str(status), "job_type": history_job_type(history),
        "source_name": source_name,
        "material_name": str(history.get("material_name") or ""),
        "image_preset": str(history.get("image_preset") or ""),
        "abstract_filter": str(history.get("abstract_filter") or "none"),
        "run_parameters": history.get("run_parameters") or {},
        "created_at": int(history.get("created_at") or record.get("created_at") or 0),
        "ended_at": ended_at,
        "error": error_message,
        "logs": visible_job_logs(logs, error_message) if include_logs else None,
        "logs_included": include_logs,
        "outputs": outputs,
    })


def delete_account_job(event, task_id):
    """Delete one owned history record and only that job's private artifacts."""
    owner = user_id(event)
    owner_key = {"pk": f"JOB#{task_id}", "sk": "OWNER"}
    record = table.get_item(Key=owner_key, ConsistentRead=True).get("Item")
    if not record or record.get("user_id") != owner:
        return response(404, {"message": "Job not found"})
    live = runtime(task_id)
    if live and live.get("user_id") == owner:
        status = str(live.get("status") or "").lower()
        if status == "processing" or (status == "pending" and live.get("payload")):
            return response(409, {"message": "Wait for this active job to finish before deleting it"})

    deleted_assets, _ = delete_job_assets_and_records(task_id, owner, record)
    return response(200, {"task_id": task_id, "deleted": True, "deleted_assets": deleted_assets})


def clean_depth_palette(data):
    name = str(data.get("name") or "").strip()
    if not name or len(name) > 160:
        raise ValueError("Depth Palette names must be between 1 and 160 characters")
    official = {color.upper(): swatch for swatch, color in PALETTE}
    entries, seen = [], set()
    for raw in data.get("entries") if isinstance(data.get("entries"), list) else []:
        if not isinstance(raw, dict):
            continue
        color = str(raw.get("hex") or "").upper()
        if color not in official or color in seen:
            continue
        seen.add(color)
        entries.append({
            "hex": color, "name": official[color],
            "depth": max(0, min(100, float(raw.get("depth", 50)))),
            "influence": max(0, min(100, float(raw.get("influence", 0)))),
            "enabled": raw.get("enabled") is not False,
        })
    if not entries:
        raise ValueError("Keep at least one Rasterizer swatch in the Depth Palette")
    return name, entries


def save_depth_palette(event, palette_id=None):
    owner, data = user_id(event), body_json(event)
    name, entries = clean_depth_palette(data)
    palette_id = palette_id or str(uuid.uuid4())
    key = {"pk": f"USER#{owner}", "sk": f"DEPTHPALETTE#{palette_id}"}
    existing = table.get_item(Key=key, ConsistentRead=True).get("Item") if palette_id else None
    if palette_id and event.get("rawPath", "").rstrip("/") != "/account/depth-palettes" and not existing:
        return response(404, {"message": "Depth Palette not found"})
    now = int(time.time())
    item = {**key, "palette_id": palette_id, "name": name, "entries": dynamo_value(entries),
            "created_at": int((existing or {}).get("created_at") or now), "updated_at": now}
    table.put_item(Item=item)
    return response(200 if existing else 201, {"palette": item})


def delete_owned_item(event, kind, item_id):
    owner = user_id(event)
    definitions = {
        "depth": (f"DEPTHPALETTE#{item_id}", None),
        "material": (f"MATERIAL#{item_id}", f"users/{owner}/materials/{item_id}/"),
        "recipe": (f"HOLORECIPE#{item_id}", f"users/{owner}/holographic-recipes/{item_id}/"),
    }
    sk, expected_prefix = definitions[kind]
    key = {"pk": f"USER#{owner}", "sk": sk}
    item = table.get_item(Key=key, ConsistentRead=True).get("Item")
    if not item:
        return response(404, {"message": "Saved item not found"})
    object_key = str(item.get("s3_key") or "")
    if expected_prefix:
        if not object_key.startswith(expected_prefix):
            return response(400, {"message": "We couldn't safely delete this saved item, so it was left unchanged. Report the problem with the item name and your account email."})
        s3.delete_object(Bucket=BUCKET, Key=object_key)
    table.delete_item(Key=key)
    return response(200, {"deleted": True})


def rename_material(event, library_id):
    owner, data = user_id(event), body_json(event)
    key = {"pk": f"USER#{owner}", "sk": f"MATERIAL#{library_id}"}
    existing = table.get_item(Key=key, ConsistentRead=True).get("Item")
    if not existing:
        return response(404, {"message": "Material Library not found"})
    name = str(data.get("name") or "").strip()
    if not name or len(name) > 160:
        raise ValueError("Material Library names must be between 1 and 160 characters")
    source = s3.get_object(Bucket=BUCKET, Key=existing["s3_key"])["Body"].read(MAX_MATERIAL_BYTES + 1)
    if len(source) > MAX_MATERIAL_BYTES:
        raise ValueError(f"This Material Library exceeds the {MATERIAL_LIMIT_MB} limit. Export a smaller library from LightBurn and import it again.")
    root = ET.fromstring(source)
    material, old_material_name = single_palette_material(root)
    material_name = str(data.get("material_name") or old_material_name).strip()
    if not material_name or len(material_name) > 160:
        raise ValueError("Palette material names must be between 1 and 160 characters")
    material.set("name", material_name)
    if material_name != old_material_name:
        for link in material.findall(".//LinkPath"):
            value = str(link.get("Value") or "")
            if value.startswith(old_material_name + "/"):
                link.set("Value", material_name + value[len(old_material_name):])
    contents = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    summary = material_summary(contents)
    s3.put_object(Bucket=BUCKET, Key=existing["s3_key"], Body=contents, ContentType="application/xml")
    intent = "hatch_palette" if existing.get("library_intent") == "hatch_palette" else "color_palette"
    table.update_item(Key=key, UpdateExpression="SET #name=:name, material_name=:material, summary=:summary, updated_at=:now",
                      ExpressionAttributeNames={"#name": "name"},
                      ExpressionAttributeValues={":name": name, ":material": material_name,
                                                 ":summary": dynamo_value(summary), ":now": int(time.time())})
    return response(200, {"name": name, "material_name": material_name,
                          "library_intent": intent, "summary": public_library_summary(summary)})


def single_palette_material(root, context="Palette"):
    """Return the one populated LightBurn material owned by a swatch palette."""
    materials = [material for material in root.findall("./Material") if material.findall("./Entry")]
    if len(materials) != 1:
        raise ValueError(f"{context} must contain settings for exactly one material")
    material_name = str(materials[0].get("name") or "").strip()
    if not material_name or len(material_name) > 160:
        raise ValueError(f"{context} must have one material name between 1 and 160 characters")
    return materials[0], material_name


def edit_material_entry(event, library_id, entry_id):
    owner, data = user_id(event), body_json(event)
    library = owned_material(owner, library_id)
    if not library:
        return response(404, {"message": "Material Library not found"})
    description = str(data.get("description") or "").strip()
    setting_type = str(data.get("type") or "Scan").strip()
    settings = data.get("settings") if isinstance(data.get("settings"), dict) else {}
    unset_settings = data.get("unset_settings") if isinstance(data.get("unset_settings"), list) else []
    if not description or len(description) > 160:
        raise ValueError("Description is required and must be 160 characters or fewer")
    if setting_type not in {"Cut", "Scan", "Image", "Offset"} or len(settings) + len(unset_settings) > 80:
        raise ValueError("Choose a valid operation type and a small settings object")
    source = s3.get_object(Bucket=BUCKET, Key=library["s3_key"])["Body"].read(MAX_MATERIAL_BYTES + 1)
    if len(source) > MAX_MATERIAL_BYTES:
        raise ValueError(f"This Material Library exceeds the {MATERIAL_LIMIT_MB} limit. Export a smaller library from LightBurn and import it again.")
    root = ET.fromstring(source)
    destination, material_name = single_palette_material(root, "Destination palette")
    entries = [(material, entry) for material in root.findall("./Material") for entry in material.findall("./Entry")]
    if entry_id < 0 or entry_id >= len(entries):
        return response(404, {"message": "Material Library entry not found"})
    _old_material, entry = entries[entry_id]
    old_description = str(entry.get("Desc") or "").strip()
    for candidate in destination.findall("./Entry"):
        if candidate is not entry and str(candidate.get("Desc") or "").casefold() == description.casefold():
            raise ValueError("That palette already contains a setting with this Description")
    entry.set("Desc", description)
    cut = entry.find("./CutSetting")
    if cut is None: cut = ET.SubElement(entry, "CutSetting")
    cut.set("type", setting_type)
    for name in unset_settings:
        name = str(name)
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name): continue
        field = cut.find(f"./{name}")
        if field is not None: cut.remove(field)
    for name, value in settings.items():
        name = str(name)
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name) or isinstance(value, (dict, list)): continue
        field = cut.find(f"./{name}")
        if field is None: field = ET.SubElement(cut, name)
        field.set("Value", str(value)[:160])
    contents = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    summary, now = material_summary(contents), int(time.time())
    s3.put_object(Bucket=BUCKET, Key=library["s3_key"], Body=contents, ContentType="application/xml")
    table.update_item(Key={"pk": f"USER#{owner}", "sk": f"MATERIAL#{library_id}"},
                      UpdateExpression="SET summary=:summary, material_name=:material, updated_at=:now",
                      ExpressionAttributeValues={":summary": dynamo_value(summary), ":material": material_name, ":now": now})
    preserve_material_assignment_names(owner, library_id, old_description, description)
    return response(200, {"summary": public_library_summary(summary)})


LIGHTBURN_SETTING_FIELD_ORDER = (
    "index", "name", "LinkPath", "minPower", "maxPower", "minPower2", "maxPower2",
    "speed", "frequency", "PPI", "QPulseWidth", "LaserOn_TC", "LaserOff_TC",
    "Polygon_TC", "JumpSpeed", "MinJumpDelay", "MaxJumpDelay", "numPasses",
    "crossHatch", "angle", "anglePerPass", "perfLen", "perfSkip", "dotTime",
    "dotSpacing", "scanOpt", "floodFill", "overscan", "overscanPercent", "interval", "tabsEnabled",
    "priority", "tabSize", "tabCount", "tabCountMax", "tabSpacing", "hide",
)


def lightburn_snapshot_element(snapshot):
    validate_lightburn_setting_snapshot(snapshot)
    cut = ET.Element("CutSetting", {"type":str(snapshot.get("type") or "Setting")})
    settings = snapshot.get("settings") or {}
    order = {name:index for index,name in enumerate(LIGHTBURN_SETTING_FIELD_ORDER)}
    for name, value in sorted(settings.items(), key=lambda item:(order.get(str(item[0]), len(order)), str(item[0]))):
        ET.SubElement(cut, str(name), {"Value":str(value)})
    for sub_layer in snapshot.get("sub_layers") or []:
        child = lightburn_snapshot_element(sub_layer)
        child.tag = "SubLayer"
        cut.append(child)
    return cut


def nearest_lightburn_palette_index(color_hex):
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(color_hex or "")):
        return 0
    sample = tuple(int(color_hex[index:index+2], 16) for index in (1,3,5))
    return min(range(len(PALETTE)), key=lambda index: sum(
        (sample[channel] - int(PALETTE[index][1][1+channel*2:3+channel*2], 16)) ** 2
        for channel in range(3)
    ))


def selected_settings_root(owner, selections, material_name, allow_duplicates=False):
    if not isinstance(selections, list) or not 1 <= len(selections) <= 500:
        raise ValueError("Select between 1 and 500 Material Library settings")
    material_name = str(material_name or "").strip()
    if not material_name or len(material_name) > 160:
        raise ValueError("Provide a Material Name between 1 and 160 characters")
    requested, recipe_requested = {}, {}
    for selection in selections:
        library_id = str(selection.get("library_id") or "") if isinstance(selection, dict) else ""
        entry_id = selection.get("entry_id") if isinstance(selection, dict) else None
        recipe_id = str(selection.get("recipe_id") or "") if isinstance(selection, dict) else ""
        recipe_index = selection.get("recipe_index") if isinstance(selection, dict) else None
        if library_id and isinstance(entry_id, int) and entry_id >= 0:
            requested.setdefault(library_id, set()).add(entry_id)
        elif recipe_id and isinstance(recipe_index, int) and recipe_index >= 0:
            recipe_requested.setdefault(recipe_id, set()).add(recipe_index)
        else:
            raise ValueError("We couldn't read one or more selected settings. Reload the page, select them again, and retry.")
    root = ET.Element("LightBurnLibrary")
    target = ET.SubElement(root, "Material", {"name": material_name})
    descriptions = set()
    for library_id, entry_ids in requested.items():
        library = owned_material(owner, library_id)
        if not library:
            raise ValueError("One of the selected Material Libraries no longer exists. Reload the Vault, select the settings again, and retry.")
        contents = s3.get_object(Bucket=BUCKET, Key=library["s3_key"])["Body"].read(MAX_MATERIAL_BYTES + 1)
        if len(contents) > MAX_MATERIAL_BYTES:
            raise ValueError(f"One of the selected Material Libraries exceeds the {MATERIAL_LIMIT_MB} limit. Select a smaller library or import a smaller LightBurn export.")
        source_root = ET.fromstring(contents)
        entries = [entry for material in source_root.findall("./Material") for entry in material.findall("./Entry")]
        for entry_id in sorted(entry_ids):
            if entry_id >= len(entries):
                raise ValueError("One of the selected Material Library settings no longer exists. Reload the Vault, select the settings again, and retry.")
            entry = entries[entry_id]
            description = str(entry.get("Desc") or "").strip().casefold()
            if description in descriptions and not allow_duplicates:
                raise ValueError(f"Duplicate swatch name '{entry.get('Desc')}' is not allowed")
            descriptions.add(description)
            target.append(deepcopy(entry))
    for recipe_id, recipe_indexes in recipe_requested.items():
        record = owned_recipe(owner, recipe_id)
        if not record:
            raise ValueError("One of the selected Fauxlographic Palettes no longer exists. Reload the Vault, select the settings again, and retry.")
        profile = json.loads(s3.get_object(Bucket=BUCKET, Key=record["s3_key"])["Body"].read(MAX_RECIPE_BYTES + 1))
        measured = profile.get("recipes") if isinstance(profile, dict) else None
        if fauxlographic_schema_version(profile) < 2 or not isinstance(measured, list):
            raise ValueError("Only self-contained Fauxlographic Palette swatches can be exported")
        for recipe_index in sorted(recipe_indexes):
            if recipe_index >= len(measured):
                raise ValueError("One of the selected Fauxlographic Palette swatches no longer exists. Reload the Vault, select the settings again, and retry.")
            recipe = measured[recipe_index]
            description = str(recipe.get("name") or "").strip()
            normalized = description.casefold()
            if not description or normalized in descriptions and not allow_duplicates:
                raise ValueError(f"Duplicate swatch name '{description}' is not allowed")
            descriptions.add(normalized)
            entry = ET.Element("Entry", {"Thickness":"-1.0000", "Desc":description,
                                         "NoThickTitle":f"{description} {str(recipe.get('observed_hex') or '')}"[:160]})
            cut = lightburn_snapshot_element(recipe.get("laser_settings"))
            index_node = cut.find("./index")
            if index_node is None:
                index_node = ET.SubElement(cut, "index")
            index_node.set("Value", str(nearest_lightburn_palette_index(recipe.get("observed_hex"))))
            name_node = cut.find("./name")
            if name_node is None:
                name_node = ET.SubElement(cut, "name")
            name_node.set("Value", description)
            entry.append(cut)
            target.append(entry)
    return root


def fauxlographic_swatch_capacity(black_setting):
    has_black_layer = usable_preserved_black_setting(black_setting) is not None
    return MAX_LIGHTBURN_LAYERS - int(has_black_layer)


def fauxlographic_swatch_limit_message(black_setting):
    capacity = fauxlographic_swatch_capacity(black_setting)
    if capacity < MAX_LIGHTBURN_LAYERS:
        return f"A Fauxlographic Palette with preserved Black can have at most {capacity} measured swatches ({MAX_LIGHTBURN_LAYERS} LightBurn layers total)."
    return f"A Fauxlographic Palette can have at most {capacity} swatches."


def fauxlographic_schema_version(profile):
    try:
        version = int(profile.get("schema_version") or 1)
        if version < 1:
            raise ValueError("Version must be positive")
    except (AttributeError, TypeError, ValueError, OverflowError) as error:
        raise ValueError("This Fauxlographic Palette has an invalid file version. Export a fresh palette JSON and import it again.") from error
    return version


def uploaded_holographic_settings_root(profile, recipe_indexes, material_name):
    """Build a transient LightBurn library from an uploaded Fauxlographic Palette."""
    if not isinstance(profile, dict) or profile.get("kind") != "holographic_calibration_profile":
        raise ValueError("Choose a valid Fauxlographic Swatch Palette")
    measured = profile.get("recipes")
    if fauxlographic_schema_version(profile) < 2 or not isinstance(measured, list) or not measured:
        raise ValueError("Choose a self-contained Fauxlographic Swatch Palette")
    black_setting = profile.get("black_setting")
    capacity = fauxlographic_swatch_capacity(black_setting)
    if len(measured) > capacity:
        raise ValueError(f"{fauxlographic_swatch_limit_message(black_setting)} Choose a palette with fewer swatches.")
    if not isinstance(recipe_indexes, list) or not recipe_indexes:
        raise ValueError("Select at least one Fauxlographic Palette swatch")
    recipe_indexes = list(dict.fromkeys(recipe_indexes))
    if len(recipe_indexes) > capacity:
        raise ValueError(f"Select no more than {capacity} Fauxlographic Palette swatches for one job.")
    if any(not isinstance(index, int) or isinstance(index, bool)
           or index < 0 or index >= len(measured) for index in recipe_indexes):
        raise ValueError("One or more selected Fauxlographic Palette swatches are no longer available. Reload the palette and select them again.")
    material_name = str(material_name or profile.get("profile_name") or "Fauxlographic Palette").strip()
    if not material_name or len(material_name) > 160:
        raise ValueError("Provide a Material Name between 1 and 160 characters")
    root = ET.Element("LightBurnLibrary")
    target = ET.SubElement(root, "Material", {"name": material_name})
    descriptions = {}
    for recipe_index in sorted(recipe_indexes):
        recipe = measured[recipe_index]
        if not isinstance(recipe, dict):
            raise ValueError(f"Swatch {recipe_index + 1} in the uploaded Fauxlographic Palette could not be read. Check the JSON file or export a fresh palette, then try again.")
        description = str(recipe.get("name") or "").strip()
        normalized = description.casefold()
        if not description:
            raise ValueError(f"Swatch {recipe_index + 1} in the uploaded Fauxlographic Palette has no name. Name it in the JSON file or export a fresh palette, then try again.")
        if normalized in descriptions:
            raise ValueError(f"Swatches {descriptions[normalized]} and {recipe_index + 1} in the uploaded Fauxlographic Palette both use the name '{description}'. Give them distinct names in the JSON file, then try again.")
        descriptions[normalized] = recipe_index + 1
        entry = ET.Element("Entry", {
            "Thickness": "-1.0000", "Desc": description,
            "NoThickTitle": f"{description} {str(recipe.get('observed_hex') or '')}"[:160],
        })
        try:
            cut = lightburn_snapshot_element(recipe.get("laser_settings"))
        except ValueError as error:
            raise ValueError(f"Swatch {recipe_index + 1} ('{description}') has invalid embedded LightBurn settings in the uploaded Fauxlographic Palette. Check the JSON file or export a fresh palette, then try again.") from error
        index_node = cut.find("./index")
        if index_node is None:
            index_node = ET.SubElement(cut, "index")
        index_node.set("Value", str(nearest_lightburn_palette_index(recipe.get("observed_hex"))))
        name_node = cut.find("./name")
        if name_node is None:
            name_node = ET.SubElement(cut, "name")
        name_node.set("Value", description)
        entry.append(cut)
        target.append(entry)
    return root


def validate_library_descriptions(root):
    for material in root.findall("./Material"):
        seen = set()
        for entry in material.findall("./Entry"):
            description = str(entry.get("Desc") or "").strip()
            if not description or description.casefold() in seen:
                raise ValueError(
                    f"Material '{material.get('name')}' has a missing or repeated LightBurn entry Description. "
                    "Give each setting in that material a distinct Description, then import the library again."
                )
            seen.add(description.casefold())


LIGHTBURN_SAFE_OPTIMIZATION_PREFS = (
    ("Optimize_ByLayer", "0"),
    ("Optimize_ByGroup", "-1"),
    ("Optimize_ByPriority", "-1"),
    ("Optimize_WhichDirection", "0"),
    ("Optimize_InnerToOuter", "0"),
    ("Optimize_ByDirection", "0"),
    ("Optimize_ReduceTravel", "0"),
    ("Optimize_HideBacklash", "0"),
    ("Optimize_ReduceDirChanges", "0"),
    ("Optimize_ChooseCorners", "0"),
    ("Optimize_AllowReverse", "0"),
    ("Optimize_RemoveOverlaps", "0"),
    ("Optimize_OptimalEntryPoint", "0"),
    ("Optimize_OverlapDist", "0.025"),
)


def add_lightburn_safe_optimization_prefs(project):
    """Keep layer order while disabling expensive LightBurn path optimization."""
    prefs = ET.SubElement(project, "UIPrefs")
    for name, value in LIGHTBURN_SAFE_OPTIMIZATION_PREFS:
        ET.SubElement(prefs, name, {"Value": value})
    return prefs


def coupon_project(library_root, material_name, width, length, label_entry=None):
    entries = [entry for material in library_root.findall("./Material") for entry in material.findall("./Entry")]
    if not 1 <= len(entries) <= 29:
        raise ValueError("A labeled LightBurn coupon requires between 1 and 29 selected settings")
    width, length = float(width), float(length)
    if not 10 <= width <= 1000 or not 10 <= length <= 1000:
        raise ValueError("Coupon width and length must each be between 10 and 1000 mm")
    project = ET.Element("LightBurnProject", {"AppVersion":"2.1.04","FormatVersion":"1","MaterialHeight":"0","MirrorX":"False","MirrorY":"True","AskForSendName":"True"})
    add_lightburn_safe_optimization_prefs(project)
    columns = min(10, max(1, math.ceil(math.sqrt(len(entries)))))
    rows = math.ceil(len(entries) / columns)
    cell, gap, label_space = 10.0, 2.0, 6.0
    native_width = columns * cell + max(0, columns - 1) * gap
    native_length = 8 + (rows - 1) * (cell + label_space) + label_space / 2 + cell
    scale_x, scale_y = width / native_width, length / native_length
    transform = lambda x, y: f"{scale_x:.12g} 0 0 {scale_y:.12g} {x * scale_x:.12g} {y * scale_y:.12g}"
    label_source = label_entry if label_entry is not None else next(
        (entry for entry in entries if str(entry.get("Desc") or "").strip().casefold() == "labels"), entries[0],
    )
    label_layer = deepcopy(label_source.find("./CutSetting"))
    if label_layer is None: label_layer = ET.Element("CutSetting", {"type":"Scan"})
    index = label_layer.find("./index")
    if index is None: index = ET.SubElement(label_layer, "index")
    index.set("Value", "0")
    name = label_layer.find("./name")
    if name is None: name = ET.SubElement(label_layer, "name")
    name.set("Value", "Coupon labels")
    project.append(label_layer)
    title = ET.Element("Shape", {"Type":"Text","ShapeID":"0","CutIndex":"0","Font":"Arial,-1,100,5,50,0,0,0,0,0","Str":str(material_name)[:120],"H":"5.25","LS":"0","LnS":"0","Ah":"1","Av":"1","Weld":"1","HasBackupPath":"0"})
    ET.SubElement(title, "XForm").text = transform(native_width / 2, 3); project.append(title)
    for position, entry in enumerate(entries):
        layer = deepcopy(entry.find("./CutSetting"))
        if layer is None: layer = ET.Element("CutSetting", {"type":"Scan"})
        cut_index = position + 1
        index = layer.find("./index")
        if index is None: index = ET.SubElement(layer, "index")
        index.set("Value", str(cut_index))
        name = layer.find("./name")
        if name is None: name = ET.SubElement(layer, "name")
        name.set("Value", str(entry.get("Desc") or f"Coupon {cut_index}")[:80])
        project.append(layer)
        row, column = divmod(position, columns)
        x, label_y = cell / 2 + column * (cell + gap), 8 + row * (cell + label_space)
        label = ET.Element("Shape", {"Type":"Text","ShapeID":str(position*2+1),"CutIndex":"0","Font":"Arial,-1,100,5,50,0,0,0,0,0","Str":str(entry.get("Desc") or f"Cell {cut_index}")[:80],"H":"3.5","LS":"0","LnS":"0","Ah":"1","Av":"1","Weld":"1","HasBackupPath":"0"})
        ET.SubElement(label, "XForm").text = transform(x, label_y); project.append(label)
        shape = ET.Element("Shape", {"Type":"Rect","ShapeID":str(position*2+2),"CutIndex":str(cut_index),"W":f"{cell:g}","H":f"{cell:g}","Cr":"0"})
        ET.SubElement(shape, "XForm").text = transform(x, label_y + label_space / 2 + cell / 2); project.append(shape)
    return project


def selected_blank_project_settings(owner, selections):
    """Resolve selected private swatches in selection order for a blank project."""
    if not isinstance(selections, list) or not 1 <= len(selections) <= len(PALETTE):
        raise ValueError(f"Select between 1 and {len(PALETTE)} settings for a blank LightBurn project")
    material_cache, recipe_cache, resolved = {}, {}, []
    for selection in selections:
        if not isinstance(selection, dict):
            raise ValueError("We couldn't read one or more selected settings. Reload the page, select them again, and retry.")
        library_id = str(selection.get("library_id") or "")
        recipe_id = str(selection.get("recipe_id") or "")
        entry_id = selection.get("entry_id")
        recipe_index = selection.get("recipe_index")
        preferred_hex = str(selection.get("swatch_hex") or "").strip().upper()
        preferred_index = next(
            (index for index, (_, color) in enumerate(PALETTE) if color.upper() == preferred_hex), None,
        )
        if library_id and isinstance(entry_id, int) and not isinstance(entry_id, bool) and entry_id >= 0:
            if library_id not in material_cache:
                library = owned_material(owner, library_id)
                if not library:
                    raise ValueError("One of the selected Material Libraries no longer exists. Reload the Vault, select the settings again, and retry.")
                contents = s3.get_object(Bucket=BUCKET, Key=library["s3_key"])["Body"].read(MAX_MATERIAL_BYTES + 1)
                if len(contents) > MAX_MATERIAL_BYTES:
                    raise ValueError(f"One of the selected Material Libraries exceeds the {MATERIAL_LIMIT_MB} limit. Select a smaller library or import a smaller LightBurn export.")
                source = ET.fromstring(contents)
                material_cache[library_id] = [
                    entry for material in source.findall("./Material") for entry in material.findall("./Entry")
                ]
            entries = material_cache[library_id]
            if entry_id >= len(entries):
                raise ValueError("One of the selected Material Library settings no longer exists. Reload the Vault, select the settings again, and retry.")
            entry = deepcopy(entries[entry_id])
            expected = str(selection.get("entry_description") or "").strip()
            description = str(entry.get("Desc") or "").strip()
            if expected and description != expected:
                raise ValueError("A selected Material Library setting changed since this page loaded. Reload the Vault, select the settings again, and retry.")
            if preferred_index is None:
                official_hex = PALETTE_HEX.get(description.casefold())
                preferred_index = next(
                    (index for index, (_, color) in enumerate(PALETTE) if color == official_hex), None,
                )
            resolved.append((entry, preferred_index))
            continue
        if recipe_id and isinstance(recipe_index, int) and not isinstance(recipe_index, bool) and recipe_index >= 0:
            if recipe_id not in recipe_cache:
                record = owned_recipe(owner, recipe_id)
                if not record:
                    raise ValueError("One of the selected Fauxlographic Palettes no longer exists. Reload the Vault, select the settings again, and retry.")
                profile = json.loads(s3.get_object(Bucket=BUCKET, Key=record["s3_key"])["Body"].read(MAX_RECIPE_BYTES + 1))
                measured = profile.get("recipes") if isinstance(profile, dict) else None
                if fauxlographic_schema_version(profile) < 2 or not isinstance(measured, list):
                    raise ValueError("Only self-contained Fauxlographic Palette swatches can be used")
                recipe_cache[recipe_id] = measured
            measured = recipe_cache[recipe_id]
            if recipe_index >= len(measured) or not isinstance(measured[recipe_index], dict):
                raise ValueError("One of the selected Fauxlographic Palette swatches no longer exists. Reload the Vault, select the settings again, and retry.")
            recipe = measured[recipe_index]
            description = str(recipe.get("name") or "").strip()
            expected_name = str(selection.get("recipe_name") or "").strip()
            expected_hex = str(selection.get("recipe_hex") or "").strip().upper()
            observed_hex = str(recipe.get("observed_hex") or "").strip().upper()
            if (expected_name and description != expected_name) or (expected_hex and observed_hex != expected_hex):
                raise ValueError("A selected Fauxlographic Palette swatch changed since this page loaded. Reload the Vault, select the swatches again, and retry.")
            if not description:
                raise ValueError("A selected Fauxlographic Palette swatch has no name. Name that swatch in the Vault, then select it again.")
            entry = ET.Element("Entry", {
                "Thickness":"-1.0000", "Desc":description,
                "NoThickTitle":f"{description} {observed_hex}"[:160],
            })
            entry.append(lightburn_snapshot_element(recipe.get("laser_settings")))
            if preferred_index is None:
                preferred_index = nearest_lightburn_palette_index(observed_hex)
            resolved.append((entry, preferred_index))
            continue
        raise ValueError("We couldn't read one or more selected settings. Reload the page, select them again, and retry.")
    return resolved


def blank_lightburn_project(settings):
    """Build a geometry-free LightBurn project with deterministic layer assignment."""
    if not isinstance(settings, list) or not 1 <= len(settings) <= len(PALETTE):
        raise ValueError(f"A blank LightBurn project requires between 1 and {len(PALETTE)} settings")
    claimed, overflow = {}, []
    for entry, preferred_index in settings:
        if isinstance(preferred_index, int) and not isinstance(preferred_index, bool) and 0 <= preferred_index < len(PALETTE) and preferred_index not in claimed:
            claimed[preferred_index] = entry
        else:
            overflow.append(entry)
    unused = [index for index in range(len(PALETTE)) if index not in claimed]
    if len(overflow) > len(unused):
        raise ValueError(f"The selected settings exceed LightBurn's {MAX_LIGHTBURN_LAYERS}-layer limit. Deselect settings until the project fits, then try again.")
    assignments = list(claimed.items()) + list(zip(unused, overflow))
    project = ET.Element("LightBurnProject", {
        "AppVersion":"2.1.04", "FormatVersion":"1", "MaterialHeight":"0",
        "MirrorX":"False", "MirrorY":"True", "AskForSendName":"True",
    })
    add_lightburn_safe_optimization_prefs(project)
    for layer_index, entry in sorted(assignments, key=lambda item:item[0]):
        layer = deepcopy(entry.find("./CutSetting"))
        if layer is None:
            raise ValueError(
                f"Selected setting '{entry.get('Desc') or 'Unnamed setting'}' has no LightBurn cut settings. "
                "Choose another setting or correct that entry in LightBurn and import the library again."
            )
        for link_path in layer.findall("./LinkPath"):
            layer.remove(link_path)
        index_node = layer.find("./index")
        if index_node is None:
            index_node = ET.SubElement(layer, "index")
        index_node.set("Value", str(layer_index))
        name_node = layer.find("./name")
        if name_node is None:
            name_node = ET.SubElement(layer, "name")
        name_node.set("Value", str(entry.get("Desc") or f"Layer {layer_index}")[:80])
        project.append(layer)
    return project


def delete_selected_palette_settings(owner, selections):
    """Delete selected Material Library and Fauxlographic Palette swatches."""
    if not isinstance(selections, list) or not 1 <= len(selections) <= 500:
        raise ValueError("Select between 1 and 500 palette settings")
    requested, recipe_requested = {}, {}
    for selection in selections:
        library_id = str(selection.get("library_id") or "") if isinstance(selection, dict) else ""
        entry_id = selection.get("entry_id") if isinstance(selection, dict) else None
        entry_description = str(selection.get("entry_description") or "").strip() if isinstance(selection, dict) else ""
        recipe_id = str(selection.get("recipe_id") or "") if isinstance(selection, dict) else ""
        recipe_index = selection.get("recipe_index") if isinstance(selection, dict) else None
        recipe_name = str(selection.get("recipe_name") or "").strip() if isinstance(selection, dict) else ""
        recipe_hex = str(selection.get("recipe_hex") or "").strip().upper() if isinstance(selection, dict) else ""
        if library_id and isinstance(entry_id, int) and not isinstance(entry_id, bool) and entry_id >= 0 and entry_description:
            expected = requested.setdefault(library_id, {})
            if entry_id in expected and expected[entry_id] != entry_description:
                raise ValueError("Some selected items have conflicting details. Reload the page, select them again, and retry.")
            expected[entry_id] = entry_description
        elif (recipe_id and isinstance(recipe_index, int) and not isinstance(recipe_index, bool)
              and recipe_index >= 0 and recipe_name and recipe_hex):
            expected = recipe_requested.setdefault(recipe_id, {})
            identity = (recipe_name, recipe_hex)
            if recipe_index in expected and expected[recipe_index] != identity:
                raise ValueError("Some selected items have conflicting details. Reload the page, select them again, and retry.")
            expected[recipe_index] = identity
        else:
            raise ValueError("We couldn't read one or more selected settings. Reload the page, select them again, and retry.")

    material_updates, recipe_updates, deleted_count = [], [], 0
    for library_id, expected_entries in requested.items():
        entry_ids = set(expected_entries)
        library = owned_material(owner, library_id)
        if not library:
            raise ValueError("One of the selected Material Libraries no longer exists. Reload the Vault, select the settings again, and retry.")
        source = s3.get_object(Bucket=BUCKET, Key=library["s3_key"])["Body"].read(MAX_MATERIAL_BYTES + 1)
        if len(source) > MAX_MATERIAL_BYTES:
            raise ValueError(f"One of the selected Material Libraries exceeds the {MATERIAL_LIMIT_MB} limit. Select a smaller library or import a smaller LightBurn export.")
        root = ET.fromstring(source)
        entries = [(material, entry) for material in root.findall("./Material") for entry in material.findall("./Entry")]
        if any(entry_id >= len(entries) for entry_id in entry_ids):
            raise ValueError("One of the selected Material Library settings no longer exists. Reload the Vault, select the settings again, and retry.")
        if any(str(entries[entry_id][1].get("Desc") or "").strip() != expected_entries[entry_id]
               for entry_id in entry_ids):
            raise ValueError("One of the selected settings changed; reload the palette and select it again")
        if len(entries) - len(entry_ids) < 1:
            raise ValueError(f"Keep at least one setting in '{library.get('name') or 'Material Library'}'")
        removed_names = set()
        for entry_id in sorted(entry_ids, reverse=True):
            material, entry = entries[entry_id]
            removed_names.add(str(entry.get("Desc") or "").strip().casefold())
            material.remove(entry)
        for material in list(root.findall("./Material")):
            if not material.findall("./Entry"):
                root.remove(material)
        contents = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        validate_library_descriptions(root)
        summary = material_summary(contents)
        material_updates.append((library_id, library, contents, summary, removed_names))
        deleted_count += len(entry_ids)

    for recipe_id, expected_recipes in recipe_requested.items():
        recipe_indexes = set(expected_recipes)
        record = owned_recipe(owner, recipe_id)
        if not record:
            raise ValueError("One of the selected Fauxlographic Palettes no longer exists. Reload the Vault, select the settings again, and retry.")
        try:
            profile = json.loads(s3.get_object(Bucket=BUCKET, Key=record["s3_key"])["Body"].read(MAX_RECIPE_BYTES + 1))
        except (ClientError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(
                "We couldn't open one of the selected Fauxlographic Palettes. Reload the Vault and try again. If it still fails, report the palette name."
            ) from error
        measured = profile.get("recipes") if isinstance(profile, dict) else None
        if (not isinstance(profile, dict) or fauxlographic_schema_version(profile) < 2
                or not isinstance(measured, list)):
            raise ValueError("Only self-contained Fauxlographic Palette swatches can be deleted")
        if any(index >= len(measured) for index in recipe_indexes):
            raise ValueError("One of the selected Fauxlographic Palette swatches no longer exists. Reload the Vault, select the settings again, and retry.")
        unreadable_index = next((index for index in sorted(recipe_indexes) if not isinstance(measured[index], dict)), None)
        if unreadable_index is not None:
            raise ValueError(
                f"Swatch {unreadable_index + 1} in Fauxlographic Palette '{record.get('name') or 'Unnamed palette'}' could not be read. "
                "Reload the Vault and try again. If it still fails, report the palette name and swatch number."
            )
        if any((str(measured[index].get("name") or "").strip(),
                str(measured[index].get("observed_hex") or "").strip().upper()) != expected_recipes[index]
               for index in recipe_indexes):
            raise ValueError("One of the selected swatches changed; reload the palette and select it again")
        if len(measured) - len(recipe_indexes) < 1:
            raise ValueError(f"Keep at least one swatch in '{record.get('name') or 'Fauxlographic Palette'}'")
        kept = [item for index, item in enumerate(measured) if index not in recipe_indexes]
        profile["recipes"] = kept
        body = json.dumps(profile, indent=2).encode()
        if len(body) > MAX_RECIPE_BYTES:
            raise ValueError("This Fauxlographic Palette exceeds the save-size limit. Remove unneeded swatches, then save again.")
        metadata = dict(record.get("metadata") or {})
        metadata.update({
            "recipe_count": len(kept), "swatch_preview": holographic_swatch_preview(kept),
            "schema_version": 2, "self_contained": True,
            "has_black_setting": bool(profile.get("black_setting")),
        })
        recipe_updates.append((recipe_id, record, body, metadata))
        deleted_count += len(recipe_indexes)

    now = int(time.time())
    for library_id, library, contents, summary, _removed_names in material_updates:
        s3.put_object(Bucket=BUCKET, Key=library["s3_key"], Body=contents, ContentType="application/xml")
        table.update_item(
            Key={"pk": f"USER#{owner}", "sk": f"MATERIAL#{library_id}"},
            UpdateExpression="SET summary=:summary, material_name=:material, updated_at=:now",
            ExpressionAttributeValues={
                ":summary": dynamo_value(summary),
                ":material": ", ".join(summary["material_names"])[:160], ":now": now,
            },
        )
    for recipe_id, record, body, metadata in recipe_updates:
        s3.put_object(Bucket=BUCKET, Key=record["s3_key"], Body=body, ContentType="application/json")
        table.update_item(
            Key={"pk": f"USER#{owner}", "sk": f"HOLORECIPE#{recipe_id}"},
            UpdateExpression="SET metadata=:metadata, updated_at=:now",
            ExpressionAttributeValues={":metadata": dynamo_value(metadata), ":now": now},
        )

    if material_updates:
        preferences_key = {"pk": f"USER#{owner}", "sk": "PREFERENCES"}
        preferences_item = table.get_item(Key=preferences_key, ConsistentRead=True).get("Item") or {}
        preferences = dict(preferences_item.get("preferences") or {})
        assignments = dict(preferences.get("material_library_color_assignments") or {})
        changed = False
        for library_id, _library, _contents, _summary, removed_names in material_updates:
            mapping = dict(assignments.get(library_id) or {})
            cleaned = {color: name for color, name in mapping.items() if str(name).strip().casefold() not in removed_names}
            if cleaned != mapping:
                changed = True
                if cleaned:
                    assignments[library_id] = cleaned
                else:
                    assignments.pop(library_id, None)
        if changed:
            preferences["material_library_color_assignments"] = assignments
            table.put_item(Item={
                **preferences_key, "preferences": dynamo_value(clean_account_preferences(preferences)),
                "updated_at": now,
            })
    return response(200, {
        "deleted": True, "deleted_settings": deleted_count,
        "updated_palettes": len(material_updates) + len(recipe_updates),
    })


def selected_material_settings(event):
    owner, data = user_id(event), body_json(event)
    action = str(data.get("action") or "")
    if action == "delete":
        return delete_selected_palette_settings(owner, data.get("selections"))
    material_name = str(data.get("material_name") or "").strip()
    if action == "blank_project":
        if not material_name or len(material_name) > 160:
            raise ValueError("Provide a project name between 1 and 160 characters")
        project = blank_lightburn_project(selected_blank_project_settings(owner, data.get("selections")))
        project_contents = ET.tostring(project, encoding="utf-8", xml_declaration=True)
        filename = safe_name(f"{material_name}-blank-project.lbrn2", "selected-settings-blank-project.lbrn2")
        object_key = f"users/{owner}/exports/{uuid.uuid4()}/{filename}"
        disposition = f'attachment; filename="{filename}"'
        s3.put_object(
            Bucket=BUCKET, Key=object_key, Body=project_contents,
            ContentType="application/octet-stream", ContentDisposition=disposition,
            Tagging="mopa-retention=job",
        )
        download_url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket":BUCKET, "Key":object_key,
                    "ResponseContentType":"application/octet-stream",
                    "ResponseContentDisposition":disposition},
            ExpiresIn=900,
        )
        return response(201, {"download_url":download_url, "filename":filename, "expires_in":900})
    target_id, library, target_root, destination = "", None, None, None
    if action == "copy_existing":
        target_id = str(data.get("target_library_id") or "")
        library = owned_material(owner, target_id)
        if not library:
            return response(404, {"message":"Destination Material Library not found"})
        existing = s3.get_object(Bucket=BUCKET, Key=library["s3_key"])["Body"].read(MAX_MATERIAL_BYTES + 1)
        if len(existing) > MAX_MATERIAL_BYTES:
            raise ValueError(f"The destination Material Library exceeds the {MATERIAL_LIMIT_MB} limit. Choose a smaller destination library or import a smaller LightBurn export.")
        target_root = ET.fromstring(existing)
        destination, material_name = single_palette_material(target_root, "Destination palette")
    root = selected_settings_root(owner, data.get("selections"), material_name, allow_duplicates=action == "coupon")
    if action != "coupon": validate_library_descriptions(root)
    contents = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    if action == "export":
        return file_response(contents, f"{material_name}-settings.clb")
    if action == "coupon":
        label_entry = None
        if isinstance(data.get("label_selection"), dict):
            label_root = selected_settings_root(owner, [data["label_selection"]], "Coupon labels", allow_duplicates=True)
            label_entry = label_root.find("./Material/Entry")
        coupon = coupon_project(
            root, material_name, data.get("coupon_width_mm", 100), data.get("coupon_length_mm", 100), label_entry,
        )
        coupon_contents = ET.tostring(coupon, encoding="utf-8", xml_declaration=True)
        filename = safe_name(f"{material_name}-coupon.lbrn2", "selected-settings-coupon.lbrn2")
        object_key = f"users/{owner}/exports/{uuid.uuid4()}/{filename}"
        disposition = f'attachment; filename="{filename}"'
        s3.put_object(
            Bucket=BUCKET, Key=object_key, Body=coupon_contents,
            ContentType="application/octet-stream", ContentDisposition=disposition,
            Tagging="mopa-retention=job",
        )
        download_url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket":BUCKET, "Key":object_key,
                    "ResponseContentType":"application/octet-stream",
                    "ResponseContentDisposition":disposition},
            ExpiresIn=900,
        )
        return response(201, {"download_url":download_url, "filename":filename, "expires_in":900})
    if action == "copy_new":
        name = str(data.get("new_library_name") or "").strip()
        if not name or len(name) > 160: raise ValueError("Give the new Material Library a name between 1 and 160 characters")
        library_id, now = str(uuid.uuid4()), int(time.time())
        filename = safe_name(name, "rasterizer-material-library") + ".clb"
        object_key = f"users/{owner}/materials/{library_id}/{filename}"
        summary = material_summary(contents)
        s3.put_object(Bucket=BUCKET, Key=object_key, Body=contents, ContentType="application/xml")
        table.put_item(Item={"pk":f"USER#{owner}","sk":f"MATERIAL#{library_id}","library_id":library_id,"name":name,"original_name":filename,"material_name":material_name,"library_intent":"color_palette","summary":dynamo_value(summary),"s3_key":object_key,"created_at":now,"updated_at":now})
        return response(201, {"library_id": library_id})
    if action == "copy_existing":
        destination.extend(deepcopy(list(root.find("./Material"))))
        validate_library_descriptions(target_root)
        updated = ET.tostring(target_root, encoding="utf-8", xml_declaration=True)
        summary, now = material_summary(updated), int(time.time())
        s3.put_object(Bucket=BUCKET, Key=library["s3_key"], Body=updated, ContentType="application/xml")
        table.update_item(Key={"pk":f"USER#{owner}","sk":f"MATERIAL#{target_id}"},UpdateExpression="SET summary=:summary, material_name=:material, updated_at=:now",ExpressionAttributeValues={":summary":dynamo_value(summary),":material":material_name,":now":now})
        return response(200, {"summary": public_library_summary(summary)})
    raise ValueError("Choose an action for the selected settings")


def holographic_svg_grid(columns, rows, cell_mm, intervals, angles, calibration_id):
    top_label, right_label = max(4.0, min(8.0, cell_mm * .45)), max(3.0, min(6.0, cell_mm * .3))
    label_baseline = max(.8, top_label * .24)
    grid_width, grid_height = columns * cell_mm, rows * cell_mm
    width, height = grid_width + right_label, grid_height + top_label
    root = ET.Element("svg", xmlns="http://www.w3.org/2000/svg", width=f"{width:g}mm",
                      height=f"{height:g}mm", viewBox=f"0 0 {width:g} {height:g}")
    ET.SubElement(root, "text", x=".35", y=f"{label_baseline:g}", fill="#000",
                  **{"font-size":"1.575","font-family":"monospace"}).text = f"HOLO GRID {calibration_id[:8]}"
    for column in range(columns):
        ET.SubElement(root, "text", x=f"{column*cell_mm+.35:g}", y=f"{label_baseline:g}", fill="#000",
                      **{"font-size":".9","font-family":"monospace"}).text = f"I {intervals[column]:.3f}"
    for row in range(rows):
        ET.SubElement(root, "text", x=f"{grid_width+.25:g}", y=f"{top_label+row*cell_mm+cell_mm*.55:g}", fill="#000",
                      **{"font-size":".9","font-family":"monospace"}).text = f"A {angles[row*columns]:g}°"
    for index, (interval, angle) in enumerate(zip(intervals, angles)):
        column, row = index % columns, index // columns
        x, y = column * cell_mm, top_label + row * cell_mm
        group = ET.SubElement(root, "g", id=f"cell_{index+1:02d}")
        ET.SubElement(group, "rect", x=f"{x:g}", y=f"{y:g}", width=f"{cell_mm:g}", height=f"{cell_mm:g}",
                      fill="none", stroke="#000", **{"stroke-width":".1"})
        radians, half = math.radians(angle), cell_mm / 2
        dx, dy, offset = math.cos(radians), math.sin(radians), -math.hypot(half, half)
        while offset <= math.hypot(half, half) + 1e-9:
            nx, ny, endpoints = -dy, dx, []
            if abs(dx) > 1e-9:
                for edge_x in (-half, half):
                    t = (edge_x - nx * offset) / dx; edge_y = ny * offset + dy * t
                    if -half-1e-9 <= edge_y <= half+1e-9: endpoints.append((edge_x, edge_y))
            if abs(dy) > 1e-9:
                for edge_y in (-half, half):
                    t = (edge_y - ny * offset) / dy; edge_x = nx * offset + dx * t
                    if -half-1e-9 <= edge_x <= half+1e-9: endpoints.append((edge_x, edge_y))
            unique = []
            for endpoint in endpoints:
                if not any(math.isclose(endpoint[0], prior[0], abs_tol=1e-8) and math.isclose(endpoint[1], prior[1], abs_tol=1e-8) for prior in unique):
                    unique.append(endpoint)
            if len(unique) == 2:
                ET.SubElement(group, "line", x1=f"{x+half+unique[0][0]:g}", y1=f"{y+half+unique[0][1]:g}",
                              x2=f"{x+half+unique[1][0]:g}", y2=f"{y+half+unique[1][1]:g}", stroke="#000", **{"stroke-width":".01"})
            offset += interval
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def lightburn_setting_snapshot(cut_setting):
    """Return a portable, lossless-enough JSON snapshot of a LightBurn cut setting."""
    if cut_setting is None:
        return None
    settings, sub_layers = {}, []
    for node in list(cut_setting):
        if node.tag == "SubLayer":
            sub_layers.append(lightburn_setting_snapshot(node))
        elif node.get("Value") is not None:
            settings[str(node.tag)] = str(node.get("Value") or "")
    snapshot = {
        "type": str(cut_setting.get("type") or "Setting"),
        "settings": settings,
    }
    if sub_layers:
        snapshot["sub_layers"] = sub_layers
    return snapshot


def validate_lightburn_setting_snapshot(snapshot, depth=0):
    """Validate the portable CutSetting subset accepted from imported v2 recipes."""
    if depth > 4 or not isinstance(snapshot, dict):
        raise ValueError("A Fauxlographic Palette contains invalid embedded laser settings")
    setting_type = str(snapshot.get("type") or "")
    settings = snapshot.get("settings")
    if not setting_type or len(setting_type) > 40 or not isinstance(settings, dict) or len(settings) > 100:
        raise ValueError("A Fauxlographic Palette contains invalid embedded laser settings")
    for name, value in settings.items():
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", str(name)) or isinstance(value, (dict, list)):
            raise ValueError("A Fauxlographic Palette contains invalid embedded laser settings")
        if len(str(value)) > 160:
            raise ValueError("A Fauxlographic Palette laser-setting value is too long")
    sub_layers = snapshot.get("sub_layers") or []
    if not isinstance(sub_layers, list) or len(sub_layers) > 20:
        raise ValueError("A Fauxlographic Palette contains invalid embedded sublayers")
    for sub_layer in sub_layers:
        validate_lightburn_setting_snapshot(sub_layer, depth + 1)
    return snapshot


def usable_preserved_black_setting(setting):
    """Ignore optional preserved Black when its embedded LightBurn setting cannot be read."""
    if not isinstance(setting, dict):
        return None
    try:
        validate_lightburn_setting_snapshot(setting.get("laser_settings"))
    except ValueError:
        return None
    return setting


def material_black_setting(material):
    """Snapshot the selected material's explicitly named Black setting, when present."""
    for entry in material.findall("./Entry"):
        cut = entry.find("./CutSetting")
        cut_name = cut.find("./name") if cut is not None else None
        names = {
            str(entry.get("Desc") or "").strip().casefold(),
            str(cut_name.get("Value") if cut_name is not None else "").strip().casefold(),
        }
        if "black" in names and cut is not None:
            return {
                "name": "Black",
                "description": str(entry.get("Desc") or "Black"),
                "laser_settings": lightburn_setting_snapshot(cut),
            }
    return None


def material_label_cut_setting(material, fallback):
    """Use an explicitly named Labels entry, or retain the supplied fallback."""
    if material is not None:
        for entry in material.findall("./Entry"):
            cut = entry.find("./CutSetting")
            cut_name = cut.find("./name") if cut is not None else None
            names = {
                str(entry.get("Desc") or "").strip().casefold(),
                str(cut_name.get("Value") if cut_name is not None else "").strip().casefold(),
            }
            if "labels" in names and cut is not None:
                return cut
    return fallback


def material_label_choice(entries, source_material, fallback, requested_entry_id=None):
    """Resolve a trusted label setting and return choices for the same material."""
    choices = []
    fallback_entry_id = None
    for entry_id, (material, entry) in enumerate(entries):
        if material is not source_material:
            continue
        cut = entry.find("./CutSetting")
        if cut is None:
            continue
        description = str(entry.get("Desc") or "").strip() or f"Setting {entry_id + 1}"
        choices.append({
            "entry_id": entry_id,
            "description": description,
            "laser_settings": lightburn_setting_snapshot(cut),
        })
        if cut is fallback:
            fallback_entry_id = entry_id
    if requested_entry_id not in (None, ""):
        try:
            requested_entry_id = int(requested_entry_id)
        except (TypeError, ValueError) as error:
            raise ValueError("Choose a valid Labels setting from the selected material") from error
        selected = next((choice for choice in choices if choice["entry_id"] == requested_entry_id), None)
        if selected is None:
            raise ValueError("Choose a valid Labels setting from the selected material")
        return lightburn_snapshot_element(selected["laser_settings"]), requested_entry_id, choices
    selected = next((choice for choice in choices if choice["description"].casefold() == "labels"), None)
    selected_id = selected["entry_id"] if selected else fallback_entry_id
    return material_label_cut_setting(source_material, fallback), selected_id, choices


def create_holographic_calibration(event, guest=False, upload_task_id=""):
    owner, data = user_id(event), body_json(event)
    library_id, contents, upload_item = str(data.get("library_id") or ""), None, None
    if upload_task_id:
        upload_item = runtime(upload_task_id)
        if guest:
            if not valid_guest_capability(upload_item, request_header(event, "x-guest-capability")):
                return response(404, {"message":"Guest calibration upload not found or access expired"})
        elif not authorize_task(event, upload_item):
            return response(404, {"message":"Calibration upload not found"})
        if not upload_item.get("holographic_calibration_upload"):
            return response(400, {"message":"Choose a Fauxlographic Etching Lab Material Library upload"})
        upload_token = str(data.pop("upload_token", ""))
        if not valid_upload_capability(upload_item, upload_token):
            return response(403, {"message":"Upload capability is invalid or expired"})
        material_key = str(data.pop("material_key", ""))
        expected_key_prefix = f"jobs/{upload_task_id}/inputs/material-"
        if not material_key.startswith(expected_key_prefix):
            return response(400, {"message":"We couldn't match the uploaded Material Library to this calibration. Review the selected file, then click \"Build Calibration Grid\" again to start a fresh upload."})
        try:
            verify_upload(material_key, upload_item["upload_capability"], MAX_MATERIAL_BYTES)
            contents = s3.get_object(Bucket=BUCKET, Key=material_key)["Body"].read(MAX_MATERIAL_BYTES + 1)
        except ValueError as error:
            return response(400, {"message":str(error)})
    else:
        library = owned_material(owner, library_id)
        if not library: return response(404, {"message":"Choose a saved Material Library"})
        contents = s3.get_object(Bucket=BUCKET, Key=library["s3_key"])["Body"].read(MAX_MATERIAL_BYTES + 1)
    try:
        entry_id = int(data.get("entry_id"))
        columns, rows = max(2, min(6, int(data.get("columns", 4)))), max(2, min(6, int(data.get("rows", 4))))
        cell_mm = max(4, min(30, float(data.get("cell_mm", 12))))
        interval_low = max(.01, min(.5, float(data.get("interval_low", .045))))
        interval_high = max(interval_low, min(.5, float(data.get("interval_high", .07))))
        sweep = str(data.get("sweep_parameter") or "none")
        sweep_fields = {"none":None,"power":"maxPower","speed":"speed","frequency":"frequency","pulse_width":"QPulseWidth","passes":"numPasses"}
        if sweep not in sweep_fields: raise ValueError("Choose a valid laser-setting sweep")
        sweep_low, sweep_high = float(data.get("sweep_low", 0)), float(data.get("sweep_high", 0))
        cut_mode = str(data.get("cut_mode") or "setting")
        cut_types = {"setting":None,"line":"Cut","fill":"Scan","offset_fill":"Offset"}
        if cut_mode not in cut_types: raise ValueError("Choose a valid cut mode")
    except (TypeError, ValueError) as error:
        if str(error).startswith("Choose a valid "):
            raise
        raise ValueError(
            "A Fauxlographic Etching Lab grid value could not be read. Review the selected LightBurn setting, "
            "grid dimensions, interval range, and sweep bounds, then build the grid again."
        ) from error
    material_name = str(data.get("material_name") or "").strip()
    if not material_name or len(material_name) > 160: raise ValueError("Provide a Material Name")
    if len(contents) > MAX_MATERIAL_BYTES: raise ValueError(f"The selected Material Library exceeds the {MATERIAL_LIMIT_MB} limit. Choose a smaller library or import a smaller LightBurn export.")
    try:
        source_root = ET.fromstring(contents)
    except ET.ParseError as error:
        raise ValueError("We couldn't read the selected Material Library. Choose a valid LightBurn library, or export a fresh copy from LightBurn and try again.") from error
    entries = [(material, entry) for material in source_root.findall("./Material") for entry in material.findall("./Entry")]
    if entry_id < 0 or entry_id >= len(entries): raise ValueError("Choose a valid Material Library setting")
    source_material, source_entry = entries[entry_id]
    source_cut = source_entry.find("./CutSetting")
    if source_cut is None: raise ValueError("The selected Material Library entry has no LightBurn setting")
    label_cut, label_entry_id, label_options = material_label_choice(
        entries, source_material, source_cut, data.get("label_entry_id"),
    )
    count = columns * rows
    column_intervals = [interval_low + (interval_high-interval_low)*index/max(columns-1,1) for index in range(columns)]
    intervals = [column_intervals[index % columns] for index in range(count)]
    angles = [180 * (index // columns) / rows for index in range(count)]
    sweep_values = [sweep_low + (sweep_high-sweep_low)*index/max(count-1,1) for index in range(count)]
    calibration_id, now = upload_task_id if guest else str(uuid.uuid4()), int(time.time())
    top_label = max(4.0, min(8.0, cell_mm * .45))
    label_center_y = max(.5, (top_label - 3.0) / 2)
    project = ET.Element("LightBurnProject", {"AppVersion":"2.1.04","FormatVersion":"1","MaterialHeight":"0","MirrorX":"False","MirrorY":"True","AskForSendName":"True"})
    add_lightburn_safe_optimization_prefs(project)
    label_layer = deepcopy(label_cut)
    label_index = label_layer.find("./index")
    if label_index is None: label_index = ET.SubElement(label_layer, "index")
    label_index.set("Value", "0")
    label_name = label_layer.find("./name")
    if label_name is None: label_name = ET.SubElement(label_layer, "name")
    label_name.set("Value", "Calibration labels")
    project.append(label_layer)
    holographic_grid_label = f"HOLO GRID {calibration_id[:8]}"
    title = ET.Element("Shape", {"Type":"Text","ShapeID":"0","CutIndex":"0","Font":"Arial,-1,100,5,50,0,0,0,0,0","Str":holographic_grid_label,"H":"3.5","LS":"0","LnS":"0","Ah":"0","Av":"0","Weld":"1","HasBackupPath":"0"})
    ET.SubElement(title, "XForm").text = f"1 0 0 1 .5 {label_center_y:g}"; project.append(title)
    cells = []
    for index, (interval, angle, sweep_value) in enumerate(zip(intervals, angles, sweep_values), 1):
        layer = deepcopy(source_cut)
        if cut_types[cut_mode]: layer.set("type", cut_types[cut_mode])
        index_node = layer.find("./index")
        if index_node is None: index_node = ET.SubElement(layer, "index")
        index_node.set("Value", str(index))
        name_node = layer.find("./name")
        if name_node is None: name_node = ET.SubElement(layer, "name")
        name_node.set("Value", f"Holo {index:02d} {angle:g}deg {interval:.3f}mm")
        interval_node = layer.find("./interval")
        if interval_node is None: interval_node = ET.SubElement(layer, "interval")
        interval_node.set("Value", f"{interval:g}")
        angle_node = layer.find("./angle")
        if angle_node is None: angle_node = ET.SubElement(layer, "angle")
        angle_node.set("Value", f"{angle:g}")
        override = None
        if sweep_fields[sweep]:
            field = layer.find(f"./{sweep_fields[sweep]}")
            if field is None: field = ET.SubElement(layer, sweep_fields[sweep])
            value = round(sweep_value) if sweep in {"frequency","passes"} else sweep_value
            field.set("Value", f"{value:g}"); override = {"parameter":sweep,"value":value}
        project.append(layer)
        column, row = (index-1) % columns, (index-1) // columns
        shape = ET.Element("Shape", {"Type":"Rect","ShapeID":str(index),"CutIndex":str(index),"W":f"{cell_mm:g}","H":f"{cell_mm:g}","Cr":"0"})
        ET.SubElement(shape, "XForm").text = f"1 0 0 1 {(column+.5)*cell_mm:g} {top_label+(row+.5)*cell_mm:g}"; project.append(shape)
        cells.append({"index":index,"row":row+1,"column":column+1,"interval_mm":interval,"angle_degrees":angle,
                      "laser_setting_override":override,"laser_settings":lightburn_setting_snapshot(layer),
                      "grating_signature":{"cell_index":index,"interval_mm":interval,"angle_degrees":angle}})
    metadata = {"kind":"holographic_calibration_grid","schema_version":2,"calibration_grid_id":calibration_id,"material":material_name,
                "setting_description":str(source_entry.get("Desc") or ""),"laser_source":str(data.get("laser_source") or "")[:160],
                "lens_field_of_view_mm":float(data.get("lens_field_mm") or 110),"columns":columns,"rows":rows,
                "cell_size_mm":cell_mm,"interval_range_mm":[interval_low,interval_high],"angles_degrees":angles,
                "intervals_mm":intervals,"cells":cells,"source_library_id":library_id or None,"source_entry_id":entry_id,
                "label_entry_id":label_entry_id,"label_options":label_options,
                "embedded_black_setting":material_black_setting(source_material),
                "cut_mode":{"selection":cut_mode},"sweep":{"parameter":sweep if sweep_fields[sweep] else None,"values":sweep_values if sweep_fields[sweep] else []}}
    prefix = (f"jobs/{calibration_id}/outputs/" if guest
              else f"users/{owner}/holographic-calibrations/{calibration_id}/")
    artifacts = {"lightburn":(f"{prefix}holographic_calibration_{calibration_id}.lbrn2",ET.tostring(project,encoding="utf-8",xml_declaration=True),"application/octet-stream"),
                 "svg":(f"{prefix}holographic_calibration_{calibration_id}.svg",holographic_svg_grid(columns,rows,cell_mm,intervals,angles,calibration_id),"image/svg+xml"),
                 "metadata":(f"{prefix}holographic_calibration_{calibration_id}.json",json.dumps(metadata,indent=2).encode(),"application/json")}
    for key, body, content_type in artifacts.values():
        put_options = {"Bucket":BUCKET,"Key":key,"Body":body,"ContentType":content_type,
                       "ContentDisposition":f'attachment; filename="{key.rsplit("/",1)[-1]}"'}
        if guest: put_options["Tagging"] = "mopa-retention=guest"
        s3.put_object(**put_options)
    artifact_keys = {name:value[0] for name,value in artifacts.items()}
    if guest:
        table.update_item(
            Key=runtime_key(upload_task_id),
            UpdateExpression="SET #status=:completed, metadata=:metadata, artifact_keys=:artifacts, updated_at=:now, expires_at=:expiry REMOVE upload_capability, upload_expires_at",
            ExpressionAttributeNames={"#status":"status"},
            ExpressionAttributeValues={":completed":"completed",":metadata":dynamo_value(metadata),":artifacts":artifact_keys,
                                       ":now":now,":expiry":now + GUEST_JOB_SECONDS},
        )
    else:
        table.put_item(Item={"pk":f"USER#{owner}","sk":f"HOLOCALIBRATION#{calibration_id}","calibration_id":calibration_id,
                             "metadata":dynamo_value(metadata),"artifact_keys":artifact_keys,"created_at":now,"updated_at":now})
    return response(201,{"calibration_id":calibration_id,"metadata":metadata,"downloads":{
        name:s3.generate_presigned_url("get_object",Params={
            "Bucket":BUCKET,"Key":value[0],
            "ResponseContentDisposition":f'attachment; filename="{value[0].rsplit("/",1)[-1]}"',
            "ResponseContentType":value[2],
        },ExpiresIn=900) for name,value in artifacts.items()}})


COLOR_DISCOVERY_PARAMETERS = {
    "speed": ("speed", "Speed", .1, 100000, True), "max_power": ("maxPower", "Maximum power", 0, 100, True),
    "min_power": ("minPower", "Minimum power", 0, 100, True), "frequency": ("frequency", "Frequency", 1, 5000000, True),
    "pulse_width": ("QPulseWidth", "Pulse width", 0, 10000, True), "passes": ("numPasses", "Passes", 1, 1000, True),
    "interval": ("interval", "Fill interval", .001, 10, False), "angle": ("angle", "Scan angle", 0, 179.999, True),
}
COLOR_DISCOVERY_REFINEMENT_STEPS = {
    "speed": 10, "max_power": 5, "min_power": 5, "frequency": 5000,
    "pulse_width": 10, "passes": 1, "interval": .005, "angle": 5,
}


def color_axis_values(parameter, low, high, count):
    field, _label, minimum, maximum, integer = COLOR_DISCOVERY_PARAMETERS[parameter]
    low, high = max(minimum, min(maximum, float(low))), max(minimum, min(maximum, float(high)))
    low, high = min(low, high), max(low, high)
    values = [low + (high - low) * index / max(1, count - 1) for index in range(count)]
    # Project generation remains authoritative when clients submit decimal
    # bounds: every integer laser parameter is floored after interpolation.
    return field, [math.floor(value) if integer else value for value in values]


def color_refinement_center(cell, parameter):
    field = COLOR_DISCOVERY_PARAMETERS[parameter][0]
    overrides = cell.get("overrides") or {}
    snapshot = cell.get("laser_settings") or {}
    settings = snapshot.get("settings") or {}
    raw = overrides.get(parameter, settings.get(field))
    try:
        value = float(raw)
    except (TypeError, ValueError) as error:
        raise ValueError(f"The selected swatch has no valid {parameter} setting to refine") from error
    if not math.isfinite(value):
        raise ValueError(f"The selected swatch has no valid {parameter} setting to refine")
    return value


def color_refinement_step(metadata, parameter):
    if parameter == metadata.get("x_parameter"):
        values = metadata.get("x_values") or []
    elif parameter == metadata.get("y_parameter"):
        values = metadata.get("y_values") or []
    else:
        return COLOR_DISCOVERY_REFINEMENT_STEPS[parameter]
    if len(values) < 2:
        return COLOR_DISCOVERY_REFINEMENT_STEPS[parameter]
    return abs(float(values[-1]) - float(values[0])) / max(1, len(values) - 1)


def color_grid_layout(width_mm, length_mm, maximum_cells=29):
    candidates = [(rows * columns, min(width_mm / columns, length_mm / rows), rows, columns)
                  for rows in range(2, maximum_cells + 1) for columns in range(2, maximum_cells + 1)
                  if rows * columns <= maximum_cells]
    _count, cell_mm, rows, columns = max(candidates, key=lambda item: (item[0], item[1]))
    return rows, columns, cell_mm


def create_color_discovery_grid(event, guest=False, upload_task_id=""):
    owner, data = ("" if guest else user_id(event)), body_json(event)
    contents, upload_item = None, None
    if upload_task_id:
        upload_item = runtime(upload_task_id)
        if guest:
            if not valid_guest_capability(upload_item, request_header(event, "x-guest-capability")):
                return response(404, {"message":"Guest Color Lab upload not found or access expired"})
        elif not authorize_task(event, upload_item):
            return response(404, {"message":"Color Lab upload not found"})
        if not upload_item.get("color_discovery_upload"):
            return response(400, {"message":"Choose a Color Lab Material Library upload"})
        upload_token = str(data.pop("upload_token", ""))
        if not valid_upload_capability(upload_item, upload_token):
            return response(403, {"message":"Upload capability is invalid or expired"})
        material_key = str(data.pop("material_key", ""))
        expected_key_prefix = f"jobs/{upload_task_id}/inputs/material-"
        if not material_key.startswith(expected_key_prefix):
            return response(400, {"message":"We couldn't match the uploaded Material Library to this Color Lab grid. Review the selected file, then click \"Generate Discovery Grid\" again to start a fresh upload."})
        try:
            verify_upload(material_key, upload_item["upload_capability"], MAX_MATERIAL_BYTES)
            contents = s3.get_object(Bucket=BUCKET, Key=material_key)["Body"].read(MAX_MATERIAL_BYTES + 1)
        except ValueError as error:
            return response(400, {"message":str(error)})
    refinement = refinement_cell = refinement_metadata = None
    refinement_grid_id = str(data.get("refine_from_grid_id") or "").strip()
    if refinement_grid_id:
        try:
            refinement_grid_id = str(uuid.UUID(refinement_grid_id))
            refinement_cell_index = int(data.get("refine_cell_index"))
        except (TypeError, ValueError) as error:
            raise ValueError("Choose one valid measured swatch to refine") from error
        refinement_record = (runtime(refinement_grid_id) if guest else table.get_item(
            Key={"pk":f"USER#{owner}", "sk":f"COLORDISCOVERY#{refinement_grid_id}"},
            ConsistentRead=True,
        ).get("Item"))
        if guest and not valid_guest_capability(refinement_record, request_header(event, "x-guest-capability")):
            refinement_record = None
        if not refinement_record:
            return response(404, {"message":"The Color Discovery grid selected for refinement was not found or has expired"})
        refinement_metadata = json_value(refinement_record.get("metadata") or {})
        refinement_cell = next(
            (cell for cell in refinement_metadata.get("cells") or [] if int(cell.get("index", -1)) == refinement_cell_index),
            None,
        )
        if not refinement_cell:
            raise ValueError("The measured swatch selected for refinement is not part of that grid")
        source_x_parameter = str(refinement_metadata.get("x_parameter") or "")
        source_y_parameter = str(refinement_metadata.get("y_parameter") or "")
        request_data = body_json(event)
        x_parameter = str(request_data.get("refine_x_parameter") or source_x_parameter)
        y_parameter = str(request_data.get("refine_y_parameter") or source_y_parameter)
        if x_parameter not in COLOR_DISCOVERY_PARAMETERS or y_parameter not in COLOR_DISCOVERY_PARAMETERS or x_parameter == y_parameter:
            raise ValueError("Choose two different supported refinement parameters")
        try:
            x_center = color_refinement_center(refinement_cell, x_parameter)
            y_center = color_refinement_center(refinement_cell, y_parameter)
            x_step = color_refinement_step(refinement_metadata, x_parameter)
            y_step = color_refinement_step(refinement_metadata, y_parameter)
        except (TypeError, ValueError) as error:
            raise ValueError(str(error) or "The selected swatch does not contain enough setting information to refine") from error
        data = {
            **data,
            "library_id":refinement_metadata.get("source_library_id"),
            "entry_id":refinement_metadata.get("source_entry_id"),
            "x_parameter":x_parameter, "y_parameter":y_parameter,
            "x_low":x_center-x_step, "x_high":x_center+x_step,
            "y_low":y_center-y_step, "y_high":y_center+y_step,
            "grid_width_mm":refinement_metadata.get("requested_grid_width_mm") or refinement_metadata.get("grid_width_mm") or 100,
            "grid_length_mm":refinement_metadata.get("requested_grid_length_mm") or refinement_metadata.get("grid_height_mm") or 100,
        }
        override_names = (("refine_x_low","x_low"),("refine_x_high","x_high"),("refine_y_low","y_low"),("refine_y_high","y_high"))
        for request_name, axis_name in override_names:
            if request_name in body_json(event):
                try: data[axis_name] = float(body_json(event)[request_name])
                except (TypeError, ValueError) as error: raise ValueError("Refinement bounds must be valid numbers") from error
        refinement = {"grid_id":refinement_grid_id, "cell_index":refinement_cell_index,
                      "source_x_parameter":source_x_parameter, "source_y_parameter":source_y_parameter,
                      "x_parameter":x_parameter, "y_parameter":y_parameter,
                      "x_center":x_center, "y_center":y_center, "x_original_step":x_step, "y_original_step":y_step,
                      "requested_x_range":[data["x_low"],data["x_high"]], "requested_y_range":[data["y_low"],data["y_high"]]}
    library_id = str(data.get("library_id") or "")
    library = owned_material(owner, library_id) if library_id and not guest else None
    if not library and contents is None and not refinement: return response(404, {"message":"Choose a saved or uploaded Material Library"})
    try:
        entry_id = int(data.get("entry_id")); width_mm = max(40,min(500,float(data.get("grid_width_mm",100))))
        length_mm = max(40,min(500,float(data.get("grid_length_mm",100))))
        rows, columns, cell_mm = color_grid_layout(width_mm, length_mm)
        x_parameter, y_parameter = str(data.get("x_parameter") or "speed"), str(data.get("y_parameter") or "frequency")
        if x_parameter not in COLOR_DISCOVERY_PARAMETERS or y_parameter not in COLOR_DISCOVERY_PARAMETERS or x_parameter == y_parameter: raise ValueError("Choose two different supported sweep parameters")
        x_field, x_values = color_axis_values(x_parameter,data.get("x_low"),data.get("x_high"),columns)
        y_field, y_values = color_axis_values(y_parameter,data.get("y_low"),data.get("y_high"),rows)
    except (TypeError, ValueError) as error:
        if str(error).startswith("Choose two different supported sweep parameters"):
            raise
        raise ValueError(
            "A Color Discovery grid value could not be read. Review the selected LightBurn setting, "
            "grid dimensions, and X- and Y-axis sweep bounds, then generate the grid again."
        ) from error
    if refinement:
        source_material = ET.Element("Material", {"Name":str(refinement_metadata.get("material") or "")})
        source_entry = ET.Element("Entry", {"Desc":str(refinement_metadata.get("setting_description") or "")})
        source_cut = lightburn_snapshot_element(refinement_cell.get("laser_settings"))
        label_options = refinement_metadata.get("label_options") or []
        requested_label_id = body_json(event).get("label_entry_id")
        if requested_label_id in (None, ""):
            requested_label_id = refinement_metadata.get("label_entry_id")
        selected_label = None
        if requested_label_id not in (None, ""):
            try:
                requested_label_id = int(requested_label_id)
            except (TypeError, ValueError) as error:
                raise ValueError("Choose a valid Labels setting from the selected material") from error
            selected_label = next(
                (choice for choice in label_options if int(choice.get("entry_id", -1)) == requested_label_id), None,
            )
            if selected_label is None and label_options:
                raise ValueError("Choose a valid Labels setting from the selected material")
        label_entry_id = requested_label_id if selected_label else refinement_metadata.get("label_entry_id")
        label_snapshot = (selected_label or {}).get("laser_settings") or refinement_metadata.get("label_laser_settings")
        label_cut = lightburn_snapshot_element(label_snapshot) if label_snapshot else source_cut
    else:
        if contents is None:
            contents = s3.get_object(Bucket=BUCKET,Key=library["s3_key"])["Body"].read(MAX_MATERIAL_BYTES+1)
        if len(contents)>MAX_MATERIAL_BYTES: raise ValueError(f"The selected Material Library exceeds the {MATERIAL_LIMIT_MB} limit. Choose a smaller library or import a smaller LightBurn export.")
        try: source_root=ET.fromstring(contents)
        except ET.ParseError as error: raise ValueError("We couldn't read the selected Material Library. Choose a valid LightBurn library, or export a fresh copy from LightBurn and try again.") from error
        entries=[(material,entry) for material in source_root.findall("./Material") for entry in material.findall("./Entry")]
        if entry_id<0 or entry_id>=len(entries): raise ValueError("Choose a valid Material Library setting")
        source_material,source_entry=entries[entry_id]; source_cut=source_entry.find("./CutSetting")
        label_cut,label_entry_id,label_options=material_label_choice(
            entries,source_material,source_cut,data.get("label_entry_id"),
        )
    if source_cut is None: raise ValueError("The selected Material Library entry has no LightBurn setting")
    grid_id,now,top_mm=(upload_task_id if guest and upload_task_id and not refinement else str(uuid.uuid4())),int(time.time()),4.0
    project=ET.Element("LightBurnProject",{"AppVersion":"2.1.04","FormatVersion":"1","MaterialHeight":"0","MirrorX":"False","MirrorY":"True","AskForSendName":"True"})
    add_lightburn_safe_optimization_prefs(project)
    label_layer=deepcopy(label_cut); label_index=label_layer.find("./index")
    if label_index is None: label_index=ET.SubElement(label_layer,"index")
    label_index.set("Value","0"); label_name=label_layer.find("./name")
    if label_name is None: label_name=ET.SubElement(label_layer,"name")
    label_name.set("Value","Grid ID"); label_layer.set("type","Scan"); project.append(label_layer)
    grid_label=f"COLOR GRID {grid_id[:8]}"; label_height=2.1; label_width=len(grid_label)*label_height*.6
    title=ET.Element("Shape",{"Type":"Text","ShapeID":"0","CutIndex":"0","Font":"Arial,-1,100,5,50,0,0,0,0,0","Str":grid_label,"H":f"{label_height:g}","LS":"0","LnS":"0","Ah":"0","Av":"1","Weld":"1","HasBackupPath":"0"})
    ET.SubElement(title,"XForm").text=f"1 0 0 1 {max(0,(columns*cell_mm-label_width)/2):g} {top_mm/2:g}"; project.append(title); cells=[]
    for row,y_value in enumerate(y_values):
        for column,x_value in enumerate(x_values):
            index=row*columns+column+1; layer=deepcopy(source_cut)
            # Discovery cells must be independent settings. Retaining the
            # Material Library LinkPath lets LightBurn resolve the base entry
            # over the interpolated values embedded below.
            for link_path in layer.findall("./LinkPath"):
                layer.remove(link_path)
            for field,value in ((x_field,x_value),(y_field,y_value)):
                node=layer.find(f"./{field}")
                if node is None: node=ET.SubElement(layer,field)
                node.set("Value",f"{value:g}")
            index_node=layer.find("./index")
            if index_node is None: index_node=ET.SubElement(layer,"index")
            index_node.set("Value",str(index)); name_node=layer.find("./name")
            if name_node is None: name_node=ET.SubElement(layer,"name")
            name_node.set("Value",f"Discovery {index:02d} {x_parameter}={x_value:g} {y_parameter}={y_value:g}")
            min_node,max_node=layer.find("./minPower"),layer.find("./maxPower")
            if min_node is not None and max_node is not None and float(min_node.get("Value",0))>float(max_node.get("Value",100)): raise ValueError("This sweep creates a cell whose minimum power exceeds maximum power")
            project.append(layer); shape=ET.Element("Shape",{"Type":"Rect","ShapeID":str(index),"CutIndex":str(index),"W":f"{cell_mm:g}","H":f"{cell_mm:g}","Cr":"0"})
            ET.SubElement(shape,"XForm").text=f"1 0 0 1 {(column+.5)*cell_mm:g} {top_mm+(row+.5)*cell_mm:g}"; project.append(shape)
            cells.append({"index":index,"row":row+1,"column":column+1,"overrides":{x_parameter:x_value,y_parameter:y_value},"laser_settings":lightburn_setting_snapshot(layer)})
    metadata={"kind":"color_discovery_grid","schema_version":1,"grid_id":grid_id,"columns":columns,"rows":rows,"cell_size_mm":cell_mm,
              "grid_width_mm":columns*cell_mm,"grid_height_mm":rows*cell_mm,"requested_grid_width_mm":width_mm,"requested_grid_length_mm":length_mm,
              "top_label_band_mm":top_mm,"x_parameter":x_parameter,"y_parameter":y_parameter,"x_values":x_values,"y_values":y_values,"cells":cells,
              "source_library_id":library_id or None,"source_entry_id":entry_id,"material":str(source_material.get("name") or source_material.get("Name") or (library or {}).get("material_name") or ""),"setting_description":str(source_entry.get("Desc") or ""),
              "label_entry_id":label_entry_id,"label_options":label_options,
              "label_laser_settings":lightburn_setting_snapshot(label_layer),
              "refinement":refinement}
    prefix=(f"jobs/{grid_id}/outputs/" if guest else f"users/{owner}/color-discovery/{grid_id}/"); project_key=f"{prefix}color_discovery_{grid_id}.lbrn2"; metadata_key=f"{prefix}color_discovery_{grid_id}.json"
    for key,body,content_type in ((project_key,ET.tostring(project,encoding="utf-8",xml_declaration=True),"application/octet-stream"),(metadata_key,json.dumps(metadata,indent=2).encode(),"application/json")):
        put_options={"Bucket":BUCKET,"Key":key,"Body":body,"ContentType":content_type,"ContentDisposition":f'attachment; filename="{key.rsplit("/",1)[-1]}"'}
        if guest: put_options["Tagging"]="mopa-retention=guest"
        s3.put_object(**put_options)
    artifact_keys={"lightburn":project_key,"metadata":metadata_key}
    if guest and upload_task_id and not refinement:
        table.update_item(Key=runtime_key(upload_task_id),UpdateExpression="SET #status=:completed, metadata=:metadata, artifact_keys=:artifacts, updated_at=:now, expires_at=:expiry REMOVE upload_capability, upload_expires_at",ExpressionAttributeNames={"#status":"status"},ExpressionAttributeValues={":completed":"completed",":metadata":dynamo_value(metadata),":artifacts":artifact_keys,":now":now,":expiry":now+GUEST_JOB_SECONDS})
    elif guest:
        table.put_item(Item={**runtime_key(grid_id),"task_id":grid_id,"status":"completed","guest":True,"guest_access_capability":refinement_record["guest_access_capability"],"guest_access_expires_at":now+GUEST_JOB_SECONDS,"metadata":dynamo_value(metadata),"artifact_keys":artifact_keys,"created_at":now,"updated_at":now,"expires_at":now+GUEST_JOB_SECONDS})
    else:
        table.put_item(Item={"pk":f"USER#{owner}","sk":f"COLORDISCOVERY#{grid_id}","grid_id":grid_id,"metadata":dynamo_value(metadata),"artifact_keys":artifact_keys,"created_at":now,"updated_at":now,"expires_at":now+TTL_SECONDS})
    downloads={name:s3.generate_presigned_url("get_object",Params={"Bucket":BUCKET,"Key":key,"ResponseContentDisposition":f'attachment; filename="{key.rsplit("/",1)[-1]}"'},ExpiresIn=900) for name,key in (("lightburn",project_key),("metadata",metadata_key))}
    return response(201,{"grid_id":grid_id,"metadata":metadata,"downloads":downloads})


def get_color_discovery_grid(event, grid_reference, guest=False):
    owner = "" if guest else user_id(event)
    reference = str(grid_reference or "").strip().lower()
    if guest:
        try: reference = str(uuid.UUID(reference))
        except ValueError as error: raise ValueError("Enter the full Grid ID for a guest Color Lab grid") from error
        item = runtime(reference)
        if not valid_guest_capability(item, request_header(event, "x-guest-capability")):
            item = None
    elif re.fullmatch(r"[0-9a-f]{8}", reference):
        matches = user_items(owner, f"COLORDISCOVERY#{reference}")
        if len(matches) > 1:
            raise ValueError("That short Grid ID matches more than one grid; enter the full Grid ID")
        item = matches[0] if matches else None
    else:
        try:
            reference = str(uuid.UUID(reference))
        except ValueError as error:
            raise ValueError("Enter the 8-character engraved Grid ID or the full Grid ID") from error
        item = table.get_item(
            Key={"pk":f"USER#{owner}", "sk":f"COLORDISCOVERY#{reference}"},
            ConsistentRead=True,
        ).get("Item")
    if not item:
        return response(404, {"message":"Color Discovery grid not found or expired"})
    grid_id = str(item.get("grid_id") or str(item.get("sk") or "").removeprefix("COLORDISCOVERY#"))
    artifacts = item.get("artifact_keys") if isinstance(item.get("artifact_keys"), dict) else {}
    downloads = {}
    for name in ("lightburn", "metadata"):
        key = str(artifacts.get(name) or "")
        expected_prefix = f"jobs/{grid_id}/outputs/" if guest else f"users/{owner}/color-discovery/{grid_id}/"
        if not key.startswith(expected_prefix):
            continue
        filename = key.rsplit("/", 1)[-1]
        downloads[name] = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket":BUCKET, "Key":key,
                    "ResponseContentDisposition":f'attachment; filename="{filename}"'},
            ExpiresIn=900,
        )
    return response(200, {"grid_id":grid_id, "metadata":json_value(item.get("metadata") or {}), "downloads":downloads})


def list_color_discovery_grids(event):
    owner, now, grids = user_id(event), int(time.time()), []
    for item in user_items(owner, "COLORDISCOVERY#", limit=50):
        if int(item.get("expires_at") or 0) <= now:
            continue
        grid_id = str(item.get("grid_id") or str(item.get("sk") or "").removeprefix("COLORDISCOVERY#"))
        metadata = json_value(item.get("metadata") or {})
        grids.append({
            "grid_id":grid_id, "short_id":grid_id[:8],
            "created_at":int(item.get("created_at") or 0),
            "material":str(metadata.get("material") or ""),
            "setting_description":str(metadata.get("setting_description") or ""),
            "cell_count":len(metadata.get("cells") or []),
        })
    grids.sort(key=lambda item:item["created_at"], reverse=True)
    return response(200, {"grids":grids})


def save_color_discovery_palette(event):
    owner, data = user_id(event), body_json(event)
    grid_id = str(data.get("grid_id") or "")
    try: uuid.UUID(grid_id)
    except ValueError as error: raise ValueError("Choose a Color Discovery grid created by this account") from error
    record = table.get_item(Key={"pk":f"USER#{owner}","sk":f"COLORDISCOVERY#{grid_id}"},ConsistentRead=True).get("Item")
    if not record: return response(404,{"message":"Color Discovery grid not found"})
    metadata = json_value(record.get("metadata") or {})
    known = {int(cell["index"]):cell for cell in metadata.get("cells") or []}
    measured = data.get("swatches")
    if not isinstance(measured,list) or not measured: raise ValueError("Enable at least one measured swatch")
    palette_name = str(data.get("palette_name") or "").strip()
    material_name = str(data.get("material_name") or palette_name).strip()
    if not palette_name or len(palette_name)>160: raise ValueError("Provide a palette name between 1 and 160 characters")
    if not material_name or len(material_name)>160: raise ValueError("Provide a material name between 1 and 160 characters")
    selected, seen, assigned = [], set(), {}
    for selected_position, swatch in enumerate(measured, start=1):
        if not isinstance(swatch, dict):
            raise ValueError(f"Selected swatch {selected_position} could not be read. Reopen the Color Lab results, review its cell, and save again.")
        try:
            index=int(swatch.get("index")); color=str(swatch.get("observed_hex") or "").strip().upper()
            rasterizer_hex=str(swatch.get("rasterizer_hex") or "").strip().upper()
        except (TypeError,ValueError) as error:
            raise ValueError(f"Selected swatch {selected_position} has an invalid cell number. Reopen the Color Lab results and select the cell again.") from error
        if index not in known:
            raise ValueError(f"Cell {index} is not in this Color Discovery grid. Reload the grid and select its swatches again.")
        if index in seen:
            raise ValueError(f"Cell {index} was selected more than once. Reload the Color Lab results and save again.")
        if not re.fullmatch(r"#[0-9A-F]{6}", color):
            raise ValueError(f"Cell {index} has an invalid observed color. Measure again or manually correct the cell's values, then save the palette again.")
        palette_index=next((candidate for candidate,item in enumerate(PALETTE) if item[1].upper()==rasterizer_hex),None)
        if palette_index is None: raise ValueError(f"Cell {index} must use one of the official Rasterizer color hex codes")
        if palette_index in assigned:
            raise ValueError(f"Cells {assigned[palette_index]} and {index} both use the official {PALETTE[palette_index][0]} swatch. Disable one or choose a different official color before saving.")
        assigned[palette_index]=index; seen.add(index); selected.append((known[index],color,palette_index))
    selected.sort(key=lambda item:item[2])
    root=ET.Element("LightBurnLibrary"); material=ET.SubElement(root,"Material",{"name":material_name})
    assignments=[]
    for cell,color,palette_index in selected:
        description,official_hex=PALETTE[palette_index]
        entry=ET.SubElement(material,"Entry",{"Thickness":"-1.0000","Desc":description,"NoThickTitle":f"{description} {color}"})
        cut=lightburn_snapshot_element(cell.get("laser_settings")); index_node=cut.find("./index")
        if index_node is None: index_node=ET.SubElement(cut,"index")
        index_node.set("Value",str(palette_index)); name_node=cut.find("./name")
        if name_node is None: name_node=ET.SubElement(cut,"name")
        name_node.set("Value",description); entry.append(cut)
        assignments.append({"cell_index":int(cell["index"]),"observed_hex":color,"rasterizer_name":description,"rasterizer_hex":official_hex})
    contents=ET.tostring(root,encoding="utf-8",xml_declaration=True); summary=material_summary(contents)
    library_id,now=str(uuid.uuid4()),int(time.time()); filename=safe_name(palette_name,"color-discovery-palette")+".clb"
    object_key=f"users/{owner}/materials/{library_id}/{filename}"
    s3.put_object(Bucket=BUCKET,Key=object_key,Body=contents,ContentType="application/xml")
    table.put_item(Item={"pk":f"USER#{owner}","sk":f"MATERIAL#{library_id}","library_id":library_id,"name":palette_name,
                         "original_name":filename,"material_name":material_name,"library_intent":"color_palette","summary":dynamo_value(summary),
                         "s3_key":object_key,"created_at":now,"updated_at":now})
    return response(201,{"library_id":library_id,"name":palette_name,"material_name":material_name,"saved_count":len(selected),"assignments":assignments})


def holographic_swatch_preview(recipes):
    preview = []
    for recipe in recipes if isinstance(recipes, list) else []:
        color = str(recipe.get("observed_hex") or "").strip().upper() if isinstance(recipe, dict) else ""
        if not re.fullmatch(r"#[0-9A-F]{6}", color):
            continue
        try:
            interval = max(.001, min(10, float(recipe.get("interval_mm") or .05)))
            angle = float(recipe.get("angle_degrees") or 0) % 180
        except (TypeError, ValueError):
            interval, angle = .05, 0
        preview.append({"name": str(recipe.get("name") or "")[:160], "hex": color,
                        "interval_mm": interval, "angle_degrees": angle})
    return preview[:100]


def save_measured_holographic_recipe(event):
    owner, data = user_id(event), body_json(event)
    calibration_id = str(data.get("calibration_id") or "")
    try: uuid.UUID(calibration_id)
    except ValueError as error: raise ValueError("Choose a calibration grid created by this account") from error
    calibration = table.get_item(Key={"pk":f"USER#{owner}","sk":f"HOLOCALIBRATION#{calibration_id}"},ConsistentRead=True).get("Item")
    if not calibration: return response(404,{"message":"Calibration grid not found"})
    metadata = json_value(calibration.get("metadata") or {})
    known = {int(cell["index"]):cell for cell in metadata.get("cells") or []}
    measurements = data.get("measurements")
    if not isinstance(measurements,list) or not measurements: raise ValueError("Keep at least one measured calibration cell")
    black_setting = usable_preserved_black_setting(metadata.get("embedded_black_setting"))
    if len(measurements) > fauxlographic_swatch_capacity(black_setting):
        raise ValueError(f"{fauxlographic_swatch_limit_message(black_setting)} Deselect some measured cells and save again.")
    recipes, names = [], set()
    for measurement in measurements:
        raw_index = measurement.get("index") if isinstance(measurement, dict) else None
        try:
            index = int(raw_index) if not isinstance(raw_index, bool) else None
        except (TypeError, ValueError, OverflowError):
            index = None
        cell_label = f"Cell {index}" if index is not None and index > 0 else "A selected cell"
        invalid_cell_message = f"{cell_label} has missing or invalid measurement data. Measure again, then save the palette."
        if index not in known:
            raise ValueError(invalid_cell_message)
        rgb = measurement.get("observed_rgb")
        if not isinstance(rgb, list) or len(rgb) != 3:
            raise ValueError(invalid_cell_message)
        name = str(measurement.get("name") or f"Fauxlographic {index:02d}").strip()[:160]
        try:
            rgb = [max(0, min(255, int(value))) for value in rgb]
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(invalid_cell_message) from error
        if not name or name.casefold() in names:
            raise ValueError("Each selected Fauxlographic Palette swatch needs a unique name. Rename or deselect duplicate swatches, then save again.")
        names.add(name.casefold()); recipes.append({"name":name,"observed_rgb":rgb,"observed_hex":"#"+"".join(f"{value:02X}" for value in rgb),**known[index]})
    profile_name = str(data.get("profile_name") or "").strip()
    if not profile_name or len(profile_name)>160:
        raise ValueError("Give the Fauxlographic Palette a name between 1 and 160 characters.")
    recipe_id, now = str(uuid.uuid4()), int(time.time())
    profile = {"kind":"holographic_calibration_profile","schema_version":2,"status":"recipe_palette_ready",
               "self_contained":True,"profile_id":recipe_id,"profile_name":profile_name,"grid":metadata,
               "capture":data.get("capture") if isinstance(data.get("capture"),dict) else {},
               "black_setting":black_setting,"recipes":recipes}
    filename = safe_name(profile_name,"holographic-recipe")+".json"
    object_key = f"users/{owner}/holographic-recipes/{recipe_id}/{filename}"
    body = json.dumps(profile,indent=2).encode()
    if len(body)>MAX_RECIPE_BYTES:
        raise ValueError("This Fauxlographic Palette exceeds the save-size limit. Shorten the capture details and save again.")
    s3.put_object(Bucket=BUCKET,Key=object_key,Body=body,ContentType="application/json")
    metadata_summary={"profile_name":profile_name,"recipe_count":len(recipes),"material":str(metadata.get("material") or "")[:160],
                      "swatch_preview": holographic_swatch_preview(recipes),
                      "schema_version":2,"self_contained":True,"has_black_setting":bool(profile.get("black_setting"))}
    table.put_item(Item={"pk":f"USER#{owner}","sk":f"HOLORECIPE#{recipe_id}","recipe_id":recipe_id,"name":profile_name,
                         "original_name":filename,"metadata":dynamo_value(metadata_summary),"s3_key":object_key,"created_at":now,"updated_at":now})
    return response(201,{"recipe_id":recipe_id,"name":profile_name,"recipe_count":len(recipes)})


def holographic_recipe_detail(event, recipe_id):
    owner = user_id(event)
    recipe = owned_recipe(owner, recipe_id)
    if not recipe:
        return response(404, {"message":"Fauxlographic Palette not found"})
    try:
        profile = json.loads(s3.get_object(Bucket=BUCKET, Key=recipe["s3_key"])["Body"].read(MAX_RECIPE_BYTES + 1))
    except (ClientError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(
            "We couldn't open this saved Fauxlographic Palette. Reload the Vault and try again. If it still fails, report the palette name."
        ) from error
    preview = holographic_swatch_preview(profile.get("recipes"))
    metadata = dict(recipe.get("metadata") or {})
    if metadata.get("swatch_preview") != preview:
        metadata["swatch_preview"] = preview
        table.update_item(Key={"pk":f"USER#{owner}","sk":f"HOLORECIPE#{recipe_id}"},
                          UpdateExpression="SET metadata=:metadata, updated_at=:now",
                          ExpressionAttributeValues={":metadata":dynamo_value(metadata),":now":int(time.time())})
    return response(200, {"recipe_id":recipe_id, "name":str(recipe.get("name") or ""), "profile":profile})


def update_holographic_recipe(event, recipe_id):
    owner, data = user_id(event), body_json(event)
    record = owned_recipe(owner, recipe_id)
    if not record:
        return response(404, {"message":"Fauxlographic Palette not found"})
    try:
        profile = json.loads(s3.get_object(Bucket=BUCKET, Key=record["s3_key"])["Body"].read(MAX_RECIPE_BYTES + 1))
    except (ClientError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(
            "We couldn't open this saved Fauxlographic Palette. Reload the Vault and try again. If it still fails, report the palette name."
        ) from error
    name = str(data.get("name") or "").strip()
    measured = data.get("recipes")
    if not name or len(name) > 160:
        raise ValueError("Fauxlographic Palette names must be between 1 and 160 characters")
    capacity = fauxlographic_swatch_capacity(profile.get("black_setting"))
    if not isinstance(measured, list) or not measured or len(measured) > capacity:
        raise ValueError(f"Keep between 1 and {capacity} Fauxlographic Palette swatches. Preserved Black uses one of the {MAX_LIGHTBURN_LAYERS} LightBurn layers when present.")
    cleaned, names = [], set()
    for swatch_index, raw in enumerate(measured, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Swatch {swatch_index} in this Fauxlographic Palette could not be read. Reload the Vault palette, then try saving again.")
        swatch_name = str(raw.get("name") or "").strip()
        normalized_name = swatch_name.casefold()
        observed_hex = str(raw.get("observed_hex") or "").strip().upper()
        if not swatch_name or len(swatch_name) > 160 or normalized_name in names:
            raise ValueError("Each Fauxlographic Palette swatch needs a unique name between 1 and 160 characters. Correct the names, then save again.")
        if not re.fullmatch(r"#[0-9A-F]{6}", observed_hex):
            raise ValueError(f"Swatch '{swatch_name}' has an invalid observed color. Open that swatch, choose a color under Observed color, then save again.")
        try:
            interval = float(raw.get("interval_mm"))
            if not math.isfinite(interval):
                raise ValueError("Interval must be finite")
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(f"Swatch '{swatch_name}' has an invalid Interval (mm). Enter a number, then save again.") from error
        interval = max(.001, min(10, interval))
        try:
            angle = float(raw.get("angle_degrees"))
            if not math.isfinite(angle):
                raise ValueError("Angle must be finite")
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(f"Swatch '{swatch_name}' has an invalid Angle (degrees). Enter a number, then save again.") from error
        angle %= 180
        try:
            laser_settings = validate_lightburn_setting_snapshot(raw.get("laser_settings"))
        except ValueError as error:
            raise ValueError(f"Swatch '{swatch_name}' has invalid embedded LightBurn settings. Review its laser-setting fields in the Vault editor, then save again.") from error
        names.add(normalized_name)
        item = dict(raw)
        item.update({"name":swatch_name,"observed_hex":observed_hex,
                     "observed_rgb":[int(observed_hex[index:index+2],16) for index in (1,3,5)],
                     "interval_mm":interval,"angle_degrees":angle,"laser_settings":laser_settings})
        # Force artwork matching to use the edited observed color instead of
        # a stale Lab value retained from the original calibration analysis.
        item.pop("observed_lab", None)
        settings = laser_settings["settings"]
        settings["interval"] = f"{interval:g}"
        settings["angle"] = f"{angle:g}"
        cleaned.append(item)
    profile.update({"schema_version":2,"self_contained":True,"profile_name":name,"recipes":cleaned})
    body = json.dumps(profile, indent=2).encode()
    if len(body) > MAX_RECIPE_BYTES:
        raise ValueError("This Fauxlographic Palette exceeds the save-size limit. Remove unneeded swatches, then save again.")
    now = int(time.time())
    s3.put_object(Bucket=BUCKET, Key=record["s3_key"], Body=body, ContentType="application/json")
    metadata = dict(record.get("metadata") or {})
    metadata.update({"profile_name":name,"recipe_count":len(cleaned),"swatch_preview":holographic_swatch_preview(cleaned),"schema_version":2,
                     "self_contained":True,"has_black_setting":bool(profile.get("black_setting"))})
    table.update_item(Key={"pk":f"USER#{owner}","sk":f"HOLORECIPE#{recipe_id}"},
                      UpdateExpression="SET #name=:name, metadata=:metadata, updated_at=:now",
                      ExpressionAttributeNames={"#name":"name"},
                      ExpressionAttributeValues={":name":name,":metadata":dynamo_value(metadata),":now":now})
    return response(200,{"recipe_id":recipe_id,"name":name,"recipe_count":len(cleaned),"metadata":metadata})


def import_upload(event):
    data, owner = body_json(event), user_id(event)
    kind = str(data.get("kind") or "")
    extensions = {"material": {".clb", ".lbmat", ".lbrn"}, "recipe": {".json"}}
    filename = safe_name(data.get("filename"), "upload")
    extension = os.path.splitext(filename)[1].lower()
    if kind not in extensions or extension not in extensions[kind]:
        raise ValueError("Choose a supported Material Library or Fauxlographic Palette file")
    import_id, token = str(uuid.uuid4()), secrets.token_urlsafe(32)
    digest, now = token_hash(token), int(time.time())
    key = f"imports/{owner}/{import_id}/{filename}"
    content_type = "application/json" if kind == "recipe" else "application/xml"
    fields = {"Content-Type": content_type, "x-amz-meta-upload-capability": digest}
    signed = s3.generate_presigned_post(
        Bucket=BUCKET, Key=key, Fields=fields,
        Conditions=[{"key": key}, {"Content-Type": content_type},
                    {"x-amz-meta-upload-capability": digest},
                    ["content-length-range", 1, MAX_MATERIAL_BYTES]], ExpiresIn=600,
    )
    material_name = str(data.get("material_name") or "").strip()[:160]
    if kind == "material" and not material_name:
        raise ValueError("Choose a material name from the Material Library")
    table.put_item(Item={
        "pk": f"USER#{owner}", "sk": f"IMPORT#{import_id}", "import_id": import_id,
        "kind": kind, "filename": filename, "s3_key": key, "capability": digest,
        "display_name": str(data.get("name") or os.path.splitext(filename)[0]).strip()[:160],
        "material_name": material_name,
        "base_setting_id": data.get("base_setting_id"),
        "hatch_operation": str(data.get("hatch_operation") or "setting"),
        "start_angle": str(data.get("start_angle", "0")), "angular_span": str(data.get("angular_span", "180")),
        "first_interval": str(data.get("first_interval", "0.1")), "last_interval": str(data.get("last_interval", "0.1")),
        "library_intent": "hatch_palette" if data.get("library_intent") == "hatch_palette" else "color_palette",
        "created_at": now, "expires_at": now + 900,
    })
    return response(201, {"import_id": import_id, "upload_token": token,
                          "upload": {"url": signed["url"], "fields": signed["fields"], "key": key,
                                     "kind": kind, "max_file_bytes": MAX_MATERIAL_BYTES}})


def effective_lightburn_settings(setting):
    """Return the values explicitly stored by a LightBurn cut setting."""
    values = {}
    if setting is None:
        return values
    for node in list(setting):
        if node.tag != "SubLayer" and node.get("Value") is not None:
            values[str(node.tag)] = str(node.get("Value") or "")
    return values


def material_summary(contents):
    root = ET.fromstring(contents)
    if root.tag != "LightBurnLibrary":
        raise ValueError("The file is not a LightBurn Material Library")
    populated_materials = [material for material in root.findall("./Material") if material.findall("./Entry")]
    if len(populated_materials) != 1:
        if not populated_materials:
            raise ValueError("The selected material needs at least one laser setting entry. Choose a material with settings or add a setting in LightBurn, then import the library again.")
        raise ValueError("Palette must contain settings for exactly one material")
    entries, names, description_issues = [], [], []
    for material in root.findall(".//Material"):
        material_name = str(material.get("name") or "").strip()
        if material_name and material_name not in names: names.append(material_name)
        material_label = material_name or "(unnamed material)"
        descriptions = {}
        for entry_number, entry in enumerate(material.findall("./Entry"), start=1):
            description = str(entry.get("Desc") or "").strip()
            normalized = description.casefold()
            if not description:
                description_issues.append(
                    f"Material '{material_label}' entry {entry_number} has no Description"
                )
            elif normalized in descriptions:
                description_issues.append(
                    f"Material '{material_label}' entries {descriptions[normalized]} and "
                    f"{entry_number} both use Description '{description}'"
                )
            else:
                descriptions[normalized] = entry_number
            setting = entry.find("./CutSetting")
            values = effective_lightburn_settings(setting)
            entries.append({"material": material_name, "description": description,
                            "type": str(setting.get("type") if setting is not None else "Setting"),
                            "entry_id": len(entries), "settings": values})
    if description_issues:
        shown = description_issues[:10]
        suffix = f"; plus {len(description_issues) - len(shown)} more issue(s)" if len(description_issues) > len(shown) else ""
        raise ValueError(
            "Material Library setting descriptions must be present and unique within each material: "
            + "; ".join(shown) + suffix
        )
    if not entries or len(entries) > 500:
        raise ValueError("Material Library must contain between 1 and 500 settings")
    return {"entry_count": len(entries), "material_names": names, "entries": entries}


def normalize_imported_material_descriptions(contents):
    """Give imported entries stable, unique labels before they reach the editor."""
    root = ET.fromstring(contents)
    adjustments = []
    for material in root.findall("./Material"):
        used = set()
        next_suffix = {}
        for entry_number, entry in enumerate(material.findall("./Entry"), start=1):
            original = str(entry.get("Desc") or "").strip()
            base = original or "Unnamed setting"
            description = base
            normalized = description.casefold()
            if normalized in used:
                suffix = max(2, next_suffix.get(base.casefold(), 2))
                while True:
                    suffix_text = f"-{suffix}"
                    candidate = f"{base[:160 - len(suffix_text)]}{suffix_text}"
                    if candidate.casefold() not in used:
                        description = candidate
                        normalized = candidate.casefold()
                        next_suffix[base.casefold()] = suffix + 1
                        break
                    suffix += 1
            used.add(normalized)
            next_suffix.setdefault(base.casefold(), 2)
            if description == original:
                continue
            entry.set("Desc", description)
            cut = entry.find("./CutSetting")
            name = cut.find("./name") if cut is not None else None
            if name is not None and str(name.get("Value") or "").strip().casefold() == original.casefold():
                name.set("Value", description)
            adjustments.append({
                "entry": entry_number,
                "from": original,
                "to": description,
            })
    return ET.tostring(root, encoding="utf-8", xml_declaration=True), adjustments


def retain_selected_material(contents, selected_name):
    root = ET.fromstring(contents)
    if root.tag != "LightBurnLibrary":
        raise ValueError(
            "This isn't a LightBurn Material Library. Export a copy as a .clb file from LightBurn's Material Library. "
            "For a swatch palette, rename the copy's setting descriptions to match your desired Rasterizer swatches, "
            "then start the import again."
        )
    selected_name = str(selected_name or "").strip()
    materials = root.findall("./Material")
    matches = [material for material in materials if str(material.get("name") or "").strip() == selected_name]
    if not selected_name or not matches:
        available = [str(material.get("name") or "").strip() for material in materials]
        available = [name for name in available if name]
        detail = f" Available materials: {', '.join(available[:20])}." if available else ""
        raise ValueError(
            f"Material '{selected_name or '(none selected)'}' was not found in the library.{detail} "
            "Choose a material name present in the library that contains the settings you want to import."
        )
    if len(matches) > 1:
        raise ValueError(
            f"The LightBurn library contains more than one material named '{selected_name}'. "
            "Give the materials distinct names in LightBurn, save the library, and import it again."
        )
    for material in materials:
        if material is not matches[0]:
            root.remove(material)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def hatch_palette_contents(material_name, base_entry=None, base_settings=None, base_type="Scan",
                           start_angle=0, angular_span=180, first_interval=.1, last_interval=None):
    material_name = str(material_name or "").strip()
    if not 1 <= len(material_name) <= 160:
        raise ValueError("Hatch Palette material names must be between 1 and 160 characters")
    try:
        start_angle, angular_span = float(start_angle), float(angular_span)
        first_interval = float(first_interval)
        last_interval = first_interval if last_interval in (None, "") else float(last_interval)
    except (TypeError, ValueError) as error:
        raise ValueError("Hatch angles and intervals must be valid numbers") from error
    if not 0 < angular_span <= 360 or first_interval <= 0 or last_interval <= 0:
        raise ValueError("Angular span must be between 0 and 360 degrees and intervals must be positive")
    if base_entry is not None:
        base_cut = base_entry.find("./CutSetting")
        if base_cut is None or base_cut.get("type") not in {"Scan", "Offset"}:
            raise ValueError("A Hatch Palette base setting must use Fill or Offset Fill")
    elif base_type not in {"Scan", "Offset"}:
        raise ValueError("A Hatch Palette base setting must use Fill or Offset Fill")
    root = ET.Element("LightBurnLibrary", {"RasterizerPalette": "HATCH"})
    material = ET.SubElement(root, "Material", {"name": material_name})
    count = len(PALETTE)
    for index, (swatch_name, _hex) in enumerate(PALETTE):
        if base_entry is not None:
            entry = deepcopy(base_entry)
            entry.set("Desc", swatch_name)
            entry.set("Thickness", entry.get("Thickness") or "-1.0000")
            material.append(entry)
            cut = entry.find("./CutSetting")
        else:
            entry = ET.SubElement(material, "Entry", {"Thickness": "-1.0000", "Desc": swatch_name})
            cut = ET.SubElement(entry, "CutSetting", {"type": base_type})
            defaults = {"minPower":0,"maxPower":0,"maxPower2":0,"speed":0,"frequency":0,
                        "QPulseWidth":0,"anglePerPass":0,"crossHatch":0,"bidir":0,"overscan":0,
                        "doOutput":0,"hide":1,"numPasses":1}
            defaults.update(base_settings or {})
            for field, value in defaults.items(): ET.SubElement(cut, field, {"Value": str(value)})
        ratio = index / max(1, count - 1)
        replacements = {"index":index,"name":swatch_name,
                        "LinkPath":f"{material_name}/-1.0000/{swatch_name}",
                        "angle":f"{start_angle + angular_span * index / count:.6f}".rstrip("0").rstrip("."),
                        "interval":f"{first_interval + (last_interval - first_interval) * ratio:.6f}".rstrip("0").rstrip(".")}
        for field, value in replacements.items():
            node = cut.find(f"./{field}")
            if node is None: node = ET.SubElement(cut, field)
            node.set("Value", str(value))
        for sublayer in cut.findall(".//SubLayer"):
            for field in ("angle", "interval"):
                node = sublayer.find(f"./{field}")
                if node is None: node = ET.SubElement(sublayer, field)
                node.set("Value", replacements[field])
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def finalize_import(event, import_id):
    owner, data = user_id(event), body_json(event)
    key = {"pk": f"USER#{owner}", "sk": f"IMPORT#{import_id}"}
    pending = table.get_item(Key=key, ConsistentRead=True).get("Item")
    if not pending:
        return response(404, {"message": "This import session is no longer available. Start the import again."})
    token = str(data.get("upload_token") or "")
    if not token or not secrets.compare_digest(token_hash(token), str(pending.get("capability") or "")):
        return response(403, {"message": "This import session could not be verified. Start a new import and upload the file using its new link."})
    temporary_key = str(pending["s3_key"])
    try:
        try:
            result = s3.get_object(Bucket=BUCKET, Key=temporary_key)
        except ClientError as error:
            raise ValueError("We couldn't retrieve the uploaded file. Start a new import and upload the file again using its new link.") from error
        if (result.get("Metadata") or {}).get("upload-capability") != pending.get("capability"):
            raise ValueError("We couldn't verify this uploaded file. Start a new import and upload the file using its new link.")
        size = int(result.get("ContentLength") or 0)
        if size < 1:
            raise ValueError("The uploaded file is empty. Choose a nonempty file and start a new import.")
        limit_mb = f"{MAX_MATERIAL_BYTES / (1024 * 1024):g} MB"
        if pending["kind"] == "material":
            size_error = (
                f"This LightBurn Material Library exceeds the {limit_mb} upload limit. "
                "Save a copy in LightBurn, remove materials you don't plan to import from that copy, "
                "export it as a .clb file, and start a new import."
            )
        else:
            size_error = (
                f"This Fauxlographic Palette exceeds the {limit_mb} upload limit. "
                "Export a smaller palette with only the swatches and capture details you need, then start a new import."
            )
        if size > MAX_MATERIAL_BYTES:
            raise ValueError(size_error)
        contents = result["Body"].read(MAX_MATERIAL_BYTES + 1)
        if not contents:
            raise ValueError("The uploaded file is empty. Choose a nonempty file and start a new import.")
        if len(contents) > MAX_MATERIAL_BYTES:
            raise ValueError(size_error)
        asset_id, now = str(uuid.uuid4()), int(time.time())
        if pending["kind"] == "material":
            contents = retain_selected_material(contents, pending.get("material_name"))
            if pending.get("library_intent") == "hatch_palette":
                root = ET.fromstring(contents)
                source_entries = [entry for material in root.findall("./Material") for entry in material.findall("./Entry")]
                try: base_setting_id = int(pending.get("base_setting_id"))
                except (TypeError, ValueError) as error:
                    raise ValueError(
                        "The Hatch Palette base setting selection could not be read. Start a new import and select one setting from the material."
                    ) from error
                if base_setting_id < 0 or base_setting_id >= len(source_entries):
                    raise ValueError("The selected Hatch Palette base setting no longer exists in that material. Start a new import and select the base setting again.")
                base_entry = source_entries[base_setting_id]
                operation = str(pending.get("hatch_operation") or "setting")
                if operation in {"Scan", "Offset"}:
                    cut = base_entry.find("./CutSetting")
                    if cut is None:
                        raise ValueError(
                            "The selected Hatch Palette base entry has no LightBurn cut setting. Give it a Fill or Offset Fill setting in LightBurn, export the .clb file again, and start a new import."
                        )
                    cut.set("type", operation)
                elif operation != "setting":
                    raise ValueError("Choose Use setting, Fill, or Offset Fill")
                contents = hatch_palette_contents(
                    pending.get("material_name"), base_entry=base_entry,
                    start_angle=pending.get("start_angle"), angular_span=pending.get("angular_span"),
                    first_interval=pending.get("first_interval"), last_interval=pending.get("last_interval"),
                )
            contents, import_adjustments = normalize_imported_material_descriptions(contents)
            summary = material_summary(contents)
            filename = pending["filename"]
            destination = f"users/{owner}/materials/{asset_id}/{filename}"
            item = {"pk": f"USER#{owner}", "sk": f"MATERIAL#{asset_id}", "library_id": asset_id,
                    "name": pending.get("display_name") or os.path.splitext(filename)[0] or "Material Library",
                    "original_name": filename, "material_name": ", ".join(summary["material_names"])[:160],
                    "library_intent": pending.get("library_intent") or "color_palette",
                    "summary": dynamo_value(summary), "s3_key": destination, "created_at": now}
            response_body = {"material_library": public_library_summary(summary) | {
                "library_id": asset_id, "name": item["name"], "library_intent": item["library_intent"]},
                "import_adjustments": import_adjustments}
        else:
            recipe = json.loads(contents.decode("utf-8"))
            if not isinstance(recipe, dict) or recipe.get("kind") != "holographic_calibration_profile":
                raise ValueError("This file is not a Fauxlographic Palette. Choose a Fauxlographic Palette JSON file.")
            recipes = recipe.get("recipes")
            if not isinstance(recipes, list) or not recipes:
                raise ValueError("This Fauxlographic Palette has no saved swatches. Choose a palette containing at least one swatch.")
            original_black_setting = recipe.get("black_setting")
            black_setting = usable_preserved_black_setting(original_black_setting)
            ignored_preserved_black = original_black_setting is not None and black_setting is None
            if ignored_preserved_black:
                recipe["black_setting"] = None
                contents = json.dumps(recipe, separators=(",", ":")).encode("utf-8")
            if len(recipes) > fauxlographic_swatch_capacity(black_setting):
                raise ValueError(f"{fauxlographic_swatch_limit_message(black_setting)} Import a palette with fewer swatches.")
            schema_version = fauxlographic_schema_version(recipe)
            if schema_version >= 2:
                for swatch_index, measured in enumerate(recipes, start=1):
                    if not isinstance(measured, dict):
                        raise ValueError(f"Swatch {swatch_index} in the uploaded Fauxlographic Palette could not be read. Check the JSON file or export a fresh palette, then try again.")
                    try:
                        validate_lightburn_setting_snapshot(measured.get("laser_settings"))
                    except ValueError as error:
                        swatch_name = str(measured.get("name") or f"Swatch {swatch_index}").strip()[:160]
                        raise ValueError(f"Swatch {swatch_index} ('{swatch_name}') has invalid embedded LightBurn settings in the uploaded Fauxlographic Palette. Check the JSON file or export a fresh palette, then try again.") from error
            filename = pending["filename"]
            destination = f"users/{owner}/holographic-recipes/{asset_id}/{filename}"
            metadata = {"profile_name": str(recipe.get("profile_name") or "")[:160],
                        "recipe_count": len(recipes),
                        "swatch_preview": holographic_swatch_preview(recipes),
                        "material": str((recipe.get("grid") or {}).get("material") or "")[:160],
                        "schema_version": schema_version,
                        "self_contained": schema_version >= 2,
                        "has_black_setting": bool(recipe.get("black_setting"))}
            item = {"pk": f"USER#{owner}", "sk": f"HOLORECIPE#{asset_id}", "recipe_id": asset_id,
                    "name": pending.get("display_name") or metadata["profile_name"] or os.path.splitext(filename)[0],
                    "original_name": filename, "metadata": metadata, "s3_key": destination, "created_at": now}
            response_body = {"holographic_recipe": {"recipe_id": asset_id, "name": item["name"], "metadata": metadata},
                             "ignored_preserved_black": ignored_preserved_black}
        if pending["kind"] == "material":
            s3.put_object(Bucket=BUCKET, Key=destination, Body=contents, ContentType="application/xml")
        elif ignored_preserved_black:
            s3.put_object(Bucket=BUCKET, Key=destination, Body=contents, ContentType="application/json")
        else:
            s3.copy_object(Bucket=BUCKET, CopySource={"Bucket": BUCKET, "Key": temporary_key}, Key=destination)
        table.put_item(Item=item)
        return response(201, response_body)
    except (ET.ParseError, UnicodeDecodeError, json.JSONDecodeError) as error:
        owner_ref = hashlib.sha256(owner.encode("utf-8")).hexdigest()[:12]
        print(
            "Staging import validation failed "
            f"owner_ref={owner_ref} import_id={import_id} kind={pending.get('kind')} "
            f"intent={pending.get('library_intent')} filename={safe_name(pending.get('filename'), 'upload')}: malformed file",
            flush=True,
        )
        if pending.get("kind") == "material":
            raise ValueError(
                "This LightBurn Material Library could not be read. Choose a valid .clb file exported from LightBurn and start the import again."
            ) from error
        raise ValueError(
            "This Fauxlographic Palette JSON could not be read. Choose a valid Fauxlographic Palette JSON file and start the import again."
        ) from error
    except ValueError as error:
        owner_ref = hashlib.sha256(owner.encode("utf-8")).hexdigest()[:12]
        print(
            "Staging import validation failed "
            f"owner_ref={owner_ref} import_id={import_id} kind={pending.get('kind')} "
            f"intent={pending.get('library_intent')} filename={safe_name(pending.get('filename'), 'upload')}: {error}",
            flush=True,
        )
        raise
    finally:
        s3.delete_object(Bucket=BUCKET, Key=temporary_key)
        table.delete_item(Key=key)


def presigned_post(task_id, category, filename, content_type, maximum, digest, guest=False):
    key = f"jobs/{task_id}/inputs/{category}-{filename}"
    fields = {"Content-Type": content_type, "x-amz-meta-upload-capability": digest}
    policy = [
        {"key": key}, {"Content-Type": content_type},
        {"x-amz-meta-upload-capability": digest},
        ["content-length-range", 1, maximum],
    ]
    if guest:
        fields["x-amz-tagging"] = "mopa-retention=guest"
        policy.append({"x-amz-tagging": "mopa-retention=guest"})
    signed = s3.generate_presigned_post(Bucket=BUCKET, Key=key, Fields=fields,
                                         Conditions=policy, ExpiresIn=UPLOAD_CAPABILITY_SECONDS)
    return {"url": signed["url"], "fields": signed["fields"], "key": key,
            "maximum_bytes": maximum}


def create_upload(event):
    data = body_json(event)
    owner = user_id(event)
    task_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(32)
    digest = token_hash(token)
    artwork_name = safe_name(data.get("artwork_name"), "artwork.png")
    saved_library_id = str(data.get("saved_material_library_id") or "").strip()
    saved_recipe_id = str(data.get("saved_holographic_recipe_id") or "").strip()
    svg_only = data.get("svg_only") is True or str(data.get("svg_only") or "").strip().lower() in {"1", "true", "yes", "on"}
    if svg_only and (saved_library_id or saved_recipe_id):
        raise ValueError("SVG-Only cannot include a Material Library or Fauxlographic Palette")
    if saved_library_id and saved_recipe_id:
        raise ValueError("Choose either a Material Library or a self-contained Fauxlographic Palette")
    saved_material = owned_material(owner, saved_library_id) if saved_library_id else None
    if saved_library_id and not saved_material:
        return response(404, {"message": "Saved Material Library not found"})
    saved_recipe = owned_recipe(owner, saved_recipe_id) if saved_recipe_id else None
    if saved_recipe_id and not saved_recipe:
        return response(404, {"message": "Saved Fauxlographic Palette not found"})
    if saved_recipe and not (saved_recipe.get("metadata") or {}).get("self_contained"):
        raise ValueError("Only self-contained Fauxlographic Palettes can be used by Rasterizer")
    material_name = safe_name(
        saved_material.get("original_name") if saved_material else data.get("material_name"),
        "materials.clb",
    )
    if saved_recipe:
        material_name = safe_name(f"{saved_recipe.get('name') or 'holographic-palette'}.clb", "holographic-palette.clb")
    artwork_type = str(data.get("artwork_content_type") or mimetypes.guess_type(artwork_name)[0] or "application/octet-stream")[:120]
    material_type = str(data.get("material_content_type") or "application/octet-stream")[:120]
    now = int(time.time())
    runtime_item = {**runtime_key(task_id), "task_id": task_id, "user_id": owner,
                         "status": "uploading", "upload_capability": digest,
                         "upload_expires_at": now + UPLOAD_CAPABILITY_SECONDS,
                         "log_count": 0, "created_at": now, "updated_at": now,
                          "expires_at": now + TTL_SECONDS}
    if svg_only:
        runtime_item["svg_only"] = True
    if saved_material:
        runtime_item["saved_material_key"] = saved_material["s3_key"]
        runtime_item["saved_material_name"] = material_name
        runtime_item["saved_material_library_id"] = saved_library_id
    generated_material_key = ""
    if saved_recipe:
        profile = json.loads(s3.get_object(Bucket=BUCKET, Key=saved_recipe["s3_key"])["Body"].read(MAX_RECIPE_BYTES + 1))
        measured = profile.get("recipes") if isinstance(profile, dict) else None
        if fauxlographic_schema_version(profile) < 2 or not isinstance(measured, list) or not measured:
            raise ValueError("Only self-contained Fauxlographic Palettes can be used by Rasterizer")
        if len(measured) > fauxlographic_swatch_capacity(profile.get("black_setting")):
            raise ValueError(f"{fauxlographic_swatch_limit_message(profile.get('black_setting'))} Choose a palette with fewer swatches.")
        selections = [{"recipe_id":saved_recipe_id,"recipe_index":index} for index in range(len(measured))]
        library_root = selected_settings_root(owner, selections, saved_recipe.get("name") or "Fauxlographic Palette")
        embedded_black_name = ""
        black_setting = usable_preserved_black_setting(profile.get("black_setting"))
        if black_setting is not None:
            embedded_black_name = "Rasterizer Preserved Black"
            target_material = library_root.find("./Material")
            black_entry = ET.SubElement(target_material, "Entry", {
                "Thickness":"-1.0000", "Desc":embedded_black_name, "NoThickTitle":embedded_black_name,
            })
            black_cut = lightburn_snapshot_element(black_setting["laser_settings"])
            black_index = black_cut.find("./index")
            if black_index is None: black_index = ET.SubElement(black_cut, "index")
            black_index.set("Value", "0")
            black_name = black_cut.find("./name")
            if black_name is None: black_name = ET.SubElement(black_cut, "name")
            black_name.set("Value", embedded_black_name)
            black_entry.append(black_cut)
        library_bytes = ET.tostring(library_root, encoding="utf-8", xml_declaration=True)
        if len(library_bytes) > MAX_MATERIAL_BYTES:
            raise ValueError(f"The generated Fauxlographic Palette Material Library exceeds the {MATERIAL_LIMIT_MB} limit. Use fewer swatches and try again.")
        generated_material_key = f"jobs/{task_id}/inputs/material-{material_name}"
        s3.put_object(Bucket=BUCKET, Key=generated_material_key, Body=library_bytes,
                      ContentType="application/xml", Metadata={"upload-capability":digest})
        runtime_item["generated_recipe_id"] = saved_recipe_id
        runtime_item["saved_recipe_key"] = saved_recipe["s3_key"]
        runtime_item["saved_recipe_name"] = safe_name(saved_recipe.get("original_name"), "recipe.json")
        runtime_item["generated_material_name"] = saved_recipe.get("name") or "Fauxlographic Palette"
        runtime_item["generated_black_setting_name"] = embedded_black_name
        runtime_item["generated_recipe_count"] = len(measured)
    table.put_item(Item=runtime_item,
                   ConditionExpression="attribute_not_exists(pk)")
    result = {
        "task_id": task_id, "upload_token": token,
        "artwork": presigned_post(task_id, "artwork", artwork_name, artwork_type, MAX_ARTWORK_BYTES, digest),
        "expires_in_seconds": UPLOAD_CAPABILITY_SECONDS,
    }
    result["material"] = (None if svg_only else
                          {"key": generated_material_key, "saved": True, "generated": True, "name": material_name}
                          if saved_recipe else
                          {"key": saved_material["s3_key"], "saved": True, "name": material_name}
                          if saved_material else
                          presigned_post(task_id, "material", material_name, material_type, MAX_MATERIAL_BYTES, digest))
    return response(201, result)


def guest_config():
    """Return only the harmless client data required by the guest Rasterizer."""
    return response(200, {
        "palette": [{"name": name, "hex": color} for name, color in PALETTE],
        "daily_job_limit": GUEST_DAILY_JOB_LIMIT,
        "retention_hours": max(1, GUEST_JOB_SECONDS // 3600),
    })


def create_holographic_calibration_upload(event, guest=False):
    """Grant one short-lived Material Library upload for a calibration grid."""
    data = body_json(event)
    owner = "" if guest else user_id(event)
    task_id = str(uuid.uuid4())
    upload_token = secrets.token_urlsafe(32)
    access_token = secrets.token_urlsafe(32) if guest else ""
    digest = token_hash(upload_token)
    filename = safe_name(data.get("material_name"), "materials.clb")
    content_type = str(data.get("material_content_type") or "application/octet-stream")[:120]
    now = int(time.time())
    item = {
        **runtime_key(task_id), "task_id":task_id, "status":"uploading",
        "upload_capability":digest, "upload_expires_at":now + UPLOAD_CAPABILITY_SECONDS,
        "log_count":0, "created_at":now, "updated_at":now,
        "expires_at":now + (GUEST_JOB_SECONDS if guest else TTL_SECONDS),
        "holographic_calibration_upload":True,
    }
    if guest:
        item.update({
            "guest":True, "guest_access_capability":token_hash(access_token),
            "guest_access_expires_at":now + GUEST_JOB_SECONDS,
        })
    else:
        item["user_id"] = owner
    table.put_item(Item=item, ConditionExpression="attribute_not_exists(pk)")
    result = {
        "task_id":task_id, "upload_token":upload_token,
        "material":presigned_post(
            task_id, "material", filename, content_type, MAX_MATERIAL_BYTES, digest, guest=guest,
        ),
        "expires_in_seconds":UPLOAD_CAPABILITY_SECONDS,
    }
    if guest:
        result.update({
            "guest_access_token":access_token,
            "guest_access_expires_in_seconds":GUEST_JOB_SECONDS,
        })
    return response(201, result)


def create_color_discovery_upload(event, guest=False):
    """Grant one short-lived Material Library upload for a Color Lab grid."""
    data = body_json(event)
    owner = "" if guest else user_id(event)
    task_id = str(uuid.uuid4())
    upload_token = secrets.token_urlsafe(32)
    access_token = secrets.token_urlsafe(32) if guest else ""
    digest = token_hash(upload_token)
    filename = safe_name(data.get("material_name"), "materials.clb")
    content_type = str(data.get("material_content_type") or "application/octet-stream")[:120]
    now = int(time.time())
    item = {
        **runtime_key(task_id), "task_id":task_id, "status":"uploading",
        "upload_capability":digest, "upload_expires_at":now + UPLOAD_CAPABILITY_SECONDS,
        "log_count":0, "created_at":now, "updated_at":now,
        "expires_at":now + (GUEST_JOB_SECONDS if guest else TTL_SECONDS),
        "color_discovery_upload":True,
    }
    if guest:
        item.update({"guest":True, "guest_access_capability":token_hash(access_token),
                     "guest_access_expires_at":now + GUEST_JOB_SECONDS})
    else:
        item["user_id"] = owner
    table.put_item(Item=item, ConditionExpression="attribute_not_exists(pk)")
    result = {
        "task_id":task_id, "upload_token":upload_token,
        "material":presigned_post(task_id, "material", filename, content_type, MAX_MATERIAL_BYTES, digest, guest=guest),
        "expires_in_seconds":UPLOAD_CAPABILITY_SECONDS,
    }
    if guest:
        result.update({"guest_access_token":access_token, "guest_access_expires_in_seconds":GUEST_JOB_SECONDS})
    return response(201, result)


def create_guest_upload(event):
    """Create an isolated guest upload grant without creating account resources."""
    data = body_json(event)
    if data.get("saved_material_library_id") or data.get("saved_holographic_recipe_id"):
        raise ValueError("Guest jobs cannot use saved palettes or Material Libraries")
    svg_only = data.get("svg_only") is True or str(data.get("svg_only") or "").strip().lower() in {
        "1", "true", "yes", "on",
    }
    uploaded_holographic_palette = data.get("upload_holographic_palette") is True or str(
        data.get("upload_holographic_palette") or ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    if svg_only and uploaded_holographic_palette:
        raise ValueError("Choose either SVG-Only or a Fauxlographic Swatch Palette")
    task_id = str(uuid.uuid4())
    upload_token = secrets.token_urlsafe(32)
    access_token = secrets.token_urlsafe(32)
    upload_digest = token_hash(upload_token)
    artwork_name = safe_name(data.get("artwork_name"), "artwork.png")
    artwork_type = str(
        data.get("artwork_content_type") or mimetypes.guess_type(artwork_name)[0]
        or "application/octet-stream"
    )[:120]
    material_name = safe_name(data.get("material_name"), "materials.clb")
    material_type = str(data.get("material_content_type") or "application/octet-stream")[:120]
    palette_name = safe_name(data.get("holographic_palette_name"), "holographic-palette.json")
    palette_type = str(data.get("holographic_palette_content_type") or "application/json")[:120]
    now = int(time.time())
    item = {
        **runtime_key(task_id), "task_id": task_id, "guest": True,
        "status": "uploading", "upload_capability": upload_digest,
        "upload_expires_at": now + UPLOAD_CAPABILITY_SECONDS,
        "guest_access_capability": token_hash(access_token),
        "guest_access_expires_at": now + GUEST_JOB_SECONDS,
        "log_count": 0, "created_at": now, "updated_at": now,
        "expires_at": now + GUEST_JOB_SECONDS,
    }
    if svg_only:
        item["svg_only"] = True
    if uploaded_holographic_palette:
        item["uploaded_holographic_palette"] = True
        item["uploaded_holographic_palette_name"] = palette_name
    table.put_item(Item=item, ConditionExpression="attribute_not_exists(pk)")
    return response(201, {
        "task_id": task_id, "upload_token": upload_token,
        "guest_access_token": access_token,
        "artwork": presigned_post(
            task_id, "artwork", artwork_name, artwork_type, MAX_ARTWORK_BYTES, upload_digest,
            guest=True,
        ),
        "material": None if svg_only or uploaded_holographic_palette else presigned_post(
            task_id, "material", material_name, material_type, MAX_MATERIAL_BYTES, upload_digest,
            guest=True,
        ),
        "holographic_palette": presigned_post(
            task_id, "holographic-palette", palette_name, palette_type, MAX_RECIPE_BYTES,
            upload_digest, guest=True,
        ) if uploaded_holographic_palette else None,
        "expires_in_seconds": UPLOAD_CAPABILITY_SECONDS,
        "guest_access_expires_in_seconds": GUEST_JOB_SECONDS,
    })


def verify_upload(key, digest, maximum):
    if not key.startswith("jobs/") or "/inputs/" not in key:
        raise ValueError("The uploaded file does not match this request. Select the file again and retry to start a fresh upload.")
    try:
        head = s3.head_object(Bucket=BUCKET, Key=key)
    except ClientError as error:
        raise ValueError(
            "We couldn't access the uploaded file. Select it again and retry to start a fresh upload. "
            "If this keeps happening, report the time and any job or grid ID shown."
        ) from error
    size = int(head.get("ContentLength") or 0)
    if size < 1:
        raise ValueError("The uploaded file is empty. Choose a nonempty file and retry the upload.")
    if size > maximum:
        raise ValueError(
            f"The uploaded file exceeds the {maximum / (1024 * 1024):g} MB limit. "
            "Choose a smaller file and retry the upload."
        )
    if (head.get("Metadata") or {}).get("upload-capability") != digest:
        raise ValueError("The uploaded file no longer matches this request. Select it again and retry to start a fresh upload.")
    return head


def record_artwork_duplicate_telemetry(owner, task_id, head):
    """Record user-scoped repeat detection plus anonymous daily totals.

    ETag and size are sufficient for measuring likely duplicate browser uploads,
    but are deliberately not treated as a security checksum or cache identity.
    Telemetry failure must never prevent an otherwise valid job from running.
    """
    try:
        size = int(head.get("ContentLength") or 0)
        etag = str(head.get("ETag") or "").strip().strip('"').casefold()
        if not owner or not etag or size < 1:
            raise ValueError("verified upload did not include a usable ETag and size")
        now = int(time.time())
        expires_at = now + ARTWORK_TELEMETRY_SECONDS
        fingerprint = hashlib.sha256(f"s3-etag-size-v1:{etag}:{size}".encode("utf-8")).hexdigest()
        fingerprint_key = {
            "pk": f"USER#{owner}",
            "sk": f"UPLOADFINGERPRINT#ARTWORK#{fingerprint}",
        }
        duplicate = False
        try:
            table.put_item(
                Item={
                    **fingerprint_key,
                    "fingerprint_version": "s3-etag-size-v1",
                    "content_length": size,
                    "use_count": 1,
                    "duplicate_count": 0,
                    "first_seen_at": now,
                    "last_seen_at": now,
                    "expires_at": expires_at,
                },
                ConditionExpression="attribute_not_exists(pk)",
            )
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            duplicate = True
            table.update_item(
                Key=fingerprint_key,
                UpdateExpression=(
                    "SET last_seen_at=:now, expires_at=:expiry "
                    "ADD use_count :one, duplicate_count :one"
                ),
                ExpressionAttributeValues={":now": now, ":expiry": expires_at, ":one": 1},
            )

        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        table.update_item(
            Key={"pk": "TELEMETRY#ARTWORK_UPLOADS", "sk": f"DAY#{day}"},
            UpdateExpression=(
                "SET updated_at=:now, expires_at=:expiry "
                "ADD upload_count :one, uploaded_bytes :bytes, "
                "duplicate_count :duplicate, duplicate_bytes :duplicate_bytes"
            ),
            ExpressionAttributeValues={
                ":now": now,
                ":expiry": expires_at,
                ":one": 1,
                ":bytes": size,
                ":duplicate": 1 if duplicate else 0,
                ":duplicate_bytes": size if duplicate else 0,
            },
        )
        print(json.dumps({
            "event": "artwork_upload_telemetry",
            "task_id": task_id,
            "owner_ref": hashlib.sha256(owner.encode("utf-8")).hexdigest()[:12],
            "fingerprint_version": "s3-etag-size-v1",
            "content_length": size,
            "duplicate": duplicate,
        }, separators=(",", ":")), flush=True)
        return {"duplicate": duplicate, "content_length": size, "day": day}
    except Exception as error:
        print(json.dumps({
            "event": "artwork_upload_telemetry_failed",
            "task_id": task_id,
            "error": f"{type(error).__name__}: {error}",
        }, separators=(",", ":")), flush=True)
        return None


def verify_saved_material(key, owner, maximum):
    if not key.startswith(f"users/{owner}/materials/"):
        raise ValueError("This saved Material Library isn't available to the signed-in account. Check that you're signed into the right account, or choose another library.")
    try:
        head = s3.head_object(Bucket=BUCKET, Key=key)
    except ClientError as error:
        raise ValueError("We couldn't access the saved Material Library. Try again. If it keeps happening, re-import the library or report the problem, including any job ID shown.") from error
    size = int(head.get("ContentLength") or 0)
    if size < 1:
        raise ValueError("The saved Material Library is empty. Choose another library or import a valid LightBurn file.")
    if size > maximum:
        raise ValueError(f"The saved Material Library exceeds the {maximum / (1024 * 1024):g} MB limit. Choose a smaller library or import a smaller LightBurn export.")


def verify_saved_recipe(key, owner, maximum):
    if not key.startswith(f"users/{owner}/holographic-recipes/"):
        raise ValueError("This saved Fauxlographic Palette isn't available to the signed-in account. Check that you're signed into the right account, or choose another palette.")
    try:
        head = s3.head_object(Bucket=BUCKET, Key=key)
    except ClientError as error:
        raise ValueError("We couldn't access the saved Fauxlographic Palette. Try again. If it keeps happening, re-import the palette or report the problem, including any job ID shown.") from error
    size = int(head.get("ContentLength") or 0)
    if size < 1:
        raise ValueError("The saved Fauxlographic Palette is empty. Choose another palette or import a valid palette file.")
    if size > maximum:
        raise ValueError(f"The saved Fauxlographic Palette exceeds the {maximum / (1024 * 1024):g} MB limit. Choose a smaller palette or import a smaller palette file.")


def create_holographic_upload(event):
    data = body_json(event)
    owner = user_id(event)
    material = owned_material(owner, str(data.get("saved_material_library_id") or "").strip())
    recipe = owned_recipe(owner, str(data.get("saved_holographic_recipe_id") or "").strip())
    if not material:
        return response(404, {"message": "Choose a saved Material Library"})
    if not recipe:
        return response(404, {"message": "Choose a saved Fauxlographic Palette"})
    task_id, token = str(uuid.uuid4()), secrets.token_urlsafe(32)
    digest = token_hash(token)
    artwork_name = safe_name(data.get("artwork_name"), "artwork.png")
    artwork_type = str(data.get("artwork_content_type") or mimetypes.guess_type(artwork_name)[0]
                       or "application/octet-stream")[:120]
    now = int(time.time())
    table.put_item(Item={
        **runtime_key(task_id), "task_id": task_id, "user_id": owner,
        "status": "uploading", "upload_capability": digest, "log_count": 0,
        "upload_expires_at": now + UPLOAD_CAPABILITY_SECONDS,
        "created_at": now, "updated_at": now, "expires_at": now + TTL_SECONDS,
        "saved_material_key": material["s3_key"],
        "saved_material_name": safe_name(material.get("original_name"), "materials.clb"),
        "saved_recipe_key": recipe["s3_key"],
        "saved_recipe_name": safe_name(recipe.get("original_name"), "recipe.json"),
    }, ConditionExpression="attribute_not_exists(pk)")
    return response(201, {
        "task_id": task_id, "upload_token": token,
        "artwork": presigned_post(task_id, "artwork", artwork_name, artwork_type,
                                    MAX_ARTWORK_BYTES, digest),
        "material": {"key": material["s3_key"], "saved": True},
        "recipe": {"key": recipe["s3_key"], "saved": True},
        "expires_in_seconds": UPLOAD_CAPABILITY_SECONDS,
    })


def submit_holographic_job(event, task_id):
    paused = service_paused_response()
    if paused:
        return paused
    item = runtime(task_id)
    if not authorize_task(event, item):
        return response(404, {"message": "Task not found"})
    data = body_json(event)
    token = str(data.get("upload_token") or "")
    if not valid_upload_capability(item, token):
        return response(403, {"message": "Upload capability is invalid or expired"})
    artwork_key = str(data.get("artwork_key") or "")
    recipe_key = str(data.get("recipe_key") or "")
    material_key = str(data.get("material_key") or "")
    if not artwork_key.startswith(f"jobs/{task_id}/inputs/"):
        return response(400, {"message": "We couldn't match the uploaded artwork to this job. Submit the job again to start a fresh upload."})
    if recipe_key != item.get("saved_recipe_key") or material_key != item.get("saved_material_key"):
        return response(400, {"message": "Your input selection changed while the file was uploading. Review your selection, then submit the job again."})
    try:
        max_dimension = max(8, min(1600, int(data.get("max_dimension", 96))))
        pixel_mm = max(0.01, min(5, float(data.get("pixel_mm", 0.5))))
        cut_mode = str(data.get("cut_mode") or "setting").strip().lower()
        if cut_mode not in {"setting", "line", "fill", "offset_fill"}:
            raise ValueError("Choose a valid cut mode")
        artwork_head = verify_upload(artwork_key, item["upload_capability"], MAX_ARTWORK_BYTES)
        verify_saved_recipe(recipe_key, user_id(event), MAX_RECIPE_BYTES)
        verify_saved_material(material_key, user_id(event), MAX_MATERIAL_BYTES)
    except (TypeError, ValueError) as error:
        return response(400, {"message": str(error)})
    payload = {
        "job_type": "holographic_artwork", "task_id": task_id,
        "artwork_key": artwork_key, "recipe_key": recipe_key, "material_key": material_key,
        "artwork_name": safe_name(artwork_key.rsplit("/", 1)[-1].removeprefix("artwork-"), "artwork.png"),
        "recipe_name": item["saved_recipe_name"], "material_name": item["saved_material_name"],
        "max_dimension": max_dimension, "pixel_mm": pixel_mm,
        "preserve_black_outlines": bool(data.get("preserve_black_outlines")),
        "cut_mode": cut_mode, "user_id": user_id(event),
    }
    now = int(time.time())
    try:
        table.update_item(
            Key=runtime_key(task_id),
            UpdateExpression="SET #status=:pending, payload=:payload, updated_at=:now, expires_at=:expiry REMOVE upload_capability, upload_expires_at",
            ConditionExpression="#status=:uploading AND upload_expires_at >= :now",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":pending": "pending", ":uploading": "uploading",
                                       ":payload": dynamo_value(payload), ":now": now,
                                       ":expiry": now + TTL_SECONDS},
        )
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return response(409, {"message": "Task was already submitted"})
        raise
    history_sk = f"JOB#{now:010d}#{task_id}"
    artifact_prefix = f"users/{user_id(event)}/jobs/{task_id}/"
    run_parameters = {key: payload[key] for key in (
        "job_type", "recipe_name", "material_name", "max_dimension", "pixel_mm",
        "preserve_black_outlines", "cut_mode",
    )}
    history = {
        "pk": f"USER#{user_id(event)}", "sk": history_sk, "task_id": task_id,
        "job_type": "holographic_artwork",
        "source_name": payload["artwork_name"], "image_preset": "holographic_artwork",
        "abstract_filter": "none", "material_name": payload["material_name"],
        "run_parameters": dynamo_value(run_parameters), "created_at": now,
        "updated_at": now, "status": "pending", "artifact_prefix": artifact_prefix,
        "input_keys": [artwork_key, recipe_key, material_key],
        "expires_at": now + TTL_SECONDS,
    }
    with table.batch_writer() as batch:
        batch.put_item(Item=history)
        batch.put_item(Item={
            "pk": f"JOB#{task_id}", "sk": "OWNER", "user_id": user_id(event),
            "job_type": "holographic_artwork",
            "created_at": now, "updated_at": now, "history_sk": history_sk,
            "status": "pending", "artifact_prefix": artifact_prefix,
            "input_keys": [artwork_key, recipe_key, material_key],
            "expires_at": now + TTL_SECONDS,
        })
        batch.put_item(Item=admin_job_index_item(event, history))
    try:
        sqs.send_message(QueueUrl=QUEUE_URL, MessageBody=json.dumps({"task_id": task_id}, separators=(",", ":")))
    except Exception:
        table.update_item(
            Key=runtime_key(task_id),
            UpdateExpression="SET #status=:uploading, upload_capability=:capability, upload_expires_at=:upload_expiry, updated_at=:now",
            ConditionExpression="#status=:pending",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":uploading": "uploading", ":pending": "pending",
                                       ":capability": token_hash(token),
                                       ":upload_expiry": int(item["upload_expires_at"]),
                                       ":now": int(time.time())},
        )
        raise
    record_artwork_duplicate_telemetry(user_id(event), task_id, artwork_head)
    return response(202, {"task_id": task_id, "status": "pending"})


def dynamo_value(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {key: dynamo_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [dynamo_value(item) for item in value]
    return value


def json_value(value):
    """Convert DynamoDB Decimal values back into ordinary JSON numbers."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_value(item) for item in value]
    return value


def submit_job(event, task_id, guest=False):
    paused = service_paused_response()
    if paused:
        return paused
    item = runtime(task_id)
    if guest:
        if not valid_guest_capability(item, request_header(event, "x-guest-capability")):
            return response(404, {"message": "Guest task not found or access expired"})
    elif not authorize_task(event, item):
        return response(404, {"message": "Task not found"})
    data = body_json(event)
    owner = "" if guest else user_id(event)
    svg_only = item.get("svg_only") is True
    requested_svg_only = data.get("svg_only") is True or str(data.get("svg_only") or "").strip().lower() in {"1", "true", "yes", "on"}
    if requested_svg_only != svg_only:
        return response(400, {"message": "The SVG-Only choice no longer matches this upload. Review your output choice, then submit the job again."})
    data["svg_only"] = "true" if svg_only else "false"
    preset = str(data.get("image_preset") or "cartoon").strip().lower()
    if preset not in RASTER_PRESETS and not (
        preset.startswith("abstract_") and preset.removeprefix("abstract_") in ABSTRACT_FILTERS
    ):
        return response(400, {"message": "Choose a valid raster image style"})
    raw_parameters = data.get("abstract_filter_parameters") or "{}"
    try:
        parameters = json.loads(raw_parameters) if isinstance(raw_parameters, str) else raw_parameters
    except (TypeError, json.JSONDecodeError):
        return response(400, {"message": "We couldn't read the Image Style settings. Reload Rasterizer, choose the style again, and submit the job again."})
    if not isinstance(parameters, dict) or len(parameters) > 20:
        return response(400, {"message": "The Image Style settings could not be read or contain too many controls. Reload Rasterizer, choose the style again, and submit the job again."})
    if any(not isinstance(value, (str, int, float, bool)) for value in parameters.values()):
        return response(400, {"message": "An Image Style control has an invalid value. Use Reset settings under Image Style, then configure it and submit again."})
    # Color matching is independent of abstract-filter controls. Older cached
    # clients briefly sent these keys inside the abstract settings object, so
    # pop them there as a compatibility measure before the worker's numeric
    # abstract-setting validation sees them.
    legacy_matching = {
        key: parameters.pop(key)
        for key in tuple(parameters)
        if key.startswith("color_matching_")
    }
    matching_mode = str(
        data.get("color_matching_mode")
        or legacy_matching.get("color_matching_mode")
        or "balanced"
    ).strip().lower()
    if matching_mode not in {"balanced", "hue", "shades", "closest", "custom"}:
        return response(400, {"message": "Choose a valid color matching mode"})
    data["color_matching_mode"] = matching_mode
    matching_weights = []
    for key, default in (
        ("color_matching_hue_weight", 4.0),
        ("color_matching_saturation_weight", 1.0),
        ("color_matching_lightness_weight", 1.0),
    ):
        try:
            value = float(data.get(key, legacy_matching.get(key, default)))
            if not math.isfinite(value) or not 0 <= value <= 10:
                raise ValueError
        except (TypeError, ValueError):
            label = key.removeprefix("color_matching_").removesuffix("_weight").capitalize()
            return response(400, {"message": f"Color matching {label} influence must be between 0 and 10. Adjust that control and submit again."})
        data[key] = value
        matching_weights.append(value)
    if matching_mode == "custom" and not sum(matching_weights):
        return response(400, {"message": "Custom color matching needs at least one non-zero influence"})
    try:
        pixel_square_mm = float(data.get("pixel_square_mm") or 1)
        if not math.isfinite(pixel_square_mm) or pixel_square_mm < .01:
            raise ValueError
    except (TypeError, ValueError):
        return response(400, {"message": "Pixel size must be at least 0.01 mm"})
    data["pixel_square_mm"] = str(pixel_square_mm)
    crop_shape = str(data.get("crop_shape") or "").strip().lower()
    if crop_shape not in {"", "rectangle", "square", "oval", "circle", "transparency"}:
        return response(400, {"message": "Choose a valid artwork crop shape"})
    data["crop_shape"] = crop_shape
    data["image_preset"] = preset
    data["abstract_filter"] = preset.removeprefix("abstract_") if preset.startswith("abstract_") else "none"
    data["abstract_filter_parameters"] = json.dumps(parameters, separators=(",", ":"))
    geometry_style = str(data.get("geometry_style") or "vectors").strip().lower()
    if geometry_style not in {"vectors", "glyphs", "krasnow_grating", "by_swatch"}:
        return response(400, {"message": "Choose a valid geometry style"})
    if geometry_style in {"glyphs", "krasnow_grating", "by_swatch"} and data["abstract_filter"] in {
        "halftone_newsprint", "optical_color_mix", "krasnow_grating",
    }:
        return response(400, {"message": "This Geometry Style is not available with the selected specialized image style"})
    raw_geometry_parameters = data.get("geometry_style_parameters") or "{}"
    try:
        geometry_parameters = (
            json.loads(raw_geometry_parameters)
            if isinstance(raw_geometry_parameters, str)
            else raw_geometry_parameters
        )
    except (TypeError, json.JSONDecodeError):
        return response(400, {"message": "We couldn't read the Geometry Style settings. Reload Rasterizer, choose the geometry again, and submit the job again."})
    if not isinstance(geometry_parameters, dict):
        return response(400, {"message": "The Geometry Style settings could not be read. Use Reset geometry settings, configure the geometry again, and submit the job again."})
    # Older cached staging pages exposed this retired experimental control.
    # Discard it so a browser/API/worker rolling deployment cannot strand an
    # otherwise valid Rasterizer job.
    geometry_parameters = dict(geometry_parameters)
    geometry_parameters.pop("posterize_colors", None)
    if len(geometry_parameters) > 24:
        return response(400, {"message": "The Geometry Style settings contain too many controls. Use Reset geometry settings, configure the geometry again, and submit the job again."})
    if len(json.dumps(geometry_parameters, separators=(",", ":"))) > 120000:
        return response(400, {"message": "The Geometry Style settings are too large to submit. Remove extra Flow Painter regions, masks, or brush strokes and try again."})
    numeric_geometry_parameters = {
        "cell_size_mm", "minimum_glyph_ratio", "maximum_glyph_ratio",
        "non_black_glyph_density", "tone_curve", "contrast", "grid_angle",
        "glyph_rotation", "seed", "speed_spread", "gradient_top",
        "gradient_bottom", "gradient_curve", "hue_rotation",
        "saturation_cutoff", "patch_size_mm", "line_spacing_mm",
        "hue_line_spacing_minimum_mm", "hue_line_spacing_maximum_mm",
        "angle_min", "angle_max", "custom_glyph_threshold",
        "custom_glyph_padding",
    }
    toggle_geometry_parameters = {
        "invert", "invert_fill", "black_only", "preserve_black", "custom_glyph_invert",
    }
    glyph_shapes = {
        "circle", "square", "diamond", "triangle", "hexagon", "octagon",
        "star", "cross", "bar", "skull", "heart", "space_invader",
        "ghost", "bat", "alien_head", "paw_print", "fish_scale",
        "puzzle_piece", "mixed", "custom",
    }
    cell_shapes = {
        "square", "hexagon", "triangle", "diamond", "skull", "heart",
        "space_invader", "ghost", "bat", "alien_head", "paw_print",
        "fish_scale", "puzzle_piece",
    }
    gradient_scopes = {"entire_artwork", "each_shape"}
    grating_render_modes = {"line", "fill"}
    gradient_directions = {
        "top_to_bottom", "bottom_to_top", "left_to_right", "right_to_left",
        "center_to_edge", "edge_to_center",
    }
    def validate_compact_mask(value, *, flow_region_number=None):
        message = (
            f"Fauxlogram Flow Painter region {flow_region_number}'s image mask couldn't be used. "
            "Remove the mask and add a PNG, JPEG, or WebP image again."
            if flow_region_number is not None else
            "The custom glyph image couldn't be used. Remove it and choose a PNG, "
            "JPEG, or WebP image again."
        )
        if not isinstance(value, dict) or set(value) != {"width", "height", "data"}:
            raise ValueError(message)
        width, height, encoded = value.get("width"), value.get("height"), value.get("data")
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
    def validate_fauxlogram_flow(value):
        if not isinstance(value, dict):
            raise ValueError("Fauxlogram Flow Painter settings could not be read. Use Reset geometry settings and rebuild the flow setup.")
        regions = value.get("regions") or []
        strokes = value.get("strokes") or []
        if not isinstance(regions, list) or not 1 <= len(regions) <= 8:
            raise ValueError("Fauxlogram Flow Painter needs 1 to 8 regions. Reopen the painter and adjust the regions, or use Reset geometry settings if it won't open.")
        if not isinstance(strokes, list) or len(strokes) > 256:
            raise ValueError("Fauxlogram Flow Painter supports at most 256 brush strokes. Reopen the painter and clear or simplify painted regions.")
        point_count = 0
        for region_number, region in enumerate(regions, start=1):
            if not isinstance(region, dict):
                raise ValueError(
                    f"Fauxlogram Flow Painter region {region_number} could not be read. "
                    "Reopen the painter and recreate that region. If the painter won't open, "
                    "use Reset geometry settings and rebuild the flow setup."
                )
            if str(region.get("region_type") or "painted") not in {"painted", "image_mask"}:
                raise ValueError(
                    f"Fauxlogram Flow Painter region {region_number} has an unsupported region type. "
                    "Reopen the painter and recreate that region. If the painter won't open, "
                    "use Reset geometry settings and rebuild the flow setup."
                )
            if str(region.get("scope") or "combined_region") not in {
                "combined_region", "each_shape", "entire_artwork",
            }:
                raise ValueError(
                    f"Fauxlogram Flow Painter region {region_number} has an invalid Gradient scope. "
                    "Reopen the painter and choose a valid Gradient scope for that region. "
                    "If the painter won't open, use Reset geometry settings and rebuild the flow setup."
                )
            if str(region.get("guide_type") or "linear") not in {"linear", "radial"}:
                raise ValueError(
                    f"Fauxlogram Flow Painter region {region_number} has an invalid Guide type. "
                    "Reopen the painter and choose Linear or Radial for that region. "
                    "If the painter won't open, use Reset geometry settings and rebuild the flow setup."
                )
            if str(region.get("orientation") or "parallel") not in {
                "parallel", "perpendicular", "fixed", "offset",
            }:
                raise ValueError(
                    f"Fauxlogram Flow Painter region {region_number} has an invalid Grating orientation. "
                    "Reopen the painter and choose a Grating orientation for that region. "
                    "If the painter won't open, use Reset geometry settings and rebuild the flow setup."
                )
            mask = region.get("mask")
            if mask is not None:
                validate_compact_mask(mask, flow_region_number=region_number)
                if str(region.get("mask_mode") or "silhouette") not in {
                    "silhouette", "grayscale",
                }:
                    raise ValueError(
                        f"Fauxlogram Flow Painter region {region_number} has an invalid mask Interpretation. "
                        "Reopen the painter and choose Grayscale gradient map or Silhouette for that region."
                    )
                threshold = region.get("mask_threshold", 0.5)
                if (
                    isinstance(threshold, bool)
                    or not isinstance(threshold, (int, float))
                    or not math.isfinite(threshold)
                    or not 0 <= threshold <= 1
                ):
                    raise ValueError(
                        f"Fauxlogram Flow Painter region {region_number} has an invalid mask Threshold. "
                        "Reopen the painter and adjust that region's Threshold slider."
                    )
                mask_invert = region.get("mask_invert", False)
                if not isinstance(mask_invert, (bool, int)) or mask_invert not in (False, True, 0, 1):
                    raise ValueError(
                        f"Fauxlogram Flow Painter region {region_number} has an invalid Invert mask setting. "
                        "Reopen the painter and toggle Invert mask for that region."
                    )
                offset = region.get("mask_offset", [0, 0])
                if not isinstance(offset, list) or len(offset) != 2 or any(
                    isinstance(item, bool) or not isinstance(item, (int, float))
                    or not math.isfinite(item) or not -1 <= item <= 1
                    for item in offset
                ):
                    raise ValueError(
                        f"Fauxlogram Flow Painter region {region_number} has an invalid mask position. "
                        "Reopen the painter and reposition that region's mask, or remove and add the mask again."
                    )
            for point in (region.get("start", [.25, .5]), region.get("end", [.75, .5])):
                if not isinstance(point, list) or len(point) != 2 or any(
                    isinstance(item, bool) or not isinstance(item, (int, float))
                    or not math.isfinite(item) or not 0 <= item <= 1 for item in point
                ):
                    raise ValueError(
                        f"Fauxlogram Flow Painter region {region_number} has an invalid guide position. "
                        "Reopen the painter and redraw that region's guide. If the painter won't open, "
                        "use Reset geometry settings and rebuild the flow setup."
                    )
        for stroke_number, stroke in enumerate(strokes, start=1):
            if not isinstance(stroke, dict):
                raise ValueError(
                    f"Fauxlogram Flow Painter brush stroke {stroke_number} could not be read. "
                    "Reopen the painter and clear the affected region, then paint it again."
                )
            points = stroke.get("points")
            region_index = stroke.get("region")
            if not isinstance(region_index, int) or not 0 <= region_index < len(regions):
                raise ValueError(
                    f"Fauxlogram Flow Painter brush stroke {stroke_number} refers to a region that is no longer available. "
                    "Use Reset geometry settings and rebuild the flow setup."
                )
            if not isinstance(points, list) or not 1 <= len(points) <= 512:
                raise ValueError(
                    f"Fauxlogram Flow Painter brush stroke {stroke_number} could not be read. "
                    "Reopen the painter and clear the affected region, then paint it again."
                )
            point_count += len(points)
            if point_count > 4000:
                raise ValueError("Fauxlogram Flow Painter supports at most 4,000 brush points. Reopen the painter and clear or simplify painted regions.")
            for point in points:
                if not isinstance(point, list) or len(point) != 2 or any(
                    isinstance(item, bool) or not isinstance(item, (int, float))
                    or not math.isfinite(item) or not 0 <= item <= 1 for item in point
                ):
                    raise ValueError(
                        f"Fauxlogram Flow Painter brush stroke {stroke_number} has an invalid point. "
                        "Reopen the painter and clear the affected region, then paint it again."
                    )
    def validate_geometry_section(section):
        if not isinstance(section, dict) or len(section) > 24:
            raise ValueError("The Geometry Style settings could not be read or contain too many controls. Use Reset geometry settings, configure the geometry again, and submit the job again.")
        for key, value in section.items():
            valid = (
                (key == "glyph_shape" and value in glyph_shapes)
                or (key == "cell_shape" and value in cell_shapes)
                or (key == "grating_render_mode" and value in grating_render_modes)
                or (key == "fauxlogram_gradient_scope" and value in gradient_scopes)
                or (
                    key == "fauxlogram_gradient_direction"
                    and value in gradient_directions
                )
                or (key == "fauxlogram_flow" and isinstance(value, dict))
                or (key == "custom_glyph_mask" and isinstance(value, dict))
                or (key in toggle_geometry_parameters and isinstance(value, (bool, int)) and value in {0, 1})
                or (
                    key in numeric_geometry_parameters
                    and not isinstance(value, bool)
                    and isinstance(value, (int, float))
                    and math.isfinite(value)
                )
            )
            if not valid:
                if key == "custom_glyph_mask":
                    validate_compact_mask(value)
                raise ValueError(f"Geometry Style control '{str(key)[:60]}' has an invalid value. Use Reset geometry settings, configure it again, and submit the job again.")
            if key == "fauxlogram_flow":
                validate_fauxlogram_flow(value)
            elif key == "custom_glyph_mask":
                validate_compact_mask(value)
        if section.get("invert_fill") and section.get("black_only"):
            raise ValueError("Invert Fill and Black Only cannot be used together. Turn off one of those Geometry Style controls and submit again.")
        if section.get("glyph_shape") == "custom" and not section.get("custom_glyph_mask"):
            raise ValueError("Upload a custom glyph image before submitting the job")

    try:
        if geometry_style == "by_swatch":
            if set(geometry_parameters) - {"assignments", "glyphs", "krasnow_grating"}:
                raise ValueError("Choose-by-Swatch geometry settings could not be read. Use Reset geometry settings, review the swatch routing, and submit again.")
            assignments = geometry_parameters.get("assignments") or {}
            if not isinstance(assignments, dict) or len(assignments) > 64:
                raise ValueError("Choose-by-Swatch routing could not be read or has too many assignments. Reload Rasterizer, review the swatch routing, and submit again.")
            selected_hexes = {
                str(value).strip().upper()
                for value in (data.get("selected_color_hexes") or [])
            }
            clean_assignments = {}
            for color_hex, assigned_style in assignments.items():
                color_hex = str(color_hex).strip().upper()
                assigned_style = str(assigned_style).strip().lower()
                if not re.fullmatch(r"#[0-9A-F]{6}", color_hex):
                    raise ValueError("A Choose-by-Swatch color could not be read. Reload Rasterizer, review the swatch routing, and submit again.")
                if color_hex not in selected_hexes | {"#000000"}:
                    raise ValueError(f"Choose-by-Swatch routing includes {color_hex}, which is not selected for this job. Select that swatch or remove its routing, then submit again.")
                if assigned_style not in {"vectors", "glyphs", "krasnow_grating"}:
                    raise ValueError(f"Choose-by-Swatch routing for {color_hex} has an unsupported geometry. Choose Vectors, Glyphs, or Krasnow and submit again.")
                clean_assignments[color_hex] = assigned_style
            clean_assignments["#000000"] = "vectors"
            glyph_parameters = geometry_parameters.get("glyphs") or {}
            krasnow_parameters = geometry_parameters.get("krasnow_grating") or {}
            validate_geometry_section(glyph_parameters)
            validate_geometry_section(krasnow_parameters)
            geometry_parameters = {
                "assignments": clean_assignments,
                "glyphs": glyph_parameters,
                "krasnow_grating": krasnow_parameters,
            }
        else:
            validate_geometry_section(geometry_parameters)
    except ValueError as error:
        return response(400, {"message": str(error)})
    data["geometry_style"] = geometry_style
    data["geometry_style_parameters"] = json.dumps(geometry_parameters, separators=(",", ":"))
    token = str(data.get("upload_token", ""))
    if not valid_upload_capability(item, token):
        return response(403, {"message": "Upload capability is invalid or expired"})
    if item.get("uploaded_holographic_palette") is True:
        palette_key = str(data.get("holographic_palette_key") or "")
        expected_prefix = f"jobs/{task_id}/inputs/"
        if not palette_key.startswith(expected_prefix):
            return response(400, {"message": "We couldn't match the uploaded Fauxlographic Swatch Palette to this job. Check your selected palette, then submit the job again to start a fresh upload."})
        try:
            verify_upload(palette_key, item["upload_capability"], MAX_RECIPE_BYTES)
            contents = s3.get_object(Bucket=BUCKET, Key=palette_key)["Body"].read(MAX_RECIPE_BYTES + 1)
            if len(contents) > MAX_RECIPE_BYTES:
                raise ValueError(
                    f"The Fauxlographic Swatch Palette exceeds the {MAX_RECIPE_BYTES / (1024 * 1024):g} MB limit. "
                    "Choose a smaller palette file and submit the job again."
                )
            profile = json.loads(contents.decode("utf-8"))
            measured = profile.get("recipes") if isinstance(profile, dict) else None
            all_indexes = list(range(len(measured))) if isinstance(measured, list) else []
            palette_material_name = str(profile.get("profile_name") or "Fauxlographic Palette") if isinstance(profile, dict) else ""
            library_root = uploaded_holographic_settings_root(profile, all_indexes, palette_material_name)
            embedded_black_name = ""
            black_setting = usable_preserved_black_setting(profile.get("black_setting"))
            if black_setting is not None:
                embedded_black_name = "Rasterizer Preserved Black"
                target_material = library_root.find("./Material")
                black_entry = ET.SubElement(target_material, "Entry", {
                    "Thickness": "-1.0000", "Desc": embedded_black_name,
                    "NoThickTitle": embedded_black_name,
                })
                black_cut = lightburn_snapshot_element(black_setting["laser_settings"])
                black_index = black_cut.find("./index")
                if black_index is None:
                    black_index = ET.SubElement(black_cut, "index")
                black_index.set("Value", "0")
                black_name = black_cut.find("./name")
                if black_name is None:
                    black_name = ET.SubElement(black_cut, "name")
                black_name.set("Value", embedded_black_name)
                black_entry.append(black_cut)
            library_bytes = ET.tostring(library_root, encoding="utf-8", xml_declaration=True)
            if len(library_bytes) > MAX_MATERIAL_BYTES:
                raise ValueError(f"The generated Fauxlographic Palette Material Library exceeds the {MATERIAL_LIMIT_MB} limit. Use fewer swatches and try again.")
            material_filename = safe_name(f"{palette_material_name}.clb", "holographic-palette.clb")
            generated_material_key = f"jobs/{task_id}/inputs/material-{material_filename}"
            s3.put_object(
                Bucket=BUCKET, Key=generated_material_key, Body=library_bytes,
                ContentType="application/xml", Metadata={"upload-capability": item["upload_capability"]},
                Tagging="mopa-retention=guest",
            )
            item.update({
                "generated_recipe_id": "uploaded-holographic-palette",
                "generated_recipe_count": len(measured),
                "saved_recipe_key": palette_key,
                "saved_recipe_name": safe_name(item.get("uploaded_holographic_palette_name"), "holographic-palette.json"),
                "generated_material_name": palette_material_name,
                "generated_black_setting_name": embedded_black_name,
            })
            data["material_key"] = generated_material_key
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            return response(400, {"message": str(error) or "The Fauxlographic Swatch Palette is malformed"})
    generated_recipe_id = str(item.get("generated_recipe_id") or "")
    raw_overrides = data.get("color_name_overrides") or {}
    try:
        overrides = json.loads(raw_overrides) if isinstance(raw_overrides, str) else raw_overrides
    except (TypeError, json.JSONDecodeError):
        return response(400, {"message": "We couldn't read the selected raster swatch names. Reload Rasterizer, review the swatch selections, and submit again."})
    if not isinstance(overrides, dict):
        return response(400, {"message": "The selected raster swatch names could not be read. Reload Rasterizer, review the swatch selections, and submit again."})
    clean_overrides = {
        color: str(overrides.get(color) or default_name).strip()[:80]
        for color, default_name in PALETTE_NAMES.items()
    }
    if any(not name for name in clean_overrides.values()):
        return response(400, {"message": "A selected raster swatch has no Material Library name. Assign a name to each selected swatch, then submit again."})
    selected_hexes = data.get("selected_color_hexes")
    selected_recipe_indexes = data.get("selected_holographic_recipe_indexes")
    if generated_recipe_id:
        if (not isinstance(selected_recipe_indexes, list)
                or any(not isinstance(index, int) or isinstance(index, bool) for index in selected_recipe_indexes)):
            return response(400, {"message": "Select at least one valid Fauxlographic Palette swatch"})
        selected_recipe_indexes = list(dict.fromkeys(selected_recipe_indexes))
        recipe_count = int(item.get("generated_recipe_count") or 0)
        capacity = MAX_LIGHTBURN_LAYERS - int(bool(item.get("generated_black_setting_name")))
        if not selected_recipe_indexes or len(selected_recipe_indexes) > capacity:
            return response(400, {"message": f"Select between 1 and {capacity} Fauxlographic Palette swatches for this job. Preserved Black uses one of the {MAX_LIGHTBURN_LAYERS} LightBurn layers when present."})
        if any(index < 0 or index >= recipe_count for index in selected_recipe_indexes):
            return response(400, {"message": "One or more selected Fauxlographic Palette swatches are no longer available. Reload the palette and select them again."})
        selected_hexes = []
    elif isinstance(selected_hexes, list):
        selected_hexes = [str(color).upper() for color in selected_hexes]
        if not selected_hexes or any(color not in PALETTE_NAMES for color in selected_hexes):
            return response(400, {"message": "Select at least one valid raster palette swatch"})
        selected_hexes = list(dict.fromkeys(selected_hexes))
        saved_library_id = str(item.get("saved_material_library_id") or "").strip()
        if saved_library_id:
            preferences_item = table.get_item(
                Key={"pk": f"USER#{owner}", "sk": "PREFERENCES"}, ConsistentRead=True,
            ).get("Item") or {}
            assignments = (preferences_item.get("preferences") or {}).get(
                "material_library_color_assignments"
            ) or {}
            if saved_library_id in assignments:
                active_mapping = assignments.get(saved_library_id) or {}
                allowed_hexes = {str(color).upper() for color in active_mapping}
                unavailable = [color for color in selected_hexes if color not in allowed_hexes]
                if unavailable:
                    names = ", ".join(PALETTE_NAMES[color] for color in unavailable)
                    return response(400, {
                        "message": f"The selected Swatch Palette no longer assigns: {names}. "
                                   "Refresh the Rasterizer page and choose assigned swatches.",
                    })
                for color, name in active_mapping.items():
                    color = str(color).upper()
                    if color in clean_overrides and str(name).strip():
                        clean_overrides[color] = str(name).strip()[:80]
    else:
        # Compatibility for submissions created before selected hex identities
        # were added. Renamed labels deliberately use the hex path above.
        allowed_names = {name.casefold(): color for name, color in PALETTE}
        requested_names = [name.strip() for name in str(data.get("colors") or "").split(",") if name.strip()]
        if not requested_names or any(name.casefold() not in allowed_names for name in requested_names):
            return response(400, {"message": "Select at least one valid raster palette swatch"})
        selected_hexes = [allowed_names[name.casefold()] for name in requested_names]
    data["selected_color_hexes"] = selected_hexes
    if generated_recipe_id:
        data["selected_holographic_recipe_indexes"] = selected_recipe_indexes
        data["image_preset"] = "holographic_artwork"
        data["abstract_filter"] = "none"
    data["color_name_overrides"] = json.dumps(clean_overrides, separators=(",", ":"))
    data["colors"] = ",".join(clean_overrides[color] for color in selected_hexes)
    data.pop("upload_token", None)
    artwork_key = str(data.pop("artwork_key", ""))
    material_key = str(data.pop("material_key", ""))
    expected_prefix = f"jobs/{task_id}/inputs/"
    if not artwork_key.startswith(expected_prefix):
        return response(400, {"message": "We couldn't match the uploaded artwork to this job. Submit the job again to start a fresh upload."})
    saved_material_key = str(item.get("saved_material_key") or "")
    if svg_only and material_key:
        return response(400, {"message": "SVG-Only jobs cannot include a Material Library"})
    if not svg_only and material_key != saved_material_key and not material_key.startswith(expected_prefix):
        return response(400, {"message": "We couldn't match the selected Material Library to this job. Review your library choice, then submit the job again."})
    try:
        artwork_head = verify_upload(artwork_key, item["upload_capability"], MAX_ARTWORK_BYTES)
        if svg_only:
            pass
        elif saved_material_key:
            if material_key != saved_material_key:
                raise ValueError("The saved Material Library no longer matches this upload. Review your library choice, then submit the job again.")
            verify_saved_material(material_key, owner, MAX_MATERIAL_BYTES)
        else:
            verify_upload(material_key, item["upload_capability"], MAX_MATERIAL_BYTES)
    except ValueError as error:
        return response(400, {"message": str(error)})
    holographic_parameters = None
    if generated_recipe_id:
        try:
            requested_dimensions = [data.get("new_width"), data.get("new_height")]
            requested_dimensions = [int(value) for value in requested_dimensions if str(value or "").strip()]
            if any(value < 0 for value in requested_dimensions):
                raise ValueError("Fauxlographic processing dimensions cannot be negative")
            explicit_dimensions = [value for value in requested_dimensions if value > 0]
            max_dimension = max(explicit_dimensions) if explicit_dimensions else 0
            if max_dimension and not 8 <= max_dimension <= 1600:
                raise ValueError("Fauxlographic processing dimensions must be between 8 and 1600 pixels")
            pixel_mm = float(data.get("pixel_square_mm") or .5)
            if not .01 <= pixel_mm <= 5:
                raise ValueError("Fauxlographic pixel size must be between 0.01 and 5 mm")
        except (TypeError, ValueError) as error:
            return response(400, {"message": str(error)})
        holographic_parameters = (max_dimension, pixel_mm)
    payload = {
        "task_id": task_id, "data": data,
        "image_key": artwork_key, "material_key": material_key,
        "image_name": safe_name(artwork_key.rsplit("/", 1)[-1].removeprefix("artwork-"), "artwork.png"),
        "material_name": "" if svg_only else safe_name(material_key.rsplit("/", 1)[-1].removeprefix("material-"), "materials.clb"),
        "output_name": f"output_{task_id}_{safe_name(artwork_key.rsplit('/', 1)[-1], 'artwork.png')}",
        "user_id": None if guest else owner,
        "guest_job": guest,
    }
    if guest:
        quota_visitor, quota_day = guest_quota_context(event)
        payload.update({
            "guest_quota_visitor": quota_visitor,
            "guest_quota_day": quota_day,
            "guest_daily_job_limit": GUEST_DAILY_JOB_LIMIT,
        })
    if generated_recipe_id:
        max_dimension, pixel_mm = holographic_parameters
        cut_mode = str(data.get("cut_mode") or "setting").strip().lower()
        if cut_mode not in {"setting", "line", "fill", "offset_fill"}:
            return response(400, {"message": "Choose a valid Fauxlographic Artwork cut mode"})
        embedded_black_setting_name = str(item.get("generated_black_setting_name") or "")
        preserve_black_outlines = data.get("preserve_black_outlines") is True and bool(embedded_black_setting_name)
        payload.update({
            "job_type": "holographic_artwork",
            "artwork_key": artwork_key,
            "artwork_name": payload["image_name"],
            "recipe_key": str(item.get("saved_recipe_key") or ""),
            "recipe_name": str(item.get("saved_recipe_name") or "recipe.json"),
            "max_dimension": max_dimension,
            "pixel_mm": pixel_mm,
            "cut_mode": cut_mode,
            "preserve_black_outlines": preserve_black_outlines,
            "selected_recipe_indexes": selected_recipe_indexes,
            "embedded_material_name": str(item.get("generated_material_name") or "Fauxlographic Palette"),
            "embedded_black_setting_name": embedded_black_setting_name,
        })
    now = int(time.time())
    try:
        table.update_item(
            Key=runtime_key(task_id),
            UpdateExpression="SET #status=:pending, payload=:payload, updated_at=:now, expires_at=:expiry REMOVE upload_capability, upload_expires_at",
            ConditionExpression="#status=:uploading AND upload_expires_at >= :now",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":pending": "pending", ":uploading": "uploading",
                                       ":payload": dynamo_value(payload), ":now": now,
                                       ":expiry": now + (GUEST_JOB_SECONDS if guest else TTL_SECONDS)},
        )
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return response(409, {"message": "Task was already submitted"})
        raise
    history_sk = f"JOB#{now:010d}#{task_id}"
    artifact_prefix = f"jobs/{task_id}/" if guest else f"users/{owner}/jobs/{task_id}/"
    job_type = "holographic_artwork" if generated_recipe_id else "rasterizer"
    recipe_input_key = str(item.get("saved_recipe_key") or "") if generated_recipe_id else ""
    history = {
        "pk": f"USER#{owner}", "sk": history_sk,
        "task_id": task_id, "job_type": job_type, "source_name": payload["image_name"],
        "image_preset": str(data.get("image_preset") or ""),
        "abstract_filter": str(data.get("abstract_filter") or "none"),
        "material_name": str(data.get("material") or ""),
        "run_parameters": dynamo_value(data), "created_at": now,
        "updated_at": now, "status": "pending", "artifact_prefix": artifact_prefix,
        "input_keys": list(dict.fromkeys(key for key in (artwork_key, material_key, recipe_input_key) if key)),
        "expires_at": now + TTL_SECONDS,
    }
    owner_record = {
        "pk": f"JOB#{task_id}", "sk": "OWNER", "user_id": owner, "guest": guest,
        "job_type": job_type, "source_name": payload["image_name"],
        "material_name": str(data.get("material") or ""),
        "image_preset": str(data.get("image_preset") or ""),
        "abstract_filter": str(data.get("abstract_filter") or "none"),
        "created_at": now, "updated_at": now, "history_sk": history_sk,
        "status": "pending", "artifact_prefix": artifact_prefix,
        "input_keys": list(dict.fromkeys(key for key in (artwork_key, material_key, recipe_input_key) if key)),
        "expires_at": now + (GUEST_JOB_SECONDS if guest else TTL_SECONDS),
    }
    with table.batch_writer() as batch:
        if not guest:
            batch.put_item(Item=history)
        batch.put_item(Item=owner_record)
        admin_index = admin_job_index_item(event, history)
        if guest:
            admin_index["guest"] = True
            admin_index["expires_at"] = now + GUEST_JOB_SECONDS
        batch.put_item(Item=admin_index)
    try:
        sqs.send_message(QueueUrl=QUEUE_URL, MessageBody=json.dumps({"task_id": task_id}, separators=(",", ":")))
    except Exception:
        # Restore the capability so a transient SQS error is safely retryable.
        table.update_item(
            Key=runtime_key(task_id),
            UpdateExpression="SET #status=:uploading, upload_capability=:capability, upload_expires_at=:upload_expiry, updated_at=:now",
            ConditionExpression="#status=:pending",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":uploading": "uploading", ":pending": "pending",
                                       ":capability": token_hash(token),
                                       ":upload_expiry": int(item["upload_expires_at"]),
                                       ":now": int(time.time())},
        )
        raise
    if not guest:
        record_artwork_duplicate_telemetry(owner, task_id, artwork_head)
    return response(202, {"task_id": task_id, "status": "pending"})


def get_job(event, task_id, guest=False):
    item = runtime(task_id)
    if guest:
        if not valid_guest_capability(item, request_header(event, "x-guest-capability")):
            return response(404, {"message": "Guest task not found or access expired"})
    elif not authorize_task(event, item):
        return response(404, {"message": "Task not found"})
    logs = job_logs(task_id, item)
    count = len(logs)
    error_message = str(item.get("error_message") or "")
    result = {"task_id": task_id, "status": item.get("status", "unknown"),
              "logs": visible_job_logs(logs, error_message), "log_count": count}
    if item.get("status") == "completed":
        output_prefix = f"jobs/{task_id}/outputs/" if guest else f"users/{item['user_id']}/jobs/{task_id}/outputs/"
        listed = s3.list_objects_v2(Bucket=BUCKET, Prefix=output_prefix).get("Contents", [])
        payload = json_value(item.get("payload") or {})
        source_name = str(payload.get("image_name") or "Artwork")
        result["outputs"] = ordered_output_descriptors(task_id, source_name, listed)
    if error_message:
        result["error"] = error_message
    return response(200, result)


def handler(event, _context):
    try:
        method = ((event.get("requestContext") or {}).get("http") or {}).get("method", "GET")
        path = unquote(event.get("rawPath") or "/")
        if method == "GET" and path == "/service-status":
            return public_service_status()
        if path == "/guest" or path.startswith("/guest/"):
            if not GUEST_ACCESS_ENABLED:
                return response(403, {"message": "Guest access is disabled in this environment"})
        if method == "GET" and path == "/guest/config":
            return guest_config()
        if method == "POST" and path == "/guest/uploads":
            return create_guest_upload(event)
        if method == "POST" and path == "/guest/holographic/calibration-uploads":
            return create_holographic_calibration_upload(event, guest=True)
        if method == "POST" and path == "/guest/color-discovery/uploads":
            return create_color_discovery_upload(event, guest=True)
        guest_parts = path.strip("/").split("/")
        if (method == "POST" and len(guest_parts) == 4
                and guest_parts[:3] == ["guest", "holographic", "calibrations"]):
            uuid.UUID(guest_parts[3])
            return create_holographic_calibration(event, guest=True, upload_task_id=guest_parts[3])
        if (len(guest_parts) >= 4 and guest_parts[:3] == ["guest", "color-discovery", "grids"]):
            uuid.UUID(guest_parts[3])
            if method == "POST" and len(guest_parts) == 4:
                return create_color_discovery_grid(event, guest=True, upload_task_id=guest_parts[3])
            if method == "GET" and len(guest_parts) == 4:
                return get_color_discovery_grid(event, guest_parts[3], guest=True)
            if method == "POST" and len(guest_parts) == 5 and guest_parts[4] == "refine":
                return create_color_discovery_grid(event, guest=True)
        if len(guest_parts) >= 3 and guest_parts[:2] == ["guest", "jobs"]:
            guest_task_id = guest_parts[2]
            uuid.UUID(guest_task_id)
            if method == "POST" and len(guest_parts) == 4 and guest_parts[3] == "submit":
                return submit_job(event, guest_task_id, guest=True)
            if method == "GET" and len(guest_parts) == 3:
                return get_job(event, guest_task_id, guest=True)
        if not user_id(event):
            return response(401, {"message": "Authentication required"})
        subject = user_id(event)
        if ALLOWED_USER_SUB and not secrets.compare_digest(subject, ALLOWED_USER_SUB):
            return response(403, {"message": "This account is not authorized for this environment"})
        if method == "POST" and path == "/uploads":
            return create_upload(event)
        if method == "POST" and path == "/holographic/uploads":
            return create_holographic_upload(event)
        if method == "POST" and path == "/holographic/calibration-uploads":
            return create_holographic_calibration_upload(event)
        if method == "POST" and path == "/color-discovery/uploads":
            return create_color_discovery_upload(event)
        if method == "POST" and path == "/holographic/calibrations":
            return create_holographic_calibration(event)
        holographic_parts = path.strip("/").split("/")
        if (method == "POST" and len(holographic_parts) == 3
                and holographic_parts[:2] == ["holographic", "calibrations"]):
            uuid.UUID(holographic_parts[2])
            return create_holographic_calibration(event, upload_task_id=holographic_parts[2])
        if method == "POST" and path == "/color-discovery/grids":
            return create_color_discovery_grid(event)
        color_parts = path.strip("/").split("/")
        if (method == "POST" and len(color_parts) == 3
                and color_parts[:2] == ["color-discovery", "grids"]):
            uuid.UUID(color_parts[2])
            return create_color_discovery_grid(event, upload_task_id=color_parts[2])
        if method == "GET" and path == "/color-discovery/grids":
            return list_color_discovery_grids(event)
        if method == "POST" and path == "/account/color-palettes/discovered":
            return save_color_discovery_palette(event)
        if method == "POST" and path == "/account/holographic-recipes/measured":
            return save_measured_holographic_recipe(event)
        if method == "GET" and path == "/account/resources":
            return account_resources(event)
        if path == "/account/preferences" and method in {"GET", "PUT", "PATCH"}:
            return account_preferences(event)
        if method == "GET" and path == "/account/jobs":
            return account_jobs(event)
        if method == "GET" and path == "/admin/jobs":
            return admin_jobs(event)
        if method == "GET" and path == "/admin/users":
            return admin_users(event)
        if path == "/admin/service-control" and method in {"GET", "POST"}:
            return admin_service_control(event)
        if method == "GET" and path == "/community-set/settings":
            return community_settings(event)
        if method == "POST" and path == "/account/community-set":
            return publish_community_palette(event)
        if method == "POST" and path == "/account/material-libraries/selected-settings":
            return selected_material_settings(event)
        if method == "POST" and path == "/account/depth-palettes":
            return save_depth_palette(event)
        if method == "POST" and path == "/account/imports":
            return import_upload(event)
        parts = path.strip("/").split("/")
        if method == "POST" and len(parts) == 3 and parts[:2] == ["holographic", "calibrations"]:
            uuid.UUID(parts[2])
            return create_holographic_calibration(event, upload_task_id=parts[2])
        if method == "GET" and len(parts) == 3 and parts[:2] == ["color-discovery", "grids"]:
            return get_color_discovery_grid(event, parts[2])
        if method == "POST" and len(parts) == 4 and parts[:2] == ["account", "imports"] and parts[3] == "finalize":
            uuid.UUID(parts[2])
            return finalize_import(event, parts[2])
        if len(parts) == 3 and parts[0] == "account":
            item_id = parts[2]
            uuid.UUID(item_id)
            if parts[1] == "depth-palettes":
                if method == "PUT": return save_depth_palette(event, item_id)
                if method == "DELETE": return delete_owned_item(event, "depth", item_id)
            if parts[1] == "material-libraries":
                if method == "PATCH": return rename_material(event, item_id)
                if method == "DELETE": return delete_owned_item(event, "material", item_id)
            if parts[1] == "holographic-recipes":
                if method == "GET": return holographic_recipe_detail(event, item_id)
                if method == "PUT": return update_holographic_recipe(event, item_id)
                if method == "DELETE": return delete_owned_item(event, "recipe", item_id)
        if method == "PATCH" and len(parts) == 5 and parts[:2] == ["account", "material-libraries"] and parts[3] == "entries":
            uuid.UUID(parts[2])
            return edit_material_entry(event, parts[2], int(parts[4]))
        if method in {"GET", "DELETE"} and len(parts) == 3 and parts[:2] == ["account", "jobs"]:
            uuid.UUID(parts[2])
            return account_job(event, parts[2]) if method == "GET" else delete_account_job(event, parts[2])
        if method == "GET" and len(parts) == 3 and parts[:2] == ["admin", "jobs"]:
            uuid.UUID(parts[2])
            return admin_job(event, parts[2])
        if method == "POST" and len(parts) == 4 and parts[:2] == ["admin", "jobs"] and parts[3] == "cancel":
            uuid.UUID(parts[2])
            return cancel_admin_job(event, parts[2])
        if method == "DELETE" and len(parts) == 3 and parts[:2] == ["admin", "jobs"]:
            uuid.UUID(parts[2])
            return delete_admin_job(event, parts[2])
        if (method == "POST" and len(parts) == 4 and parts[0] == "holographic"
                and parts[1] == "jobs" and parts[3] == "submit"):
            uuid.UUID(parts[2])
            return submit_holographic_job(event, parts[2])
        if len(parts) >= 2 and parts[0] == "jobs":
            task_id = parts[1]
            uuid.UUID(task_id)
            if method == "POST" and len(parts) == 3 and parts[2] == "submit":
                return submit_job(event, task_id)
            if method == "GET" and len(parts) == 2:
                return get_job(event, task_id)
        return response(404, {"message": "Not found"})
    except (ValueError, json.JSONDecodeError, ET.ParseError) as error:
        return response(400, {"message": str(error)})
    except Exception as error:
        print(f"Unhandled API error: {error}", flush=True)
        return response(500, {"message": (
            "We couldn't complete this request. Please try again. If it happens again, "
            "note the time and any job ID shown when reporting the problem."
        )})
