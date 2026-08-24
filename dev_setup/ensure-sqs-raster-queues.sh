#!/usr/bin/env bash
# Create or reconcile only the raster job SQS queue and its dead-letter queue.
set -euo pipefail

REGION="${AWS_REGION:-us-east-2}"
export AWS_PROFILE="${DEPLOY_AWS_PROFILE:-mopa-admin}"
SQS_QUEUE_NAME="${SQS_QUEUE_NAME:-mopa-laser-raster-jobs}"
SQS_DLQ_NAME="${SQS_DLQ_NAME:-mopa-laser-raster-jobs-dlq}"
SQS_MAX_RECEIVE_COUNT="${SQS_MAX_RECEIVE_COUNT:-3}"
SQS_ATTRIBUTES_FILE="$(mktemp)"
SQS_DLQ_ATTRIBUTES_FILE="$(mktemp)"
trap 'rm -f "$SQS_ATTRIBUTES_FILE" "$SQS_DLQ_ATTRIBUTES_FILE"' EXIT

if ! aws configure list-profiles | grep -Fxq "$AWS_PROFILE"; then
  echo "AWS profile '$AWS_PROFILE' has not been configured." >&2
  echo "Run: aws configure sso --profile $AWS_PROFILE --use-device-code" >&2
  exit 1
fi
if ! aws sts get-caller-identity >/dev/null; then
  echo "AWS profile '$AWS_PROFILE' is not authenticated." >&2
  echo "Run: aws sso login --profile $AWS_PROFILE --use-device-code" >&2
  exit 1
fi

ensure_queue_url() {
  queue_name="$1"
  queue_url="$(aws sqs get-queue-url --region "$REGION" \
    --queue-name "$queue_name" --query QueueUrl --output text 2>/dev/null || true)"
  if [ -z "$queue_url" ] || [ "$queue_url" = "None" ]; then
    if ! queue_url="$(aws sqs create-queue --region "$REGION" \
      --queue-name "$queue_name" --query QueueUrl --output text)"; then
      return 1
    fi
  fi
  if [ -z "$queue_url" ] || [ "$queue_url" = "None" ]; then
    echo "AWS did not return a queue URL for $queue_name." >&2
    return 1
  fi
  printf '%s' "$queue_url"
}

SQS_DLQ_URL="$(ensure_queue_url "$SQS_DLQ_NAME")"
SQS_DLQ_ARN="$(aws sqs get-queue-attributes --region "$REGION" \
  --queue-url "$SQS_DLQ_URL" --attribute-names QueueArn \
  --query 'Attributes.QueueArn' --output text)"
SQS_QUEUE_URL="$(ensure_queue_url "$SQS_QUEUE_NAME")"
SQS_QUEUE_ARN="$(aws sqs get-queue-attributes --region "$REGION" \
  --queue-url "$SQS_QUEUE_URL" --attribute-names QueueArn \
  --query 'Attributes.QueueArn' --output text)"

printf '{"SqsManagedSseEnabled":"true","VisibilityTimeout":"7200","MessageRetentionPeriod":"604800","ReceiveMessageWaitTimeSeconds":"20","RedrivePolicy":"{\\"deadLetterTargetArn\\":\\"%s\\",\\"maxReceiveCount\\":\\"%s\\"}"}' \
  "$SQS_DLQ_ARN" "$SQS_MAX_RECEIVE_COUNT" > "$SQS_ATTRIBUTES_FILE"
printf '{"SqsManagedSseEnabled":"true","MessageRetentionPeriod":"1209600","RedriveAllowPolicy":"{\\"redrivePermission\\":\\"byQueue\\",\\"sourceQueueArns\\":[\\"%s\\"]}"}' \
  "$SQS_QUEUE_ARN" > "$SQS_DLQ_ATTRIBUTES_FILE"

aws sqs set-queue-attributes --region "$REGION" --queue-url "$SQS_QUEUE_URL" \
  --attributes "file://${SQS_ATTRIBUTES_FILE}"
aws sqs set-queue-attributes --region "$REGION" --queue-url "$SQS_DLQ_URL" \
  --attributes "file://${SQS_DLQ_ATTRIBUTES_FILE}"
aws sqs tag-queue --region "$REGION" --queue-url "$SQS_QUEUE_URL" \
  --tags application=mopa-laser-rasterizer,workload=raster-worker,purpose=jobs
aws sqs tag-queue --region "$REGION" --queue-url "$SQS_DLQ_URL" \
  --tags application=mopa-laser-rasterizer,workload=raster-worker,purpose=dead-letter

printf 'AWS_REGION=%s\nSQS_QUEUE_NAME=%s\nSQS_QUEUE_URL=%s\nSQS_QUEUE_ARN=%s\nSQS_DLQ_NAME=%s\nSQS_DLQ_URL=%s\nSQS_DLQ_ARN=%s\n' \
  "$REGION" "$SQS_QUEUE_NAME" "$SQS_QUEUE_URL" "$SQS_QUEUE_ARN" \
  "$SQS_DLQ_NAME" "$SQS_DLQ_URL" "$SQS_DLQ_ARN"
