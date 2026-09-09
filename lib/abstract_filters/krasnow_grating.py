"""Ben Krasnow-style open-path grating geometry with view correction.

The ordinary raster pipeline still prepares, color-separates, and cleans the
artwork. This module's optional ``remap_layers`` capability then
rebuilds those finished color regions as open parallel-line patches and
assigns each patch across the available non-black LightBurn layers.

The layer colors are identifiers, not promises about the engraved color. Black
is excluded from the grating carriers and is emitted later as an independent,
source-derived dark mask. This preset does not synthesize a Black canvas or
punch into Black. The selected material's
Holographic recipe is treated as a calibrated 1-micron anchor. Every non-black
output layer receives an independent copy whose speed is scaled to create its
target microscopic pitch while retaining the anchor's other laser values.
Speed Spread lets the user contract or expand those speed differences around
the unchanged 1-micron anchor speed.
"""

import colorsys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import math
import os
from threading import Lock

from shapely.affinity import affine_transform
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

from .common import number


USES_SOURCE_LUMINANCE = True
PRESERVE_SOURCE_BLACK = True
OUTPUT_PATH_MODE = "Cut"
SETTING_NAME = "holographic"
REPLICATE_SETTING_TO_OUTPUT_LAYERS = True
REFERENCE_PITCH_UM = 1.0
PITCH_MIN_UM = .55
PITCH_MAX_UM = 1.55

DEFAULTS = {
    "preserve_black": 1,
    "cell_shape": "square",
    "speed_spread": 1,
    "gradient_top": 165,
    "gradient_bottom": 90,
    "gradient_curve": 1,
    "hue_rotation": .13,
    "saturation_cutoff": .2,
    "patch_size_mm": .4,
    "line_spacing_mm": .06,
    "hue_line_spacing_minimum_mm": .06,
    "hue_line_spacing_maximum_mm": .06,
    "angle_min": -90,
    "angle_max": 90,
}

CELL_SHAPES = (
    "square", "hexagon", "triangle", "diamond", "skull", "heart",
    "space_invader", "ghost", "bat", "alien_head", "paw_print",
    "fish_scale", "puzzle_piece",
)

# The general Abstract preset deliberately performs aggressive cleanup for
# broad filled shapes. Krasnow needs the source regions to remain faithful so
# thin outlines are not closed into large blobs before the gratings are built.
VECTOR_DEFAULTS = {
    "min_island_area": 0,
    "simplification_factor": 0.0,
    "smoothing_radius": 0.001,
}

CONTROLS = (
    ("speed_spread", 0, 2, .001),
    ("gradient_top", 0, 255, 1),
    ("gradient_bottom", 0, 255, 1),
    ("gradient_curve", .2, 5, .05),
    ("hue_rotation", 0, 1, .01),
    ("saturation_cutoff", 0, 1, .01),
    ("patch_size_mm", .1, 5, .05),
    ("line_spacing_mm", .01, .5, .005),
    ("hue_line_spacing_minimum_mm", .01, .5, .001),
    ("hue_line_spacing_maximum_mm", .01, .5, .001),
    ("angle_min", -180, 180, 1),
    ("angle_max", -180, 180, 1),
)


def apply(geometry, settings):
    """Preserve each cleaned source region until all layers can be remapped."""
    return geometry


def _cell_shape(settings):
    """Return a supported cell shape with Square as fallback."""
    value = str(settings.get("cell_shape", "square")).strip().lower()
    return value if value in CELL_SHAPES else "square"


def _preserve_black(settings):
    """Keep source Black separate unless the user explicitly grates it."""
    return number(settings.get("preserve_black"), 1, 0, 1) >= .5


def _pitch_for_level(level, level_count):
    """Spread available carriers over Ben's approximate 0.55..1.55 um range."""
    if level_count <= 1:
        return REFERENCE_PITCH_UM
    fraction = min(1.0, max(0.0, level / (level_count - 1)))
    return PITCH_MIN_UM + fraction * (PITCH_MAX_UM - PITCH_MIN_UM)


def _speed_for_pitch(reference_speed, target_pitch_um, speed_spread=1):
    """Scale pitch deviation around the fixed 1-micron anchor speed."""
    reference_speed = number(reference_speed, 0)
    if reference_speed <= 0:
        raise ValueError(
            "The Holographic Material Library setting must have a positive speed."
        )
    spread = number(speed_spread, 1, 0, 2)
    pitch_ratio = target_pitch_um / REFERENCE_PITCH_UM
    speed_ratio = 1 + spread * (pitch_ratio - 1)
    return reference_speed * speed_ratio


