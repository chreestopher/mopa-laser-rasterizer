#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Load workstation-specific AWS identifiers from the ignored .env.aws file.
# shellcheck source=dev_setup/load-aws-env.sh
source "$SCRIPT_DIR/load-aws-env.sh"

REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-2}}"
PROFILE="${DEPLOY_AWS_PROFILE:-${AWS_PROFILE:-}}"
USER_POOL_ID="${COGNITO_USER_POOL_ID:-${COGNITO_POOL_ID:-}}"
COGNITO_DOMAIN_VALUE="${COGNITO_DOMAIN:-}"
DOMAIN_PREFIX="${COGNITO_DOMAIN_PREFIX:-}"
if [[ -z "$DOMAIN_PREFIX" && -n "$COGNITO_DOMAIN_VALUE" ]]; then
  DOMAIN_PREFIX="${COGNITO_DOMAIN_VALUE%%.*}"
fi
PRODUCTION_CLIENT_ID="${COGNITO_PRODUCTION_CLIENT_ID:-${COGNITO_CLIENT_ID:-}}"
STAGING_CLIENT_ID="${COGNITO_STAGING_CLIENT_ID:-${1:-}}"
SETTINGS_FILE="${COGNITO_MANAGED_BRANDING_SETTINGS:-$ROOT_DIR/ecs/cognito-managed-login-settings.json}"
SETTINGS_FILE_FOR_AWS="$SETTINGS_FILE"
# Native Windows AWS CLI cannot resolve Git Bash's /c/... filesystem syntax.
if command -v cygpath >/dev/null 2>&1; then
  SETTINGS_FILE_FOR_AWS="$(cygpath -m "$SETTINGS_FILE")"
fi

require_value() {
  local name="$1"
  local value="$2"
  if [[ -z "$value" ]]; then
    echo "$name is required in .env.aws or the shell environment." >&2
    exit 2
  fi
}

require_value "DEPLOY_AWS_PROFILE (or AWS_PROFILE)" "$PROFILE"
require_value "COGNITO_POOL_ID (or COGNITO_USER_POOL_ID)" "$USER_POOL_ID"
require_value "COGNITO_DOMAIN (or COGNITO_DOMAIN_PREFIX)" "$DOMAIN_PREFIX"
require_value "COGNITO_CLIENT_ID (or COGNITO_PRODUCTION_CLIENT_ID)" "$PRODUCTION_CLIENT_ID"
require_value "COGNITO_STAGING_CLIENT_ID (or the first command argument)" "$STAGING_CLIENT_ID"

aws_args=(--profile "$PROFILE" --region "$REGION")

aws cognito-idp update-user-pool-domain "${aws_args[@]}" \
  --user-pool-id "$USER_POOL_ID" \
  --domain "$DOMAIN_PREFIX" \
  --managed-login-version 2 >/dev/null

apply_client_branding() {
  local client_id="$1"
  local branding_id
  branding_id="$(aws cognito-idp describe-managed-login-branding-by-client "${aws_args[@]}" \
    --user-pool-id "$USER_POOL_ID" \
    --client-id "$client_id" \
    --query 'ManagedLoginBranding.ManagedLoginBrandingId' \
    --output text 2>/dev/null || true)"

  if [[ -z "$branding_id" || "$branding_id" == "None" ]]; then
    branding_id="$(aws cognito-idp create-managed-login-branding "${aws_args[@]}" \
      --user-pool-id "$USER_POOL_ID" \
      --client-id "$client_id" \
      --use-cognito-provided-values \
      --query 'ManagedLoginBranding.ManagedLoginBrandingId' \
      --output text)"
  fi

  aws cognito-idp update-managed-login-branding "${aws_args[@]}" \
    --user-pool-id "$USER_POOL_ID" \
    --managed-login-branding-id "$branding_id" \
    --settings "file://$SETTINGS_FILE_FOR_AWS" >/dev/null
  echo "Managed login branding applied to client $client_id ($branding_id)"
}

apply_client_branding "$PRODUCTION_CLIENT_ID"
apply_client_branding "$STAGING_CLIENT_ID"

echo "Cognito domain $DOMAIN_PREFIX is using managed login version 2."
echo "Rollback command: aws cognito-idp update-user-pool-domain --profile $PROFILE --region $REGION --user-pool-id $USER_POOL_ID --domain $DOMAIN_PREFIX --managed-login-version 1"
