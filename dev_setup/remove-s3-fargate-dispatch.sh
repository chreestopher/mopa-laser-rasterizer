#!/usr/bin/env bash
# Retire only the legacy dispatch.ready notification while preserving other bucket notifications.
set -euo pipefail

REGION="${AWS_REGION:-us-east-2}"
export AWS_PROFILE="${DEPLOY_AWS_PROFILE:-mopa-admin}"
: "${S3_BUCKET_NAME:?S3_BUCKET_NAME is required}"

CURRENT_FILE="$(mktemp)"
UPDATED_FILE="$(mktemp)"
trap 'rm -f "$CURRENT_FILE" "$UPDATED_FILE"' EXIT

aws s3api get-bucket-notification-configuration --region "$REGION" \
  --bucket "$S3_BUCKET_NAME" > "$CURRENT_FILE"
python3 - "$CURRENT_FILE" "$UPDATED_FILE" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    configuration = json.load(source)
queues = configuration.get("QueueConfigurations", [])
configuration["QueueConfigurations"] = [
    item for item in queues if item.get("Id") != "mopa-raster-fargate-dispatch"
]
if not configuration["QueueConfigurations"]:
    configuration.pop("QueueConfigurations")
with open(sys.argv[2], "w", encoding="utf-8") as destination:
    json.dump(configuration, destination, separators=(",", ":"))
PY
aws s3api put-bucket-notification-configuration --region "$REGION" \
  --bucket "$S3_BUCKET_NAME" \
  --notification-configuration "file://${UPDATED_FILE}"

echo "Legacy S3 dispatch.ready notification is absent from $S3_BUCKET_NAME."