def configure_output_layers(lightburn_project, target_colors, settings=None):
    """Clone the 1 um anchor and scale each speed by pitch and Speed Spread."""
    settings = settings or {}
    setting_layer_id = settings.get("_setting_layer_id")
    project_layers = list(getattr(lightburn_project, "_layers", []))
    source_layer = next(
        (
            layer for layer in project_layers
            if getattr(layer, "index", None) == setting_layer_id
        ),
        None,
    )
    if source_layer is None:
        raise ValueError(
            "Krasnow Color Grating requires a Material Library setting "
            "matching 'holographic'."
        )

    # The palette entry's parent CutSetting is the user-editable Holographic
    # recipe and is therefore authoritative.  Offset child passes can omit
    # fields such as QPulseWidth or retain stale imported values, so they must
    # not become the template for generated grating layers.  The generated
    # geometry is already open paths; child passes are cleared on each clone.
    setting_template = source_layer
    reference_frequency = number(getattr(setting_template, "frequency", 0), 0)
    if reference_frequency <= 0:
        raise ValueError(
            "The Holographic Material Library setting must have a positive frequency."
        )

    output_layers = {}
    grating_swatches = _grating_swatches(target_colors, settings)
    for level, color_hex in enumerate(grating_swatches):
        metadata = target_colors[color_hex]
        target_pitch_um = _pitch_for_level(level, len(grating_swatches))
        clone = deepcopy(setting_template)
        clone.index = metadata[1]
        clone.name = metadata[2]
        clone.type = OUTPUT_PATH_MODE
        clone.subLayers = []
        clone.speed = round(
            _speed_for_pitch(
                getattr(setting_template, "speed", 0),
                target_pitch_um,
                settings.get("speed_spread"),
            ),
            6,
        )
        clone.materialName = getattr(source_layer, "materialName", "")
        clone.entryDesc = getattr(source_layer, "entryDesc", SETTING_NAME)
        output_layers[clone.index] = clone

    replaced_layers = []
    replaced_ids = set()
    for layer in project_layers:
        layer_id = getattr(layer, "index", None)
        if layer_id == setting_layer_id and layer_id not in output_layers:
            continue
        if layer_id in output_layers:
            if layer_id not in replaced_ids:
                replaced_layers.append(output_layers[layer_id])
                replaced_ids.add(layer_id)
            continue
        replaced_layers.append(layer)

    for layer_id in sorted(output_layers):
        if layer_id not in replaced_ids:
            replaced_layers.append(output_layers[layer_id])
    lightburn_project._layers = replaced_layers


def _hex_hsv(color_hex):
    value = str(color_hex or "").strip().lstrip("#")
    if len(value) != 6:
        return 0.0, 0.0, 0.0
    try:
        red, green, blue = (int(value[index:index + 2], 16) / 255 for index in (0, 2, 4))
    except ValueError:
        return 0.0, 0.0, 0.0
    return colorsys.rgb_to_hsv(red, green, blue)


def _hue_offset(color_hex, settings):
    """Reproduce Ben's hue rotation and 15..240 inverse control mapping."""
    hue, saturation, _ = _hex_hsv(color_hex)
    cutoff = number(settings.get("saturation_cutoff"), .2, 0, 1)
    if saturation < cutoff:
        return 0.0
    rotation = number(settings.get("hue_rotation"), .13, 0, 1)
    hue_scaled = (hue + rotation) % 1.0
    return 240 - hue_scaled * (240 - 15) - 127


