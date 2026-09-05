#!/usr/bin/env bash
# Create/update the isolated AWS job data plane and its one-shot worker.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"

REGION="${AWS_REGION:-us-east-2}"
export AWS_PROFILE="${DEPLOY_AWS_PROFILE:-mopa-admin}"
FOUNDATION_STACK="${SERVERLESS_STAGING_FOUNDATION_STACK:-mopa-rasterizer-serverless-staging}"
WORKER_STACK="${SERVERLESS_STAGING_WORKER_STACK:-mopa-rasterizer-serverless-staging-worker}"
ORCHESTRATION_STACK="${SERVERLESS_STAGING_ORCHESTRATION_STACK:-mopa-rasterizer-serverless-staging-orchestration}"

# Reuse the proven production network by discovery when it is not duplicated
# in .env.aws. Only subnet/VPC placement is shared; all staging data resources
# and task definitions remain isolated.
SOURCE_WORKER_STACK="${FARGATE_STACK_NAME:-mopa-rasterizer-worker}"
if [ -z "${SUBNET_IDS:-}" ]; then
  SUBNET_IDS="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$SOURCE_WORKER_STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='SubnetIds'].OutputValue" --output text)"
fi
if [ -z "${VPC_ID:-}" ] && [ -n "$SUBNET_IDS" ]; then
  FIRST_SUBNET="${SUBNET_IDS%%,*}"
  VPC_ID="$(aws ec2 describe-subnets --region "$REGION" --subnet-ids "$FIRST_SUBNET" \
    --query 'Subnets[0].VpcId' --output text)"
fi
if [ -z "${FARGATE_ASSIGN_PUBLIC_IP:-}" ]; then
  FARGATE_ASSIGN_PUBLIC_IP="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$SOURCE_WORKER_STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='AssignPublicIp'].OutputValue" --output text)"
fi

required=(VPC_ID SUBNET_IDS)
for name in "${required[@]}"; do
  [ -n "${!name:-}" ] || { echo "$name is required." >&2; exit 2; }
done

aws sts get-caller-identity >/dev/null
aws cloudformation deploy --region "$REGION" --stack-name "$FOUNDATION_STACK" \
  --template-file "$REPO_ROOT/ecs/serverless-staging-foundation.yaml" \
  --no-fail-on-empty-changeset

output() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$1" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text
}

ARTIFACT_BUCKET="$(output "$FOUNDATION_STACK" ArtifactBucketName)"
RUNTIME_TABLE="$(output "$FOUNDATION_STACK" RuntimeTableName)"
QUEUE_URL="$(output "$FOUNDATION_STACK" JobQueueUrl)"
QUEUE_ARN="$(output "$FOUNDATION_STACK" JobQueueArn)"
DLQ_URL="$(output "$FOUNDATION_STACK" DeadLetterQueueUrl)"
DLQ_ARN="$(output "$FOUNDATION_STACK" DeadLetterQueueArn)"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
REPOSITORY="${ECR_REPOSITORY:-mopa-laser-rasterizer}"
LIFECYCLE_POLICY="$SCRIPT_DIR/ecr-lifecycle-policy.json"

# Reconcile separate production and staging retention pools before publishing
# a staging image. This prevents frequent staging builds from expiring an image
# still referenced by a production ECS task definition or k3s deployment.
aws ecr put-lifecycle-policy --region "$REGION" \
  --repository-name "$REPOSITORY" \
  --lifecycle-policy-text "file://${LIFECYCLE_POLICY}" >/dev/null

if [ -n "${SERVERLESS_STAGING_IMAGE_URI:-}" ]; then
  IMAGE_URI="$SERVERLESS_STAGING_IMAGE_URI"
