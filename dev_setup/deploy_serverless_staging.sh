#!/usr/bin/env bash
# Create/update an AWS-native job data plane and its one-shot worker.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"

REGION="${AWS_REGION:-us-east-2}"
export AWS_PROFILE="${DEPLOY_AWS_PROFILE:-mopa-admin}"
ENVIRONMENT_NAME="${SERVERLESS_ENVIRONMENT_NAME:-serverless-staging}"
ENVIRONMENT_LABEL="${SERVERLESS_ENVIRONMENT_LABEL:-Serverless staging}"
FOUNDATION_STACK="${SERVERLESS_FOUNDATION_STACK:-${SERVERLESS_STAGING_FOUNDATION_STACK:-mopa-rasterizer-serverless-staging}}"
WORKER_STACK="${SERVERLESS_WORKER_STACK:-${SERVERLESS_STAGING_WORKER_STACK:-mopa-rasterizer-serverless-staging-worker}}"
ORCHESTRATION_STACK="${SERVERLESS_ORCHESTRATION_STACK:-${SERVERLESS_STAGING_ORCHESTRATION_STACK:-mopa-rasterizer-serverless-staging-orchestration}}"
PIPE_NAME="${SERVERLESS_PIPE_NAME:-${SERVERLESS_STAGING_PIPE_NAME:-mopa-rasterizer-serverless-staging-to-fargate}}"
CLUSTER_NAME="${SERVERLESS_CLUSTER_NAME:-mopa-rasterizer-serverless-staging}"
WORKER_NAME="${SERVERLESS_WORKER_NAME:-mopa-rasterizer-serverless-staging-worker}"
STATE_MACHINE_NAME="${SERVERLESS_STATE_MACHINE_NAME:-mopa-rasterizer-serverless-staging-job}"
FOUNDATION_TEMPLATE="${SERVERLESS_FOUNDATION_TEMPLATE:-$REPO_ROOT/ecs/serverless-staging-foundation.yaml}"

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
FOUNDATION_PARAMETERS=()
if [ -n "${SERVERLESS_ARTIFACT_BUCKET_NAME:-}" ]; then
  FOUNDATION_PARAMETERS+=("ArtifactBucketName=$SERVERLESS_ARTIFACT_BUCKET_NAME")
fi
if [ -n "${SERVERLESS_RUNTIME_TABLE_NAME:-}" ]; then
  FOUNDATION_PARAMETERS+=("RuntimeTableName=$SERVERLESS_RUNTIME_TABLE_NAME")
fi
if [ -n "${SERVERLESS_JOB_QUEUE_NAME:-}" ]; then
  FOUNDATION_PARAMETERS+=("JobQueueName=$SERVERLESS_JOB_QUEUE_NAME")
fi
if [ -n "${SERVERLESS_DLQ_NAME:-}" ]; then
  FOUNDATION_PARAMETERS+=("DeadLetterQueueName=$SERVERLESS_DLQ_NAME")
fi

FOUNDATION_COMMAND=(aws cloudformation deploy --region "$REGION" --stack-name "$FOUNDATION_STACK"
  --template-file "$FOUNDATION_TEMPLATE" --no-fail-on-empty-changeset)
if [ "${#FOUNDATION_PARAMETERS[@]}" -gt 0 ]; then
  FOUNDATION_COMMAND+=(--parameter-overrides "${FOUNDATION_PARAMETERS[@]}")
fi
"${FOUNDATION_COMMAND[@]}"

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

if [ -n "${SERVERLESS_IMAGE_URI:-${SERVERLESS_STAGING_IMAGE_URI:-}}" ]; then
  IMAGE_URI="${SERVERLESS_IMAGE_URI:-$SERVERLESS_STAGING_IMAGE_URI}"
else
  if [ "${SERVERLESS_ALLOW_LOCAL_IMAGE_BUILD:-true}" != "true" ]; then
    echo "SERVERLESS_IMAGE_URI is required; local worker image builds are disabled for $ENVIRONMENT_LABEL." >&2
    exit 2
  fi
  IMAGE_TAG_PREFIX="${SERVERLESS_IMAGE_TAG_PREFIX:-serverless-staging}"
  LOCAL_IMAGE="${REPOSITORY}:${IMAGE_TAG_PREFIX}-build"
  docker build --pull -t "$LOCAL_IMAGE" "$REPO_ROOT"
  IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$LOCAL_IMAGE")"
  IMAGE_ID="${IMAGE_ID#sha256:}"
  [ -n "$IMAGE_ID" ] || { echo "Could not resolve the built worker image ID." >&2; exit 2; }
  TAG="${IMAGE_TAG_PREFIX}-${IMAGE_ID:0:20}"
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

wait_for_pipe_state() {
  expected="$1"
  attempts=0
  while [ "$attempts" -lt 60 ]; do
    current="$(aws pipes describe-pipe --region "$REGION" --name "$PIPE_NAME" \
      --query CurrentState --output text)"
    [ "$current" = "$expected" ] && return 0
    attempts=$((attempts + 1))
    sleep 2
  done
  echo "Timed out waiting for EventBridge Pipe $PIPE_NAME to reach $expected." >&2
  return 1
}

# CloudFormation deregisters the previous ECS task definition as soon as the
# worker stack advances. Pause queue consumption until the state machine has
# been updated to the new revision, otherwise a job submitted in that small
# deployment window can be consumed against an inactive task definition.
RESUME_PIPE=false
PIPE_STATE="$(aws pipes describe-pipe --region "$REGION" --name "$PIPE_NAME" \
  --query CurrentState --output text 2>/dev/null || true)"
