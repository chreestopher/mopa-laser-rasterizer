#!/usr/bin/env bash
# Route zero-byte S3 dispatch markers to the raster SQS queue.
set -euo pipefail

REGION="${AWS_REGION:-us-east-2}"
export AWS_PROFILE="${DEPLOY_AWS_PROFILE:-mopa-admin}"
: "${S3_BUCKET_NAME:?S3_BUCKET_NAME is required}"
: "${SQS_QUEUE_URL:?SQS_QUEUE_URL is required}"
: "${SQS_QUEUE_ARN:?SQS_QUEUE_ARN is required}"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
POLICY_FILE="$(mktemp)"
ATTRIBUTES_FILE="$(mktemp)"
NOTIFICATION_FILE="$(mktemp)"
trap 'rm -f "$POLICY_FILE" "$ATTRIBUTES_FILE" "$NOTIFICATION_FILE"' EXIT

cat > "$POLICY_FILE" <<JSON
{"Version":"2012-10-17","Statement":[{"Sid":"AllowRasterDispatchFromS3","Effect":"Allow","Principal":{"Service":"s3.amazonaws.com"},"Action":"sqs:SendMessage","Resource":"${SQS_QUEUE_ARN}","Condition":{"StringEquals":{"aws:SourceAccount":"${ACCOUNT_ID}"},"ArnLike":{"aws:SourceArn":"arn:aws:s3:::${S3_BUCKET_NAME}"}}}]}
JSON
python3 - "$POLICY_FILE" "$ATTRIBUTES_FILE" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    policy = source.read()
with open(sys.argv[2], "w", encoding="utf-8") as destination:
    json.dump({"Policy": policy}, destination)
PY
aws sqs set-queue-attributes --region "$REGION" --queue-url "$SQS_QUEUE_URL" \
  --attributes "file://${ATTRIBUTES_FILE}"

cat > "$NOTIFICATION_FILE" <<JSON
{"QueueConfigurations":[{"Id":"mopa-raster-fargate-dispatch","QueueArn":"${SQS_QUEUE_ARN}","Events":["s3:ObjectCreated:Put"],"Filter":{"Key":{"FilterRules":[{"Name":"prefix","Value":"jobs/"},{"Name":"suffix","Value":"dispatch.ready"}]}}}]}
JSON
aws s3api put-bucket-notification-configuration --region "$REGION" \
  --bucket "$S3_BUCKET_NAME" \
  --notification-configuration "file://${NOTIFICATION_FILE}"

echo "S3 dispatch markers now route to $SQS_QUEUE_ARN."
