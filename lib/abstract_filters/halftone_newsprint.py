"""Color halftone/newsprint geometry built on one shared matrix.

Each matrix cell samples the source artwork, belongs to exactly one source
swatch, and emits one variable-size mark.  Because ownership is decided before
geometry is emitted, different LightBurn layers cannot receive duplicate dots
in the same cell.
"""

import math

from shapely import affinity
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union
from shapely.prepared import prep

from .common import number


USES_SOURCE_LUMINANCE = True
PRESERVE_SOURCE_BLACK = True

DEFAULTS = {
    "cell_size_mm": 0.6,
    "minimum_dot_ratio": 0.48,
    "maximum_dot_ratio": 0.97,
    "non_black_dot_density": 2.3,
    "tone_curve": 0.75,
    "contrast": 2.0,
    "grid_angle": -45.0,
    "square_dots": 0,
    "invert": 0,
    "black_only": 0,
}

VECTOR_DEFAULTS = {
    "min_island_area": 0,
    "simplification_factor": 0.0,
    "smoothing_radius": 0.001,
}

CONTROLS = (
    ("cell_size_mm", 0.2, 1.0, 0.05),
    ("minimum_dot_ratio", 0.16, 0.8, 0.01),
    ("maximum_dot_ratio", 0.94, 1.0, 0.01),
    ("non_black_dot_density", 0.6, 4.0, 0.05),
    ("tone_curve", 0.2, 1.3, 0.05),
    ("contrast", 1.0, 3.0, 0.05),
    ("grid_angle", -90, 0, 1),
    ("square_dots", 0, 1, 1),
    ("invert", 0, 1, 1),
    ("black_only", 0, 1, 1),
)

MAXIMUM_CELLS = 250_000
PROGRESS_BATCHES = 10


def _regular_polygon(x, y, radius, sides, rotation_degrees=0):
    rotation = math.radians(rotation_degrees - 90)
    return Polygon(
        [
            (
                x + radius * math.cos(rotation + 2 * math.pi * index / sides),
                y + radius * math.sin(rotation + 2 * math.pi * index / sides),
            )
            for index in range(sides)
        ]
    )


def _star(x, y, radius, rotation_degrees=0):
    rotation = math.radians(rotation_degrees - 90)
    points = []
    for index in range(10):
        point_radius = radius if index % 2 == 0 else radius * 0.46
        angle = rotation + index * math.pi / 5
        points.append((x + point_radius * math.cos(angle), y + point_radius * math.sin(angle)))
    return Polygon(points)


def _glyph_mark(shape, x, y, half_size, rotation_degrees=0):
    """Build one bounded solid glyph for the shared halftone matrix."""
    center = Point(x, y)
    shape = str(shape or "circle").strip().lower()
    if shape == "circle":
        return center.buffer(half_size, quad_segs=8)
    if shape == "square":
        mark = box(x - half_size, y - half_size, x + half_size, y + half_size)
    elif shape == "diamond":
        mark = _regular_polygon(x, y, half_size, 4)
    elif shape == "triangle":
        mark = _regular_polygon(x, y, half_size, 3)
    elif shape == "hexagon":
        mark = _regular_polygon(x, y, half_size, 6)
    elif shape == "octagon":
        mark = _regular_polygon(x, y, half_size, 8)
    elif shape == "star":
        mark = _star(x, y, half_size)
    elif shape == "cross":
        arm = half_size * 0.42
        mark = unary_union((
            box(x - arm, y - half_size, x + arm, y + half_size),
            box(x - half_size, y - arm, x + half_size, y + arm),
        ))
    elif shape == "bar":
        mark = box(x - half_size, y - half_size * 0.32, x + half_size, y + half_size * 0.32)
    else:
        return center.buffer(half_size, quad_segs=8)
    if rotation_degrees:
        mark = affinity.rotate(mark, rotation_degrees, origin=(x, y))
    return mark


def apply(geometry, settings):
    """Preserve cleaned regions until all swatches can share one matrix."""
    return geometry


