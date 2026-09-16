#!/usr/bin/env bash
# Update existing production application resources sequentially from CI.
# Foundational infrastructure and the cost guard remain workstation-admin tasks.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"
configure_aws_deployment_credentials

if [ "${1:-}" != "--apply" ]; then
  echo "No production changes made. Pass --apply only from the approved release workflow." >&2
  exit 2
fi

# This release path targets the live custom domain, not the pre-DNS preview.
# Fail before publishing a worker image or touching a stack if CI/local config
# would switch the browser callback away from the production origin.
if [ -z "${SERVERLESS_PRODUCTION_CERTIFICATE_ARN:-}" ]; then
  echo "SERVERLESS_PRODUCTION_CERTIFICATE_ARN is required for a production release." >&2
  exit 2
fi
if [ "${SERVERLESS_PRODUCTION_USE_CLOUDFRONT_CALLBACK:-false}" != "false" ]; then
  echo "Production releases must use the custom-domain Cognito callback." >&2
  exit 2
fi
if [ "${SERVERLESS_PRODUCTION_HOSTNAME:-mopa-laser-rasterizer.com}" != "mopa-laser-rasterizer.com" ] ||
   [ "${SERVERLESS_PRODUCTION_ALTERNATE_HOSTNAME:-www.mopa-laser-rasterizer.com}" != "www.mopa-laser-rasterizer.com" ]; then
  echo "Production release hostnames must remain the approved apex and www origins." >&2
  exit 2
fi

export SERVERLESS_SKIP_FOUNDATION_DEPLOY=true
export SERVERLESS_RECONCILE_ECR_LIFECYCLE=false
export SERVERLESS_REMOVE_RETIRED_DOCS=false
export COGNITO_UPDATE_DOMAIN=false
export COGNITO_APPLY_PRODUCTION_BRANDING=false
export COGNITO_APPLY_STAGING_BRANDING=false

# Keep these sequential. Queue dispatch is paused around the worker update, and
# the public web/API revision is published only after orchestration succeeds.
bash "$SCRIPT_DIR/deploy_serverless_production.sh" --apply
bash "$SCRIPT_DIR/deploy_serverless_production_web.sh" --apply
python3 "$SCRIPT_DIR/verify_production_auth.py"

echo "Existing production worker, orchestration, API, and frontend are updated."
