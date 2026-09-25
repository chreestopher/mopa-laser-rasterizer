#!/usr/bin/env python3
"""Copy one Cognito user's durable production data into isolated staging.

Uses only Python's standard library and AWS CLI v2 so workstation setup does
not need a separately installed boto3 package.
"""

import argparse
import atexit
import json
import os
import subprocess
import tempfile
import time
from decimal import Decimal
from urllib.parse import quote, urlencode


TEMP_FILES = []
COMMUNITY_PUBLIC_SETTING_FIELDS = (
    "speed", "minPower", "maxPower", "frequency", "QPulseWidth", "interval",
    "angle", "numPasses", "anglePerPass", "bidir", "crossHatch", "type",
)


@atexit.register
def remove_temp_files():
    for path in TEMP_FILES:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def aws(profile, *args, json_output=True):
    command = ["aws", "--profile", profile, *args]
    if json_output:
        command.extend(["--output", "json"])
    result = subprocess.run(command, check=True, text=True, capture_output=True)
    if not json_output:
        return result.stdout
    return json.loads(result.stdout) if result.stdout.strip() else {}


def attribute_value(value):
    if value is None:
        return {"NULL": True}
    if isinstance(value, bool):
        return {"BOOL": value}
    if isinstance(value, (int, Decimal)):
        return {"N": str(value)}
    if isinstance(value, float):
        return {"N": str(Decimal(str(value)))}
    if isinstance(value, str):
        return {"S": value}
    if isinstance(value, list):
        return {"L": [attribute_value(item) for item in value]}
    if isinstance(value, dict):
        return {"M": {key: attribute_value(item) for key, item in value.items()}}
    raise TypeError(f"Unsupported DynamoDB value: {type(value).__name__}")


def ordinary(value):
    if "S" in value:
        return value["S"]
    if "N" in value:
        number = Decimal(value["N"])
        return int(number) if number == number.to_integral() else number
    if "BOOL" in value:
        return value["BOOL"]
    if "NULL" in value:
        return None
    if "L" in value:
        return [ordinary(item) for item in value["L"]]
    if "M" in value:
        return {key: ordinary(item) for key, item in value["M"].items()}
    if "SS" in value:
        return value["SS"]
    if "NS" in value:
        return [Decimal(item) for item in value["NS"]]
    raise TypeError(f"Unsupported DynamoDB attribute: {value.keys()}")


def item_value(item, key, default=None):
    return ordinary(item[key]) if key in item else default


def compact_community_item(item):
    """Copy Community Set records without private LightBurn metadata."""
    plain = {key: ordinary(value) for key, value in item.items()}
    summary = plain.get("summary") if isinstance(plain.get("summary"), dict) else {}
    entries = []
    for entry in summary.get("entries", []):
        if not isinstance(entry, dict):
            continue
        settings = entry.get("settings") if isinstance(entry.get("settings"), dict) else {}
        entries.append({
            **entry,
            "settings": {
                field: settings[field]
                for field in COMMUNITY_PUBLIC_SETTING_FIELDS
                if field in settings and not isinstance(settings[field], (dict, list))
            },
        })
    plain["summary"] = {**summary, "entries": entries, "entry_count": len(entries)}
    return {key: attribute_value(value) for key, value in plain.items()}


def json_argument(value):
    handle = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", delete=False)
    with handle:
        json.dump(value, handle, default=str)
    TEMP_FILES.append(handle.name)
    return "file://" + handle.name


def cognito_sub(profile, region, pool_id, account):
    result = aws(profile, "cognito-idp", "list-users", "--region", region,
                 "--user-pool-id", pool_id)
    target = account.strip().casefold()
    matches = []
    for user in result.get("Users", []):
        attrs = {item["Name"]: item.get("Value", "") for item in user.get("Attributes", [])}
        email = str(attrs.get("email", ""))
        candidates = {str(user.get("Username", "")).casefold(), email.casefold(), email.split("@", 1)[0].casefold()}
        if target in candidates:
            matches.append(attrs)
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one Cognito match for {account!r}; found {len(matches)}")
    if not matches[0].get("sub"):
        raise RuntimeError("The matched Cognito user has no sub attribute")
    return matches[0]["sub"]


def query_items(profile, region, table, user_id, prefix):
    values = {":pk": {"S": f"USER#{user_id}"}, ":prefix": {"S": prefix}}
    result = aws(profile, "dynamodb", "query", "--region", region, "--table-name", table,
                 "--key-condition-expression", "pk = :pk AND begins_with(sk, :prefix)",
                 "--expression-attribute-values", json_argument(values), "--no-scan-index-forward")
    return result.get("Items", [])


def query_partition(profile, region, table, partition):
    values = {":pk": {"S": partition}}
    items = []
    start_key = None
    while True:
        command = ["dynamodb", "query", "--region", region, "--table-name", table,
                   "--key-condition-expression", "pk = :pk",
                   "--expression-attribute-values", json_argument(values)]
        if start_key:
            command.extend(["--exclusive-start-key", json_argument(start_key)])
        result = aws(profile, *command)
        items.extend(result.get("Items", []))
        start_key = result.get("LastEvaluatedKey")
        if not start_key:
            return items


def put_item(profile, region, table, item):
    aws(profile, "dynamodb", "put-item", "--region", region, "--table-name", table,
        "--item", json_argument(item))


def get_item(profile, region, table, pk, sk):
    key = {"pk": {"S": pk}, "sk": {"S": sk}}
    return aws(profile, "dynamodb", "get-item", "--region", region, "--table-name", table,
               "--key", json_argument(key), "--consistent-read").get("Item")


