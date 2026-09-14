#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ACTIVATE_SCRIPT="${SCRIPT_DIR}/.venv/bin/activate"

if [[ ! -f "${ACTIVATE_SCRIPT}" ]]; then
  echo "The repository virtual environment does not exist." >&2
  echo "Run this first from Ubuntu WSL:" >&2
  echo "  bash dev_setup/setup-wsl.sh" >&2
  exit 1
fi

if [[ "$#" -lt 10 ]]; then
  echo "Usage:" >&2
  echo "  bash run-cli.sh INPUT OUTPUT_BASE PIXEL_MM WIDTH HEIGHT MATERIAL_LIBRARY MATERIAL COLORS PRESET FILTER [FILTER_JSON] [PALETTE_NAMES_JSON] [SVG_ONLY]" >&2
  exit 2
fi

cd "${SCRIPT_DIR}"
# shellcheck disable=SC1091
source "${ACTIVATE_SCRIPT}"

python -u lib/Material_Library.py "$@"
