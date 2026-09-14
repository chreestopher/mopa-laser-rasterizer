"""Vector approximation of repeated-compression, 'deep fried meme' artifacts."""

import math

from shapely.affinity import translate
from shapely.geometry import box
from shapely.ops import unary_union

from .common import number


DEFAULTS = {
    "block_size": 24,
    "band_height": 34,
    "compression_gap": .7,
    "smear_amount": 18,
    "echo_count": 2,
    "echo_spacing": 5,
    "degradation": .35,
    "seed": 1,
}

CONTROLS = (
    ("block_size", 4, 120, 1),
    ("band_height", 4, 180, 1),
    ("compression_gap", 0, 8, .1),
    ("smear_amount", 0, 120, 1),
    ("echo_count", 0, 5, 1),
    ("echo_spacing", 0, 40, 1),
    ("degradation", 0, 1, .05),
    ("seed", 0, 999999, 1),
)


def _noise(value):
    """Return repeatable pseudo-random values without global random state."""
    return math.modf(math.sin(value * 12.9898) * 43758.5453)[0] % 1


def apply(geometry, settings):
    if geometry.is_empty:
        return geometry

    x1, y1, x2, y2 = settings.get("_canvas_bounds") or geometry.bounds
    canvas = box(x1, y1, x2, y2)
    block_size = number(settings.get("block_size"), 24, 1, 1000)
    band_height = number(settings.get("band_height"), 34, 1, 2000)
    compression_gap = number(settings.get("compression_gap"), .7, 0, 100)
    smear_amount = number(settings.get("smear_amount"), 18, 0, 2000)
    echo_count = int(number(settings.get("echo_count"), 2, 0, 10))
    echo_spacing = number(settings.get("echo_spacing"), 5, 0, 1000)
    degradation = number(settings.get("degradation"), .35, 0, 1)
    seed = int(number(settings.get("seed"), 1, 0, 2147483647))

    pieces = []
    row = 0
    y = y1
    while y < y2:
        # Each horizontal band gets one coherent shift, imitating the way a
        # mangled codec or screen capture drags a whole scanline sideways.
        band_noise = _noise(seed + row * 7919)
        band_offset = (band_noise - .5) * 2 * smear_amount
        x = x1
        column = 0
        while x < x2:
            tile = box(x, y, min(x + block_size, x2), min(y + band_height, y2))
            if compression_gap:
                tile = tile.buffer(-compression_gap / 2, join_style=2)
            fragment = geometry.intersection(tile)
            if not fragment.is_empty:
                index = seed + row * 4099 + column * 131
                # Higher degradation drops more tiles, leaving familiar
                # JPEG-like damage rather than uniformly perfect blocks.
                if _noise(index + 31) >= degradation * .55:
                    local_offset = (_noise(index + 67) - .5) * smear_amount * .42
                    direction = -1 if _noise(index + 101) < .5 else 1
                    shifted = translate(fragment, xoff=band_offset + local_offset)
                    pieces.append(shifted.intersection(canvas))
                    # Repeated, increasingly faint-looking copies become
                    # stacked vector echoes; this is the copy/paste/screenshot
                    # loop at the heart of the deep-fried look.
                    for echo in range(1, echo_count + 1):
                        if _noise(index + echo * 179) < .35 + degradation * .55:
                            echo_piece = translate(
                                fragment,
                                xoff=band_offset + local_offset + direction * echo * echo_spacing,
                            )
                            pieces.append(echo_piece.intersection(canvas))
            x += block_size
            column += 1
        y += band_height
        row += 1

    return unary_union([piece for piece in pieces if not piece.is_empty]) if pieces else canvas.intersection(box(0, 0, 0, 0))
