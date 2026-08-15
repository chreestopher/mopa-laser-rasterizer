import math

import numpy as np
from shapely.geometry import LineString, box
from shapely.ops import unary_union

from .common import number


DEFAULTS = {
    "grating_spacing": 3,
    "line_width": .35,
    "field_scale": 42,
    "field_strength": .7,
    "symmetry": 6,
    "base_angle": 0,
    "step_size": 1.5,
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
PUNCH_SOURCE_GEOMETRY = True
PRESERVE_BACKGROUND_TRANSPARENCY = True


def _field_direction(x, y, bounds, scale, strength, symmetry, base_angle, phase):
    """Return a smooth tangent sampled from an invisible sacred lattice."""
    x1, y1, _, _ = bounds
    row_height = scale * math.sqrt(3) / 2
    row = round((y - y1 - phase) / row_height)
    col = round((x - x1 - phase - (scale / 2 if row & 1 else 0)) / scale)
    vx = math.cos(base_angle) * (1 - strength)
    vy = math.sin(base_angle) * (1 - strength)
    radius = scale * .72

    for row_offset in (-1, 0, 1):
        lattice_row = row + row_offset
        offset = scale / 2 if lattice_row & 1 else 0
        cy = y1 + lattice_row * row_height + phase
        for col_offset in (-1, 0, 1):
            lattice_col = col + col_offset
            cx = x1 + lattice_col * scale + offset + phase
            dx, dy = x - cx, y - cy
            distance = math.hypot(dx, dy)
            if distance < 1e-6 or distance > scale * 1.6:
                continue
            angle = math.atan2(dy, dx)
            # Quantized radial phase supplies the rotational symmetry without
            # ever drawing the circles, petals, or polygon scaffold itself.
            sector = round((angle - base_angle) * symmetry / (2 * math.pi))
            sacred_angle = base_angle + sector * 2 * math.pi / symmetry
            tangent = angle + math.pi / 2
            influence = math.exp(-((distance - radius) / (scale * .42)) ** 2)
            influence *= .55 + .45 * math.cos(symmetry * (angle - sacred_angle))
            vx += math.cos(tangent) * influence * strength
            vy += math.sin(tangent) * influence * strength

    if vx < 0:
        vx, vy = -vx, -vy
    return math.atan2(vy, max(vx, 1e-6))


def _grating(bounds, settings):
    x1, y1, x2, y2 = bounds
    spacing = number(settings.get("grating_spacing"), 3, .25, 100)
    scale = number(settings.get("field_scale"), 42, 5, 1000)
    strength = number(settings.get("field_strength"), .7, 0, 1)
    symmetry = int(number(settings.get("symmetry"), 6, 3, 24))
    base_angle = math.radians(number(settings.get("base_angle"), 0, -180, 180))
    step = number(settings.get("step_size"), 1.5, .1, 10)
    seed = int(number(settings.get("seed"), 1, 0, 2147483647))
    rng = np.random.default_rng(seed)
    phase = (seed * .6180339887498949 % 1) * scale
    lines = []
    margin = max(x2 - x1, y2 - y1) * .35

    for start_y in np.arange(y1 - margin, y2 + margin + spacing, spacing):
        y = float(start_y + rng.uniform(-spacing * .08, spacing * .08))
        points = [(x1 - margin, y)]
        x = x1 - margin
        while x < x2 + margin:
            angle = _field_direction(
                x, y, bounds, scale, strength, symmetry, base_angle, phase
            )
            x += step
            y += math.tan(max(-1.25, min(1.25, angle))) * step
            points.append((x, y))
            if y < y1 - margin * 2 or y > y2 + margin * 2:
                break
        if len(points) > 1:
            lines.append(LineString(points))
    return unary_union(lines) if lines else box(0, 0, 0, 0)


def apply(geometry, settings):
    bounds = settings.get("_canvas_bounds") or geometry.bounds
    width = number(settings.get("line_width"), .35, .02, 20)
    ribbons = _grating(bounds, settings).buffer(width / 2, cap_style=2, join_style=2)
    return geometry.intersection(ribbons)
