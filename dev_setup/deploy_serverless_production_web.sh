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

required=(COGNITO_POOL_ID COGNITO_DOMAIN)
for name in "${required[@]}"; do
  [ -n "${!name:-}" ] || { echo "$name is required in .env.aws or the shell environment." >&2; exit 2; }
done

PRIMARY_HOSTNAME="${SERVERLESS_PRODUCTION_HOSTNAME:-mopa-laser-rasterizer.com}"
ALTERNATE_HOSTNAME="${SERVERLESS_PRODUCTION_ALTERNATE_HOSTNAME:-www.mopa-laser-rasterizer.com}"
CERTIFICATE_ARN="${SERVERLESS_PRODUCTION_CERTIFICATE_ARN:-}"
case "$PRIMARY_HOSTNAME $ALTERNATE_HOSTNAME" in
  *staging*) echo "Refusing to attach a staging hostname to production." >&2; exit 2 ;;
esac

export SERVERLESS_ENVIRONMENT_LABEL="Serverless production"
export SERVERLESS_FOUNDATION_STACK="${SERVERLESS_PRODUCTION_FOUNDATION_STACK:-mopa-rasterizer-serverless-production}"
export SERVERLESS_WORKER_STACK="${SERVERLESS_PRODUCTION_WORKER_STACK:-mopa-rasterizer-serverless-production-worker}"
export SERVERLESS_ORCHESTRATION_STACK="${SERVERLESS_PRODUCTION_ORCHESTRATION_STACK:-mopa-rasterizer-serverless-production-orchestration}"
export SERVERLESS_WEB_STACK="${SERVERLESS_PRODUCTION_WEB_STACK:-mopa-rasterizer-serverless-production-web}"
export SERVERLESS_DEPLOYMENT_NAME="${SERVERLESS_PRODUCTION_DEPLOYMENT_NAME:-mopa-rasterizer-serverless-production}"
export SERVERLESS_API_FUNCTION_NAME="${SERVERLESS_PRODUCTION_API_FUNCTION_NAME:-mopa-rasterizer-serverless-production-api}"
if [ -n "$CERTIFICATE_ARN" ]; then
  export SERVERLESS_PRIMARY_HOSTNAME="$PRIMARY_HOSTNAME"
  export SERVERLESS_ALTERNATE_HOSTNAME="$ALTERNATE_HOSTNAME"
  export SERVERLESS_CERTIFICATE_ARN="$CERTIFICATE_ARN"
  export SERVERLESS_PUBLIC_URL="https://${PRIMARY_HOSTNAME}/"
else
  # A pre-DNS production rehearsal can use CloudFront's generated hostname and
  # default TLS certificate. Custom aliases are attached only after an issued
  # us-east-1 certificate has been supplied explicitly.
  export SERVERLESS_PRIMARY_HOSTNAME=""
  export SERVERLESS_ALTERNATE_HOSTNAME=""
  export SERVERLESS_CERTIFICATE_ARN=""
  unset SERVERLESS_PUBLIC_URL
  echo "No production certificate supplied; deploying a CloudFront preview without custom aliases."
fi
# Before DNS cutover the CloudFront hostname is the browser-test endpoint. The
# Cognito client permits both it and the eventual production hostnames.
export SERVERLESS_USE_CLOUDFRONT_CALLBACK="${SERVERLESS_PRODUCTION_USE_CLOUDFRONT_CALLBACK:-true}"
export SERVERLESS_CONFIGURE_ARTIFACT_CORS=true
export SERVERLESS_ADMIN_EMAIL="${SERVERLESS_PRODUCTION_ADMIN_EMAIL:-${IDENTITY_CENTER_ADMIN_EMAIL:-}}"
export SERVERLESS_ACCESS_GATE_AUTHORIZATION=""
export SERVERLESS_GUEST_ACCESS_ENABLED="true"
export SERVERLESS_ALLOWED_USER_SUB=""

exec bash "$SCRIPT_DIR/deploy_serverless_staging_web.sh"
