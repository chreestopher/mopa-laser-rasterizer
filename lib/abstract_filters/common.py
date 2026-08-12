import math

from shapely.geometry import box
from shapely.ops import unary_union


def number(value, default, low=None, high=None):
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = float(default)
    if not math.isfinite(value):
        value = float(default)
    return min(high, max(low, value)) if low is not None and high is not None else value


def cell_union(geometry, cells, gap):
    pieces = []
    for cell in cells:
        tile = cell.buffer(-gap / 2, join_style=2) if gap else cell
        clipped = geometry.intersection(tile)
        if not clipped.is_empty:
            pieces.append(clipped)
    return unary_union(pieces) if pieces else geometry.intersection(box(0, 0, 0, 0))


def radial_center(geometry, settings):
    bounds = settings.get("_canvas_bounds") or geometry.bounds
    x1, y1, x2, y2 = bounds
    cx = x1 + (x2 - x1) * number(settings.get("center_x"), .5, -1, 2)
    cy = y1 + (y2 - y1) * number(settings.get("center_y"), .5, -1, 2)
    radius = max(math.hypot(x - cx, y - cy) for x, y in
                 ((x1, y1), (x2, y1), (x2, y2), (x1, y2))) or 1
    return cx, cy, radius