def _line_spacing_for_color(color_hex, settings, scale_factor):
    """Map chromatic hue to a wavelength-ordered visible line spacing.

    At a fixed incidence angle, viewing angle, and diffraction order, the
    grating equation makes grating period proportional to wavelength.  RGB
    hue is not itself a wavelength (and purple/magenta are non-spectral), so
    the anchors below are an intentionally approximate visible-spectrum
    proxy.  The non-spectral arc blends between violet and red endpoints.

    This controls the macroscopic spacing of the generated vector lines.  The
    calibrated microscopic pitch remains controlled independently by the
    Krasnow carrier layer speed/frequency settings.
    """
    default_mm = number(settings.get("line_spacing_mm"), .06, .01, .5)
    hue, saturation, _ = _hex_hsv(color_hex)
    cutoff = number(settings.get("saturation_cutoff"), .2, 0, 1)
    if saturation < cutoff:
        return default_mm / scale_factor

    minimum_mm = number(
        settings.get("hue_line_spacing_minimum_mm"), .06, .01, .5
    )
    maximum_mm = number(
        settings.get("hue_line_spacing_maximum_mm"), .06, .01, .5
    )

    # Approximate dominant-wavelength anchors for the spectral HSV arc,
    # followed by a continuous violet-to-red proxy for non-spectral purples.
    # Normalizing the wavelength proxy makes the user-supplied endpoints the
    # exact spacing used for violet and red.
    hue_degrees = (hue % 1.0) * 360.0
    wavelength_anchors = (
        (0.0, 650.0),    # red
        (30.0, 600.0),   # orange
        (60.0, 580.0),   # yellow
        (120.0, 530.0),  # green
        (180.0, 490.0),  # cyan
        (240.0, 460.0),  # blue
        (270.0, 400.0),  # violet
        (360.0, 650.0),  # non-spectral purple/magenta arc back to red
    )
    wavelength_nm = wavelength_anchors[-1][1]
    for (start_hue, start_nm), (end_hue, end_nm) in zip(
        wavelength_anchors, wavelength_anchors[1:]
    ):
        if hue_degrees <= end_hue:
            span = max(end_hue - start_hue, 1e-9)
            fraction = (hue_degrees - start_hue) / span
            wavelength_nm = start_nm + fraction * (end_nm - start_nm)
            break

    wavelength_fraction = (wavelength_nm - 400.0) / (650.0 - 400.0)
    spacing_mm = minimum_mm + wavelength_fraction * (maximum_mm - minimum_mm)
    return spacing_mm / scale_factor


def _gradient_value(y, min_y, max_y, settings):
    top = number(settings.get("gradient_top"), 165, 0, 255)
    bottom = number(settings.get("gradient_bottom"), 90, 0, 255)
    curve = number(settings.get("gradient_curve"), 1, .2, 5)
    span = max(max_y - min_y, 1e-9)
    position = min(1.0, max(0.0, (y - min_y) / span))
    shaped = position ** curve
    return top + (bottom - top) * shaped


def _level_at_y(color_hex, y, min_y, max_y, settings, level_count):
    control = _gradient_value(y, min_y, max_y, settings) + _hue_offset(color_hex, settings)
    control = min(255.0, max(0.0, control))
    return min(level_count - 1, math.floor(control / 256 * level_count))


def _grating_swatches(target_colors, settings=None):
    """Return available carriers in their native LightBurn layer order."""
    preserve_black = _preserve_black(settings or {})
    return [
        color_hex
        for color_hex, metadata in sorted(
            target_colors.items(), key=lambda item: item[1][1]
        )
        if not preserve_black or str(color_hex).upper() != "#000000"
    ]


def _source_angle(x, y, bounds, settings):
    angle_image = settings.get("_angle_image")
    if angle_image is not None and getattr(angle_image, "size", None):
        width, height = angle_image.size
        min_x, min_y, max_x, max_y = bounds
        x_fraction = (x - min_x) / max(max_x - min_x, 1e-9)
        y_fraction = (y - min_y) / max(max_y - min_y, 1e-9)
        pixel_x = min(width - 1, max(0, math.floor(x_fraction * width)))
        pixel_y = min(height - 1, max(0, math.floor(y_fraction * height)))
        value = number(angle_image.getpixel((pixel_x, pixel_y)), 127, 0, 255)
    else:
        value = 127

    angle_min = number(settings.get("angle_min"), -90, -180, 180)
    angle_max = number(settings.get("angle_max"), 90, -180, 180)
    return angle_min + (value / 255) * (angle_max - angle_min)


