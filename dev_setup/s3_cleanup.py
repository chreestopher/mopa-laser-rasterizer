#!/usr/bin/env python3
"""Delete (or list) one Rasterizer task's private S3 artifact prefix.

This runs inside the application pod so it uses the EC2 instance role through
the normal boto3 credential chain.  It intentionally accepts only UUID task
IDs and only deletes that task's `jobs/<uuid>/` prefix.
"""

import os
import re
import sys

import boto3


TASK_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def main():
    if len(sys.argv) != 2 or not TASK_ID_RE.fullmatch(sys.argv[1]):
        raise SystemExit("Usage: s3_cleanup.py <UUID task id>")

    bucket = os.environ.get("S3_BUCKET_NAME", "").strip()
    if not bucket:
        raise SystemExit("S3_BUCKET_NAME is not configured in this pod.")

    prefix = f"jobs/{sys.argv[1]}/"
    client = boto3.client("s3")
    keys = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        keys.extend(item["Key"] for item in page.get("Contents", []))

    dry_run = os.environ.get("S3_CLEANUP_DRY_RUN", "0") == "1"
    action = "Would delete" if dry_run else "Deleting"
    print(f"{action} {len(keys)} S3 object(s) from s3://{bucket}/{prefix}")
    for key in keys:
        print(f" - {key}")
    if dry_run:
        return
    for start in range(0, len(keys), 1000):
        client.delete_objects(
            Bucket=bucket,
            Delete={"Objects": [{"Key": key} for key in keys[start:start + 1000]], "Quiet": True},
        )


if __name__ == "__main__":
    main()
