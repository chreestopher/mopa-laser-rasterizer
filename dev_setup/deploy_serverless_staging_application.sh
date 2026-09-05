#!/usr/bin/env bash
# Idempotently deploy the complete retained serverless staging application.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

bash "$SCRIPT_DIR/deploy_serverless_staging.sh"
bash "$SCRIPT_DIR/deploy_serverless_staging_web.sh"

echo "Serverless staging worker, orchestration, API, and web UI are deployed."