if [ "$PIPE_STATE" = "RUNNING" ] || [ "$PIPE_STATE" = "STARTING" ]; then
    echo "Pausing $ENVIRONMENT_LABEL job dispatch while worker and orchestration revisions update..."
  aws pipes stop-pipe --region "$REGION" --name "$PIPE_NAME" >/dev/null
  wait_for_pipe_state STOPPED
  RESUME_PIPE=true
fi
deployment_exit_notice() {
  status=$?
  if [ "$status" -ne 0 ] && [ "$RESUME_PIPE" = true ]; then
    echo "Deployment failed while $ENVIRONMENT_LABEL dispatch is paused. The pipe remains STOPPED so queued jobs are preserved." >&2
  fi
}
trap deployment_exit_notice EXIT

aws cloudformation deploy --region "$REGION" --stack-name "$WORKER_STACK" \
  --template-file "$REPO_ROOT/ecs/rasterizer-worker.yaml" --capabilities CAPABILITY_IAM \
  --parameter-overrides "ClusterName=$CLUSTER_NAME" \
    "WorkerName=$WORKER_NAME" \
    "ImageUri=$IMAGE_URI" "VpcId=$VPC_ID" "SubnetIds=$SUBNET_IDS" \
    "RedisHost=" "RedisSecurityGroupId=" "S3BucketName=$ARTIFACT_BUCKET" \
    "DynamoDbTableName=$RUNTIME_TABLE" \
    "Cpu=${SERVERLESS_FARGATE_CPU:-${SERVERLESS_STAGING_FARGATE_CPU:-${FARGATE_CPU:-2048}}}" \
    "Memory=${SERVERLESS_FARGATE_MEMORY:-${SERVERLESS_STAGING_FARGATE_MEMORY:-${FARGATE_MEMORY:-4096}}}" \
    "WorkerProcesses=${SERVERLESS_WORKER_PROCESSES:-${SERVERLESS_STAGING_WORKER_PROCESSES:-${FARGATE_WORKER_PROCESSES:-2}}}" \
    "KrasnowProgress=${SERVERLESS_KRASNOW_PROGRESS:-${SERVERLESS_STAGING_KRASNOW_PROGRESS:-true}}" \
    "SourceBlackComponents=${SERVERLESS_SOURCE_BLACK_COMPONENTS:-${SERVERLESS_STAGING_SOURCE_BLACK_COMPONENTS:-true}}" \
    "AssignPublicIp=${FARGATE_ASSIGN_PUBLIC_IP:-DISABLED}" \
  --no-fail-on-empty-changeset

aws cloudformation deploy --region "$REGION" --stack-name "$ORCHESTRATION_STACK" \
  --template-file "$REPO_ROOT/ecs/rasterizer-orchestration.yaml" --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    "PipeName=$PIPE_NAME" \
    "StateMachineName=$STATE_MACHINE_NAME" \
    "ClusterName=$(output "$WORKER_STACK" ClusterName)" \
    "TaskDefinitionArn=$(output "$WORKER_STACK" TaskDefinitionArn)" \
    "SubnetIds=$SUBNET_IDS" \
    "WorkerSecurityGroupId=$(output "$WORKER_STACK" WorkerSecurityGroupId)" \
    "AssignPublicIp=${FARGATE_ASSIGN_PUBLIC_IP:-DISABLED}" \
    "TaskExecutionRoleArn=$(output "$WORKER_STACK" TaskExecutionRoleArn)" \
    "TaskRoleArn=$(output "$WORKER_STACK" TaskRoleArn)" \
    "SqsQueueArn=$QUEUE_ARN" "SqsDlqArn=$DLQ_ARN" "SqsDlqUrl=$DLQ_URL" \
    "RuntimeTableName=$RUNTIME_TABLE" \
    "SpotWorkerAttempts=${SERVERLESS_SPOT_WORKER_ATTEMPTS:-${FARGATE_SPOT_WORKER_ATTEMPTS:-2}}" \
  --no-fail-on-empty-changeset

if [ "$RESUME_PIPE" = true ]; then
  PIPE_STATE="$(aws pipes describe-pipe --region "$REGION" --name "$PIPE_NAME" \
    --query CurrentState --output text)"
  if [ "$PIPE_STATE" != "RUNNING" ]; then
    echo "Resuming $ENVIRONMENT_LABEL job dispatch on the updated orchestration revision..."
    aws pipes start-pipe --region "$REGION" --name "$PIPE_NAME" >/dev/null
    wait_for_pipe_state RUNNING
  fi
  RESUME_PIPE=false
fi

cat <<EOF
$ENVIRONMENT_LABEL worker data plane is ready.
Image: $IMAGE_URI
Artifact bucket: $ARTIFACT_BUCKET
Runtime table: $RUNTIME_TABLE
Queue URL: $QUEUE_URL

Web environment:
  JOB_BACKEND=aws
  JOB_RUNTIME_TABLE_NAME=$RUNTIME_TABLE
  DYNAMODB_TABLE_NAME=$RUNTIME_TABLE
  S3_BUCKET_NAME=$ARTIFACT_BUCKET
  SQS_QUEUE_URL=$QUEUE_URL
  FARGATE_DISPATCH_VIA_S3=false
EOF