def _rotate_point(x, y, center_x, center_y, radians):
    relative_x = x - center_x
    relative_y = y - center_y
    cosine = math.cos(radians)
    sine = math.sin(radians)
    return (
        center_x + relative_x * cosine - relative_y * sine,
        center_y + relative_x * sine + relative_y * cosine,
    )


def _sample_luminance(image, x, y, bounds):
    if image is None or not getattr(image, "size", None):
        return 127.0
    width, height = image.size
    min_x, min_y, max_x, max_y = bounds
    x_fraction = (x - min_x) / max(max_x - min_x, 1e-9)
    y_fraction = (y - min_y) / max(max_y - min_y, 1e-9)
    pixel_x = min(width - 1, max(0, math.floor(x_fraction * width)))
    pixel_y = min(height - 1, max(0, math.floor(y_fraction * height)))
    value = image.getpixel((pixel_x, pixel_y))
    if isinstance(value, (tuple, list)):
        value = sum(value[:3]) / max(1, len(value[:3]))
    return number(value, 127, 0, 255)


def _dot_ratio(luminance, settings):
    darkness = 1.0 - luminance / 255.0
    if number(settings.get("invert"), 0, 0, 1) >= 0.5:
        darkness = 1.0 - darkness
    # Keep accepting the filter's established backend bounds so saved jobs and
    # API callers remain compatible even though the UI now focuses on the
    # engraving-validated portion of the parameter space.
    contrast = number(settings.get("contrast"), 2.0, 0.2, 3.0)
    darkness = min(1.0, max(0.0, (darkness - 0.5) * contrast + 0.5))
    curve = number(settings.get("tone_curve"), 0.75, 0.2, 5.0)
    darkness = darkness ** curve

    minimum = number(settings.get("minimum_dot_ratio"), 0.48, 0.0, 0.8)
    maximum = number(settings.get("maximum_dot_ratio"), 0.97, 0.1, 1.0)
    minimum, maximum = min(minimum, maximum), max(minimum, maximum)
    # Interpolate area, rather than diameter, so tone changes remain visually
    # proportional for both circles and squares.
    area_ratio = minimum * minimum + darkness * (
        maximum * maximum - minimum * minimum
    )
    return math.sqrt(max(0.0, area_ratio))


def _adjust_dot_ratio_for_color(ratio, color_hex, black_only, settings):
    """Scale non-Black mark area while keeping every mark inside its cell."""
    if black_only or str(color_hex).upper() == "#000000":
        return ratio
    density = number(settings.get("non_black_dot_density"), 2.3, 0.25, 4.0)
    # Geometry uses a linear ratio, so sqrt(density) produces the requested
    # area multiplier for both circles and squares.
    return min(1.0, ratio * math.sqrt(density))


def _owner(point, prepared_layers):
    for color_hex, prepared_geometry in prepared_layers:
        if prepared_geometry.covers(point):
            return color_hex
    return None


