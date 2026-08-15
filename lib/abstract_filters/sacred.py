import math

import numpy as np
from shapely.geometry import LineString, box
from shapely.ops import unary_union

from .common import number


DEFAULTS = {
    "grating_spacing": 1.25,
    "line_width": .3,
    "field_scale": 60,
    "field_strength": .35,
    "symmetry": 6,
    "base_angle": 0,
    "step_size": .75,
    "seed": 1,
}
CONTROLS = (
    ("grating_spacing", .5, 12, .1),
    ("line_width", .05, 3, .05),
    ("field_scale", 10, 160, 1),
    ("field_strength", 0, 1, .05),
    ("symmetry", 3, 12, 1),
    ("base_angle", -180, 180, 1),
    ("step_size", .25, 5, .25),
    ("seed", 0, 999999, 1),
)

# The source regions remain invisible masks. Only the clipped diffraction
# ribbons are exported, all on the matched Holographic material layer.
SETTING_NAME = "holographic"
SETTING_NAME_PARAMETER = "holographic"
LAYER_NAME = "Holographic"
LAYER_COLOR = "#FEFEFE"
LAYER_AFTER_GEOMETRY = True
PUNCH_SOURCE_GEOMETRY = True
PRESERVE_BACKGROUND_TRANSPARENCY = True
PER_COLOR_BASE_ANGLE = True
DEFER_TO_EXPORT = True
BUFFER_BATCH_SIZE = 8


def _field_direction(
    x,
    y,
    x1,
    y1,
    scale,
    strength,
    symmetry,
    base_angle,
    phase,
    row_height,
    half_scale,
    base_vx,
    base_vy,
    radius,
    influence_width,
    maximum_distance,
    two_pi,
):
    """Return a smooth tangent sampled from an invisible sacred lattice."""
    row = round((y - y1 - phase) / row_height)
    col = round((x - x1 - phase - (half_scale if row & 1 else 0)) / scale)
    vx = base_vx
    vy = base_vy

    for row_offset in (-1, 0, 1):
        lattice_row = row + row_offset
        offset = half_scale if lattice_row & 1 else 0
        cy = y1 + lattice_row * row_height + phase
        for col_offset in (-1, 0, 1):
            lattice_col = col + col_offset
            cx = x1 + lattice_col * scale + offset + phase
            dx, dy = x - cx, y - cy
            distance = math.hypot(dx, dy)
            if distance < 1e-6 or distance > maximum_distance:
                continue
            angle = math.atan2(dy, dx)
            # Quantized radial phase supplies the rotational symmetry without
            # ever drawing the circles, petals, or polygon scaffold itself.
            sector = round((angle - base_angle) * symmetry / two_pi)
            sacred_angle = base_angle + sector * two_pi / symmetry
            tangent = angle + math.pi / 2
            influence = math.exp(-((distance - radius) / influence_width) ** 2)
            influence *= .55 + .45 * math.cos(symmetry * (angle - sacred_angle))
            vx += math.cos(tangent) * influence * strength
            vy += math.sin(tangent) * influence * strength

    if vx < 0:
        vx, vy = -vx, -vy
    return math.atan2(vy, max(vx, 1e-6))


def _grating(bounds, settings):
    x1, y1, x2, y2 = bounds
    spacing = number(settings.get("grating_spacing"), 1.25, .25, 100)
    scale = number(settings.get("field_scale"), 60, 5, 1000)
    strength = number(settings.get("field_strength"), .35, 0, 1)
    symmetry = int(number(settings.get("symmetry"), 6, 3, 24))
    user_angle = number(settings.get("base_angle"), 0, -180, 180)
    color_angle = number(settings.get("_color_base_angle"), 0, 0, 180)
    base_angle = math.radians((user_angle + color_angle) % 180)
    step = number(settings.get("step_size"), .75, .1, 10)
    seed = int(number(settings.get("seed"), 1, 0, 2147483647))
    rng = np.random.default_rng(seed)
    phase = (seed * .6180339887498949 % 1) * scale
    row_height = scale * math.sqrt(3) / 2
    half_scale = scale / 2
    base_vx = math.cos(base_angle) * (1 - strength)
    base_vy = math.sin(base_angle) * (1 - strength)
    radius = scale * .72
    influence_width = scale * .42
    maximum_distance = scale * 1.6
    two_pi = 2 * math.pi
    lines = []
    margin = max(x2 - x1, y2 - y1) * .35
    progress = settings.get("_progress_logger")
    start_positions = np.arange(y1 - margin, y2 + margin + spacing, spacing)
    if callable(progress):
        progress(f"Sacred streamline generation START: {len(start_positions)} line batches.")

    for start_y in start_positions:
        y = float(start_y + rng.uniform(-spacing * .08, spacing * .08))
        points = [(x1 - margin, y)]
        x = x1 - margin
        while x < x2 + margin:
            angle = _field_direction(
                x,
                y,
                x1,
                y1,
                scale,
                strength,
                symmetry,
                base_angle,
                phase,
                row_height,
                half_scale,
                base_vx,
                base_vy,
                radius,
                influence_width,
                maximum_distance,
                two_pi,
            )
            x += step
            y += math.tan(max(-1.25, min(1.25, angle))) * step
            points.append((x, y))
            if y < y1 - margin * 2 or y > y2 + margin * 2:
                break
        if len(points) > 1:
            lines.append(LineString(points))
    if callable(progress):
        progress(f"Sacred streamline generation DONE: {len(lines)} line batches.")
    return lines


def apply(geometry, settings):
    bounds = settings.get("_canvas_bounds") or geometry.bounds
    width = number(settings.get("line_width"), .3, .02, 20)
    progress = settings.get("_progress_logger")
    lines = _grating(bounds, settings)
    if not lines:
        return box(0, 0, 0, 0)

    total_batches = math.ceil(len(lines) / BUFFER_BATCH_SIZE)
    clipped_batches = []
    if callable(progress):
        progress(
            f"Sacred bounded ribbon buffer START: {len(lines)} lines in "
            f"{total_batches} batches."
        )
    for batch_index, start in enumerate(range(0, len(lines), BUFFER_BATCH_SIZE), 1):
        line_batch = unary_union(lines[start:start + BUFFER_BATCH_SIZE])
        ribbons = line_batch.buffer(width / 2, cap_style=2, join_style=2)
        clipped = geometry.intersection(ribbons)
        if not clipped.is_empty:
            clipped_batches.append(clipped)
        if callable(progress) and (
            batch_index == 1 or batch_index == total_batches or batch_index % 10 == 0
        ):
            progress(
                f"Sacred bounded ribbon buffer: batch {batch_index}/{total_batches}; "
                f"{min(start + BUFFER_BATCH_SIZE, len(lines))}/{len(lines)} lines processed."
            )
    if callable(progress):
        progress(
            f"Sacred bounded ribbon buffer DONE: {len(clipped_batches)} non-empty "
            f"clipped batches from {total_batches} batches."
        )
        progress(f"Sacred clipped-batch union START: {len(clipped_batches)} batches.")
    result = unary_union(clipped_batches) if clipped_batches else box(0, 0, 0, 0)
    if callable(progress):
        progress(f"Sacred clipped-batch union DONE: {len(clipped_batches)} batches.")
    return result
