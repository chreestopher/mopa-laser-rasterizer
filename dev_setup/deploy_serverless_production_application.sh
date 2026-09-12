#!/usr/bin/env bash
# Deploy production serverless components in a deliberately sequential order.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

if [ "${1:-}" != "--apply" ]; then
  echo "No production changes made. Pass --apply only after the promotion gate is approved." >&2
  echo "Validate with: bash dev_setup/validate_serverless_production_deployment.sh" >&2
  exit 2
fi

# Do not run these concurrently. The worker/orchestration deployment pauses its
# own queue dispatch during task-definition changes, then the API/static site is
# published only after that update succeeds.
bash "$SCRIPT_DIR/deploy_serverless_production.sh" --apply
bash "$SCRIPT_DIR/deploy_serverless_production_web.sh" --apply
bash "$SCRIPT_DIR/deploy_serverless_cost_guard.sh" --apply

echo "Serverless production infrastructure is deployed. Route 53 is unchanged."
