"""Ben Krasnow-style open-path grating geometry with view correction.

The ordinary raster pipeline still prepares, color-separates, and cleans the
artwork. This module's optional ``remap_layers`` capability then
rebuilds those finished color regions as open parallel-line patches and
assigns each patch across the available non-black LightBurn layers.

The layer colors are identifiers, not promises about the engraved color. True
Black contains only geometry classified from the source raster; this preset
does not synthesize a Black canvas or punch into Black. The selected material's
Holographic recipe is treated as a calibrated 1-micron anchor. Every non-black
output layer receives an independent copy whose speed is scaled to create its
target microscopic pitch while retaining the anchor's other laser values.
Speed Spread lets the user contract or expand those speed differences around
the unchanged 1-micron anchor speed.
"""

import colorsys
from copy import deepcopy
import math

from shapely.geometry import LineString, box
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
    "speed_spread": 1,
    "gradient_top": 165,
    "gradient_bottom": 90,
    "gradient_curve": 1,
    "hue_rotation": .13,
    "saturation_cutoff": .2,
    "patch_size_mm": .4,
    "line_spacing_mm": .06,
    "angle_min": -90,
    "angle_max": 90,
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
    ("angle_min", -180, 180, 1),
    ("angle_max", -180, 180, 1),
)


def apply(geometry, settings):
    """Preserve each cleaned source region until all layers can be remapped."""
    return geometry


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

    # Offset Fill entries store their concrete laser values in child passes.
    # The generated geometry is already a set of open paths, so copy the first
    # concrete pass when present and convert every clone to LightBurn Line mode.
    sublayers = getattr(source_layer, "subLayers", None) or []
    setting_template = sublayers[0] if sublayers else source_layer
    reference_frequency = number(getattr(setting_template, "frequency", 0), 0)
    if reference_frequency <= 0:
        raise ValueError(
            "The Holographic Material Library setting must have a positive frequency."
        )

    output_layers = {}
    grating_swatches = _grating_swatches(target_colors)
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


def _grating_swatches(target_colors):
    """Return available carriers in their native LightBurn layer order."""
    return [
        color_hex
        for color_hex, metadata in sorted(
            target_colors.items(), key=lambda item: item[1][1]
        )
        if str(color_hex).upper() != "#000000"
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


def remap_layers(processed_layers, target_colors, settings):
    """Build open gratings while retaining only source-derived Black geometry."""
    source_black = {
        color_hex: geometry
        for color_hex, geometry in processed_layers.items()
        if str(color_hex).upper() == "#000000"
    }
    bounds = settings.get("_canvas_bounds")
    if not bounds or len(bounds) != 4:
        nonempty = [geometry for geometry in processed_layers.values() if not geometry.is_empty]
        if not nonempty:
            return processed_layers
        bounds = unary_union(nonempty).bounds

    bounds = tuple(number(value, 0) for value in bounds)
    min_x, min_y, max_x, max_y = bounds
    grating_swatches = _grating_swatches(target_colors)
    if not grating_swatches:
        return source_black

    scale_factor = number(settings.get("_scale_factor"), 1, 1e-9, 1000)
    patch_size = number(settings.get("patch_size_mm"), .4, .1, 5) / scale_factor
    line_spacing = number(settings.get("line_spacing_mm"), .06, .01, .5) / scale_factor
    pieces = {swatch: [] for swatch in grating_swatches}

    for source_hex, geometry in processed_layers.items():
        if geometry.is_empty or str(source_hex).upper() == "#000000":
            continue

        start_x = max(
            min_x,
            math.floor((geometry.bounds[0] - min_x) / patch_size) * patch_size + min_x,
        )
        start_y = max(
            min_y,
            math.floor((geometry.bounds[1] - min_y) / patch_size) * patch_size + min_y,
        )
        x = start_x
        while x < min(geometry.bounds[2], max_x):
            y = start_y
            while y < min(geometry.bounds[3], max_y):
                patch = box(x, y, min(x + patch_size, max_x), min(y + patch_size, max_y))
                region = geometry.intersection(patch)
                if not region.is_empty:
                    center_x = (patch.bounds[0] + patch.bounds[2]) / 2
                    center_y = (patch.bounds[1] + patch.bounds[3]) / 2
                    level = _level_at_y(
                        source_hex,
                        center_y,
                        min_y,
                        max_y,
                        settings,
                        len(grating_swatches),
                    )
                    angle = _source_angle(center_x, center_y, bounds, settings)
                    pieces[grating_swatches[level]].extend(
                        _patch_lines(region, patch, angle, line_spacing)
                    )
                y += patch_size
            x += patch_size

    remapped = dict(source_black)
    for swatch, swatch_pieces in pieces.items():
        if swatch_pieces:
            remapped[swatch] = unary_union(swatch_pieces)
    return remapped
