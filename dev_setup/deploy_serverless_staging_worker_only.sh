#!/usr/bin/env bash
# Update only the existing serverless-staging worker and its orchestration task reference.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"
REGION="${AWS_REGION:-us-east-2}"
configure_aws_deployment_credentials
WORKER_STACK="mopa-rasterizer-serverless-staging-worker"
ORCHESTRATION_STACK="mopa-rasterizer-serverless-staging-orchestration"
FOUNDATION_STACK="mopa-rasterizer-serverless-staging"
REPOSITORY="${ECR_REPOSITORY:-mopa-laser-rasterizer}"

for stack in "$WORKER_STACK" "$ORCHESTRATION_STACK"; do
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$stack" >/dev/null
done

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
LOCAL_IMAGE="${REPOSITORY}:serverless-staging-worker-only-build"
docker build --pull -t "$LOCAL_IMAGE" "$REPO_ROOT"
IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$LOCAL_IMAGE")"
IMAGE_ID="${IMAGE_ID#sha256:}"
TAG="serverless-staging-${IMAGE_ID:0:20}"
IMAGE_URI="${REGISTRY}/${REPOSITORY}:${TAG}"

if aws ecr describe-images --region "$REGION" --repository-name "$REPOSITORY" \
    --image-ids "imageTag=$TAG" >/dev/null 2>&1; then
  echo "Reusing unchanged immutable staging image: $IMAGE_URI"
else
  aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"
  docker tag "$LOCAL_IMAGE" "$IMAGE_URI"
  docker push "$IMAGE_URI"
fi

aws cloudformation deploy --region "$REGION" --stack-name "$WORKER_STACK" \
  --template-file "$REPO_ROOT/ecs/rasterizer-worker.yaml" --capabilities CAPABILITY_IAM \
  --parameter-overrides "ImageUri=$IMAGE_URI" \
  --no-fail-on-empty-changeset

TASK_DEFINITION_ARN="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$WORKER_STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='TaskDefinitionArn'].OutputValue" --output text)"
QUEUE_URL="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$FOUNDATION_STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='JobQueueUrl'].OutputValue" --output text)"
aws cloudformation deploy --region "$REGION" --stack-name "$ORCHESTRATION_STACK" \
  --template-file "$REPO_ROOT/ecs/rasterizer-orchestration.yaml" --capabilities CAPABILITY_IAM \
  --parameter-overrides "TaskDefinitionArn=$TASK_DEFINITION_ARN" "SqsQueueUrl=$QUEUE_URL" \
  --no-fail-on-empty-changeset

echo "Serverless staging worker-only update complete: $IMAGE_URI"
