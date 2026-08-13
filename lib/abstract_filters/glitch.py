"""Structured, deterministic digital-glitch geometry transform."""

import math

from shapely.affinity import translate
from shapely.geometry import box
from shapely.ops import unary_union

from .common import number


DEFAULTS = {
    "slice_height": 18,
    "fragment_width": 70,
    "shift_amount": 28,
    "echo_count": 2,
    "echo_spacing": 9,
    "density": .55,
    "fibonacci_stride": 2,
    "vertical_jitter": 3,
    "seed": 1,
}
CONTROLS = (
    ("slice_height", 3, 100, 1),
    ("fragment_width", 8, 240, 1),
    ("shift_amount", 0, 180, 1),
    ("echo_count", 0, 5, 1),
    ("echo_spacing", 0, 80, 1),
    ("density", 0, 1, .05),
    ("fibonacci_stride", 1, 8, 1),
    ("vertical_jitter", 0, 60, 1),
    ("seed", 0, 999999, 1),
)

_FIBONACCI = (1, 1, 2, 3, 5, 8, 13, 21)


def _noise(value):
    """A repeatable 0..1 pseudo-random value without global RNG state."""
    return math.modf(math.sin(value * 12.9898) * 43758.5453)[0] % 1


def apply(geometry, settings):
    if geometry.is_empty:
        return geometry

    x1, y1, x2, y2 = settings.get("_canvas_bounds") or geometry.bounds
    slice_height = number(settings.get("slice_height"), 18, 1, 1000)
    fragment_width = number(settings.get("fragment_width"), 70, 1, 10000)
    shift_amount = number(settings.get("shift_amount"), 28, 0, 10000)
    echo_count = int(number(settings.get("echo_count"), 2, 0, 12))
    echo_spacing = number(settings.get("echo_spacing"), 9, 0, 10000)
    density = number(settings.get("density"), .55, 0, 1)
    fibonacci_stride = int(number(settings.get("fibonacci_stride"), 2, 1, 32))
    vertical_jitter = number(settings.get("vertical_jitter"), 3, 0, 10000)
    seed = int(number(settings.get("seed"), 1, 0, 9999999))

    pieces = []
    row = 0
    y = y1
    while y < y2:
        column = 0
        x = x1
        while x < x2:
            fragment = geometry.intersection(
                box(x, y, min(x + fragment_width, x2), min(y + slice_height, y2))
            )
            if not fragment.is_empty:
                index = row * 4099 + column * 131 + seed
                if _noise(index) <= density:
                    # Travel up and down the Fibonacci sequence rather than
                    # resetting abruptly, producing repeated growing and
                    # shrinking signal bursts across neighboring fragments.
                    fib_cycle = len(_FIBONACCI) * 2 - 2
                    fib_index = (row * fibonacci_stride + column + seed) % fib_cycle
                    if fib_index >= len(_FIBONACCI):
                        fib_index = fib_cycle - fib_index
                    fib = _FIBONACCI[fib_index]
                    scale = fib / _FIBONACCI[-1]
                    direction = -1 if (row + column + seed) % 2 else 1
                    x_offset = direction * shift_amount * scale
                    y_offset = (_noise(index + 17) - .5) * vertical_jitter
                    pieces.append(translate(fragment, xoff=x_offset, yoff=y_offset))
                    for echo in range(1, echo_count + 1):
                        pieces.append(translate(
                            fragment,
                            xoff=x_offset + direction * echo * echo_spacing * scale,
                            yoff=y_offset,
                        ))
                else:
                    pieces.append(fragment)
            x += fragment_width
            column += 1
        y += slice_height
        row += 1

    return unary_union(pieces) if pieces else geometry.intersection(box(0, 0, 0, 0))
