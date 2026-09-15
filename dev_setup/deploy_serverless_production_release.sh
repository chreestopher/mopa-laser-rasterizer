#!/usr/bin/env bash
# Update existing production application resources sequentially from CI.
# Foundational infrastructure and the cost guard remain workstation-admin tasks.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

if [ "${1:-}" != "--apply" ]; then
  echo "No production changes made. Pass --apply only from the approved release workflow." >&2
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

echo "Existing production worker, orchestration, API, and frontend are updated."
