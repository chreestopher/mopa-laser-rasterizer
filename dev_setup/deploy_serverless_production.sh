#!/usr/bin/env bash
# Deploy the production serverless worker path sequentially without rebuilding locally.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"
source "$SCRIPT_DIR/serverless-production-guard.sh"

if [ "${1:-}" != "--apply" ]; then
  echo "Refusing to mutate production without the explicit --apply argument." >&2
  echo "Run local validation first: bash dev_setup/validate_serverless_production_deployment.sh" >&2
  exit 2
fi
serverless_production_guard

required=(SERVERLESS_PRODUCTION_IMAGE_URI S3_BUCKET_NAME DYNAMODB_TABLE_NAME)
for name in "${required[@]}"; do
  [ -n "${!name:-}" ] || { echo "$name is required in .env.aws or the shell environment." >&2; exit 2; }
done

if [[ ! "$SERVERLESS_PRODUCTION_IMAGE_URI" =~ @sha256:[0-9a-f]{64}$ ]]; then
  echo "SERVERLESS_PRODUCTION_IMAGE_URI must use an immutable @sha256 digest, not a mutable tag." >&2
  exit 2
fi

case "$S3_BUCKET_NAME $DYNAMODB_TABLE_NAME" in
  *serverless-staging*)
    echo "Refusing to use a staging bucket or table for production." >&2
    exit 2
    ;;
esac

# The retained production table is passed into CloudFormation rather than
# created by it, so reconcile selective job-record TTL explicitly. The helper
# aborts if any durable Material Library or palette record contains expires_at.
bash "$SCRIPT_DIR/ensure_dynamodb_job_ttl.sh" --apply "$DYNAMODB_TABLE_NAME"

export SERVERLESS_ENVIRONMENT_NAME=serverless-production
export SERVERLESS_ENVIRONMENT_LABEL="Serverless production"
export SERVERLESS_FOUNDATION_STACK="${SERVERLESS_PRODUCTION_FOUNDATION_STACK:-mopa-rasterizer-serverless-production}"
export SERVERLESS_WORKER_STACK="${SERVERLESS_PRODUCTION_WORKER_STACK:-mopa-rasterizer-serverless-production-worker}"
export SERVERLESS_ORCHESTRATION_STACK="${SERVERLESS_PRODUCTION_ORCHESTRATION_STACK:-mopa-rasterizer-serverless-production-orchestration}"
export SERVERLESS_PIPE_NAME="${SERVERLESS_PRODUCTION_PIPE_NAME:-mopa-rasterizer-serverless-production-to-fargate}"
export SERVERLESS_CLUSTER_NAME="${SERVERLESS_PRODUCTION_CLUSTER_NAME:-mopa-rasterizer-serverless-production}"
export SERVERLESS_WORKER_NAME="${SERVERLESS_PRODUCTION_WORKER_NAME:-mopa-rasterizer-serverless-production-worker}"
export SERVERLESS_STATE_MACHINE_NAME="${SERVERLESS_PRODUCTION_STATE_MACHINE_NAME:-mopa-rasterizer-serverless-production-job}"
export SERVERLESS_FOUNDATION_TEMPLATE="$SCRIPT_DIR/../ecs/serverless-production-foundation.yaml"
export SERVERLESS_ARTIFACT_BUCKET_NAME="$S3_BUCKET_NAME"
export SERVERLESS_RUNTIME_TABLE_NAME="$DYNAMODB_TABLE_NAME"
export SERVERLESS_JOB_QUEUE_NAME="${SERVERLESS_PRODUCTION_JOB_QUEUE_NAME:-mopa-rasterizer-serverless-production-jobs}"
export SERVERLESS_DLQ_NAME="${SERVERLESS_PRODUCTION_DLQ_NAME:-mopa-rasterizer-serverless-production-jobs-dlq}"
export SERVERLESS_IMAGE_URI="$SERVERLESS_PRODUCTION_IMAGE_URI"
export SERVERLESS_ALLOW_LOCAL_IMAGE_BUILD=false
export SERVERLESS_FARGATE_CPU="${SERVERLESS_PRODUCTION_FARGATE_CPU:-2048}"
export SERVERLESS_FARGATE_MEMORY="${SERVERLESS_PRODUCTION_FARGATE_MEMORY:-4096}"
export SERVERLESS_WORKER_PROCESSES="${SERVERLESS_PRODUCTION_WORKER_PROCESSES:-1}"
export SERVERLESS_KRASNOW_PROGRESS="${SERVERLESS_PRODUCTION_KRASNOW_PROGRESS:-true}"
export SERVERLESS_SOURCE_BLACK_COMPONENTS="${SERVERLESS_PRODUCTION_SOURCE_BLACK_COMPONENTS:-true}"
export SERVERLESS_SPOT_WORKER_ATTEMPTS="${SERVERLESS_PRODUCTION_SPOT_WORKER_ATTEMPTS:-2}"

exec bash "$SCRIPT_DIR/deploy_serverless_staging.sh"
