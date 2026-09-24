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
from .packing import (
    SpatialCollisionIndex,
    independent_rotation_degrees,
    placement_variant,
)


USES_SOURCE_LUMINANCE = True
PRESERVE_SOURCE_BLACK = True

DEFAULTS = {
    "dot_size_source": "source_brightness",
    "seed": 1,
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
    "tight_pack_geometry": 0,
    "random_rotation": 0,
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


def _glyph_mark(shape, x, y, half_size, rotation_degrees=0, custom_template=None):
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
    elif shape == "custom" and custom_template is not None:
        mark = affinity.scale(
            custom_template,
            xfact=half_size * 2,
            yfact=half_size * 2,
            origin=(0, 0),
        )
        mark = affinity.translate(mark, xoff=x, yoff=y)
    elif shape in {
        "skull", "heart", "space_invader", "ghost", "bat", "alien_head",
        "paw_print", "fish_scale", "puzzle_piece",
    }:
        # Import lazily so the shared glyph renderer can reuse the exact
        # Krasnow silhouettes without introducing an import cycle.
        from . import krasnow_grating
        mark = krasnow_grating.solid_glyph_shape(shape, x, y, half_size * 2)
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


def _seeded_dot_ratio(row_index, column_index, seed, settings):
    """Choose a stable ratio across the configured range for one matrix cell."""
    value = placement_variant(row_index, column_index, seed)
    # Mix the existing stable placement value so adjacent cells do not form a
    # visible linear ramp even though the result remains repeatable per seed.
    value ^= value >> 16
    value = (value * 0x45D9F3B) & 0x7FFFFFFF
    value ^= value >> 16
    amount = value / 0x7FFFFFFF
    minimum = number(settings.get("minimum_dot_ratio"), 0.48, 0.0, 0.8)
    maximum = number(settings.get("maximum_dot_ratio"), 0.97, 0.1, 1.0)
    minimum, maximum = min(minimum, maximum), max(minimum, maximum)
    area_ratio = minimum * minimum + amount * (
        maximum * maximum - minimum * minimum
    )
    return math.sqrt(max(0.0, area_ratio))


def _adjust_dot_ratio_for_color(ratio, color_hex, black_only, settings):
    """Scale non-Black mark area while keeping every mark inside its cell."""
    if black_only or str(color_hex).upper() == "#000000":
        return ratio
    density = number(settings.get("non_black_dot_density"), 2.3, 0.25, 4.0)
    if number(settings.get("_preserve_dot_ratio_range"), 0, 0, 1) >= 0.5:
        minimum = number(settings.get("minimum_dot_ratio"), 0.48, 0.0, 0.8)
        maximum = number(settings.get("maximum_dot_ratio"), 0.97, 0.1, 1.0)
        minimum, maximum = min(minimum, maximum), max(minimum, maximum)
        minimum_area = minimum * minimum
        maximum_area = maximum * maximum
        if maximum_area <= minimum_area + 1e-12:
            return minimum
        position = min(
            1.0,
            max(0.0, (ratio * ratio - minimum_area) / (maximum_area - minimum_area)),
        )
        # Increase colored engraved area without clipping most marks to one
        # identical full-cell size. Both user-selected endpoints remain exact.
        boosted_position = 1.0 - ((1.0 - position) ** density)
        return math.sqrt(
            minimum_area + boosted_position * (maximum_area - minimum_area)
        )
    # Geometry uses a linear ratio, so sqrt(density) produces the requested
    # area multiplier for both circles and squares.
    return min(1.0, ratio * math.sqrt(density))


def _owner(point, prepared_layers):
    for color_hex, prepared_geometry in prepared_layers:
        if prepared_geometry.covers(point):
            return color_hex
    return None


def _exclusive_layers(layer_geometries, ordered_colors, canvas):
    """Clip layers to the canvas and give every point one deterministic owner."""
    claimed = None
    exclusive = {}
    for color_hex in ordered_colors:
        geometry = layer_geometries.get(color_hex)
        if geometry is None or geometry.is_empty:
            continue
        geometry = geometry.intersection(canvas)
        if claimed is not None and not claimed.is_empty:
            geometry = geometry.difference(claimed)
        if geometry.is_empty:
            continue
        exclusive[color_hex] = geometry
        claimed = geometry if claimed is None else unary_union((claimed, geometry))
    return exclusive


def _assert_exclusive_layers(layer_geometries, tolerance=1e-9):
    """Refuse to export glyph geometry engraved by more than one setting."""
    nonempty = [
        (color_hex, geometry)
        for color_hex, geometry in layer_geometries.items()
        if geometry is not None and not geometry.is_empty
    ]
    for index, (left_color, left_geometry) in enumerate(nonempty):
        for right_color, right_geometry in nonempty[index + 1:]:
            if not left_geometry.intersects(right_geometry):
                continue
            overlap_area = left_geometry.intersection(right_geometry).area
            if overlap_area > tolerance:
                raise ValueError(
                    "Glyph geometry overlap validation failed: "
                    f"{left_color} and {right_color} overlap by {overlap_area:.12g}."
                )


def remap_layers(processed_layers, target_colors, settings):
    """Replace source regions with non-overlapping, color-owned halftone dots."""
    black_only = number(settings.get("black_only"), 0, 0, 1) >= 0.5
    invert_fill = number(settings.get("invert_fill"), 0, 0, 1) >= 0.5
    if black_only and invert_fill:
        raise ValueError("Invert Fill cannot be combined with Black Only.")
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
    tight_pack = number(
        settings.get("_tight_pack_geometry", settings.get("tight_pack_geometry")),
        0, 0, 1,
    ) >= .5
    random_rotation = number(
        settings.get("_random_rotation", settings.get("random_rotation")),
        0, 0, 1,
    ) >= .5
    angle = number(settings.get("grid_angle"), -45.0, -90, 45)
    square_dots = number(settings.get("square_dots"), 0, 0, 1) >= 0.5
    glyph_shape = str(settings.get("_glyph_shape") or ("square" if square_dots else "circle"))
    staggered_row_step = None
    if glyph_shape in {
        "skull", "heart", "space_invader", "ghost", "bat", "alien_head",
        "paw_print", "fish_scale",
    }:
        from . import krasnow_grating
        staggered_row_step = krasnow_grating.solid_glyph_row_step(glyph_shape)
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
    row_step = cell_size * staggered_row_step if staggered_row_step else cell_size
    if tight_pack:
        tight_column_step = cell_size * .82
        tight_row_step = cell_size * .72
        column_count = max(
            1, math.ceil((local_max_x - local_min_x) / tight_column_step) + 3
        )
        row_count = max(
            1, math.ceil((local_max_y - local_min_y) / tight_row_step) + 3
        )
    elif staggered_row_step:
        column_count = max(1, math.ceil((local_max_x - local_min_x) / cell_size) + 2)
        row_count = max(1, math.ceil((local_max_y - local_min_y) / row_step) + 2)
    else:
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
    canvas = box(min_x, min_y, max_x, max_y)
    exclusive_source_layers = _exclusive_layers(
        processed_layers, ordered_colors, canvas
    )
    prepared_layers = [
        (color_hex, prep(exclusive_source_layers[color_hex]))
        for color_hex in ordered_colors
        if color_hex in exclusive_source_layers
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

    tone_image = settings.get("_angle_image")
    glyph_size_source = str(
        settings.get("_glyph_size_source")
        or settings.get("dot_size_source")
        or "source_brightness"
    ).strip().lower()
    glyph_rotation = number(settings.get("_glyph_rotation"), 0, -180, 180)
    glyph_seed = int(number(
        settings.get("_glyph_seed", settings.get("seed", 1)), 1, 0, 999999
    ))
    custom_glyph_template = settings.get("_custom_glyph_template")
    mixed_shapes = ("circle", "square", "diamond", "triangle", "hexagon", "octagon", "star", "cross", "bar")
    pieces = (
        {black_hex: []}
        if black_only
        else {color_hex: [] for color_hex, _ in prepared_layers}
    )
    progress_interval = max(1, math.ceil(row_count / PROGRESS_BATCHES))
    last_reported_row = 0

    if tight_pack:
        # A staggered, slightly compressed candidate lattice lets concave and
        # small tone-scaled marks occupy gaps in neighboring rows. The spatial
        # index rejects actual overlaps, so dense candidates never create a
        # double-engraved area. Regular mode above remains byte-for-byte stable.
        collision_index = SpatialCollisionIndex(cell_size)
    else:
        collision_index = None

    for row_index in range(row_count):
        if tight_pack:
            local_y = local_min_y - cell_size / 2 + row_index * tight_row_step
            row_x_offset = (row_index & 1) * tight_column_step / 2
        elif staggered_row_step:
            local_y = local_min_y - cell_size / 2 + row_index * row_step
            row_x_offset = (row_index & 1) * cell_size / 2
        else:
            local_y = local_min_y + (row_index + 0.5) * cell_size
            row_x_offset = 0
        for column_index in range(column_count):
            if tight_pack:
                local_x = (
                    local_min_x - cell_size / 2
                    + column_index * tight_column_step + row_x_offset
                )
                variant = placement_variant(row_index, column_index, glyph_seed)
                local_x += (((variant >> 3) % 5) - 2) * cell_size * .018
                local_y_for_mark = local_y + (((variant >> 7) % 5) - 2) * cell_size * .018
            elif staggered_row_step:
                local_x = local_min_x - cell_size / 2 + column_index * cell_size + row_x_offset
                local_y_for_mark = local_y
            else:
                local_x = local_min_x + (column_index + 0.5) * cell_size
                local_y_for_mark = local_y
            x, y = _rotate_point(
                local_x, local_y_for_mark, center_x, center_y, radians
            )
            center = Point(x, y)
            source_color_hex = _owner(center, prepared_layers)
            if source_color_hex is None:
                continue
            color_hex = black_hex if black_only else source_color_hex
            ratio = (
                _seeded_dot_ratio(row_index, column_index, glyph_seed, settings)
                if glyph_size_source == "seeded_variation"
                else _dot_ratio(_sample_luminance(tone_image, x, y, bounds), settings)
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
            independent_rotation = 0
            if random_rotation:
                independent_rotation = independent_rotation_degrees(
                    row_index, column_index, glyph_seed
                )
            elif tight_pack:
                independent_rotation = (-18, -9, 0, 9, 18)[variant % 5]
            mark = _glyph_mark(
                cell_shape,
                x,
                y,
                half_size,
                angle + glyph_rotation + independent_rotation,
                custom_template=custom_glyph_template,
            )
            mark = mark.intersection(canvas)
            if tight_pack:
                # Keep each packed mark in the source swatch that selected it;
                # close packing must never move geometry into another color.
                mark = mark.intersection(exclusive_source_layers[source_color_hex])
                if mark.is_empty or collision_index.overlaps(mark):
                    continue
                collision_index.add(mark)
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

    mark_layers = {
        color_hex: unary_union(color_pieces)
        for color_hex, color_pieces in pieces.items()
        if color_pieces
    }
    if invert_fill:
        output = {}
        for color_hex, source_geometry in exclusive_source_layers.items():
            cutouts = mark_layers.get(color_hex)
            carved = (
                source_geometry.difference(cutouts)
                if cutouts is not None and not cutouts.is_empty
                else source_geometry
            )
            if not carved.is_empty:
                output[color_hex] = carved
    else:
        output_order = [
            color_hex for color_hex in ordered_colors if color_hex in mark_layers
        ]
        if black_only:
            output_order = [black_hex]
        output = _exclusive_layers(mark_layers, output_order, canvas)
    _assert_exclusive_layers(output)
    if callable(logger):
        logger(
            f"{progress_name}: matrix complete with "
            f"{sum(len(items) for items in pieces.values()):,} "
            f"{'cutouts' if invert_fill else 'marks'} across "
            f"{len(output)} swatch layers."
        )
    return output
