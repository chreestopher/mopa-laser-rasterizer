"""Ben Krasnow-style grating geometry with view correction.

The ordinary raster pipeline still prepares, color-separates, and cleans the
artwork. This module's optional ``remap_layers`` capability then
rebuilds those finished color regions as either open parallel-line patches or
closed cells assigned to native LightBurn Fill layers, then distributes the
result across the available non-black LightBurn layers.

The layer colors are identifiers, not promises about the engraved color. Black
is excluded from the grating carriers and is emitted later as an independent,
source-derived dark mask. This preset does not synthesize a Black canvas or
punch into Black. The selected material's
Fauxlographic recipe is treated as a calibrated 1-micron anchor. Every non-black
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

from shapely import affinity
from shapely.affinity import affine_transform
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

from .common import number
from .packing import SpatialCollisionIndex, placement_variant
from custom_shape import decode_grayscale_mask, svg_to_unit_geometry


USES_SOURCE_LUMINANCE = True
PRESERVE_SOURCE_BLACK = True
OUTPUT_PATH_MODE = "Cut"
OUTPUT_FILL_MODE = "Scan"
SETTING_NAME = "fauxlographic"
SETTING_ALIASES = ("holographic",)
REPLICATE_SETTING_TO_OUTPUT_LAYERS = True
REFERENCE_PITCH_UM = 1.0
PITCH_MIN_UM = .55
PITCH_MAX_UM = 1.55
MAX_LIGHTBURN_LAYERS = 30
FILL_TARGET_CARRIER_LEVELS = 7
FILL_TARGET_ANGLE_BINS = 4

DEFAULTS = {
    "preserve_black": 1,
    "cell_shape": "square",
    "tight_pack_geometry": 0,
    "grating_render_mode": "line",
    "fauxlogram_gradient_scope": "entire_artwork",
    "fauxlogram_gradient_direction": "top_to_bottom",
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
    "custom",
)

FAUXLOGRAM_GRADIENT_SCOPES = ("entire_artwork", "each_shape")
FAUXLOGRAM_GRADIENT_DIRECTIONS = (
    "top_to_bottom", "bottom_to_top", "left_to_right", "right_to_left",
    "center_to_edge", "edge_to_center",
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


def _grating_render_mode(settings):
    """Return the stable renderer name, retaining explicit lines by default."""
    value = str(settings.get("grating_render_mode", "line")).strip().lower()
    return value if value in {"line", "fill"} else "line"


def _preserve_black(settings):
    """Keep source Black separate unless the user explicitly grates it."""
    return number(settings.get("preserve_black"), 1, 0, 1) >= .5


def _automatic_fill_dimensions(layer_slots):
    """Choose a useful carrier/angle split without exceeding available layers.

    The search balances both dimensions and stops improving once it reaches
    seven carriers and four angle bins, the practical target for the
    experimental renderer. Empty palette slots are allowed when no exact
    factorization offers a better optical balance.
    """
    layer_slots = max(1, min(MAX_LIGHTBURN_LAYERS, int(layer_slots)))
    candidates = []
    for carrier_count in range(1, layer_slots + 1):
        for angle_count in range(1, min(FILL_TARGET_ANGLE_BINS, layer_slots) + 1):
            used = carrier_count * angle_count
            if used > layer_slots:
                continue
            carrier_utility = min(carrier_count, FILL_TARGET_CARRIER_LEVELS) \
                / FILL_TARGET_CARRIER_LEVELS
            angle_utility = min(angle_count, FILL_TARGET_ANGLE_BINS) \
                / FILL_TARGET_ANGLE_BINS
            score = carrier_utility * angle_utility
            balance = min(carrier_utility, angle_utility)
            candidates.append(
                (score, balance, used, carrier_count, angle_count)
            )
    _, _, _, carrier_count, angle_count = max(candidates)
    return carrier_count, angle_count


def _fill_angle_controls(settings, angle_count):
    """Return center-sampled normal angles for the automatically sized bins."""
    angle_min = number(settings.get("angle_min"), -90, -180, 180)
    angle_max = number(settings.get("angle_max"), 90, -180, 180)
    if angle_count <= 1:
        return ((angle_min + angle_max) / 2,)
    span = angle_max - angle_min
    return tuple(
        angle_min + ((index + .5) / angle_count) * span
        for index in range(angle_count)
    )


def _lightburn_fill_angle(normal_angle):
    """Convert Rasterizer's grating normal to LightBurn's path direction."""
    return (normal_angle + 90) % 180


def _fill_layer_plan(target_colors, settings=None):
    """Map available palette layers onto automatic carrier/angle combinations."""
    settings = settings or {}
    swatches = _grating_swatches(target_colors, settings)
    if not swatches:
        return {
            "carrier_count": 0, "angle_count": 0, "angles": (),
            "entries": (), "by_combination": {},
        }
    carrier_count, angle_count = _automatic_fill_dimensions(len(swatches))
    angles = _fill_angle_controls(settings, angle_count)
    entries = []
    by_combination = {}
    for carrier_index in range(carrier_count):
        for angle_index, normal_angle in enumerate(angles):
            swatch = swatches[len(entries)]
            entry = {
                "swatch": swatch,
                "carrier_index": carrier_index,
                "angle_index": angle_index,
                "normal_angle": normal_angle,
                "fill_angle": _lightburn_fill_angle(normal_angle),
            }
            entries.append(entry)
            by_combination[(carrier_index, angle_index)] = swatch
    return {
        "carrier_count": carrier_count,
        "angle_count": angle_count,
        "angles": angles,
        "entries": tuple(entries),
        "by_combination": by_combination,
    }


def _nearest_fill_angle_index(angle, fill_plan):
    """Quantize a continuous Krasnow normal angle to the nearest native Fill bin."""
    angles = fill_plan["angles"]
    def axial_distance(candidate):
        # Parallel lines repeat every 180 degrees, so -90 and +90 describe
        # the same axis even when a painted-flow offset crosses the endpoint.
        return abs(((angle - candidate + 90) % 180) - 90)
    return min(range(len(angles)), key=lambda index: axial_distance(angles[index]))


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
            "The Fauxlographic Material Library setting must have a positive speed."
        )
    spread = number(speed_spread, 1, 0, 2)
    pitch_ratio = target_pitch_um / REFERENCE_PITCH_UM
    speed_ratio = 1 + spread * (pitch_ratio - 1)
    return reference_speed * speed_ratio


def configure_output_layers(lightburn_project, target_colors, settings=None):
    """Clone the 1 um anchor into explicit-line or native-Fill carriers."""
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
            "matching 'Fauxlographic' or the classic name 'Holographic'."
        )

    # The palette entry's parent CutSetting is the user-editable Fauxlographic
    # recipe and is therefore authoritative.  Offset child passes can omit
    # fields such as QPulseWidth or retain stale imported values, so they must
    # not become the template for generated grating layers.  The generated
    # geometry is already open paths; child passes are cleared on each clone.
    setting_template = source_layer
    reference_frequency = number(getattr(setting_template, "frequency", 0), 0)
    if reference_frequency <= 0:
        raise ValueError(
            "The Fauxlographic Material Library setting must have a positive frequency."
        )

    grating_swatches = _grating_swatches(target_colors, settings)
    fill_mode = _grating_render_mode(settings) == "fill"
    fill_plan = _fill_layer_plan(target_colors, settings) if fill_mode else None
    if fill_mode:
        layer_entries = [
            (
                entry["swatch"],
                entry["carrier_index"],
                fill_plan["carrier_count"],
                entry,
            )
            for entry in fill_plan["entries"]
        ]
    else:
        layer_entries = [
            (color_hex, level, len(grating_swatches), None)
            for level, color_hex in enumerate(grating_swatches)
        ]

    output_layers = {}
    for color_hex, level, level_count, fill_entry in layer_entries:
        metadata = target_colors[color_hex]
        target_pitch_um = _pitch_for_level(level, level_count)
        clone = deepcopy(setting_template)
        clone.index = metadata[1]
        clone.name = metadata[2]
        clone.type = OUTPUT_FILL_MODE if fill_mode else OUTPUT_PATH_MODE
        clone.subLayers = []
        clone.speed = round(
            _speed_for_pitch(
                getattr(setting_template, "speed", 0),
                target_pitch_um,
                settings.get("speed_spread"),
            ),
            6,
        )
        if fill_mode:
            clone.interval = number(
                settings.get("line_spacing_mm"), .06, .01, .5
            )
            clone.angle = round(fill_entry["fill_angle"], 6)
            clone.anglePerPass = 0
            clone.crossHatch = False
            clone.scanOpt = "individual"
            clone.floodFill = False
        clone.materialName = getattr(source_layer, "materialName", "")
        clone.entryDesc = getattr(source_layer, "entryDesc", SETTING_NAME)
        output_layers[clone.index] = clone

    replaced_layers = []
    replaced_ids = set()
    for layer in project_layers:
        layer_id = getattr(layer, "index", None)
        if layer_id == setting_layer_id and layer_id not in output_layers:
            continue
        if fill_mode and layer_id in {
            target_colors[swatch][1] for swatch in grating_swatches
        } and layer_id not in output_layers:
            # Some factorisations intentionally leave a palette slot unused.
            # Remove its now-empty original layer instead of exposing a stale
            # non-carrier setting in the generated LightBurn project.
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


def _fauxlogram_gradient_scope(settings):
    value = str(settings.get(
        "fauxlogram_gradient_scope", "entire_artwork"
    )).strip().lower()
    return value if value in FAUXLOGRAM_GRADIENT_SCOPES else "entire_artwork"


def _fauxlogram_gradient_direction(settings):
    value = str(settings.get(
        "fauxlogram_gradient_direction", "top_to_bottom"
    )).strip().lower()
    return value if value in FAUXLOGRAM_GRADIENT_DIRECTIONS else "top_to_bottom"


def _gradient_position(x, y, bounds, settings):
    """Return the directed 0..1 position within artwork or shape bounds."""
    min_x, min_y, max_x, max_y = bounds
    direction = _fauxlogram_gradient_direction(settings)
    if direction in {"left_to_right", "right_to_left"}:
        position = (x - min_x) / max(max_x - min_x, 1e-9)
        if direction == "right_to_left":
            position = 1.0 - position
    elif direction in {"center_to_edge", "edge_to_center"}:
        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2
        half_width = max((max_x - min_x) / 2, 1e-9)
        half_height = max((max_y - min_y) / 2, 1e-9)
        position = math.hypot(
            (x - center_x) / half_width,
            (y - center_y) / half_height,
        )
        if direction == "edge_to_center":
            position = 1.0 - position
    else:
        position = (y - min_y) / max(max_y - min_y, 1e-9)
        if direction == "bottom_to_top":
            position = 1.0 - position
    return min(1.0, max(0.0, position))


def _gradient_value_at(x, y, bounds, settings):
    top = number(settings.get("gradient_top"), 165, 0, 255)
    bottom = number(settings.get("gradient_bottom"), 90, 0, 255)
    curve = number(settings.get("gradient_curve"), 1, .2, 5)
    position = _gradient_position(x, y, bounds, settings)
    shaped = position ** curve
    return top + (bottom - top) * shaped


def _gradient_value(y, min_y, max_y, settings):
    """Compatibility wrapper for the original vertical-gradient helper."""
    return _gradient_value_at(0, y, (0, min_y, 1, max_y), settings)


def _level_at_position(color_hex, x, y, bounds, settings, level_count):
    control = _gradient_value_at(x, y, bounds, settings) \
        + _hue_offset(color_hex, settings)
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


def _distance_to_stroke(x, y, stroke):
    """Return the normalized distance to a painted polyline."""
    points = stroke.get("points") or []
    if not points:
        return float("inf")
    if len(points) == 1:
        return math.hypot(x - points[0][0], y - points[0][1])
    closest = float("inf")
    for first, second in zip(points, points[1:]):
        ax, ay = first
        bx, by = second
        dx, dy = bx - ax, by - ay
        length_squared = dx * dx + dy * dy
        amount = 0 if length_squared <= 1e-12 else min(
            1, max(0, ((x - ax) * dx + (y - ay) * dy) / length_squared)
        )
        closest = min(closest, math.hypot(x - (ax + amount * dx), y - (ay + amount * dy)))
    return closest


def _stroke_bounds(stroke):
    points = stroke.get("points") or []
    if not points:
        return (0, 0, 1, 1)
    radius = number(stroke.get("width"), .08, .002, .5) / 2
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (
        max(0, min(xs) - radius), max(0, min(ys) - radius),
        min(1, max(xs) + radius), min(1, max(ys) + radius),
    )


def _prepare_fauxlogram_flow(settings):
    """Compile the small browser-authored flow plan for repeated cell sampling."""
    plan = settings.get("fauxlogram_flow")
    if not isinstance(plan, dict) or not plan.get("enabled"):
        return None
    regions = plan.get("regions") or []
    strokes = plan.get("strokes") or []
    if not regions:
        return None
    region_bounds = {}
    masks = {}
    for index in range(len(regions)):
        painted = [
            _stroke_bounds(stroke) for stroke in strokes
            if stroke.get("region") == index and not stroke.get("erase")
        ]
        region = regions[index]
        mask_spec = region.get("mask") if isinstance(region, dict) else None
        if isinstance(mask_spec, dict):
            image = decode_grayscale_mask(mask_spec)
            values = image.astype(float) / 255.0
            offset = region.get("mask_offset") or [0, 0]
            offset_x = number(offset[0] if len(offset) > 0 else 0, 0, -1, 1)
            offset_y = number(offset[1] if len(offset) > 1 else 0, 0, -1, 1)
            if region.get("mask_invert"):
                values = 1.0 - values
            threshold = number(region.get("mask_threshold"), 0.5, 0, 1)
            active_y, active_x = ((values > 0) & (values >= threshold)).nonzero()
            if len(active_x):
                width = max(image.shape[1] - 1, 1)
                height = max(image.shape[0] - 1, 1)
                mask_bounds = (
                    float(active_x.min()) / width + offset_x,
                    float(active_y.min()) / height + offset_y,
                    float(active_x.max()) / width + offset_x,
                    float(active_y.max()) / height + offset_y,
                )
                painted.append(mask_bounds)
                masks[index] = {
                    "values": values,
                    "threshold": threshold,
                    "mode": str(region.get("mask_mode") or "silhouette"),
                    "offset": (offset_x, offset_y),
                }
        if painted:
            region_bounds[index] = (
                min(item[0] for item in painted), min(item[1] for item in painted),
                max(item[2] for item in painted), max(item[3] for item in painted),
            )
    if not region_bounds:
        return None
    return {
        "regions": regions,
        "strokes": strokes,
        "bounds": region_bounds,
        "masks": masks,
    }


def _flow_scope_bounds(region, matched_stroke, compiled, region_index):
    scope = region.get("scope", "combined_region")
    if scope == "entire_artwork":
        return (0, 0, 1, 1)
    if scope == "each_shape":
        if matched_stroke is not None:
            return _stroke_bounds(matched_stroke)
        return compiled["bounds"].get(region_index, (0, 0, 1, 1))
    return compiled["bounds"].get(region_index, (0, 0, 1, 1))


def _flow_mask_value(mask, x, y):
    values = mask["values"]
    offset_x, offset_y = mask.get("offset", (0, 0))
    local_x = x - offset_x
    local_y = y - offset_y
    if not 0 <= local_x <= 1 or not 0 <= local_y <= 1:
        return 0.0
    column = min(values.shape[1] - 1, max(0, round(local_x * (values.shape[1] - 1))))
    row = min(values.shape[0] - 1, max(0, round(local_y * (values.shape[0] - 1))))
    return float(values[row, column])


def _flow_mask_gradient_angle(mask, x, y, bounds):
    """Use a grayscale mask's local dark-to-light slope as its direction."""
    values = mask["values"]
    if min(values.shape) < 2:
        return None
    offset_x, offset_y = mask.get("offset", (0, 0))
    local_x = x - offset_x
    local_y = y - offset_y
    column = min(values.shape[1] - 1, max(0, round(local_x * (values.shape[1] - 1))))
    row = min(values.shape[0] - 1, max(0, round(local_y * (values.shape[0] - 1))))
    left = max(0, column - 1)
    right = min(values.shape[1] - 1, column + 1)
    top = max(0, row - 1)
    bottom = min(values.shape[0] - 1, row + 1)
    width = max(bounds[2] - bounds[0], 1e-9)
    height = max(bounds[3] - bounds[1], 1e-9)
    slope_x = (values[row, right] - values[row, left]) * (values.shape[1] - 1) / max(right - left, 1) / width
    slope_y = (values[bottom, column] - values[top, column]) * (values.shape[0] - 1) / max(bottom - top, 1) / height
    if math.hypot(slope_x, slope_y) < 1e-3:
        return None
    return math.degrees(math.atan2(slope_y, slope_x))


