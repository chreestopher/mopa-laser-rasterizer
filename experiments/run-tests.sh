#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
ACTIVATE_SCRIPT="${REPO_DIR}/.venv/bin/activate"

if [[ ! -f "${ACTIVATE_SCRIPT}" ]]; then
  echo "The repository virtual environment does not exist." >&2
  echo "Run: bash dev_setup/setup-wsl.sh" >&2
  exit 1
fi

cd "${REPO_DIR}"
# shellcheck disable=SC1091
source "${ACTIVATE_SCRIPT}"
python -m pytest experiments/tests -q "$@"
