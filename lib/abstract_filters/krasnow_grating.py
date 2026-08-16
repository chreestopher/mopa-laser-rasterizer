"""Ben Krasnow-style open-path grating geometry with view correction.

The ordinary raster pipeline still prepares, color-separates, cleans, and
punches the artwork.  This module's optional ``remap_layers`` capability then
rebuilds those finished color regions as open parallel-line patches and
assigns each patch to one of 21 calibrated LightBurn grating layers.

The layer colors are identifiers, not promises about the engraved color.  The
operator must attach monotonically ordered, tested grating recipes to them.
True Black remains reserved for the Rasterizer's punched background, so Sage
Green carries grating level zero instead of Ben's original Black identifier.
"""

import colorsys
import math

from shapely.geometry import LineString, box
from shapely.ops import unary_union

from .common import number


# Ben's remaining 20 SVG layer identifiers keep their original level numbers.
# Sage Green is a spare non-black identifier used for level zero so the normal
# Rasterizer can continue to own LightBurn's true Black layer.
GRATING_SWATCHES = (
    "#8CD78C",  # level 0 (Ben used #000000)
    "#0000FF", "#FF0000", "#00E000", "#D0D000", "#FF8000",
    "#00E0E0", "#FF00FF", "#B4B4B4", "#0000A0", "#A00000",
    "#00A000", "#A0A000", "#C08000", "#00A0FF", "#A000A0",
    "#808080", "#7D87B9", "#BB7784", "#4A6FE3", "#D33F6A",
)

# Material_Library.py uses this capability only for this preset.  It loads the
# complete palette so every correction level can resolve a real cut setting.
REQUIRES_FULL_PALETTE = True
REQUIRED_OUTPUT_SWATCHES = GRATING_SWATCHES
USES_SOURCE_LUMINANCE = True
OUTPUT_PATH_MODE = "Cut"

DEFAULTS = {
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


def configure_output_layers(lightburn_project, target_colors):
    """Force only the open grating carriers to LightBurn Line mode."""
    output_layer_ids = {
        target_colors[color_hex][1]
        for color_hex in GRATING_SWATCHES
        if color_hex in target_colors
    }
    for layer in getattr(lightburn_project, "_layers", []):
        if getattr(layer, "index", None) in output_layer_ids:
            layer.type = OUTPUT_PATH_MODE
            layer.subLayers = []


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


def _level_at_y(color_hex, y, min_y, max_y, settings):
    control = _gradient_value(y, min_y, max_y, settings) + _hue_offset(color_hex, settings)
    control = min(255.0, max(0.0, control))
    return min(len(GRATING_SWATCHES) - 1, math.floor(control / 256 * len(GRATING_SWATCHES)))


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
    """Build open grating paths and return their original closed punch masks."""
    bounds = settings.get("_canvas_bounds")
    if not bounds or len(bounds) != 4:
        nonempty = [geometry for geometry in processed_layers.values() if not geometry.is_empty]
        if not nonempty:
            return processed_layers
        bounds = unary_union(nonempty).bounds

    bounds = tuple(number(value, 0) for value in bounds)
    min_x, min_y, max_x, max_y = bounds
    available = [swatch for swatch in GRATING_SWATCHES if swatch in target_colors]
    if len(available) != len(GRATING_SWATCHES):
        missing = [swatch for swatch in GRATING_SWATCHES if swatch not in target_colors]
        raise ValueError(
            "Krasnow Color Grating requires all 21 calibrated grating swatches; "
            f"missing: {', '.join(missing)}"
        )

    scale_factor = number(settings.get("_scale_factor"), 1, 1e-9, 1000)
    patch_size = number(settings.get("patch_size_mm"), .4, .1, 5) / scale_factor
    line_spacing = number(settings.get("line_spacing_mm"), .06, .01, .5) / scale_factor
    pieces = {swatch: [] for swatch in GRATING_SWATCHES}
    punch_layers = dict(processed_layers)

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
                    level = _level_at_y(source_hex, center_y, min_y, max_y, settings)
                    angle = _source_angle(center_x, center_y, bounds, settings)
                    pieces[GRATING_SWATCHES[level]].extend(
                        _patch_lines(region, patch, angle, line_spacing)
                    )
                y += patch_size
            x += patch_size

    remapped = {}
    for swatch, swatch_pieces in pieces.items():
        if swatch_pieces:
            remapped[swatch] = unary_union(swatch_pieces)
    return remapped, punch_layers
