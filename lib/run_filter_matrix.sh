#!/usr/bin/env bash

# Run every image-preset / abstract-filter combination through
# Material_Library.py. Designed for Bash in WSL.
#
# Usage:
#   ./run_filter_matrix.sh INPUT_IMAGE OUTPUT_DIRECTORY
#
# Optional environment settings:
#   MATERIAL_LIBRARY=/path/to/lightburn-material-library.clb
#   MATERIAL_SCRIPT=/path/to/Material_Library.py
#   PYTHON_BIN=python3
#   PIXEL_SIZE_MM=1
#   MATERIAL_NAME="stainless - steel"
#   RASTER_WIDTH=300       # Set one of RASTER_WIDTH/RASTER_HEIGHT to 0.
#   RASTER_HEIGHT=0
#   LIMIT_COLORS=""        # Empty means every available LightBurn color.
#   CONTINUE_EXISTING=1    # Skip output combinations already present.

set -u
set -o pipefail

usage() {
  echo "Usage: $0 INPUT_IMAGE OUTPUT_DIRECTORY" >&2
  exit 2
}

[[ $# -eq 2 ]] || usage

input_file=$1
output_dir=$2
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
python_bin=${PYTHON_BIN:-python3}
pixel_size_mm=${PIXEL_SIZE_MM:-1}
material_name=${MATERIAL_NAME:-stainless - steel}
raster_width=${RASTER_WIDTH:-300}
raster_height=${RASTER_HEIGHT:-0}
limit_colors=${LIMIT_COLORS:-}
continue_existing=${CONTINUE_EXISTING:-0}

if [[ ! -f $input_file ]]; then
  echo "Input image does not exist: $input_file" >&2
  exit 2
fi

if ! command -v "$python_bin" >/dev/null 2>&1; then
  echo "Python executable not found: $python_bin" >&2
  exit 2
fi

material_script=${MATERIAL_SCRIPT:-}
if [[ -z $material_script ]]; then
  for candidate in \
    "$script_dir/Material_Library.py" \
    "$script_dir/lib/Material_Library.py" \
    "$PWD/Material_Library.py" \
    "$PWD/lib/Material_Library.py"; do
    if [[ -f $candidate ]]; then
      material_script=$candidate
      break
    fi
  done
fi

if [[ -z $material_script || ! -f $material_script ]]; then
  echo "Material_Library.py was not found." >&2
  echo "Place this script beside it, run from the project root, or set MATERIAL_SCRIPT." >&2
  exit 2
fi

material_library=${MATERIAL_LIBRARY:-}
if [[ -z $material_library ]]; then
  shopt -s nullglob nocaseglob
  candidates=(
    "$script_dir"/*.clb "$script_dir"/*.lbmat "$script_dir"/*.xml
    "$script_dir/materials"/*.clb "$script_dir/materials"/*.lbmat "$script_dir/materials"/*.xml
  )
  shopt -u nullglob nocaseglob
  if [[ ${#candidates[@]} -eq 1 ]]; then
    material_library=${candidates[0]}
  elif [[ ${#candidates[@]} -gt 1 ]]; then
    echo "Several possible material libraries were found. Set MATERIAL_LIBRARY explicitly:" >&2
    printf '  %s\n' "${candidates[@]}" >&2
    exit 2
  fi
fi

if [[ -z $material_library || ! -f $material_library ]]; then
  echo "A LightBurn material-library file is required by the full export pipeline." >&2
  echo "Set it once for this command, for example:" >&2
  echo "  MATERIAL_LIBRARY=/mnt/c/path/materials.clb $0 \"$input_file\" \"$output_dir\"" >&2
  exit 2
fi

if [[ $raster_width != 0 && $raster_height != 0 ]]; then
  echo "Set either RASTER_WIDTH or RASTER_HEIGHT to 0 so aspect ratio remains constrained." >&2
  exit 2
fi
if [[ $raster_width == 0 && $raster_height == 0 ]]; then
  echo "RASTER_WIDTH and RASTER_HEIGHT cannot both be 0." >&2
  exit 2
fi

mkdir -p -- "$output_dir"
output_dir=$(cd -- "$output_dir" && pwd)
input_file=$(cd -- "$(dirname -- "$input_file")" && pwd)/$(basename -- "$input_file")
material_script=$(cd -- "$(dirname -- "$material_script")" && pwd)/$(basename -- "$material_script")
material_library=$(cd -- "$(dirname -- "$material_library")" && pwd)/$(basename -- "$material_library")

presets=(cartoon color_photograph bw_dither_photograph abstract)
filters=(none wave voronoi shear spiral mosaic crystal ripple centerline glitch shattered)

# Defaults exercise each filter predictably. Override individual values by
# editing these JSON objects or by copying this script for a test profile.
declare -A filter_json=(
  [none]='{}'
  [wave]='{"amplitude_x":4,"amplitude_y":4,"frequency_x":0.1,"frequency_y":0.1,"phase":0}'
  [voronoi]='{"cell_size":15,"jitter":0.45,"gap":0.8,"seed":1}'
  [shear]='{"shear_x":0.5,"shear_y":0,"scale_x":1,"scale_y":0.8}'
  [spiral]='{"twist":2.25,"falloff":1,"center_x":0.5,"center_y":0.5}'
  [mosaic]='{"tile_size":12,"gap":1,"stagger":0.5}'
  [crystal]='{"cell_size":18,"gap":0.7}'
  [ripple]='{"amplitude":3,"frequency":0.18,"phase":0,"center_x":0.5,"center_y":0.5}'
  [centerline]='{"line_simplification":0.35,"min_branch_length":2}'
  [glitch]='{"slice_height":18,"fragment_width":70,"shift_amount":28,"echo_count":2,"echo_spacing":9,"density":0.55,"fibonacci_stride":2,"vertical_jitter":3,"seed":1}'
  [shattered]='{"min_shard_size":8,"max_shard_size":32,"density":0.6,"minimum_gap":0.7,"gap_variation":2.2,"horizontal_spread":12,"fall_distance":20,"gravity_bias":1.4,"rotation":22,"break_origin_x":0.5,"break_origin_y":0.35,"seed":1}'
)

base_name=$(basename -- "$input_file")
base_name=${base_name%.*}
base_name=${base_name//[^[:alnum:]_.-]/_}
log_dir="$output_dir/logs"
mkdir -p -- "$log_dir"

total=$((${#presets[@]} * ${#filters[@]}))
completed=0
failed=0
skipped=0
index=0

echo "Input:     $input_file"
echo "Output:    $output_dir"
echo "Pipeline:  $material_script"
echo "Materials: $material_library"
echo "Material:  $material_name"
echo "Matrix:    ${#presets[@]} presets x ${#filters[@]} filters = $total runs"
echo

for preset in "${presets[@]}"; do
  for filter in "${filters[@]}"; do
    index=$((index + 1))
    output_stem="$output_dir/${base_name}__${preset}__${filter}"
    svg_file="${output_stem}.vector.svg"
    lbrn_file="${svg_file}.lbrn2"
    log_file="$log_dir/${base_name}__${preset}__${filter}.log"

    if [[ $continue_existing == 1 && -s $svg_file && -s $lbrn_file ]]; then
      printf '[%d/%d] SKIP  %s / %s\n' "$index" "$total" "$preset" "$filter"
      skipped=$((skipped + 1))
      continue
    fi

    printf '[%d/%d] RUN   %s / %s\n' "$index" "$total" "$preset" "$filter"
    if "$python_bin" -u "$material_script" \
      "$input_file" \
      "$output_stem" \
      "$pixel_size_mm" \
      "$raster_width" \
      "$raster_height" \
      "$material_library" \
      "$material_name" \
      "$limit_colors" \
      "$preset" \
      "$filter" \
      "${filter_json[$filter]}" >"$log_file" 2>&1; then
      completed=$((completed + 1))
      printf '         OK    %s\n' "$svg_file"
    else
      failed=$((failed + 1))
      printf '         FAIL  See %s\n' "$log_file" >&2
    fi
  done
done

echo
echo "Finished: $completed succeeded, $failed failed, $skipped skipped."
echo "Logs: $log_dir"

((failed == 0))
