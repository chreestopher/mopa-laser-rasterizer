#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
INPUT_IMAGE="${REPO_DIR}/test-input.png"
MATERIAL_LIBRARY="${REPO_DIR}/tests.clb"
OUTPUT_DIR="${REPO_DIR}/uploads/no-canvas-sample"
OUTPUT_BASE="${OUTPUT_DIR}/test-input"
DEFAULT_RASTERIZER_SWATCHES="Light-Gray,Black,Blue,Red,Green,Yellow,Orange,Cyan,Magenta,Dark-Blue,Dark-Red,Dark-Green,Dark-Yellow,Dark-Orange,Light-Blue,Dark-Magenta,Medium-Gray,Slate-Blue,Rose,Periwinkle-Blue,Raspberry,Sage-Green,Peach,Light-Pink,Orchid-Pink,Deep-Purple,Rust-Brown,Teal,Bright-Mint-Green,Light-Gold"

if [[ ! -f "${INPUT_IMAGE}" ]]; then
  echo "Input image not found: ${INPUT_IMAGE}" >&2
  exit 1
fi
if [[ ! -f "${MATERIAL_LIBRARY}" ]]; then
  echo "Material library not found: ${MATERIAL_LIBRARY}" >&2
  exit 1
fi

mkdir -p "${OUTPUT_DIR}"
bash "${SCRIPT_DIR}/run-cli.sh" \
  "${INPUT_IMAGE}" \
  "${OUTPUT_BASE}" \
  "0.0625" \
  "800" \
  "0" \
  "${MATERIAL_LIBRARY}" \
  "colors - stainless steel" \
  "${DEFAULT_RASTERIZER_SWATCHES}" \
  "abstract" \
  "krasnow_grating" \
  '{"min_island_area": 10,"constrain_nonblack":true}' \
  '{}' \
  "false"


echo "No-canvas sample output:"
echo "  ${OUTPUT_BASE}.vector.svg"
echo "  ${OUTPUT_BASE}.vector.svg.lbrn2"
