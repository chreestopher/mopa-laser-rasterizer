#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INPUT_IMAGE="${SCRIPT_DIR}/test-input.png"
MATERIAL_LIBRARY="${SCRIPT_DIR}/tests.clb"
MATERIAL_NAME="colors - stainless steel"
OUTPUT_DIR="${SCRIPT_DIR}/uploads/cli-sample"
OUTPUT_BASE="${OUTPUT_DIR}/test-input"
PIXEL_SIZE_MM="0.125"
TARGET_WIDTH="800"
TARGET_HEIGHT="0"
IMAGE_PRESET="cartoon"
ABSTRACT_FILTER="none"
FILTER_PARAMETERS='{"min_island_area":50}'
PALETTE_NAMES='{}'
SVG_ONLY="false"
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
  "${PIXEL_SIZE_MM}" \
  "${TARGET_WIDTH}" \
  "${TARGET_HEIGHT}" \
  "${MATERIAL_LIBRARY}" \
  "${MATERIAL_NAME}" \
  "${DEFAULT_RASTERIZER_SWATCHES}" \
  "${IMAGE_PRESET}" \
  "${ABSTRACT_FILTER}" \
  "${FILTER_PARAMETERS}" \
  "${PALETTE_NAMES}" \
  "${SVG_ONLY}"

echo
echo "Sample output:"
echo "  ${OUTPUT_BASE}.vector.svg"
echo "  ${OUTPUT_BASE}.vector.svg.lbrn2"
