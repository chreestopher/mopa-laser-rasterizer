#!/usr/bin/env bash
# Deploy the account-level monthly spend guard for serverless production.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"

if [ "${1:-}" != "--apply" ]; then
  echo "No cost controls changed. Pass --apply to deploy the production monthly spend guard." >&2
  exit 2
fi

REGION="${AWS_REGION:-us-east-2}"
export AWS_PROFILE="${DEPLOY_AWS_PROFILE:-mopa-admin}"
FOUNDATION_STACK="${SERVERLESS_PRODUCTION_FOUNDATION_STACK:-mopa-rasterizer-serverless-production}"
ORCHESTRATION_STACK="${SERVERLESS_PRODUCTION_ORCHESTRATION_STACK:-mopa-rasterizer-serverless-production-orchestration}"
STAGING_FOUNDATION_STACK="${SERVERLESS_STAGING_FOUNDATION_STACK:-mopa-rasterizer-serverless-staging}"
STAGING_ORCHESTRATION_STACK="${SERVERLESS_STAGING_ORCHESTRATION_STACK:-mopa-rasterizer-serverless-staging-orchestration}"
COST_STACK="${SERVERLESS_PRODUCTION_COST_GUARD_STACK:-mopa-rasterizer-serverless-production-cost-guard}"
BUDGET_NAME="${SERVERLESS_MONTHLY_BUDGET_NAME:-mopa-rasterizer-monthly-spend}"
MONTHLY_LIMIT="${SERVERLESS_MONTHLY_BUDGET_USD:-100}"
WARNING_PERCENT="${SERVERLESS_BUDGET_WARNING_PERCENT:-75}"
OPERATOR_EMAIL="${SERVERLESS_BUDGET_EMAIL:-${SERVERLESS_ADMIN_EMAIL:-${IDENTITY_CENTER_ADMIN_EMAIL:-}}}"
PRODUCTION_PUBLIC_URL="${SERVERLESS_PRODUCTION_PUBLIC_URL:-https://${SERVERLESS_PRODUCTION_HOSTNAME:-}}"
STAGING_PUBLIC_URL="${SERVERLESS_STAGING_PUBLIC_URL:-https://${SERVERLESS_STAGING_HOSTNAME:-}}"
FUNCTION_NAME="${SERVERLESS_PRODUCTION_COST_GUARD_FUNCTION:-mopa-rasterizer-production-cost-guard}"

[ -n "$OPERATOR_EMAIL" ] || { echo "SERVERLESS_BUDGET_EMAIL or an admin email is required." >&2; exit 2; }
[ -n "$PRODUCTION_PUBLIC_URL" ] || { echo "SERVERLESS_PRODUCTION_PUBLIC_URL or SERVERLESS_PRODUCTION_HOSTNAME is required." >&2; exit 2; }
[ -n "$STAGING_PUBLIC_URL" ] || { echo "SERVERLESS_STAGING_PUBLIC_URL or SERVERLESS_STAGING_HOSTNAME is required." >&2; exit 2; }

output() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$1" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text
}

aws sts get-caller-identity >/dev/null
BUCKET="$(output "$FOUNDATION_STACK" StaticBucketName 2>/dev/null || output "$FOUNDATION_STACK" ArtifactBucketName)"
PRODUCTION_TABLE="$(output "$FOUNDATION_STACK" RuntimeTableName)"
PRODUCTION_PIPE_ARN="$(output "$ORCHESTRATION_STACK" PipeArn)"
PRODUCTION_PIPE_NAME="${PRODUCTION_PIPE_ARN##*/}"
STAGING_TABLE="$(output "$STAGING_FOUNDATION_STACK" RuntimeTableName)"
STAGING_PIPE_ARN="$(output "$STAGING_ORCHESTRATION_STACK" PipeArn)"
STAGING_PIPE_NAME="${STAGING_PIPE_ARN##*/}"
BUILD_DIR="$(mktemp -d)"
trap 'rm -rf -- "$BUILD_DIR"' EXIT
cp "$REPO_ROOT/serverless_cost_guard/handler.py" "$BUILD_DIR/handler.py"
BUILD_DIR="$BUILD_DIR" python3 -c 'import os,zipfile
root=os.environ["BUILD_DIR"]
with zipfile.ZipFile(os.path.join(root,"function.zip"),"w",zipfile.ZIP_DEFLATED) as archive:
    info=zipfile.ZipInfo("handler.py",(1980,1,1,0,0,0)); info.external_attr=0o644<<16
    archive.writestr(info,open(os.path.join(root,"handler.py"),"rb").read())'
CODE_DIGEST="$(sha256sum "$BUILD_DIR/function.zip" | cut -d' ' -f1)"
CODE_KEY="cost-guard/function-${CODE_DIGEST}.zip"
aws s3 cp "$BUILD_DIR/function.zip" "s3://$BUCKET/$CODE_KEY" --region "$REGION" --only-show-errors

aws cloudformation deploy --region "$REGION" --stack-name "$COST_STACK" \
  --template-file "$REPO_ROOT/ecs/serverless-cost-guard.yaml" \
  --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset \
  --parameter-overrides \
    "BudgetName=$BUDGET_NAME" "MonthlyLimitUsd=$MONTHLY_LIMIT" \
    "WarningThresholdPercent=$WARNING_PERCENT" "OperatorEmail=$OPERATOR_EMAIL" \
    "ProductionPublicUrl=$PRODUCTION_PUBLIC_URL" "ProductionRuntimeTableName=$PRODUCTION_TABLE" \
    "ProductionPipeName=$PRODUCTION_PIPE_NAME" "StagingPublicUrl=$STAGING_PUBLIC_URL" \
    "StagingRuntimeTableName=$STAGING_TABLE" "StagingPipeName=$STAGING_PIPE_NAME" \
    "LambdaCodeBucket=$BUCKET" "LambdaCodeKey=$CODE_KEY" "FunctionName=$FUNCTION_NAME"

echo "Cost guard deployed. Confirm the SNS subscription email sent to $OPERATOR_EMAIL."
