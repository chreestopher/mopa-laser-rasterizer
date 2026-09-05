#!/usr/bin/env bash
# Idempotently seed isolated serverless staging with one production user's data.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"

ACCOUNT="${1:?Usage: bash dev_setup/copy-user-data-to-serverless-staging.sh USERNAME [JOB_LIMIT]}"
JOB_LIMIT="${2:-10}"
REGION="${AWS_REGION:-us-east-2}"
PROFILE="${DEPLOY_AWS_PROFILE:-mopa-admin}"
FOUNDATION_STACK="${SERVERLESS_STAGING_FOUNDATION_STACK:-mopa-rasterizer-serverless-staging}"

for name in COGNITO_POOL_ID S3_BUCKET_NAME DYNAMODB_TABLE_NAME; do
  [[ -n "${!name:-}" ]] || { echo "$name is required in .env.aws" >&2; exit 2; }
done

output() {
  aws --profile "$PROFILE" cloudformation describe-stacks --region "$REGION" \
    --stack-name "$FOUNDATION_STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

DESTINATION_BUCKET="$(output ArtifactBucketName)"
DESTINATION_TABLE="$(output RuntimeTableName)"

python3 "$SCRIPT_DIR/copy_user_data_to_serverless_staging.py" "$ACCOUNT" \
  --region "$REGION" --profile "$PROFILE" --user-pool-id "$COGNITO_POOL_ID" \
  --source-table "$DYNAMODB_TABLE_NAME" --source-bucket "$S3_BUCKET_NAME" \
  --destination-table "$DESTINATION_TABLE" --destination-bucket "$DESTINATION_BUCKET" \
  --job-limit "$JOB_LIMIT" --include-community-set
