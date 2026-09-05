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

if [[ "$#" -lt 10 ]]; then
  echo "Usage: bash experiments/run-cli.sh INPUT OUTPUT_BASE PIXEL_MM WIDTH HEIGHT MATERIAL_LIBRARY MATERIAL COLORS PRESET FILTER [FILTER_JSON] [PALETTE_NAMES_JSON] [SVG_ONLY]" >&2
  exit 2
fi

cd "${REPO_DIR}"
# shellcheck disable=SC1091
source "${ACTIVATE_SCRIPT}"
python -u experiments/Material_Library.py "$@"
