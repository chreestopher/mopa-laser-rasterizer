#!/usr/bin/env bash
# Reconcile staging-only Cognito Hosted UI (classic) CSS customization.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"

REGION="${AWS_REGION:-us-east-2}"
export AWS_PROFILE="${DEPLOY_AWS_PROFILE:-mopa-admin}"
POOL_ID="${COGNITO_POOL_ID:?COGNITO_POOL_ID is required}"
WEB_STACK="${SERVERLESS_STAGING_WEB_STACK:-mopa-rasterizer-serverless-staging-web}"
CLIENT_ID="${SERVERLESS_STAGING_COGNITO_CLIENT_ID:-}"
CSS_FILE="$REPO_ROOT/ecs/cognito-staging-classic.css"

if [ -z "$CLIENT_ID" ]; then
  CLIENT_ID="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$WEB_STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='CognitoClientId'].OutputValue" --output text)"
fi
[ -n "$CLIENT_ID" ] && [ "$CLIENT_ID" != "None" ] || {
  echo "Could not resolve the serverless staging Cognito app client." >&2
  exit 2
}
[ -f "$CSS_FILE" ] || { echo "Missing Cognito CSS: $CSS_FILE" >&2; exit 2; }

CSS_BYTES="$(wc -c < "$CSS_FILE" | tr -d ' ')"
[ "$CSS_BYTES" -le 3072 ] || {
  echo "Classic Cognito CSS exceeds the 3 KB service limit: $CSS_BYTES bytes" >&2
  exit 2
}

CSS_CONTENT="$(tr '\n' ' ' < "$CSS_FILE")"
aws cognito-idp set-ui-customization --region "$REGION" \
  --user-pool-id "$POOL_ID" --client-id "$CLIENT_ID" --css "$CSS_CONTENT" >/dev/null

echo "Staging Cognito classic branding applied to app client: $CLIENT_ID"