else
  LOCAL_IMAGE="${REPOSITORY}:serverless-staging-build"
  docker build --pull -t "$LOCAL_IMAGE" "$REPO_ROOT"
  IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$LOCAL_IMAGE")"
  IMAGE_ID="${IMAGE_ID#sha256:}"
  [ -n "$IMAGE_ID" ] || { echo "Could not resolve the built worker image ID." >&2; exit 2; }
  TAG="serverless-staging-${IMAGE_ID:0:20}"
  IMAGE_URI="${REGISTRY}/${REPOSITORY}:${TAG}"
  if aws ecr describe-images --region "$REGION" --repository-name "$REPOSITORY" \
      --image-ids "imageTag=$TAG" >/dev/null 2>&1; then
    echo "Reusing unchanged immutable worker image: $IMAGE_URI"
  else
    aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"
    docker tag "$LOCAL_IMAGE" "$IMAGE_URI"
    docker push "$IMAGE_URI"
  fi
fi

aws cloudformation deploy --region "$REGION" --stack-name "$WORKER_STACK" \
  --template-file "$REPO_ROOT/ecs/rasterizer-worker.yaml" --capabilities CAPABILITY_IAM \
  --parameter-overrides "ClusterName=mopa-rasterizer-serverless-staging" \
    "WorkerName=mopa-rasterizer-serverless-staging-worker" \
    "ImageUri=$IMAGE_URI" "VpcId=$VPC_ID" "SubnetIds=$SUBNET_IDS" \
    "RedisHost=" "RedisSecurityGroupId=" "S3BucketName=$ARTIFACT_BUCKET" \
    "DynamoDbTableName=$RUNTIME_TABLE" \
    "Cpu=${SERVERLESS_STAGING_FARGATE_CPU:-${FARGATE_CPU:-2048}}" \
    "Memory=${SERVERLESS_STAGING_FARGATE_MEMORY:-${FARGATE_MEMORY:-4096}}" \
    "WorkerProcesses=${SERVERLESS_STAGING_WORKER_PROCESSES:-${FARGATE_WORKER_PROCESSES:-2}}" \
    "KrasnowProgress=${SERVERLESS_STAGING_KRASNOW_PROGRESS:-true}" \
    "KrasnowGratingWins=${SERVERLESS_STAGING_KRASNOW_GRATING_WINS:-true}" \
    "SourceBlackComponents=${SERVERLESS_STAGING_SOURCE_BLACK_COMPONENTS:-true}" \
    "AssignPublicIp=${FARGATE_ASSIGN_PUBLIC_IP:-DISABLED}" \
  --no-fail-on-empty-changeset

aws cloudformation deploy --region "$REGION" --stack-name "$ORCHESTRATION_STACK" \
  --template-file "$REPO_ROOT/ecs/rasterizer-orchestration.yaml" --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    "PipeName=mopa-rasterizer-serverless-staging-to-fargate" \
    "StateMachineName=mopa-rasterizer-serverless-staging-job" \
    "ClusterName=$(output "$WORKER_STACK" ClusterName)" \
    "TaskDefinitionArn=$(output "$WORKER_STACK" TaskDefinitionArn)" \
    "SubnetIds=$SUBNET_IDS" \
    "WorkerSecurityGroupId=$(output "$WORKER_STACK" WorkerSecurityGroupId)" \
    "AssignPublicIp=${FARGATE_ASSIGN_PUBLIC_IP:-DISABLED}" \
    "TaskExecutionRoleArn=$(output "$WORKER_STACK" TaskExecutionRoleArn)" \
    "TaskRoleArn=$(output "$WORKER_STACK" TaskRoleArn)" \
    "SqsQueueArn=$QUEUE_ARN" "SqsDlqArn=$DLQ_ARN" "SqsDlqUrl=$DLQ_URL" \
    "SpotWorkerAttempts=${FARGATE_SPOT_WORKER_ATTEMPTS:-2}" \
  --no-fail-on-empty-changeset

cat <<EOF
Serverless staging worker data plane is ready.
Image: $IMAGE_URI
Artifact bucket: $ARTIFACT_BUCKET
Runtime table: $RUNTIME_TABLE
Queue URL: $QUEUE_URL

Web staging environment:
  JOB_BACKEND=aws
  JOB_RUNTIME_TABLE_NAME=$RUNTIME_TABLE
  DYNAMODB_TABLE_NAME=$RUNTIME_TABLE
  S3_BUCKET_NAME=$ARTIFACT_BUCKET
  SQS_QUEUE_URL=$QUEUE_URL
  FARGATE_DISPATCH_VIA_S3=false
EOF
