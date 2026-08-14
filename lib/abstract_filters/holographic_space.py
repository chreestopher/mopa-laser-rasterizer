"""Deterministic diffraction-band geometry for the Holographic Space filter."""

import math

from shapely.affinity import translate
from shapely.geometry import box
from shapely.ops import unary_union

from .common import number

# The vector pipeline uses this declaration to preserve dark artwork while
# applying the foil treatment to light/background swatches only.
LIGHT_LAYERS_ONLY = True
PRESERVE_BLACK_CANVAS = True

DEFAULTS = {
    "band_height": 12,
    "segment_width": 54,
    "gap": .6,
    "diffraction": 18,
    "phase_stride": 1.35,
    "echo_count": 2,
    "echo_spacing": 5,
    "density": .78,
    "light_threshold": 150,
    "seed": 1,
}

CONTROLS = (
    ("band_height", 3, 100, 1),
    ("segment_width", 8, 240, 1),
    ("gap", 0, 12, .1),
    ("diffraction", 0, 160, 1),
    ("phase_stride", .1, 8, .05),
    ("echo_count", 0, 5, 1),
    ("echo_spacing", 0, 50, 1),
    ("density", 0, 1, .05),
    ("light_threshold", 0, 255, 1),
    ("seed", 0, 999999, 1),
)


def _noise(value):
    """Repeatable 0..1 noise without changing global random state."""
    return math.modf(math.sin(value * 12.9898) * 43758.5453)[0] % 1


def apply(geometry, settings):
    if geometry.is_empty:
        return geometry

    x1, y1, x2, y2 = settings.get("_canvas_bounds") or geometry.bounds
    canvas = box(x1, y1, x2, y2)
    band_height = number(settings.get("band_height"), 12, 1, 2000)
    segment_width = number(settings.get("segment_width"), 54, 1, 10000)
    gap = number(settings.get("gap"), .6, 0, 100)
    diffraction = number(settings.get("diffraction"), 18, 0, 2000)
    phase_stride = number(settings.get("phase_stride"), 1.35, .01, 100)
    echo_count = int(number(settings.get("echo_count"), 2, 0, 12))
    echo_spacing = number(settings.get("echo_spacing"), 5, 0, 1000)
    density = number(settings.get("density"), .78, 0, 1)
    seed = int(number(settings.get("seed"), 1, 0, 2147483647))

    pieces = []
    row = 0
    y = y1
    while y < y2:
        # A whole band shares one phase, which keeps the shifts reading as
        # iridescent scan lines rather than unrelated random fragments.
        phase = seed * .017 + row * phase_stride
        band_shift = math.sin(phase) * diffraction
        x = x1
        column = 0
        while x < x2:
            segment = box(x, y, min(x + segment_width, x2), min(y + band_height, y2))
            if gap:
                segment = segment.buffer(-gap / 2, join_style=2)
            fragment = geometry.intersection(segment)
            if not fragment.is_empty:
                index = seed + row * 4099 + column * 131
                if _noise(index) <= density:
                    local_phase = phase + column * .618
                    offset = band_shift + math.sin(local_phase) * diffraction * .28
                    shifted = translate(fragment, xoff=offset).intersection(canvas)
                    if not shifted.is_empty:
                        pieces.append(shifted)
                    direction = -1 if math.cos(local_phase) < 0 else 1
                    for echo in range(1, echo_count + 1):
                        echo_piece = translate(
                            fragment,
                            xoff=offset + direction * echo * echo_spacing,
                        ).intersection(canvas)
                        if not echo_piece.is_empty:
                            pieces.append(echo_piece)
            x += segment_width
            column += 1
        y += band_height
        row += 1

    return unary_union(pieces) if pieces else canvas.intersection(box(0, 0, 0, 0))