def _line_parts(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == "LineString":
        return [geometry] if geometry.length > 0 else []
    if geometry.geom_type in ("MultiLineString", "GeometryCollection"):
        parts = []
        for item in geometry.geoms:
            parts.extend(_line_parts(item))
        return parts
    return []


def _patch_lines(region, patch, angle_degrees, spacing):
    """Reproduce Ben's parallel SVG line equation inside one clipped patch."""
    min_x, min_y, max_x, max_y = patch.bounds
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2
    half_diagonal = math.hypot(max_x - min_x, max_y - min_y) / 2
    radians = math.radians(angle_degrees)
    normal_x, normal_y = math.cos(radians), math.sin(radians)
    tangent_x, tangent_y = -normal_y, normal_x
    reach = half_diagonal * 1.05
    offset = -half_diagonal
    lines = []

    while offset <= half_diagonal + 1e-9:
        anchor_x = center_x + normal_x * offset
        anchor_y = center_y + normal_y * offset
        candidate = LineString((
            (anchor_x - tangent_x * reach, anchor_y - tangent_y * reach),
            (anchor_x + tangent_x * reach, anchor_y + tangent_y * reach),
        ))
        lines.extend(_line_parts(candidate.intersection(region)))
        offset += spacing
    return lines


def _geometry_components(geometry):
    """Yield independently bounded pieces without altering their geometry."""
    if geometry.is_empty:
        return
    if geometry.geom_type in ("MultiPolygon", "GeometryCollection"):
        for item in geometry.geoms:
            yield from _geometry_components(item)
        return
    yield geometry


def _candidate_patch_indices(geometry, bounds, patch_size):
    """Return globally aligned cells whose component bounds can intersect geometry."""
    min_x, min_y, max_x, max_y = bounds
    candidates = set()
    for component in _geometry_components(geometry):
        component_min_x, component_min_y, component_max_x, component_max_y = component.bounds
        start_x = max(
            min_x,
            math.floor((component_min_x - min_x) / patch_size) * patch_size + min_x,
        )
        start_y = max(
            min_y,
            math.floor((component_min_y - min_y) / patch_size) * patch_size + min_y,
        )
        stop_x = min(component_max_x, max_x)
        stop_y = min(component_max_y, max_y)
        x_count = max(0, math.ceil((stop_x - start_x) / patch_size - 1e-12))
        y_count = max(0, math.ceil((stop_y - start_y) / patch_size - 1e-12))
        start_x_index = round((start_x - min_x) / patch_size)
        start_y_index = round((start_y - min_y) / patch_size)
        for x_offset in range(x_count):
            for y_offset in range(y_count):
                candidates.add((start_x_index + x_offset, start_y_index + y_offset))
    return sorted(candidates)


def _ellipse_polygon(center_x, center_y, radius_x, radius_y, vertices=16):
    """Return a compact deterministic ellipse polygon for cell cutouts."""
    return Polygon([
        (
            center_x + radius_x * math.cos(2 * math.pi * index / vertices),
            center_y + radius_y * math.sin(2 * math.pi * index / vertices),
        )
        for index in range(vertices)
    ])


def _build_unit_skull():
    """Build the normalized skull once so large jobs only transform it."""
    outer_points = (
        (0, -.46), (.22, -.43), (.36, -.32), (.43, -.14),
        (.42, .05), (.34, .18), (.27, .23), (.25, .38),
        (.16, .44), (.09, .36), (.04, .45), (-.04, .45),
        (-.09, .36), (-.16, .44), (-.25, .38), (-.27, .23),
        (-.34, .18), (-.42, .05), (-.43, -.14), (-.36, -.32),
        (-.22, -.43),
    )
    outer = Polygon(outer_points)
    left_eye = _ellipse_polygon(-.16, -.04, .105, .11)
    right_eye = _ellipse_polygon(.16, -.04, .105, .11)
    nose = Polygon((
        (0, .08),
        (.075, .22),
        (-.075, .22),
    ))
    return outer.difference(unary_union((left_eye, right_eye, nose)))


_UNIT_SKULL = _build_unit_skull()


def _build_unit_heart():
    return Polygon((
        (0, .46), (-.42, .02), (-.43, -.18), (-.34, -.36),
        (-.17, -.43), (0, -.30), (.17, -.43), (.34, -.36),
        (.43, -.18), (.42, .02),
    ))


def _build_unit_space_invader():
    body = unary_union((
        box(-.34, -.34, .34, .25),
        box(-.45, -.14, .45, .13),
        box(-.27, .13, -.09, .39),
        box(.09, .13, .27, .39),
        box(-.43, -.25, -.29, -.05),
        box(.29, -.25, .43, -.05),
        box(-.25, -.43, -.10, -.30),
        box(.10, -.43, .25, -.30),
    ))
    eyes = unary_union((
        box(-.22, -.17, -.10, -.04),
        box(.10, -.17, .22, -.04),
    ))
    return body.difference(eyes)


def _build_unit_ghost():
    outer = Polygon((
        (0, -.46), (.20, -.42), (.35, -.31), (.42, -.14),
        (.42, .43), (.28, .31), (.14, .43), (0, .31),
        (-.14, .43), (-.28, .31), (-.42, .43), (-.42, -.14),
        (-.35, -.31), (-.20, -.42),
    ))
    eyes = unary_union((
        _ellipse_polygon(-.15, -.11, .075, .11),
        _ellipse_polygon(.15, -.11, .075, .11),
    ))
    return outer.difference(eyes)


def _build_unit_bat():
    return Polygon((
        (0, -.18), (.09, -.30), (.15, -.18), (.27, -.30),
        (.47, -.22), (.39, -.02), (.47, .10), (.30, .08),
        (.35, .28), (.17, .19), (.10, .34), (0, .23),
        (-.10, .34), (-.17, .19), (-.35, .28), (-.30, .08),
        (-.47, .10), (-.39, -.02), (-.47, -.22), (-.27, -.30),
        (-.15, -.18), (-.09, -.30),
    ))


def _build_unit_alien_head():
    outer = _ellipse_polygon(0, 0, .39, .46, vertices=24)
    eyes = unary_union((
        Polygon(((-.25, -.13), (-.08, -.05), (-.12, .13), (-.27, .02))),
        Polygon(((.25, -.13), (.08, -.05), (.12, .13), (.27, .02))),
    ))
    return outer.difference(eyes)


def _build_unit_paw_print():
    return unary_union((
        _ellipse_polygon(0, .17, .24, .22),
        _ellipse_polygon(-.29, -.12, .10, .14),
        _ellipse_polygon(-.10, -.29, .10, .14),
        _ellipse_polygon(.10, -.29, .10, .14),
        _ellipse_polygon(.29, -.12, .10, .14),
    ))


def _build_unit_fish_scale():
    return Polygon((
        (0, .46), (-.22, .31), (-.37, .11), (-.45, -.14),
        (-.39, -.29), (-.23, -.40), (0, -.44), (.23, -.40),
        (.39, -.29), (.45, -.14), (.37, .11), (.22, .31),
    ))


def _build_unit_puzzle_piece():
    base = box(-.5, -.5, .5, .5)
    tabs = unary_union((
        _ellipse_polygon(.5, 0, .14, .14),
        _ellipse_polygon(0, -.5, .14, .14),
    ))
    sockets = unary_union((
        _ellipse_polygon(-.5, 0, .14, .14),
        _ellipse_polygon(0, .5, .14, .14),
    ))
    return unary_union((base, tabs)).difference(sockets)


_GAPPED_CELL_TEMPLATES = {
    "skull": _UNIT_SKULL,
    "heart": _build_unit_heart(),
    "space_invader": _build_unit_space_invader(),
    "ghost": _build_unit_ghost(),
    "bat": _build_unit_bat(),
    "alien_head": _build_unit_alien_head(),
    "paw_print": _build_unit_paw_print(),
    "fish_scale": _build_unit_fish_scale(),
}

_GAPPED_CELL_ROW_STEPS = {
    "skull": .8,
    "heart": .9,
    "space_invader": .9,
    "ghost": .95,
    "bat": .7,
    "alien_head": .95,
    "paw_print": .9,
    "fish_scale": .9,
}

_UNIT_PUZZLE_PIECE = _build_unit_puzzle_piece()


def solid_glyph_shape(shape, center_x, center_y, size):
    """Return a reusable Krasnow icon silhouette for solid glyph renderers."""
    shape = str(shape or "").strip().lower()
    if shape in _GAPPED_CELL_TEMPLATES:
        template = _GAPPED_CELL_TEMPLATES[shape]
    elif shape == "puzzle_piece":
        template = _UNIT_PUZZLE_PIECE
    else:
        raise ValueError(f"Krasnow glyph shape '{shape}' is not supported.")
    return _template_polygon(template, center_x, center_y, size)


def solid_glyph_row_step(shape):
    """Return Krasnow's staggered row-spacing multiplier for an icon glyph."""
    return _GAPPED_CELL_ROW_STEPS.get(str(shape or "").strip().lower())


def _skull_polygon(center_x, center_y, patch_size):
    """Scale and place the reusable skull silhouette on its grid cell."""
    return affine_transform(
        _UNIT_SKULL,
        (patch_size, 0, 0, patch_size, center_x, center_y),
    )


def _template_polygon(template, center_x, center_y, patch_size):
    """Scale and place a reusable normalized cell template."""
    return affine_transform(
        template,
        (patch_size, 0, 0, patch_size, center_x, center_y),
    )


def _tessellated_cells(bounds, patch_size, cell_shape):
    """Build a deterministic, globally aligned non-square cell grid.

    Hexagon uses ``patch_size`` as the flat-to-flat height of a regular
    flat-top hexagon. Triangle uses it as the side length of an equilateral
    triangle. Diamond uses it as both point-to-point diagonals of a rotated
    square rhombus. Icon silhouettes use ``patch_size`` as their column pitch
    and stagger alternating rows by half a cell, leaving deliberate substrate
    gaps. Puzzle pieces use matching tabs and sockets on a regular square grid.
    Full boundary cells are retained so their centers and grating alignment do
    not change when source geometry touches a canvas edge.
    """
    min_x, min_y, max_x, max_y = bounds
    canvas = box(min_x, min_y, max_x, max_y)
    cells = []

    if cell_shape == "hexagon":
        radius = patch_size / math.sqrt(3)
        x_step = 1.5 * radius
        y_step = patch_size
        start_column = math.floor(-radius / x_step) - 1
        stop_column = math.ceil((max_x - min_x + radius) / x_step) + 1
        for column in range(start_column, stop_column + 1):
            center_x = min_x + column * x_step
            center_y_offset = (column & 1) * y_step / 2
            start_row = math.floor((-center_y_offset - patch_size / 2) / y_step) - 1
            stop_row = math.ceil(
                (max_y - min_y - center_y_offset + patch_size / 2) / y_step
            ) + 1
            for row in range(start_row, stop_row + 1):
                center_y = min_y + center_y_offset + row * y_step
                polygon = Polygon([
                    (
                        center_x + radius * math.cos(math.radians(angle)),
                        center_y + radius * math.sin(math.radians(angle)),
                    )
                    for angle in (0, 60, 120, 180, 240, 300)
                ])
                if polygon.intersection(canvas).area > 1e-12:
                    cells.append(((column, row), polygon))
    elif cell_shape == "triangle":
        side = patch_size
        height = math.sqrt(3) * side / 2
        start_band = -1
        stop_band = math.ceil((max_y - min_y) / height) + 1
        start_column = -2
        stop_column = math.ceil((max_x - min_x) / side) + 2
        for band in range(start_band, stop_band + 1):
            y = min_y + band * height
            for column in range(start_column, stop_column + 1):
                x = min_x + column * side
                upward = Polygon((
                    (x, y),
                    (x + side, y),
                    (x + side / 2, y + height),
                ))
                downward = Polygon((
                    (x + side / 2, y + height),
                    (x + side, y),
                    (x + 1.5 * side, y + height),
                ))
                if upward.intersection(canvas).area > 1e-12:
                    cells.append(((band, column, 0), upward))
                if downward.intersection(canvas).area > 1e-12:
                    cells.append(((band, column, 1), downward))
    elif cell_shape == "diamond":
        width = patch_size
        height = patch_size
        row_step = height / 2
        start_row = -2
        stop_row = math.ceil((max_y - min_y) / row_step) + 2
        start_column = -2
        stop_column = math.ceil((max_x - min_x) / width) + 2
        for row in range(start_row, stop_row + 1):
            center_y = min_y + row * row_step
            center_x_offset = (row & 1) * width / 2
            for column in range(start_column, stop_column + 1):
                center_x = min_x + center_x_offset + column * width
                polygon = Polygon((
                    (center_x, center_y - height / 2),
                    (center_x + width / 2, center_y),
                    (center_x, center_y + height / 2),
                    (center_x - width / 2, center_y),
                ))
                if polygon.intersection(canvas).area > 1e-12:
                    cells.append(((row, column), polygon))
    elif cell_shape in _GAPPED_CELL_TEMPLATES:
        row_step = patch_size * _GAPPED_CELL_ROW_STEPS[cell_shape]
        start_row = -2
        stop_row = math.ceil((max_y - min_y) / row_step) + 2
        start_column = -2
        stop_column = math.ceil((max_x - min_x) / patch_size) + 2
        for row in range(start_row, stop_row + 1):
            center_y = min_y + patch_size / 2 + row * row_step
            center_x_offset = (row & 1) * patch_size / 2
            for column in range(start_column, stop_column + 1):
                center_x = (
                    min_x + patch_size / 2 + center_x_offset
                    + column * patch_size
                )
                polygon = _template_polygon(
                    _GAPPED_CELL_TEMPLATES[cell_shape],
                    center_x,
                    center_y,
                    patch_size,
                )
                if polygon.intersection(canvas).area > 1e-12:
                    cells.append(((row, column), polygon))
    elif cell_shape == "puzzle_piece":
        start_row = -2
        stop_row = math.ceil((max_y - min_y) / patch_size) + 2
        start_column = -2
        stop_column = math.ceil((max_x - min_x) / patch_size) + 2
        for row in range(start_row, stop_row + 1):
            center_y = min_y + patch_size / 2 + row * patch_size
            for column in range(start_column, stop_column + 1):
                center_x = min_x + patch_size / 2 + column * patch_size
                polygon = _template_polygon(
                    _UNIT_PUZZLE_PIECE,
                    center_x,
                    center_y,
                    patch_size,
                )
                if polygon.intersection(canvas).area > 1e-12:
                    cells.append(((row, column), polygon))

    return cells


def _worker_count(work_units):
    try:
        configured = int(os.environ.get("RASTER_WORKER_PROCESSES", "1"))
    except (TypeError, ValueError):
        configured = 1
    return max(1, min(configured, os.cpu_count() or 1, max(1, work_units)))


def _progress_enabled():
    return str(os.environ.get("RASTER_KRASNOW_PROGRESS", "true")).strip().lower() \
        in {"1", "true", "yes", "on"}


def _process_layer_patches(layer_plan, grating_swatches, bounds, settings,
                           patch_size, scale_factor, cell_shape,
                           progress_callback=None):
    """Clip one source layer while preserving its original patch order."""
    source_hex, geometry, candidate_indices = layer_plan
    line_spacing = _line_spacing_for_color(source_hex, settings, scale_factor)
    min_x, min_y, max_x, max_y = bounds
    layer_pieces = {swatch: [] for swatch in grating_swatches}

    unreported_patches = 0
    for candidate in candidate_indices:
        if cell_shape == "square":
            x_index, y_index = candidate
            x = min_x + x_index * patch_size
            y = min_y + y_index * patch_size
            patch = box(x, y, min(x + patch_size, max_x), min(y + patch_size, max_y))
        else:
            _, patch = candidate
        region = geometry.intersection(patch)
        if not region.is_empty and (
            cell_shape == "square" or getattr(region, "area", 0) > 1e-12
        ):
            if cell_shape == "square":
                center_x = (patch.bounds[0] + patch.bounds[2]) / 2
                center_y = (patch.bounds[1] + patch.bounds[3]) / 2
            else:
                center_x, center_y = patch.centroid.coords[0]
            level = _level_at_y(
                source_hex,
                center_y,
                min_y,
                max_y,
                settings,
                len(grating_swatches),
            )
            angle = _source_angle(center_x, center_y, bounds, settings)
            layer_pieces[grating_swatches[level]].extend(
                _patch_lines(region, patch, angle, line_spacing)
            )
        unreported_patches += 1
        if progress_callback and unreported_patches >= 512:
            progress_callback(unreported_patches)
            unreported_patches = 0

    if progress_callback and unreported_patches:
        progress_callback(unreported_patches)

    return layer_pieces


def remap_layers(processed_layers, target_colors, settings):
    """Build open gratings, optionally treating Black as a normal carrier."""
    progress = settings.get("_progress_logger")

    def log(message):
        if callable(progress):
            progress(message)

    bounds = settings.get("_canvas_bounds")
    if not bounds or len(bounds) != 4:
        nonempty = [geometry for geometry in processed_layers.values() if not geometry.is_empty]
        if not nonempty:
            return processed_layers
        bounds = unary_union(nonempty).bounds

    bounds = tuple(number(value, 0) for value in bounds)
    min_x, min_y, max_x, max_y = bounds
    preserve_black = _preserve_black(settings)
    grating_swatches = _grating_swatches(target_colors, settings)
    if not grating_swatches:
        return {}

    scale_factor = number(settings.get("_scale_factor"), 1, 1e-9, 1000)
    patch_size = number(settings.get("patch_size_mm"), .4, .1, 5) / scale_factor
    cell_shape = _cell_shape(settings)
    pieces = {swatch: [] for swatch in grating_swatches}

    tessellated_cells = None
    if cell_shape != "square":
        tessellated_cells = _tessellated_cells(bounds, patch_size, cell_shape)
    cell_label = "patches" if cell_shape == "square" else f"{cell_shape} cells"

    layer_plans = []
    total_patches = 0
    for source_hex, geometry in processed_layers.items():
        if geometry.is_empty or (
            preserve_black and str(source_hex).upper() == "#000000"
        ):
            continue
        if cell_shape == "square":
            candidate_indices = _candidate_patch_indices(geometry, bounds, patch_size)
        else:
            candidate_indices = [
                cell for cell in tessellated_cells
                if geometry.intersects(cell[1])
            ]
        total_patches += len(candidate_indices)
        layer_plans.append((source_hex, geometry, candidate_indices))

    log(
        f"[Krasnow mapping 1/3] DONE: planned {total_patches} candidate "
        f"{cell_label} across {len(layer_plans)} "
        f"{'non-Black ' if preserve_black else ''}source layers."
    )
    log(
        f"[Krasnow mapping 2/3] START: clipping {cell_label} and generating "
        f"open grating paths for {total_patches} candidate cells."
    )
    progress_lock = Lock()
    processed_patches = 0
    report_interval = max(1, math.ceil(total_patches / 20))
    next_report = report_interval

    def report_progress(completed_count):
        nonlocal processed_patches, next_report
        with progress_lock:
            processed_patches += completed_count
            while (
                processed_patches >= next_report
                or processed_patches == total_patches
            ):
                reported = min(processed_patches, total_patches)
                percent = round(reported / max(total_patches, 1) * 100)
                log(
                    f"[Krasnow mapping 2/3] PROGRESS: processed "
                    f"{reported}/{total_patches} candidate patches ({percent}%)."
                )
                next_report += report_interval
                if reported == total_patches:
                    break

    worker_count = _worker_count(len(layer_plans))
    patch_progress = report_progress if _progress_enabled() else None
    if patch_progress is None:
        log(
            "[Krasnow mapping 2/3] Fine-grained progress logging is disabled; "
            "the independent worker lease heartbeat remains active."
        )
    if worker_count > 1:
        log(
            f"[Krasnow mapping 2/3] Processing {len(layer_plans)} source "
            f"layers with {worker_count} CPU workers."
        )
        with ThreadPoolExecutor(
            max_workers=worker_count, thread_name_prefix="krasnow-layer"
        ) as executor:
            layer_results = executor.map(
                lambda plan: _process_layer_patches(
                    plan,
                    grating_swatches,
                    bounds,
                    settings,
                    patch_size,
                    scale_factor,
                    cell_shape,
                    patch_progress,
                ),
                layer_plans,
            )
            layer_results = list(layer_results)
    else:
        layer_results = [
            _process_layer_patches(
                plan,
                grating_swatches,
                bounds,
                settings,
                patch_size,
                scale_factor,
                cell_shape,
                patch_progress,
            )
            for plan in layer_plans
        ]

    for layer_plan, layer_pieces in zip(layer_plans, layer_results):
        for swatch in grating_swatches:
            pieces[swatch].extend(layer_pieces[swatch])

    segment_count = sum(len(swatch_pieces) for swatch_pieces in pieces.values())
    populated = [
        (swatch, swatch_pieces)
        for swatch, swatch_pieces in pieces.items()
        if swatch_pieces
    ]
    log(
        f"[Krasnow mapping 2/3] DONE: generated {segment_count} open path "
        f"segments across {len(populated)} carrier layers."
    )
    log(
        f"[Krasnow mapping 3/3] START: merging path segments for "
        f"{len(populated)} populated carrier layers."
    )
    def merge_carrier(item):
        index, (swatch, swatch_pieces) = item
        log(
            f"[Krasnow mapping 3/3] Carrier {index}/{len(populated)} START: "
            f"merging {len(swatch_pieces)} segments for {swatch}."
        )
        merged = unary_union(swatch_pieces)
        log(
            f"[Krasnow mapping 3/3] Carrier {index}/{len(populated)} DONE: "
            f"merged {len(swatch_pieces)} segments for {swatch}."
        )
        return swatch, merged

    indexed_carriers = list(enumerate(populated, 1))
    carrier_workers = _worker_count(len(indexed_carriers))
    if carrier_workers > 1:
        log(
            f"[Krasnow mapping 3/3] Merging {len(populated)} carrier layers "
            f"with {carrier_workers} CPU workers."
        )
        with ThreadPoolExecutor(
            max_workers=carrier_workers, thread_name_prefix="krasnow-carrier"
        ) as executor:
            merged_carriers = list(executor.map(merge_carrier, indexed_carriers))
    else:
        merged_carriers = [merge_carrier(item) for item in indexed_carriers]

    # ``executor.map`` preserves native LightBurn carrier order.
    remapped = dict(merged_carriers)
    log(
        f"[Krasnow mapping 3/3] DONE: produced {len(remapped)} calibrated "
        "carrier layers."
    )
    return remapped
