#!/usr/bin/env bash
# Deploy a production-only sign-up email alert without changing Cognito triggers.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"
configure_aws_deployment_credentials

if [ "${1:-}" != "--apply" ]; then
  echo "No alerts changed. Pass --apply to deploy the production sign-up alert." >&2
  exit 2
fi

REGION="${AWS_REGION:-us-east-2}"
WEB_STACK="${SERVERLESS_PRODUCTION_WEB_STACK:-mopa-rasterizer-serverless-production-web}"
COST_STACK="${SERVERLESS_PRODUCTION_COST_GUARD_STACK:-mopa-rasterizer-serverless-production-cost-guard}"
ALERT_STACK="${SERVERLESS_PRODUCTION_SIGNUP_ALERT_STACK:-mopa-rasterizer-serverless-production-signup-alert}"

stack_value() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$1" \
    --query "Stacks[0].$2" --output text
}

aws sts get-caller-identity >/dev/null
POOL_ID="$(stack_value "$WEB_STACK" "Parameters[?ParameterKey=='CognitoUserPoolId'].ParameterValue | [0]")"
CLIENT_ID="$(stack_value "$WEB_STACK" "Outputs[?OutputKey=='CognitoClientId'].OutputValue | [0]")"
OPERATOR_EMAIL="$(stack_value "$COST_STACK" "Parameters[?ParameterKey=='OperatorEmail'].ParameterValue | [0]")"
for value in "$POOL_ID" "$CLIENT_ID" "$OPERATOR_EMAIL"; do
  if [ -z "$value" ] || [ "$value" = "None" ]; then
    echo "Production pool, client, or existing budget-alert email could not be resolved." >&2
    exit 2
  fi
done
if [ -n "${COGNITO_POOL_ID:-}" ] && [ "$POOL_ID" != "$COGNITO_POOL_ID" ]; then
  echo "Production web stack Cognito pool does not match local configuration." >&2
  exit 2
fi

aws cloudformation validate-template --region "$REGION" \
  --template-body "file://$REPO_ROOT/ecs/serverless-production-signup-alert.yaml" >/dev/null
aws cloudformation deploy --region "$REGION" --stack-name "$ALERT_STACK" \
  --template-file "$REPO_ROOT/ecs/serverless-production-signup-alert.yaml" \
  --parameter-overrides \
    "UserPoolId=$POOL_ID" "ProductionClientId=$CLIENT_ID" "OperatorEmail=$OPERATOR_EMAIL" \
  --no-fail-on-empty-changeset

echo "Production sign-up alert deployed. Confirm the new SNS email subscription before expecting alerts."