def _flow_position(x, y, region, scope_bounds, combined_bounds):
    guide_start = region.get("start") or [.25, .5]
    guide_end = region.get("end") or [.75, .5]
    dx = guide_end[0] - guide_start[0]
    dy = guide_end[1] - guide_start[1]
    if abs(dx) + abs(dy) <= 1e-9:
        dx = 1
    if region.get("guide_type") == "radial":
        combined_width = max(combined_bounds[2] - combined_bounds[0], 1e-9)
        combined_height = max(combined_bounds[3] - combined_bounds[1], 1e-9)
        center_fraction_x = (guide_start[0] - combined_bounds[0]) / combined_width
        center_fraction_y = (guide_start[1] - combined_bounds[1]) / combined_height
        center_x = scope_bounds[0] + center_fraction_x * (scope_bounds[2] - scope_bounds[0])
        center_y = scope_bounds[1] + center_fraction_y * (scope_bounds[3] - scope_bounds[1])
        radius_x = (
            (guide_end[0] - guide_start[0]) / combined_width
            * (scope_bounds[2] - scope_bounds[0])
        )
        radius_y = (
            (guide_end[1] - guide_start[1]) / combined_height
            * (scope_bounds[3] - scope_bounds[1])
        )
        radius = max(math.hypot(radius_x, radius_y), 1e-9)
        position = math.hypot(x - center_x, y - center_y) / max(radius, 1e-9)
        gradient_angle = math.degrees(math.atan2(y - center_y, x - center_x))
    else:
        corners = (
            (scope_bounds[0], scope_bounds[1]), (scope_bounds[2], scope_bounds[1]),
            (scope_bounds[0], scope_bounds[3]), (scope_bounds[2], scope_bounds[3]),
        )
        projections = [px * dx + py * dy for px, py in corners]
        projection = x * dx + y * dy
        position = (projection - min(projections)) / max(max(projections) - min(projections), 1e-9)
        gradient_angle = math.degrees(math.atan2(dy, dx))
    if region.get("reverse"):
        position = 1 - position
    return min(1, max(0, position)), gradient_angle