def copy_prefix(profile, region, source_bucket, destination_bucket, prefix):
    result = aws(profile, "s3api", "list-objects-v2", "--region", region,
                 "--bucket", source_bucket, "--prefix", prefix)
    copied = 0
    for obj in result.get("Contents", []):
        key = obj["Key"]
        try:
            destination = aws(profile, "s3api", "head-object", "--region", region,
                              "--bucket", destination_bucket, "--key", key)
        except subprocess.CalledProcessError:
            destination = None
        source_etag = str(obj.get("ETag", "")).strip('"')
        same_size = destination and destination.get("ContentLength") == obj.get("Size")
        if same_size and destination.get("ETag") == obj.get("ETag"):
            continue
        if same_size:
            destination_tags = aws(profile, "s3api", "get-object-tagging", "--region", region,
                                   "--bucket", destination_bucket, "--key", key).get("TagSet", [])
            if any(tag.get("Key") == "mopa-source-etag" and tag.get("Value") == source_etag
                   for tag in destination_tags):
                continue
        source_tags = aws(profile, "s3api", "get-object-tagging", "--region", region,
                          "--bucket", source_bucket, "--key", key).get("TagSet", [])
        copy_tags = {tag["Key"]: tag["Value"] for tag in source_tags}
        copy_tags["mopa-source-etag"] = source_etag
        aws(profile, "s3api", "copy-object", "--region", region,
            "--bucket", destination_bucket, "--key", key,
            "--copy-source", quote(f"{source_bucket}/{key}", safe="/"),
            "--metadata-directive", "COPY", "--tagging-directive", "REPLACE",
            "--tagging", urlencode(copy_tags))
        copied += 1
    return copied


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("account")
    parser.add_argument("--region", default="us-east-2")
    parser.add_argument("--profile", default="mopa-admin")
    parser.add_argument("--user-pool-id", required=True)
    parser.add_argument("--source-table", required=True)
    parser.add_argument("--source-bucket", required=True)
    parser.add_argument("--destination-table", required=True)
    parser.add_argument("--destination-bucket", required=True)
    parser.add_argument("--job-limit", type=int, default=10)
    parser.add_argument("--include-community-set", action="store_true")
    args = parser.parse_args()
    if args.source_table == args.destination_table or args.source_bucket == args.destination_bucket:
        raise RuntimeError("Source and staging destinations must be different")
    if not 1 <= args.job_limit <= 100:
        raise RuntimeError("--job-limit must be between 1 and 100")

    user_id = cognito_sub(args.profile, args.region, args.user_pool_id, args.account)
    categories = {
        "material_libraries": query_items(args.profile, args.region, args.source_table, user_id, "MATERIAL#"),
        "depth_palettes": query_items(args.profile, args.region, args.source_table, user_id, "DEPTHPALETTE#"),
        "holographic_recipes": query_items(args.profile, args.region, args.source_table, user_id, "HOLORECIPE#"),
        "jobs": query_items(args.profile, args.region, args.source_table, user_id, "JOB#")[:args.job_limit],
    }
    copied_objects = 0
    for category in ("material_libraries", "depth_palettes", "holographic_recipes"):
        for item in categories[category]:
            put_item(args.profile, args.region, args.destination_table, item)
            s3_key = str(item_value(item, "s3_key", ""))
            if s3_key:
                copied_objects += copy_prefix(args.profile, args.region, args.source_bucket, args.destination_bucket, s3_key)

    now = int(time.time())
    for history in categories["jobs"]:
        task_id = str(item_value(history, "task_id", ""))
        if not task_id:
            continue
        put_item(args.profile, args.region, args.destination_table, history)
        owner = get_item(args.profile, args.region, args.source_table, f"JOB#{task_id}", "OWNER")
        if owner:
            put_item(args.profile, args.region, args.destination_table, owner)
        created_at = item_value(history, "created_at", now)
        runtime = {
            "pk": attribute_value(f"JOB#{task_id}"), "sk": attribute_value("RUNTIME"),
            "task_id": attribute_value(task_id), "user_id": attribute_value(user_id),
            "status": attribute_value(item_value(history, "status", "completed")),
            "created_at": attribute_value(created_at),
            "updated_at": attribute_value(item_value(history, "updated_at", created_at)),
            "expires_at": attribute_value(now + 604800), "log_count": attribute_value(0),
        }
        error_message = item_value(history, "error_message", "")
        if error_message:
            runtime["error_message"] = attribute_value(error_message)
        put_item(args.profile, args.region, args.destination_table, runtime)
        prefix = str(item_value(history, "artifact_prefix", f"users/{user_id}/jobs/{task_id}/"))
        copied_objects += copy_prefix(args.profile, args.region, args.source_bucket, args.destination_bucket, prefix)

    community_items = []
    if args.include_community_set:
        community_items = query_partition(args.profile, args.region, args.source_table, "LASER_COMMUNITY")
        for item in community_items:
            put_item(args.profile, args.region, args.destination_table, compact_community_item(item))

    materials = categories["material_libraries"]
    print(f"Cognito user: {args.account} ({user_id})")
    print(f"Jobs copied: {len(categories['jobs'])}")
    print(f"Material Libraries copied: {len(materials)}")
    print(f"  Color palettes: {sum(item_value(item, 'library_intent', 'color_palette') == 'color_palette' for item in materials)}")
    print(f"  Hatch palettes: {sum(item_value(item, 'library_intent') == 'hatch_palette' for item in materials)}")
    print(f"  Processing palettes: {sum(item_value(item, 'library_intent') == 'processing_palette' for item in materials)}")
    print(f"Depth palettes copied: {len(categories['depth_palettes'])}")
    print(f"Holographic recipes copied: {len(categories['holographic_recipes'])}")
    print(f"Community Set records copied: {len(community_items)}")
    print(f"S3 objects copied or refreshed: {copied_objects}")


if __name__ == "__main__":
    main()
