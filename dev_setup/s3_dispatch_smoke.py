"""Publish one dispatch marker using the app's environment and AWS identity."""

import os
import sys

import boto3


if len(sys.argv) != 2 or not sys.argv[1].strip():
    raise SystemExit("Usage: python s3_dispatch_smoke.py TASK_ID")

bucket = os.environ.get("S3_BUCKET_NAME", "").strip()
if not bucket:
    raise SystemExit("S3_BUCKET_NAME is not configured")

task_id = sys.argv[1].strip()
boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-2")).put_object(
    Bucket=bucket,
    Key=f"jobs/{task_id}/dispatch.ready",
    Body=b"",
    ContentType="application/x-mopa-raster-dispatch",
)
print(task_id)