def _painted_flow_controls(x, y, bounds, settings):
    """Return a painted cell's carrier control and grating angle, if any."""
    compiled = settings.get("_compiled_fauxlogram_flow")
    if not compiled:
        return None
    min_x, min_y, max_x, max_y = bounds
    nx = (x - min_x) / max(max_x - min_x, 1e-9)
    ny = (y - min_y) / max(max_y - min_y, 1e-9)
    hit_strokes = [
        stroke for stroke in reversed(compiled["strokes"])
        if _distance_to_stroke(nx, ny, stroke)
        <= number(stroke.get("width"), .08, .002, .5) / 2
    ]
    if any(stroke.get("erase") for stroke in hit_strokes):
        return None
    matched = None
    region_index = None
    mask_value = None
    for candidate in reversed(range(len(compiled["regions"]))):
        matched = next(
            (stroke for stroke in hit_strokes if stroke.get("region") == candidate),
            None,
        )
        if matched is not None:
            region_index = candidate
            break
        mask = compiled["masks"].get(candidate)
        if mask is None:
            continue
        value = _flow_mask_value(mask, nx, ny)
        if value > 0 and value >= mask["threshold"]:
            region_index = candidate
            mask_value = value
            break
    if region_index is None:
        return None
    if not isinstance(region_index, int) or not 0 <= region_index < len(compiled["regions"]):
        return None
    region = compiled["regions"][region_index]
    combined_bounds = compiled["bounds"].get(region_index, (0, 0, 1, 1))
    scope_bounds = _flow_scope_bounds(region, matched, compiled, region_index)
    mask = compiled["masks"].get(region_index)
    image_gradient_region = (
        matched is None and mask is not None
        and mask.get("mode") == "grayscale"
        and region.get("region_type") == "image_mask"
    )
    if image_gradient_region:
        # The image is the gradient guide for this region. Flat pixels have no
        # local slope, so use the region's explicit fallback angle, never the
        # default draggable guide inherited by older flow plans.
        position = mask_value
        mask_angle = _flow_mask_gradient_angle(mask, nx, ny, bounds)
        gradient_angle = (
            mask_angle if mask_angle is not None
            else number(region.get("fixed_angle"), 0, -180, 180)
        )
        if region.get("reverse"):
            position = 1 - position
    else:
        position, gradient_angle = _flow_position(nx, ny, region, scope_bounds, combined_bounds)
        if matched is None and mask is not None and mask.get("mode") == "grayscale":
            position = mask_value
            mask_angle = _flow_mask_gradient_angle(mask, nx, ny, bounds)
            if mask_angle is not None:
                gradient_angle = mask_angle
            if region.get("reverse"):
                position = 1 - position
    curve = number(region.get("curve"), settings.get("gradient_curve", 1), .2, 5)
    start = number(region.get("gradient_start"), settings.get("gradient_top", 165), 0, 255)
    end = number(region.get("gradient_end"), settings.get("gradient_bottom", 90), 0, 255)
    control = start + (end - start) * (position ** curve)
    orientation = region.get("orientation", "parallel")
    if orientation == "perpendicular":
        angle = gradient_angle + 90
    elif orientation == "fixed":
        angle = number(region.get("fixed_angle"), 0, -180, 180)
    else:
        angle = gradient_angle + number(region.get("angle_offset"), 0, -180, 180)
    return control, angle


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

