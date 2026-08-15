import math

from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

from .common import number


DEFAULTS = {
    "cell_size": 32,
    "line_width": .45,
    "rings": 3,
    "petals": 6,
    "rotation": 0,
    "clearance": 2,
    "foreground_min_percent": .15,
    "seed": 1,
}
CONTROLS = (
    ("cell_size", 8, 120, 1),
    ("line_width", .1, 4, .05),
    ("rings", 1, 8, 1),
    ("petals", 3, 12, 1),
    ("rotation", 0, 360, 1),
    ("clearance", 0, 20, .25),
    ("foreground_min_percent", 0, 20, .05),
    ("seed", 0, 999999, 1),
)

# The raster pipeline isolates the subject and invokes background_geometry once.
BACKGROUND_GENERATOR = True
PRESERVE_BACKGROUND_TRANSPARENCY = True
SETTING_NAME = "holographic"
LAYER_NAME = "Holographic"
LAYER_COLOR = "#FEFEFE"


def apply(geometry, settings):
    """Sacred leaves subject geometry intact; its pattern is background-only."""
    return geometry


def background_geometry(subject, settings):
    bounds = settings.get("_canvas_bounds") or subject.bounds
    x1, y1, x2, y2 = bounds
    size = number(settings.get("cell_size"), 32, 8, 500)
    width = number(settings.get("line_width"), .45, .05, 20)
    rings = int(number(settings.get("rings"), 3, 1, 16))
    petals = int(number(settings.get("petals"), 6, 3, 24))
    rotation = math.radians(number(settings.get("rotation"), 0, 0, 360))
    clearance = number(settings.get("clearance"), 2, 0, 100)
    seed = int(number(settings.get("seed"), 1, 0, 2147483647))
    phase = (seed * .6180339887498949 % 1) * size
    row_height = size * math.sqrt(3) / 2
    strokes = []

    row_start = math.floor((y1 - size - phase) / row_height)
    row_end = math.ceil((y2 + size - phase) / row_height)
    for row in range(row_start, row_end + 1):
        cy = row * row_height + phase
        offset = size / 2 if row & 1 else 0
        col_start = math.floor((x1 - size - offset - phase) / size)
        col_end = math.ceil((x2 + size - offset - phase) / size)
        for col in range(col_start, col_end + 1):
            cx = col * size + offset + phase
            for ring in range(1, rings + 1):
                radius = size * .42 * ring / rings
                strokes.append(Point(cx, cy).buffer(radius).boundary)
            petal_radius = size * .22
            orbit = size * .19
            for petal in range(petals):
                angle = rotation + 2 * math.pi * petal / petals
                px = cx + math.cos(angle) * orbit
                py = cy + math.sin(angle) * orbit
                strokes.append(Point(px, py).buffer(petal_radius).boundary)
            vertices = [
                (cx + math.cos(rotation + 2 * math.pi * i / petals) * size * .42,
                 cy + math.sin(rotation + 2 * math.pi * i / petals) * size * .42)
                for i in range(petals)
            ]
            strokes.append(LineString(vertices + [vertices[0]]))

    canvas = box(x1, y1, x2, y2)
    available = canvas.difference(subject.buffer(clearance))
    pattern = unary_union(strokes).buffer(width / 2, cap_style=2, join_style=2)
    return pattern.intersection(available)
