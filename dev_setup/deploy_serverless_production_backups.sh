#!/usr/bin/env bash
# Configure production DynamoDB PITR and a separate scheduled durable-asset backup.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"
configure_aws_deployment_credentials

if [ "${1:-}" != "--apply" ]; then
  echo "No backup resources changed. Pass --apply to enable production protection." >&2
  exit 2
fi

REGION="${AWS_REGION:-us-east-2}"
[ "$REGION" = "us-east-2" ] || { echo "The production backup deployment expects us-east-2." >&2; exit 2; }
FOUNDATION_STACK="${SERVERLESS_PRODUCTION_FOUNDATION_STACK:-mopa-rasterizer-serverless-production}"
COST_STACK="${SERVERLESS_PRODUCTION_COST_GUARD_STACK:-mopa-rasterizer-serverless-production-cost-guard}"
BACKUP_STACK="${SERVERLESS_PRODUCTION_BACKUP_STACK:-mopa-rasterizer-serverless-production-backups}"

output() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$1" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text
}

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
[ "$ACCOUNT_ID" = "401716294893" ] || { echo "Refusing backup deployment in unexpected AWS account." >&2; exit 2; }
SOURCE_BUCKET="$(output "$FOUNDATION_STACK" ArtifactBucketName)"
TABLE_NAME="$(output "$FOUNDATION_STACK" RuntimeTableName)"
CODE_BUCKET="$(output "$FOUNDATION_STACK" StaticBucketName)"
TOPIC_ARN="$(aws cloudformation describe-stack-resources --region "$REGION" --stack-name "$COST_STACK" \
  --query "StackResources[?LogicalResourceId=='OperatorNotificationsTopic'].PhysicalResourceId" --output text)"
[ "$SOURCE_BUCKET" = "mopa-laser-rasterizer-artifacts-$ACCOUNT_ID" ] || { echo "Unexpected production artifact bucket." >&2; exit 2; }
[ "$TABLE_NAME" = "mopa-laser-rasterizer-users" ] || { echo "Unexpected production runtime table." >&2; exit 2; }
case "$TOPIC_ARN" in
  "arn:aws:sns:$REGION:$ACCOUNT_ID:"*) ;;
  *) echo "Could not resolve the existing production operator notification topic." >&2; exit 2 ;;
esac
[ -n "$CODE_BUCKET" ] && [ "$CODE_BUCKET" != "None" ] || { echo "Could not resolve the production static bucket." >&2; exit 2; }

aws cloudformation validate-template --region "$REGION" \
  --template-body "file://$REPO_ROOT/ecs/serverless-production-backups.yaml" >/dev/null

BUILD_DIR="$(mktemp -d)"
cleanup() {
  rm -f -- "$BUILD_DIR/function.zip"
  rmdir -- "$BUILD_DIR"
}
trap cleanup EXIT
CODE_SOURCE="$REPO_ROOT/serverless_backup/handler.py" BUILD_DIR="$BUILD_DIR" python3 -c 'import os,zipfile
with zipfile.ZipFile(os.path.join(os.environ["BUILD_DIR"],"function.zip"),"w",zipfile.ZIP_DEFLATED) as archive:
    info=zipfile.ZipInfo("handler.py",(1980,1,1,0,0,0)); info.external_attr=0o644<<16
    with open(os.environ["CODE_SOURCE"],"rb") as source: archive.writestr(info,source.read())'
CODE_DIGEST="$(sha256sum "$BUILD_DIR/function.zip" | cut -d' ' -f1)"
CODE_KEY="durable-backups/function-${CODE_DIGEST}.zip"
aws s3 cp "$BUILD_DIR/function.zip" "s3://$CODE_BUCKET/$CODE_KEY" --region "$REGION" --only-show-errors

aws cloudformation deploy --region "$REGION" --stack-name "$BACKUP_STACK" \
  --template-file "$REPO_ROOT/ecs/serverless-production-backups.yaml" \
  --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset \
  --parameter-overrides \
    "SourceBucketName=$SOURCE_BUCKET" "LambdaCodeBucket=$CODE_BUCKET" \
    "LambdaCodeKey=$CODE_KEY" "OperatorTopicArn=$TOPIC_ARN"

aws dynamodb update-continuous-backups --region "$REGION" --table-name "$TABLE_NAME" \
  --point-in-time-recovery-specification PointInTimeRecoveryEnabled=true,RecoveryPeriodInDays=35 >/dev/null
echo "Production durable backup schedule deployed and 35-day DynamoDB PITR requested."
