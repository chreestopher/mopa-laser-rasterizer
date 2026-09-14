#!/usr/bin/env bash
# Discover the current production network and deploy the one-shot Fargate task.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"
export DEPLOY_AWS_PROFILE="${DEPLOY_AWS_PROFILE:-mopa-admin}"
REGION="${AWS_REGION:-us-east-2}"
K3S_INSTANCE_ID="${K3S_INSTANCE_ID:-}"
S3_BUCKET_NAME="${S3_BUCKET_NAME:-}"
DYNAMODB_TABLE_NAME="${DYNAMODB_TABLE_NAME:-mopa-laser-rasterizer-users}"
SQS_QUEUE_NAME="${SQS_QUEUE_NAME:-mopa-laser-raster-jobs}"
SQS_DLQ_NAME="${SQS_DLQ_NAME:-mopa-laser-raster-jobs-dlq}"

for name in K3S_INSTANCE_ID S3_BUCKET_NAME; do
  if [ -z "${!name:-}" ]; then
    echo "$name is required in .env.aws or the shell environment." >&2
    exit 2
  fi
done

if ! aws configure list-profiles | grep -Fxq "$DEPLOY_AWS_PROFILE"; then
  echo "AWS profile '$DEPLOY_AWS_PROFILE' has not been configured." >&2
  echo "Run: aws configure sso --profile $DEPLOY_AWS_PROFILE --use-device-code" >&2
  exit 1
fi
if ! aws sts get-caller-identity --profile "$DEPLOY_AWS_PROFILE" >/dev/null; then
  echo "Run: aws sso login --profile $DEPLOY_AWS_PROFILE --use-device-code" >&2
  exit 1
fi

REDIS_HOST="$(aws ec2 describe-instances --profile "$DEPLOY_AWS_PROFILE" \
  --region "$REGION" --instance-ids "$K3S_INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].PrivateIpAddress' --output text)"
VPC_ID="$(aws ec2 describe-instances --profile "$DEPLOY_AWS_PROFILE" \
  --region "$REGION" --instance-ids "$K3S_INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].VpcId' --output text)"
REDIS_SECURITY_GROUP_ID="$(aws ec2 describe-instances \
  --profile "$DEPLOY_AWS_PROFILE" --region "$REGION" \
  --instance-ids "$K3S_INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].SecurityGroups[0].GroupId' --output text)"
SUBNET_IDS="$(aws ec2 describe-subnets --profile "$DEPLOY_AWS_PROFILE" \
  --region "$REGION" --filters "Name=vpc-id,Values=${VPC_ID}" \
  Name=default-for-az,Values=true --query 'Subnets[].SubnetId' --output text | tr '\t' ',')"
SQS_QUEUE_URL="$(aws sqs get-queue-url --profile "$DEPLOY_AWS_PROFILE" --region "$REGION" \
  --queue-name "$SQS_QUEUE_NAME" --query QueueUrl --output text)"
SQS_DLQ_URL="$(aws sqs get-queue-url --profile "$DEPLOY_AWS_PROFILE" --region "$REGION" \
  --queue-name "$SQS_DLQ_NAME" --query QueueUrl --output text)"
SQS_QUEUE_ARN="$(aws sqs get-queue-attributes --profile "$DEPLOY_AWS_PROFILE" --region "$REGION" \
  --queue-url "$SQS_QUEUE_URL" --attribute-names QueueArn --query Attributes.QueueArn --output text)"
SQS_DLQ_ARN="$(aws sqs get-queue-attributes --profile "$DEPLOY_AWS_PROFILE" --region "$REGION" \
  --queue-url "$SQS_DLQ_URL" --attribute-names QueueArn --query Attributes.QueueArn --output text)"

for value_name in REDIS_HOST VPC_ID REDIS_SECURITY_GROUP_ID SUBNET_IDS; do
  if [ -z "${!value_name}" ] || [ "${!value_name}" = "None" ]; then
    echo "Could not discover $value_name from K3s instance $K3S_INSTANCE_ID." >&2
    exit 1
  fi
done

export AWS_REGION="$REGION" VPC_ID SUBNET_IDS REDIS_HOST REDIS_SECURITY_GROUP_ID
export REDIS_PORT=30379 REDIS_SSL=false S3_BUCKET_NAME DYNAMODB_TABLE_NAME
export SQS_QUEUE_URL SQS_QUEUE_ARN SQS_DLQ_URL SQS_DLQ_ARN
export FARGATE_ASSIGN_PUBLIC_IP=ENABLED
export FARGATE_SPOT_WORKER_ATTEMPTS="${FARGATE_SPOT_WORKER_ATTEMPTS:-2}"
bash "$SCRIPT_DIR/ensure-s3-fargate-dispatch.sh"
exec bash "$SCRIPT_DIR/deploy_fargate_worker.sh" "$@"