def remap_layers(processed_layers, target_colors, settings):
    """Replace source regions with non-overlapping, color-owned halftone dots."""
    black_only = number(settings.get("black_only"), 0, 0, 1) >= 0.5
    black_hex = "#000000"
    if black_only and black_hex not in target_colors:
        raise ValueError(
            "Halftone Newsprint Black Only mode requires the official Black "
            "swatch to be assigned to a Cut Setting Entry in the selected palette."
        )
    bounds = settings.get("_canvas_bounds")
    if not bounds or len(bounds) != 4:
        nonempty = [geometry for geometry in processed_layers.values() if not geometry.is_empty]
        if not nonempty:
            return {}
        bounds = unary_union(nonempty).bounds
    min_x, min_y, max_x, max_y = map(float, bounds)
    if max_x <= min_x or max_y <= min_y:
        return {}

    scale_factor = number(settings.get("_scale_factor"), 1.0)
    if scale_factor <= 0:
        scale_factor = 1.0
    cell_size_mm = number(settings.get("cell_size_mm"), 0.6, 0.2, 5.0)
    cell_size = cell_size_mm / scale_factor
    angle = number(settings.get("grid_angle"), -45.0, -90, 45)
    radians = math.radians(angle)
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2

    local_corners = [
        _rotate_point(x, y, center_x, center_y, -radians)
        for x, y in ((min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y))
    ]
    local_min_x = min(point[0] for point in local_corners)
    local_max_x = max(point[0] for point in local_corners)
    local_min_y = min(point[1] for point in local_corners)
    local_max_y = max(point[1] for point in local_corners)
    column_count = max(1, math.ceil((local_max_x - local_min_x) / cell_size))
    row_count = max(1, math.ceil((local_max_y - local_min_y) / cell_size))
    total_cells = column_count * row_count
    if total_cells > MAXIMUM_CELLS:
        raise ValueError(
            "Halftone Newsprint would create "
            f"{total_cells:,} matrix cells. Increase Cell Size MM until the "
            f"grid contains no more than {MAXIMUM_CELLS:,} cells."
        )

    ordered_colors = [
        color_hex for color_hex in target_colors if color_hex in processed_layers
    ]
    ordered_colors.extend(
        color_hex for color_hex in processed_layers if color_hex not in ordered_colors
    )
    prepared_layers = [
        (color_hex, prep(processed_layers[color_hex]))
        for color_hex in ordered_colors
        if not processed_layers[color_hex].is_empty
    ]
    if not prepared_layers:
        return {}

    logger = settings.get("_progress_logger")
    progress_name = str(settings.get("_progress_name") or "Halftone Newsprint")
    if callable(logger):
        logger(
            f"{progress_name}: starting "
            f"{column_count} x {row_count} shared-cell matrix ({total_cells:,} cells)."
        )

    canvas = box(min_x, min_y, max_x, max_y)
    tone_image = settings.get("_angle_image")
    square_dots = number(settings.get("square_dots"), 0, 0, 1) >= 0.5
    glyph_shape = str(settings.get("_glyph_shape") or ("square" if square_dots else "circle"))
    glyph_rotation = number(settings.get("_glyph_rotation"), 0, -180, 180)
    glyph_seed = int(number(settings.get("_glyph_seed"), 1, 0, 999999))
    mixed_shapes = ("circle", "square", "diamond", "triangle", "hexagon", "octagon", "star", "cross", "bar")
    pieces = (
        {black_hex: []}
        if black_only
        else {color_hex: [] for color_hex, _ in prepared_layers}
    )
    progress_interval = max(1, math.ceil(row_count / PROGRESS_BATCHES))
    last_reported_row = 0

    for row_index in range(row_count):
        local_y = local_min_y + (row_index + 0.5) * cell_size
        for column_index in range(column_count):
            local_x = local_min_x + (column_index + 0.5) * cell_size
            x, y = _rotate_point(
                local_x, local_y, center_x, center_y, radians
            )
            center = Point(x, y)
            source_color_hex = _owner(center, prepared_layers)
            if source_color_hex is None:
                continue
            color_hex = black_hex if black_only else source_color_hex
            ratio = _dot_ratio(
                _sample_luminance(tone_image, x, y, bounds), settings
            )
            ratio = _adjust_dot_ratio_for_color(
                ratio, source_color_hex, black_only, settings
            )
            if ratio <= 1e-9:
                continue
            half_size = cell_size * ratio / 2
            cell_shape = glyph_shape
            if cell_shape == "mixed":
                cell_shape = mixed_shapes[
                    (row_index * 73856093 + column_index * 19349663 + glyph_seed * 83492791)
                    % len(mixed_shapes)
                ]
            mark = _glyph_mark(
                cell_shape, x, y, half_size, angle + glyph_rotation
            )
            mark = mark.intersection(canvas)
            if not mark.is_empty:
                pieces[color_hex].append(mark)

        completed_rows = row_index + 1
        if callable(logger) and (
            completed_rows % progress_interval == 0 or completed_rows == row_count
        ):
            logger(
                f"{progress_name}: completed rows "
                f"{last_reported_row + 1}-{completed_rows} "
                f"of {row_count}."
            )
            last_reported_row = completed_rows

    output = {
        color_hex: unary_union(color_pieces)
        for color_hex, color_pieces in pieces.items()
        if color_pieces
    }
    if callable(logger):
        logger(
            f"{progress_name}: matrix complete with "
            f"{sum(len(items) for items in pieces.values()):,} marks across "
            f"{len(output)} swatch layers."
        )
    return output
