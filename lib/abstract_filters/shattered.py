import math

import numpy as np
from shapely.affinity import rotate, translate
from shapely.geometry import MultiPoint, box
from shapely.ops import unary_union, voronoi_diagram

from .common import number


DEFAULTS = {
    "min_shard_size": 8,
    "max_shard_size": 32,
    "density": .6,
    "minimum_gap": .7,
    "gap_variation": 2.2,
    "horizontal_spread": 12,
    "fall_distance": 20,
    "gravity_bias": 1.4,
    "rotation": 22,
    "break_origin_x": .5,
    "break_origin_y": .35,
    "seed": 1,
}

CONTROLS = (
    ("min_shard_size", 2, 80, 1),
    ("max_shard_size", 4, 160, 1),
    ("density", .1, 1, .05),
    ("minimum_gap", 0, 10, .1),
    ("gap_variation", 0, 15, .1),
    ("horizontal_spread", 0, 100, 1),
    ("fall_distance", 0, 160, 1),
    ("gravity_bias", .2, 4, .1),
    ("rotation", 0, 180, 1),
    ("break_origin_x", 0, 1, .01),
    ("break_origin_y", 0, 1, .01),
    ("seed", 0, 999999, 1),
)


def _shard_field(bounds, settings):
    x1, y1, x2, y2 = bounds
    width, height = max(x2 - x1, 1), max(y2 - y1, 1)
    minimum = number(settings.get("min_shard_size"), 8, 2, 500)
    maximum = number(settings.get("max_shard_size"), 32, minimum, 1000)
    if maximum < minimum:
        minimum, maximum = maximum, minimum
    density = number(settings.get("density"), .6, .05, 2)
    seed = int(number(settings.get("seed"), 1, 0, 2147483647))
    rng = np.random.default_rng(seed)

    average = (minimum + maximum) / 2
    target_count = max(4, int(width * height / max(average * average, 1) * (0.35 + density * 1.65)))
    points = []
    attempts = 0
    while len(points) < target_count and attempts < target_count * 40:
        attempts += 1
        point = (rng.uniform(x1, x2), rng.uniform(y1, y2))
        local_spacing = rng.uniform(minimum, maximum) * (1.15 - density * .55)
        if all((point[0] - px) ** 2 + (point[1] - py) ** 2 >= local_spacing ** 2 for px, py in points):
            points.append(point)
    if len(points) < 4:
        points.extend(((x1, y1), (x2, y1), (x2, y2), (x1, y2)))

    envelope = box(x1, y1, x2, y2).buffer(maximum * 2)
    cells = voronoi_diagram(MultiPoint(points), envelope=envelope).geoms
    return list(cells), rng


def apply(geometry, settings):
    bounds = settings.get("_canvas_bounds") or geometry.bounds
    x1, y1, x2, y2 = bounds
    width, height = max(x2 - x1, 1), max(y2 - y1, 1)
    origin_x = x1 + width * number(settings.get("break_origin_x"), .5, 0, 1)
    origin_y = y1 + height * number(settings.get("break_origin_y"), .35, 0, 1)
    minimum_gap = number(settings.get("minimum_gap"), .7, 0, 100)
    gap_variation = number(settings.get("gap_variation"), 2.2, 0, 100)
    spread = number(settings.get("horizontal_spread"), 12, 0, 1000)
    fall = number(settings.get("fall_distance"), 20, 0, 2000)
    gravity = number(settings.get("gravity_bias"), 1.4, .1, 8)
    tumble = number(settings.get("rotation"), 22, 0, 720)
    cells, rng = _shard_field(bounds, settings)
    pieces = []

    for cell in cells:
        center = cell.centroid
        normalized_y = min(1, max(0, (center.y - y1) / height))
        distance_from_break = math.hypot(
            (center.x - origin_x) / width,
            (center.y - origin_y) / height,
        )
        motion = min(1.5, .15 + normalized_y ** gravity + distance_from_break * .35)
        gap = minimum_gap + rng.uniform(0, gap_variation)
        direction = -1 if center.x < origin_x else 1
        dx = direction * spread * motion * rng.uniform(.35, 1.15)
        dx += rng.uniform(-spread * .2, spread * .2)
        dy = fall * motion * rng.uniform(.45, 1.2)
        angle = rng.uniform(-tumble, tumble) * motion

        shard = cell.buffer(-gap / 2, join_style=2) if gap else cell
        clipped = geometry.intersection(shard)
        if clipped.is_empty:
            continue
        moved = rotate(clipped, angle, origin=(center.x, center.y))
        moved = translate(moved, xoff=dx, yoff=dy)
        if not moved.is_empty:
            pieces.append(moved)

    return unary_union(pieces) if pieces else geometry.intersection(box(0, 0, 0, 0))
