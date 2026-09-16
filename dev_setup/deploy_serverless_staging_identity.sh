#!/usr/bin/env bash
# Create the staging-only, admin-invite-only Cognito pool. Does not cut over the web app.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"
configure_aws_deployment_credentials

if [ "${1:-}" != "--apply" ]; then
  echo "No identity resources changed. Pass --apply to create the isolated staging pool." >&2
  exit 2
fi

REGION="${AWS_REGION:-us-east-2}"
IDENTITY_STACK="${SERVERLESS_STAGING_IDENTITY_STACK:-mopa-rasterizer-serverless-staging-identity}"
PRODUCTION_WEB_STACK="${SERVERLESS_PRODUCTION_WEB_STACK:-mopa-rasterizer-serverless-production-web}"

aws sts get-caller-identity >/dev/null
aws cloudformation validate-template --region "$REGION" \
  --template-body "file://$REPO_ROOT/ecs/serverless-staging-identity.yaml" >/dev/null
aws cloudformation deploy --region "$REGION" --stack-name "$IDENTITY_STACK" \
  --template-file "$REPO_ROOT/ecs/serverless-staging-identity.yaml" \
  --no-fail-on-empty-changeset

new_pool="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$IDENTITY_STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue | [0]" --output text)"
production_pool="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$PRODUCTION_WEB_STACK" \
  --query "Stacks[0].Parameters[?ParameterKey=='CognitoUserPoolId'].ParameterValue | [0]" --output text)"
if [ -z "$new_pool" ] || [ "$new_pool" = "None" ] || [ "$new_pool" = "$production_pool" ]; then
  echo "Isolated pool could not be verified as distinct from production." >&2
  exit 1
fi
signup_policy="$(aws cognito-idp describe-user-pool --region "$REGION" --user-pool-id "$new_pool" \
  --query 'UserPool.AdminCreateUserConfig.AllowAdminCreateUserOnly' --output text)"
if [ "$signup_policy" != "True" ]; then
  echo "New staging pool unexpectedly permits self-registration; do not cut over." >&2
  exit 1
fi
echo "Isolated staging pool created and verified as invite-only. Staging web still uses its existing pool until explicitly cut over."
