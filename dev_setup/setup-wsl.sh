#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${REPO_DIR}/.venv"

echo "Installing Python and native rasterizer build dependencies in Ubuntu WSL..."
sudo apt-get update
sudo apt-get install -y \
  build-essential \
  libagg-dev \
  libpotrace-dev \
  pkg-config \
  python3 \
  python3-dev \
  python3-pip \
  python3-venv

cd "${REPO_DIR}"

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  echo "Creating virtual environment at ${VENV_DIR}..."
  python3 -m venv "${VENV_DIR}"
else
  echo "Reusing virtual environment at ${VENV_DIR}."
fi

echo "Installing application and test dependencies..."
"${VENV_DIR}/bin/python" -m pip install --upgrade pip setuptools wheel
"${VENV_DIR}/bin/python" -m pip install -r requirements-dev.txt

echo
echo "Ubuntu WSL setup is complete. Activate this environment with:"
echo "  source .venv/bin/activate"
echo
echo "Run the experiment tests with:"
echo "  python -m pytest experiments/tests -q"
