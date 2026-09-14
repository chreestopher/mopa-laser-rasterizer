#!/usr/bin/env bash
# Launch one Fargate worker for one already-persisted raster task ID.
set -euo pipefail

if [ "$#" -ne 1 ] || [ -z "$1" ]; then
  echo "Usage: $0 TASK_ID" >&2
  exit 2
fi

TASK_ID="$1"
REGION="${AWS_REGION:-us-east-2}"
export AWS_PROFILE="${DEPLOY_AWS_PROFILE:-mopa-admin}"
STACK_NAME="${FARGATE_STACK_NAME:-mopa-rasterizer-worker}"

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

stack_output() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

CLUSTER_NAME="$(stack_output ClusterName)"
TASK_DEFINITION="$(stack_output TaskDefinitionArn)"
SUBNET_IDS="$(stack_output SubnetIds)"
SECURITY_GROUP_ID="$(stack_output WorkerSecurityGroupId)"
ASSIGN_PUBLIC_IP="$(stack_output AssignPublicIp)"
OVERRIDES="$(printf '{"containerOverrides":[{"name":"raster-worker","command":["python","-u","worker.py","--task-id","%s"]}]}' "$TASK_ID")"
NETWORK="awsvpcConfiguration={subnets=[$SUBNET_IDS],securityGroups=[$SECURITY_GROUP_ID],assignPublicIp=$ASSIGN_PUBLIC_IP}"

aws ecs run-task --region "$REGION" --cluster "$CLUSTER_NAME" \
  --task-definition "$TASK_DEFINITION" --launch-type FARGATE \
  --network-configuration "$NETWORK" --overrides "$OVERRIDES" \
  --tags key=application,value=mopa-laser-rasterizer key=workload,value=worker key=task-id,value="$TASK_ID"
