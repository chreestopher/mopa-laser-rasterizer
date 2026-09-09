#!/usr/bin/env bash
# Deploy the production serverless API/frontend sequentially without changing Route 53.
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

required=(COGNITO_POOL_ID COGNITO_DOMAIN SERVERLESS_PRODUCTION_CERTIFICATE_ARN)
for name in "${required[@]}"; do
  [ -n "${!name:-}" ] || { echo "$name is required in .env.aws or the shell environment." >&2; exit 2; }
done

PRIMARY_HOSTNAME="${SERVERLESS_PRODUCTION_HOSTNAME:-mopa-laser-rasterizer.com}"
ALTERNATE_HOSTNAME="${SERVERLESS_PRODUCTION_ALTERNATE_HOSTNAME:-www.mopa-laser-rasterizer.com}"
case "$PRIMARY_HOSTNAME $ALTERNATE_HOSTNAME" in
  *staging*) echo "Refusing to attach a staging hostname to production." >&2; exit 2 ;;
esac

export SERVERLESS_ENVIRONMENT_LABEL="Serverless production"
export SERVERLESS_FOUNDATION_STACK="${SERVERLESS_PRODUCTION_FOUNDATION_STACK:-mopa-rasterizer-serverless-production}"
export SERVERLESS_WEB_STACK="${SERVERLESS_PRODUCTION_WEB_STACK:-mopa-rasterizer-serverless-production-web}"
export SERVERLESS_DEPLOYMENT_NAME="${SERVERLESS_PRODUCTION_DEPLOYMENT_NAME:-mopa-rasterizer-serverless-production}"
export SERVERLESS_API_FUNCTION_NAME="${SERVERLESS_PRODUCTION_API_FUNCTION_NAME:-mopa-rasterizer-serverless-production-api}"
export SERVERLESS_PRIMARY_HOSTNAME="$PRIMARY_HOSTNAME"
export SERVERLESS_ALTERNATE_HOSTNAME="$ALTERNATE_HOSTNAME"
export SERVERLESS_CERTIFICATE_ARN="$SERVERLESS_PRODUCTION_CERTIFICATE_ARN"
export SERVERLESS_PUBLIC_URL="https://${PRIMARY_HOSTNAME}/"
# Before DNS cutover the CloudFront hostname is the browser-test endpoint. The
# Cognito client permits both it and the eventual production hostnames.
export SERVERLESS_USE_CLOUDFRONT_CALLBACK="${SERVERLESS_PRODUCTION_USE_CLOUDFRONT_CALLBACK:-true}"
export SERVERLESS_ADMIN_EMAIL="${SERVERLESS_PRODUCTION_ADMIN_EMAIL:-${IDENTITY_CENTER_ADMIN_EMAIL:-}}"

exec bash "$SCRIPT_DIR/deploy_serverless_staging_web.sh"
