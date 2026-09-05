#!/usr/bin/env bash
# Build/push the existing image and register its one-shot Fargate task.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"
REGION="${AWS_REGION:-us-east-2}"
export AWS_PROFILE="${DEPLOY_AWS_PROFILE:-mopa-admin}"
STACK_NAME="${FARGATE_STACK_NAME:-mopa-rasterizer-worker}"
REPOSITORY="${ECR_REPOSITORY:-mopa-laser-rasterizer}"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
TEMPLATE="$REPO_ROOT/ecs/rasterizer-worker.yaml"
ORCHESTRATION_TEMPLATE="$REPO_ROOT/ecs/rasterizer-orchestration.yaml"
ORCHESTRATION_STACK_NAME="${FARGATE_ORCHESTRATION_STACK_NAME:-mopa-rasterizer-orchestration}"

required=(VPC_ID SUBNET_IDS REDIS_HOST REDIS_SECURITY_GROUP_ID S3_BUCKET_NAME DYNAMODB_TABLE_NAME SQS_QUEUE_ARN SQS_DLQ_ARN SQS_DLQ_URL)
for name in "${required[@]}"; do
  if [ -z "${!name:-}" ]; then
    echo "$name is required." >&2
    exit 2
  fi
done

if ! aws configure list-profiles | grep -Fxq "$AWS_PROFILE"; then
  echo "AWS profile '$AWS_PROFILE' has not been configured." >&2
  echo "Run: aws configure sso --profile $AWS_PROFILE --use-device-code" >&2
  exit 1
fi

if ! ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"; then
  echo "AWS profile '$AWS_PROFILE' is not authenticated." >&2
  echo "Run: aws sso login --profile $AWS_PROFILE --use-device-code" >&2
  exit 1
fi
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
if [ -n "${FARGATE_IMAGE_URI:-}" ]; then
  IMAGE_URI="$FARGATE_IMAGE_URI"
  case "$IMAGE_URI" in
    "${REGISTRY}/${REPOSITORY}:"*) ;;
    *) echo "FARGATE_IMAGE_URI must reference ${REGISTRY}/${REPOSITORY}." >&2; exit 2 ;;
  esac
elif [ "$#" -ge 1 ]; then
  IMAGE_TAG="$1"
  IMAGE_URI="${REGISTRY}/${REPOSITORY}:${IMAGE_TAG}"
else
  GIT_REV="$(git -C "$REPO_ROOT" rev-parse --short=12 HEAD)"
  IMAGE_TAG="${GIT_REV}-$(date -u +%Y%m%d%H%M%S)"
  IMAGE_URI="${REGISTRY}/${REPOSITORY}:${IMAGE_TAG}"
fi

if ! aws ecr describe-repositories --region "$REGION" --repository-names "$REPOSITORY" >/dev/null 2>&1; then
  aws ecr create-repository --region "$REGION" --repository-name "$REPOSITORY" \
    --image-tag-mutability IMMUTABLE --image-scanning-configuration scanOnPush=true >/dev/null
fi
if [ -z "${FARGATE_IMAGE_URI:-}" ]; then
  aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"
  docker build --pull -t "$IMAGE_URI" "$REPO_ROOT"
  docker push "$IMAGE_URI"
else
  aws ecr describe-images --region "$REGION" --repository-name "$REPOSITORY" \
    --image-ids "imageTag=${IMAGE_URI##*:}" >/dev/null
fi

parameters=(
  "ImageUri=$IMAGE_URI"
  "VpcId=$VPC_ID"
  "SubnetIds=$SUBNET_IDS"
  "RedisHost=$REDIS_HOST"
  "RedisPort=${REDIS_PORT:-6379}"
  "RedisSecurityGroupId=$REDIS_SECURITY_GROUP_ID"
  "RedisSsl=${REDIS_SSL:-false}"
  "RedisPasswordSecretArn=${REDIS_PASSWORD_SECRET_ARN:-}"
  "S3BucketName=$S3_BUCKET_NAME"
  "DynamoDbTableName=$DYNAMODB_TABLE_NAME"
  "Cpu=${FARGATE_CPU:-1024}"
  "Memory=${FARGATE_MEMORY:-4096}"
  "WorkerProcesses=${FARGATE_WORKER_PROCESSES:-1}"
  "SourceBlackComponents=${FARGATE_SOURCE_BLACK_COMPONENTS:-false}"
  "AssignPublicIp=${FARGATE_ASSIGN_PUBLIC_IP:-DISABLED}"
)

aws cloudformation deploy --region "$REGION" --stack-name "$STACK_NAME" \
  --template-file "$TEMPLATE" --capabilities CAPABILITY_IAM \
  --parameter-overrides "${parameters[@]}" --no-fail-on-empty-changeset

stack_output() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

aws cloudformation deploy --region "$REGION" --stack-name "$ORCHESTRATION_STACK_NAME" \
  --template-file "$ORCHESTRATION_TEMPLATE" --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    "ClusterName=$(stack_output ClusterName)" \
    "TaskDefinitionArn=$(stack_output TaskDefinitionArn)" \
    "SubnetIds=$SUBNET_IDS" \
    "WorkerSecurityGroupId=$(stack_output WorkerSecurityGroupId)" \
    "AssignPublicIp=${FARGATE_ASSIGN_PUBLIC_IP:-DISABLED}" \
    "TaskExecutionRoleArn=$(stack_output TaskExecutionRoleArn)" \
    "TaskRoleArn=$(stack_output TaskRoleArn)" \
    "SqsQueueArn=$SQS_QUEUE_ARN" \
    "SqsDlqArn=$SQS_DLQ_ARN" \
    "SqsDlqUrl=$SQS_DLQ_URL" \
    "SpotWorkerAttempts=${FARGATE_SPOT_WORKER_ATTEMPTS:-2}" \
  --no-fail-on-empty-changeset

echo "Fargate worker task registered: $IMAGE_URI"
echo "SQS-to-Fargate orchestration deployed: $ORCHESTRATION_STACK_NAME"
echo "Worker capacity policy: ${FARGATE_SPOT_WORKER_ATTEMPTS:-2} Fargate Spot attempt(s), then one on-demand attempt"
echo "Run a persisted job with: ./dev_setup/run_fargate_worker.sh TASK_ID"