# Candidate spacing found from each normalized silhouette's actual footprint.
# Collision checks below remain authoritative; these values only determine
# where the bounded greedy search begins.
_TIGHT_PACK_STEPS = {
    "skull": (.97, .80),
    "heart": (.90, .72),
    "space_invader": (.95, .85),
    "ghost": (1.0, .95),
    "bat": (1.0, .70),
    "alien_head": (.95, .76),
    "paw_print": (.88, .70),
    "fish_scale": (.90, .72),
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


def _tight_packed_icon_cells(bounds, patch_size, cell_shape, custom_template=None):
    """Greedily nest decorative silhouettes with bounded deterministic tries."""
    min_x, min_y, max_x, max_y = bounds
    canvas = box(min_x, min_y, max_x, max_y)
    template = (
        custom_template
        if custom_template is not None
        else _GAPPED_CELL_TEMPLATES[cell_shape]
    )
    x_multiplier, y_multiplier = _TIGHT_PACK_STEPS.get(cell_shape, (.90, .78))
    x_step = patch_size * x_multiplier
    y_step = patch_size * y_multiplier
    start_row = -3
    stop_row = math.ceil((max_y - min_y) / y_step) + 3
    start_column = -3
    stop_column = math.ceil((max_x - min_x) / x_step) + 3
    collision_index = SpatialCollisionIndex(patch_size)
    cells = []
    rotations = (-12, 12, -6, 6)
    offsets = ((0, 0), (-.035, 0), (.035, 0), (0, -.025), (0, .025))

    for row in range(start_row, stop_row + 1):
        center_y = min_y + patch_size / 2 + row * y_step
        center_x_offset = (row & 1) * x_step / 2
        for column in range(start_column, stop_column + 1):
            center_x = min_x + patch_size / 2 + center_x_offset + column * x_step
            variant = placement_variant(row, column)
            accepted = None
            accepted_attempt = None
            varied_rotations = rotations[variant % 4:] + rotations[:variant % 4]
            attempts = (
                [(0, offsets[0])]
                + [(rotation, offsets[0]) for rotation in varied_rotations]
                + [(0, offset) for offset in offsets[1:]]
            )
            for attempt, (rotation, offset) in enumerate(attempts):
                candidate_x = center_x + offset[0] * patch_size
                candidate_y = center_y + offset[1] * patch_size
                polygon = _template_polygon(
                    template, candidate_x, candidate_y, patch_size
                )
                if rotation:
                    polygon = affinity.rotate(
                        polygon, rotation, origin=(candidate_x, candidate_y)
                    )
                if polygon.intersection(canvas).area <= 1e-12:
                    continue
                if collision_index.overlaps(polygon):
                    continue
                accepted = polygon
                accepted_attempt = attempt
                break
            if accepted is not None:
                collision_index.add(accepted)
                cells.append(((row, column, accepted_attempt), accepted))
    return cells


def _tessellated_cells(
    bounds, patch_size, cell_shape, tight_pack=False, custom_template=None
):
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
    if tight_pack and (
        cell_shape in _GAPPED_CELL_TEMPLATES or cell_shape == "custom"
    ):
        return _tight_packed_icon_cells(
            bounds, patch_size, cell_shape, custom_template=custom_template
        )

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
    elif cell_shape in _GAPPED_CELL_TEMPLATES or cell_shape == "custom":
        template = (
            custom_template
            if custom_template is not None
            else _GAPPED_CELL_TEMPLATES[cell_shape]
        )
        row_step = patch_size * _GAPPED_CELL_ROW_STEPS.get(cell_shape, 1.0)
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
                    template,
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
    source_hex, geometry, candidate_indices, gradient_bounds = layer_plan
    fill_plan = settings.get("_fill_layer_plan")
    fill_mode = fill_plan is not None
    line_spacing = None if fill_mode else _line_spacing_for_color(
        source_hex, settings, scale_factor
    )
    level_count = (
        fill_plan["carrier_count"] if fill_mode else len(grating_swatches)
    )
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
            painted = _painted_flow_controls(
                center_x, center_y, bounds, settings
            )
            if painted is None:
                level = _level_at_position(
                    source_hex,
                    center_x,
                    center_y,
                    gradient_bounds,
                    settings,
                    level_count,
                )
                angle = _source_angle(center_x, center_y, bounds, settings)
            else:
                control, angle = painted
                control = min(
                    255.0,
                    max(0.0, control + _hue_offset(source_hex, settings)),
                )
                level = min(
                    level_count - 1,
                    math.floor(control / 256 * level_count),
                )
            if fill_mode:
                angle_index = _nearest_fill_angle_index(angle, fill_plan)
                output_swatch = fill_plan["by_combination"][(level, angle_index)]
                layer_pieces[output_swatch].append(region)
            else:
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
    """Build explicit gratings or closed cells for native LightBurn Fill."""
    progress = settings.get("_progress_logger")

    def log(message):
        if callable(progress):
            progress(message)

    settings = dict(settings or {})
    settings["_compiled_fauxlogram_flow"] = _prepare_fauxlogram_flow(settings)
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
    fill_mode = _grating_render_mode(settings) == "fill"
    if fill_mode:
        if settings.get("_setting_layer_id") is None:
            raise ValueError(
                "LightBurn Fill grating rendering requires a Material Library-backed "
                "job so Rasterizer can store each carrier's Fill angle, interval, and "
                "laser settings. Choose a Material Library or switch Grating Render "
                "Mode back to Explicit Lines."
            )
        settings["_fill_layer_plan"] = _fill_layer_plan(target_colors, settings)
        plan = settings["_fill_layer_plan"]
        log(
            "Krasnow LightBurn Fill: automatically allocated "
            f"{plan['carrier_count']} carrier levels x {plan['angle_count']} "
            f"angle bins = {len(plan['entries'])} layers from "
            f"{len(grating_swatches)} available layer slots."
        )

    scale_factor = number(settings.get("_scale_factor"), 1, 1e-9, 1000)
    patch_size = number(settings.get("patch_size_mm"), .4, .1, 5) / scale_factor
    cell_shape = _cell_shape(settings)
    custom_cell_template = None
    if cell_shape == "custom":
        custom_cell_template = svg_to_unit_geometry(
            settings.get("custom_cell_svg"),
            padding=number(settings.get("custom_cell_padding"), .06, 0, .3),
        )
    pieces = {swatch: [] for swatch in grating_swatches}

    tessellated_cells = None
    if cell_shape != "square":
        tessellated_cells = _tessellated_cells(
            bounds,
            patch_size,
            cell_shape,
            tight_pack=number(settings.get("tight_pack_geometry"), 0, 0, 1) >= .5,
            custom_template=custom_cell_template,
        )
    cell_label = "patches" if cell_shape == "square" else f"{cell_shape} cells"

    layer_plans = []
    total_patches = 0
    gradient_scope = _fauxlogram_gradient_scope(settings)
    for source_hex, geometry in processed_layers.items():
        if geometry.is_empty or (
            preserve_black and str(source_hex).upper() == "#000000"
        ):
            continue
        gradient_regions = (
            list(_geometry_components(geometry))
            if gradient_scope == "each_shape"
            else [geometry]
        )
        for region_geometry in gradient_regions:
            if cell_shape == "square":
                candidate_indices = _candidate_patch_indices(
                    region_geometry, bounds, patch_size
                )
            else:
                candidate_indices = [
                    cell for cell in tessellated_cells
                    if region_geometry.intersects(cell[1])
                ]
            total_patches += len(candidate_indices)
            gradient_bounds = (
                region_geometry.bounds
                if gradient_scope == "each_shape"
                else bounds
            )
            layer_plans.append((
                source_hex, region_geometry, candidate_indices, gradient_bounds
            ))

    log(
        f"[Krasnow mapping 1/3] DONE: planned {total_patches} candidate "
        f"{cell_label} across {len(layer_plans)} "
        f"{'non-Black ' if preserve_black else ''}source layers."
    )
    log(
        f"[Krasnow mapping 2/3] START: clipping {cell_label} and generating "
        f"{'closed native-Fill regions' if fill_mode else 'open grating paths'} "
        f"for {total_patches} candidate cells."
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
        f"[Krasnow mapping 2/3] DONE: generated {segment_count} "
        f"{'closed cell regions' if fill_mode else 'open path segments'} "
        f"across {len(populated)} carrier layers."
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
