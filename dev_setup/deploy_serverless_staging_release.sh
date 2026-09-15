#!/usr/bin/env bash
# Update the existing staging worker/orchestration revision, followed by web/API.
# Structural infrastructure changes remain a workstation-SSO deployment task.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

bash "$SCRIPT_DIR/deploy_serverless_staging_worker_only.sh"
bash "$SCRIPT_DIR/deploy_serverless_staging_web.sh"

echo "Existing serverless staging worker, orchestration, API, and web UI are updated."
