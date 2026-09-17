"""Daily, production-only copy of durable account assets to a versioned bucket."""

import os

import boto3


SOURCE_BUCKET = os.environ["SOURCE_BUCKET"]
BACKUP_BUCKET = os.environ["BACKUP_BUCKET"]
DURABLE_KINDS = frozenset({"materials", "holographic-recipes", "holographic-calibrations"})
MAX_SINGLE_COPY_BYTES = 5 * 1024**3

s3 = boto3.client("s3")


def durable_key(key):
    parts = key.split("/", 3)
    return len(parts) == 4 and parts[0] == "users" and bool(parts[1]) and parts[2] in DURABLE_KINDS and bool(parts[3])


def listed_objects(bucket):
    objects = {}
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix="users/"):
        for item in page.get("Contents", []):
            key = item["Key"]
            if durable_key(key):
                objects[key] = item
    return objects


def backup(event, _context):
    dry_run = bool((event or {}).get("dry_run"))
    source = listed_objects(SOURCE_BUCKET)
    destination = listed_objects(BACKUP_BUCKET)
    missing = sorted(destination.keys() - source.keys())
    if destination and not source:
        raise RuntimeError("Source listing is empty while the durable backup has objects; refusing deletion")
    if len(missing) > max(5, len(destination) // 4):
        raise RuntimeError("Too many durable source objects disappeared; refusing backup deletions")

    copied = 0
    copied_bytes = 0
    for key, item in source.items():
        etag = item["ETag"]
        etag_metadata = etag.strip('"')
        modified = item["LastModified"].isoformat()
        size = item["Size"]
        if size > MAX_SINGLE_COPY_BYTES:
            raise RuntimeError("A durable object exceeds the 5 GiB single-copy limit")
        previous = None
        if key in destination:
            previous = s3.head_object(Bucket=BACKUP_BUCKET, Key=key)
        if previous and previous.get("VersionId") not in (None, "null") and previous.get("Metadata", {}).get("backup-source-etag") == etag_metadata and previous["Metadata"].get("backup-source-modified") == modified:
            continue
        if dry_run:
            copied += 1
            copied_bytes += size
            continue

        original = s3.head_object(Bucket=SOURCE_BUCKET, Key=key)
        if original["ETag"] != etag or original["LastModified"].isoformat() != modified:
            raise RuntimeError("A durable source object changed during backup; retry the run")
        metadata = dict(original.get("Metadata") or {})
        metadata.update({"backup-source-etag": etag_metadata, "backup-source-modified": modified})
        request = {
            "Bucket": BACKUP_BUCKET,
            "Key": key,
            "CopySource": {"Bucket": SOURCE_BUCKET, "Key": key},
            "CopySourceIfMatch": etag,
            "MetadataDirective": "REPLACE",
            "TaggingDirective": "REPLACE",
            "Metadata": metadata,
            "ContentType": original.get("ContentType") or "binary/octet-stream",
        }
        for field in ("CacheControl", "ContentDisposition", "ContentEncoding", "ContentLanguage", "Expires"):
            if field in original:
                request[field] = original[field]
        s3.copy_object(**request)
        copied += 1
        copied_bytes += size

    if not dry_run:
        # A delete creates a marker; the previous object remains recoverable for
        # the bucket's 30-day noncurrent-version window. The mass-delete guard
        # above prevents a bad source listing from wiping the current backup.
        for key in missing:
            s3.delete_object(Bucket=BACKUP_BUCKET, Key=key)

    result = {
        "dry_run": dry_run,
        "source_objects": len(source),
        "backup_objects": len(destination),
        "copied": copied,
        "copied_bytes": copied_bytes,
        "deletions": len(missing),
    }
    print(result)
    return result


def handler(event, context):
    return backup(event, context)
