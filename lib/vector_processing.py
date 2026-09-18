import sys
import os
import importlib.util
import json
from PIL import Image
import colorsys
import math
from concurrent.futures import ThreadPoolExecutor
import cv2
import numpy as np 
import svgwrite
import potrace
import xml.etree.ElementTree as ET
from collections import defaultdict
from shapely.geometry import Polygon, box, Point, MultiPoint, LineString, GeometryCollection
from shapely.ops import unary_union, voronoi_diagram, transform
from shapely.affinity import scale, affine_transform
from shapely.validation import make_valid
from svgelements import SVG, Path, Polygon as SVGPolygon
from datetime import datetime
from abstract_filters import (
    MODULES as ABSTRACT_FILTER_MODULES,
    apply as apply_registered_filter,
    canonical_name,
    manifest as filter_manifest,
    settings as registered_filter_settings,
)
from abstract_filters.common import number as _number
import geometry_styles


SOURCE_BLACK_PROGRESS_BATCHES = 6
SOURCE_BLACK_PROGRESS_MIN_COMPONENTS = 1000
LARGE_LIGHTBURN_PROJECT_BYTES = 50_000_000
LARGE_LIGHTBURN_PROJECT_WARNING = (
    "WARNING: This LightBurn project is larger than 50 MB and contains a large "
    "amount of geometry. Rasterizer has disabled the expensive cut-path "
    "optimizations and left only Order by Layer enabled. LightBurn may appear frozen or not responding after "
    "you press Frame, Send, or Start. Please be patient; LightBurn will typically "
    "become usable again after it finishes its calculations."
)

# from vector_processing import raster_to_puzzle_and_lightburn


def printLogMessage(message):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


def _yaml_scalar(value):
    """Return a safe, readable YAML scalar without adding a runtime dependency."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value))


def _yaml_lines(value, indent=0):
    """Serialize the job's simple settings structure to YAML lines."""
    prefix = " " * indent
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list, tuple)):
                yield f"{prefix}{key}:"
                yield from _yaml_lines(item, indent + 2)
            else:
                yield f"{prefix}{key}: {_yaml_scalar(item)}"
    elif isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, (dict, list, tuple)):
                yield f"{prefix}-"
                yield from _yaml_lines(item, indent + 2)
            else:
                yield f"{prefix}- {_yaml_scalar(item)}"
    else:
        yield f"{prefix}{_yaml_scalar(value)}"


def log_job_settings(**settings):
    """Write the input configuration as a YAML block at the top of job logs."""
    printLogMessage("--- job_settings.yaml ---")
    for line in _yaml_lines(settings):
        printLogMessage(line)
    printLogMessage("--- end job_settings.yaml ---")


def _project_note_label(value):
    return str(value or "none").replace("_", " ").strip().title()


def _project_note_value(value):
    if isinstance(value, bool):
        return "On" if value else "Off"
    if value is None or value == "":
        return "None"
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return str(value)


def _summarize_project_geometry(value):
    """Keep paint operations out of LightBurn Notes while recording their intent."""
    if not isinstance(value, dict):
        return value
    summarized = {}
    for key, item in value.items():
        if key == "fauxlogram_flow" and isinstance(item, dict):
            strokes = item.get("strokes") or []
            summarized[key] = {
                "enabled": bool(item.get("enabled")),
                "regions": len(item.get("regions") or []),
                "painted_shapes": sum(not stroke.get("erase") for stroke in strokes),
                "eraser_strokes": sum(bool(stroke.get("erase")) for stroke in strokes),
            }
        elif key == "custom_glyph_mask" and isinstance(item, dict):
            summarized[key] = {
                "width": item.get("width"),
                "height": item.get("height"),
                "uploaded": bool(item.get("data")),
            }
        elif isinstance(item, dict):
            summarized[key] = _summarize_project_geometry(item)
        else:
            summarized[key] = item
    return summarized


def build_rasterizer_project_note(
    *,
    image_preset,
    width,
    height,
    scale_factor,
    quantize_colors,
    min_island_area,
    simplification_factor,
    smoothing_radius,
    abstract_filter,
    abstract_filter_parameters,
    color_matching,
    job_settings,
    target_colors,
    geometry_style="vectors",
    geometry_style_parameters=None,
):
    """Build the human-readable Notes text embedded in every Rasterizer project."""
    job_settings = dict(job_settings or {})
    color_matching = dict(color_matching or {})
    public_filter_parameters = {
        key: value
        for key, value in dict(abstract_filter_parameters or {}).items()
        if not str(key).startswith("_")
    }
    public_geometry_parameters = _summarize_project_geometry({
        key: value
        for key, value in dict(geometry_style_parameters or {}).items()
        if not str(key).startswith("_")
    })
    job_type = "Fauxlographic" if image_preset == "holographic_artwork" else "Rasterizer"
    swatch_names = [
        str(metadata[2])
        for metadata in target_colors.values()
        if len(metadata) > 2 and str(metadata[2]).strip()
    ]

    lines = [
        "Rasterizer Parameters",
        f"Job type: {job_type}",
        f"Image preset: {_project_note_label(image_preset)}",
        f"Material: {_project_note_value(job_settings.get('selected_material'))}",
        f"Output dimensions: {width} x {height} pixels",
        f"Pixel size: {_project_note_value(scale_factor)} mm",
        f"Swatches: {', '.join(swatch_names) if swatch_names else 'None'}",
        f"Quantized colors: {_project_note_value(quantize_colors)}",
        f"Minimum island area: {_project_note_value(min_island_area)}",
        f"Simplification factor: {_project_note_value(simplification_factor)}",
        f"Smoothing radius: {_project_note_value(smoothing_radius)}",
        f"Color matching mode: {_project_note_label(color_matching.get('color_matching_mode', 'balanced'))}",
        f"Color matching hue weight: {_project_note_value(color_matching.get('color_matching_hue_weight', 4.0))}",
        f"Color matching saturation weight: {_project_note_value(color_matching.get('color_matching_saturation_weight', 1.0))}",
        f"Color matching lightness weight: {_project_note_value(color_matching.get('color_matching_lightness_weight', 1.0))}",
        "",
        f"Abstract filter: {_project_note_label(abstract_filter)}",
        "Abstract filter parameters:",
    ]
    if public_filter_parameters:
        lines.extend(
            f"- {_project_note_label(key)}: {_project_note_value(value)}"
            for key, value in sorted(public_filter_parameters.items())
        )
    else:
        lines.append("- None")
    lines.extend(["", f"Geometry style: {_project_note_label(geometry_style)}", "Geometry style parameters:"])
    if public_geometry_parameters:
        lines.extend(
            f"- {_project_note_label(key)}: {_project_note_value(value)}"
            for key, value in sorted(public_geometry_parameters.items())
        )
    else:
        lines.append("- None")
    return "\n".join(lines)


PHOTO_TYPE_PRESETS = {
    "cartoon": {
        "quantize_colors": None,
        "min_island_area": 0,
        "simplification_factor": 0.0,
        "smoothing_radius": 0.001
    },
    
    "color_photograph": {
        "quantize_colors": 24,          # Tonal color band limit
        "min_island_area": 8,           # Drops tiny laser fragments
        "simplification_factor": 0.35,  # Straightens jagged lines
        "smoothing_radius": 0.5         # Blends edge spaces
    },
    
    "bw_dither_photograph": {
        "quantize_colors": 2,           # Forced black and white output
        "min_island_area": 2,           # Retains high frequency dither dots
        "simplification_factor": 0.1,   # Drops line reshaping entirely
        "smoothing_radius": 0.1         # Locks tight boundaries
    },
    
    "abstract": {
        "quantize_colors": 12,           # posterized chunk colors
        "min_island_area": 25,          # Erases tiny geometric detail frames
        "simplification_factor": 1.8,   # High morph curve reshaping
        "smoothing_radius": 5,        # Round out geometric loops
        "abstract_filter": "wave"
    }
}

def str_to_bool(value: str) -> bool:
    # Convert to lowercase and strip whitespace
    clean_val = value.strip().lower()
    
    # Return True if it matches truthy terms
    return clean_val in ("true", "1", "yes", "on", "t")

def resize_to_specific_height_or_width( image, width=0, height=0 ):
    if (height == 0 and width != 0):
        width_percent = float(width) / float(image.size[0])
        new_height = int(float(image.size[1]) * float(width_percent))
        printLogMessage("resizing image to width: " + str(width) + " height: "+ str(new_height))
        resized_img = image.resize((width, int(new_height)), Image.Resampling.LANCZOS)
    elif (width == 0 and height != 0) :
        height_percent = float(height) / float(image.size[1])
        new_width = int(float(image.size[0]) * float(height_percent))
        printLogMessage("resizing image to width: " + str(new_width) + " height: "+ str(height))
        resized_img = image.resize((int(new_width),int(height) ), Image.Resampling.LANCZOS)
    else:
        return image
    return resized_img

found_lb_hex = {}
# Settings-only palette entries may be loaded as LightBurn layers but must
# never become a raster-color destination.
NON_IMAGE_SWATCHES = set()

# LightBurn's native layer indexes keep their official color identities even
# when a user assigns a differently named Material Library setting to them.
OFFICIAL_LIGHTBURN_LAYER_NAMES = {
    0: "Black", 1: "Blue", 2: "Red", 3: "Green", 4: "Yellow",
    5: "Orange", 6: "Cyan", 7: "Magenta", 8: "Light-Gray",
    9: "Dark-Blue", 10: "Dark-Red", 11: "Dark-Green",
    12: "Dark-Yellow", 13: "Dark-Orange", 14: "Light-Blue",
    15: "Dark-Magenta", 16: "Medium-Gray", 17: "Slate-Blue",
    18: "Rose", 19: "Periwinkle-Blue", 20: "Raspberry",
    21: "Sage-Green", 22: "Peach", 23: "Light-Pink",
    24: "Orchid-Pink", 25: "Deep-Purple", 26: "Rust-Brown",
    27: "Teal", 28: "Bright-Mint-Green", 29: "Light-Gold",
}

# Cell-clipping filters can temporarily expand one cleaned color layer into
# thousands of pieces. Running two very large source layers at once needlessly
# doubles that peak while providing little speedup inside GEOS. Above this
# object count, stream those filters one layer at a time and release each
# source batch as soon as its final geometry has been produced.
MEMORY_INTENSIVE_FILTER_SERIAL_THRESHOLD = 1_000_000
MEMORY_INTENSIVE_FILTERS = {
    "mosaic", "crystal", "spiral", "glitch", "deep_fryer",
}


def lightburn_layer_display_name(layer_index, assigned_name):
    """Show both the native color and an overridden library assignment."""
    assigned_name = str(assigned_name or "").strip()
    official_name = OFFICIAL_LIGHTBURN_LAYER_NAMES.get(int(layer_index), assigned_name)
    if not assigned_name or assigned_name.casefold() == official_name.casefold():
        return official_name
    return f"{official_name} - {assigned_name}"

LIGHTBURN_TEAL_RGB = (0, 71, 84)
LIGHTBURN_TEAL_LUMINANCE = (
    .2126 * LIGHTBURN_TEAL_RGB[0]
    + .7152 * LIGHTBURN_TEAL_RGB[1]
    + .0722 * LIGHTBURN_TEAL_RGB[2]
)


def source_black_cutoff_mask(source_img):
    """Reserve source pixels strictly darker than LightBurn Teal for Black."""
    pixels = np.asarray(source_img.convert("RGB"), dtype=np.float64)
    luminance = (
        .2126 * pixels[:, :, 0]
        + .7152 * pixels[:, :, 1]
        + .0722 * pixels[:, :, 2]
    )
    return luminance < LIGHTBURN_TEAL_LUMINANCE


def load_resized_source_black_cutoff_mask(raster_image_path, output_size):
    """Resize the source cutoff mask without interpolating its membership."""
    with Image.open(raster_image_path) as source:
        original_mask = source_black_cutoff_mask(source)
    mask_image = Image.fromarray(original_mask.astype(np.uint8) * 255)
    resized_mask = mask_image.resize(output_size, Image.Resampling.NEAREST)
    return np.asarray(resized_mask, dtype=np.uint8) == 255


def load_resized_artwork_alpha_mask(raster_image_path, output_size):
    """Return all non-fully-transparent source pixels at processing size."""
    with Image.open(raster_image_path) as source:
        alpha = np.asarray(source.convert("RGBA").getchannel("A"), dtype=np.uint8)
    mask_image = Image.fromarray((alpha > 0).astype(np.uint8) * 255)
    resized_mask = mask_image.resize(output_size, Image.Resampling.NEAREST)
    return np.asarray(resized_mask, dtype=np.uint8) == 255


def restore_reserved_black(quantized_img, source_black_mask):
    """Restore reserved source darkness after non-Black quantization."""
    output = np.asarray(quantized_img.convert("RGB"), dtype=np.uint8).copy()
    output[source_black_mask] = (0, 0, 0)
    return Image.fromarray(output)


def holographic_lab_black_mask(source_img):
    """Return the Holographic Etching Lab's adaptive dark two-color mask."""
    quantized = source_img.convert("RGB").quantize(colors=2, method=0).convert("RGB")
    pixels = np.asarray(quantized, dtype=np.uint8)
    palette_colors = {tuple(pixel) for pixel in pixels.reshape(-1, 3)}
    if not palette_colors:
        return np.zeros(pixels.shape[:2], dtype=bool)

    def luminance(rgb):
        return .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2]

    darkest_color = min(palette_colors, key=luminance)
    if len(palette_colors) == 1 and luminance(darkest_color) >= 128:
        return np.zeros(pixels.shape[:2], dtype=bool)
    return np.all(pixels == darkest_color, axis=2)


def _mask_to_merged_geometry(mask):
    """Convert a boolean raster mask into coalesced rectangle geometry."""
    height, width = mask.shape
    visited = np.zeros((height, width), dtype=bool)
    rectangles = []
    for y in range(height):
        for x in range(width):
            if not mask[y, x] or visited[y, x]:
                continue
            rectangle_width = 1
            while (
                x + rectangle_width < width
                and mask[y, x + rectangle_width]
                and not visited[y, x + rectangle_width]
            ):
                rectangle_width += 1
            rectangle_height = 1
            while y + rectangle_height < height:
                row = mask[y + rectangle_height, x:x + rectangle_width]
                row_visited = visited[y + rectangle_height, x:x + rectangle_width]
                if row_visited.any() or not np.all(row):
                    break
                rectangle_height += 1
            visited[y:y + rectangle_height, x:x + rectangle_width] = True
            rectangles.append(box(x, y, x + rectangle_width, y + rectangle_height))
    return unary_union(rectangles) if rectangles else GeometryCollection()


def artwork_crop_geometry(width, height, crop_shape):
    """Return the exact output boundary for a browser-applied artwork crop."""
    crop_shape = str(crop_shape or "").strip().lower()
    if crop_shape not in {"", "rectangle", "square", "oval", "circle", "transparency"}:
        raise ValueError("Choose a valid artwork crop shape")
    if crop_shape not in {"oval", "circle"}:
        return box(0, 0, width, height)
    if crop_shape == "circle":
        diameter = min(width, height)
        center_x, center_y = width / 2, height / 2
        return Point(center_x, center_y).buffer(diameter / 2, quad_segs=128)
    unit_circle = Point(width / 2, height / 2).buffer(1, quad_segs=128)
    return scale(unit_circle, xfact=width / 2, yfact=height / 2, origin=(width / 2, height / 2))


def replace_krasnow_black_layer(
    processed_layers,
    black_hex,
    source_img,
    reserved_black_mask=None,
):
    """Restore reserved source Black and give it exclusive output ownership."""
    output = dict(processed_layers)
    black_mask = np.asarray(reserved_black_mask, dtype=bool)
    expected_shape = (source_img.height, source_img.width)
    if black_mask.shape != expected_shape:
        raise ValueError(
            "Krasnow reserved Black mask does not match the prepared artwork dimensions."
        )
    black_geometry = _mask_to_merged_geometry(black_mask)
    for color_hex, geometry in list(output.items()):
        if color_hex == black_hex or geometry.is_empty:
            continue
        # Geometry styles run after an abstract transform, so their open
        # grating paths can cross back into source pixels reserved for Black.
        # Layer ordering is not ownership: remove those path segments so a
        # coordinate can never be engraved once by Black and again by a
        # colored carrier.
        output[color_hex] = geometry.difference(black_geometry)
    output[black_hex] = black_geometry
    return output


def nearest_available_swatch(r, g, b, target_colors, prefer_non_black=True):
    """Choose a configured swatch by RGB distance when a neutral fallback is absent."""
    candidates = [color for color in target_colors if color.upper() not in NON_IMAGE_SWATCHES]
    if prefer_non_black:
        non_black = [color for color in candidates if color.upper() != "#000000"]
        if non_black:
            candidates = non_black
    if not candidates:
        return "#000000"
    return min(
        candidates,
        key=lambda color: sum(
            (channel - reference) ** 2
            for channel, reference in zip((r, g, b), hex_to_rgb(color))
        ),
    )

def get_closest_color(r, g, b, TARGET_COLORS):
    """
    Determines the output color based on the input pixel's value (luminance) and hue.
    """
    # 1. Calculate Value (V) for thresholding (using max component for simplicity)
    try:
        return found_lb_hex[(r,g,b)]
    except KeyError as ke:
        r=int(r)
        g=int(g)
        b=int(b)
        exact_swatch = f"#{r:02X}{g:02X}{b:02X}"
        # Palette quantization above deliberately produces these exact RGB
        # values. Preserve that deliberate swatch assignment before the
        # generic low-saturation (gray) and hue fallback rules examine it.
        if exact_swatch in TARGET_COLORS and exact_swatch not in NON_IMAGE_SWATCHES:
            found_lb_hex[(r, g, b)] = exact_swatch
            return exact_swatch
        V = max(r, g, b)

        # 2. Apply Luminance Threshold Rules
        if V < 25:
            return "#000000" if "#000000" in TARGET_COLORS else nearest_available_swatch(
                r, g, b, TARGET_COLORS, prefer_non_black=False
            )
        
        # if (V > 250):
        #     return "#B4B4B4"  # Light Gray

        # 3. Apply Hue Matching Rule (between 25 and 200)
        
        # Normalize RGB to 0-1 range for colorsys
        r_norm, g_norm, b_norm = r / 255.0, g / 255.0, b / 255.0
        
        # Convert RGB to HSV. colorsys hue is 0-1, so multiply by 360
        h_float, s_float, v_float = colorsys.rgb_to_hsv(r_norm, g_norm, b_norm)
        pixel_hue = h_float * 360

        # Ensure the pixel has enough saturation/value to be considered a 'color'
        # If the pixel is too grayish or dark, the hue is meaningless.
        # We proceed with hue matching only if saturation/value is decent.
        if s_float < 0.45 or v_float < 0.15:
            # If not colorful enough, treat it as a shade of gray based on its value
            if v_float <= 0.5 and "#000000" in TARGET_COLORS:
                return "#000000"
            if "#B4B4B4" in TARGET_COLORS:
                return "#B4B4B4"
            # Some libraries intentionally omit Light-Gray. Do not leave
            # those pixels without a layer and let the black canvas consume
            # them; use the nearest configured engraving swatch instead.
            return nearest_available_swatch(r, g, b, TARGET_COLORS)
            
        
        min_diff = 360
        closest_hex = ""

        # Iterate through target hues to find the minimum angular difference
        for hex_code, (target_hue, layer_index, layer_name) in TARGET_COLORS.items():
            if hex_code.upper() in NON_IMAGE_SWATCHES:
                continue
            # Calculate the angular difference, handling the wrap-around at 0/360 degrees
            diff = abs(pixel_hue - target_hue)
            
            # Check the shortest path around the circle (e.g., 350 vs 10 is 20, not 340)
            angular_diff = min(diff, 360 - diff)
            
            if angular_diff < min_diff:
                min_diff = angular_diff
                closest_hex = hex_code

        found_lb_hex[(r,g,b)]=closest_hex
        return found_lb_hex[(r,g,b)]

def hex_to_rgb(hex_str):
    """Helper to convert #R_G_B or R_G_B hex string to a Numpy RGB tuple."""
    hex_str = hex_str.lstrip('#')
    return tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4))

def rgb_to_hex(rgb):
    """Converts an (R, G, B) tuple to a #RRGGBB hex string."""
    return '#{:02x}{:02x}{:02x}'.format(*rgb)

def parse_material_settings(
    lb,
    material_settings_path,
    limit_colors,
    TARGET_COLORS,
    material_name="stainless - steel",
    material_layer_report=None,
    required_setting_names=(),
    required_setting_aliases=None,
    return_setting_layers=False,
):
    """
    This function:
        1) parses the material settings file
        2) filters the materials based on the limit colors passed in
        3) filters the LightBurn layer TARGET_COLORS:
            to only include colors that exist in the material setings list
        4) returns the new LightBurn layer TARGET_COLORS for use in pixel generation=
            this ensures that we only find the closest LightBurn layer color that exists in our material settings
    """
    if material_layer_report is None:
        material_layer_report = {"loaded": [], "skipped": []}

    new_color_settings = lb.parse_material_library(material_settings_path)
    requested_material = str(material_name or "").strip().casefold()
    settings_per_material = {}
    for item in new_color_settings:
        name = str(getattr(item, "materialName", "") or "").strip()
        settings_per_material[name] = settings_per_material.get(name, 0) + 1

    matching_settings = [
        item for item in new_color_settings
        if requested_material == str(
            getattr(item, "materialName", "") or ""
        ).strip().casefold()
    ]
    placeholder_settings = [
        item for item in matching_settings
        if str(getattr(item, "entryDesc", "") or "").strip().casefold().startswith(
            "unconfigured "
        )
    ]
    if matching_settings and len(placeholder_settings) == len(matching_settings):
        raise ValueError(
            f"Material '{material_name}' contains only unconfigured Rasterizer palette "
            "entries. Replace placeholder values with complete tested settings and "
            "rename the configured entries before using this library."
        )
    matching_settings = [item for item in matching_settings if item not in placeholder_settings]
    material_layer_report.update({
        "selected_material": material_name,
        "available_materials": settings_per_material,
    })
    if not matching_settings:
        available = ", ".join(
            f"{name or '(unnamed)'} ({count} settings)"
            for name, count in sorted(settings_per_material.items(), key=lambda entry: entry[0].lower())
        ) or "none"
        printLogMessage(
            f"Material settings error: no entries matched '{material_name}'."
        )
        printLogMessage(f"Material names found in this file: {available}")
        raise ValueError(
            f"Material settings file does not contain '{material_name}'. "
            f"Available materials: {available}"
        )

    matched_settings = {}
    required_names = {
        str(name).strip().casefold() for name in required_setting_names if str(name).strip()
    }
    required_setting_aliases = required_setting_aliases or {}
    aliases_by_required_name = {
        required_name: {
            required_name,
            *(
                str(alias).strip().casefold()
                for alias in required_setting_aliases.get(required_name, ())
                if str(alias).strip()
            ),
        }
        for required_name in required_names
    }
    required_layers = {}
    next_layer_index = max((metadata[1] for metadata in TARGET_COLORS.values()), default=-1) + 1
    selected_targets = {
        metadata[2].casefold(): (color_hex, metadata)
        for color_hex, metadata in TARGET_COLORS.items()
        if metadata[2].casefold() in {str(color).strip().casefold() for color in limit_colors}
    }
    settings_by_target = {}
    for item in matching_settings:
        description = str(getattr(item, "entryDesc", "") or "").strip()
        target = selected_targets.get(description.casefold())
        if target is None:
            continue
        target_hex, target_metadata = target
        settings_by_target.setdefault(target_hex, []).append(description)
    target_names_by_hex = {
        color_hex: metadata[2] for color_hex, metadata in selected_targets.values()
    }
    duplicate_targets = [
        target_names_by_hex[target_hex]
        for target_hex, names in settings_by_target.items()
        if len(names) > 1
    ]
    if duplicate_targets:
        names = ", ".join(sorted(duplicate_targets, key=str.casefold))
        raise ValueError(
            f"Material '{material_name}' contains duplicate swatch name(s): {names}. "
            "Each material may contain only one setting per swatch name."
        )
    for item in matching_settings:
        # A LightBurn material-library Entry description is the palette
        # setting's identity. CutSetting/name is normally blank in genuine
        # .clb files and can contain stale project-layer metadata, so it must
        # never participate in swatch or required-setting matching.
        description = str(getattr(item, "entryDesc", "") or "").strip()
        description_key = description.casefold()
        target = selected_targets.get(description_key)
        matching_required_name = next(
            (
                required_name
                for required_name in required_names
                if any(
                    alias in description_key
                    for alias in aliases_by_required_name[required_name]
                )
            ),
            None,
        )
        if target is None and matching_required_name is not None:
            if matching_required_name in required_layers:
                continue
            item.frequency = int(item.frequency)
            item.index = next_layer_index
            next_layer_index += 1
            item.name = description
            required_layers[matching_required_name] = item.index
            lb.add_layer(item)
            material_layer_report["loaded"].append(item.name)
            printLogMessage(
                f"Additional filter setting '{item.name}' assigned to LightBurn layer {item.index}."
            )
            continue
        if target is None:
            material_layer_report["skipped"].append(description or "Unnamed setting")
            continue

        target_hex, target_metadata = target
        if target_hex in matched_settings:
            existing_name = matched_settings[target_hex][2]
            skipped_name = description or "Unnamed setting"
            material_layer_report["skipped"].append(skipped_name)
            printLogMessage(
                f"Material layer '{skipped_name}' skipped: '{existing_name}' already has "
                f"a setting assigned for LightBurn layer {target_metadata[1]}."
            )
            continue

        item.frequency = int(item.frequency)
        item.index = target_metadata[1]
        item.name = lightburn_layer_display_name(target_metadata[1], target_metadata[2])
        matched_settings[target_hex] = target_metadata
        if matching_required_name is not None:
            required_layers[matching_required_name] = target_metadata[1]
        lb.add_layer(item)
        material_layer_report["loaded"].append(item.name)
        printLogMessage(
            f"Material layer '{item.entryDesc}' assigned to LightBurn layer "
            f"{item.index}: {item.name} "
            f"(min/max power {item.minPower}/{item.maxPower}, speed {item.speed}, "
            f"frequency {item.frequency}, pulse width {item.QPulseWidth})"
        )

    missing_required = required_names.difference(required_layers)
    if missing_required:
        requested = ", ".join(sorted(missing_required))
        if missing_required == {"fauxlographic"}:
            raise ValueError(
                f"The selected Material Library material '{material_name}' is missing the "
                "cut setting required for this fauxlogram job. Add a LightBurn entry whose "
                "Description is 'fauxlographic' (the older name 'holographic' also works), "
                "set it to Cut mode, or choose a material that already has one. "
                "Then submit the job again."
            )
        raise ValueError(
            f"The selected Material Library material '{material_name}' is missing required "
            f"cut setting(s): {requested}. Add entries with matching Descriptions or choose "
            "a material that has them, then submit the job again."
        )
    if not matched_settings and not required_layers:
        raise ValueError(
            f"No colors in Material Library material '{material_name}' matched the selected "
            "Rasterizer swatch names. Rename the LightBurn entry descriptions to match "
            "those swatch names, or select a material with matching entries."
        )
    return (matched_settings, required_layers) if return_setting_layers else matched_settings


def init_lightburn(the_colors_limit, color_name_overrides=None):
    """
        This Function:
            1) initializes LightBurn module
            2) initiallizes the full list of lighburn layer colors
            3) filters the LightBurn layer colors so it only contains colors in limit_colors list
            4) returns the initialized objects to be used by other functions
    """
    # Define the module name and its exact absolute file path
    module_name = "lightburn"
    module_dir = os.path.dirname(os.path.abspath(__file__))
    lightburn_candidates = [
        os.environ.get("LIGHTBURN_MODULE"),
        os.path.join(module_dir, "lightburn.py"),
        os.path.join(module_dir, "lib", "lightburn.py"),
        os.path.join(os.path.dirname(module_dir), "lib", "lightburn.py"),
        "/app/lib/lightburn.py"
    ]
    file_path = next(
        (path for path in lightburn_candidates if path and os.path.isfile(path)),
        None
    )
    if file_path is None:
        raise FileNotFoundError(
            "lightburn.py was not found. Place it beside Material_Library.py, "
            "under lib/, or set LIGHTBURN_MODULE=/path/to/lightburn.py"
        )

    # Create a module spec from the file location
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    lightburn = importlib.util.module_from_spec(spec)
    TARGET_COLORS = {
        '#B4B4B4': (0, 8, 'Light-Gray'),
        '#000000': (0, 0, 'Black'),
        '#0000FF': (240, 1, 'Blue'),
        '#FF0000': (1, 2, 'Red'),
        '#00E000': (120, 3, 'Green'),
        '#D0D000': (60, 4, 'Yellow'),
        '#FF8000': (30, 5, 'Orange'),
        '#00E0E0': (180, 6, 'Cyan'),
        '#FF00FF': (300, 7, 'Magenta'),
        '#0000A0': (240, 9, 'Dark-Blue'),
        '#A00000': (359, 10, 'Dark-Red'),
        '#00A000': (120, 11, 'Dark-Green'),
        '#A0A000': (60, 12, 'Dark-Yellow'),
        '#C08000': (40, 13, 'Dark-Orange'),
        '#00A0FF': (202, 14, 'Light-Blue'),
        '#A000A0': (300, 15, 'Dark-Magenta'),
        '#808080': (2, 16, 'Medium-Gray'),
        '#7D87B9': (230, 17, 'Slate-Blue'),
        '#BB7784': (349, 18, 'Rose'),
        '#4A6FE3': (225, 19, 'Periwinkle-Blue'),
        '#D33F6A': (343, 20, 'Raspberry'),
        '#8CD78C': (120, 21, 'Sage-Green'),
        '#F0B98D': (27, 22, 'Peach'),
        '#F6C4E1': (325, 23, 'Light-Pink'),
        '#FA9ED4': (325, 24, 'Orchid-Pink'),
        '#500A78': (278, 25, 'Deep-Purple'),
        '#B45A00': (30, 26, 'Rust-Brown'),
        '#004754': (189, 27, 'Teal'),
        '#86FA88': (121, 28, 'Bright-Mint-Green'),
        '#FFDB66': (46, 29, 'Light-Gold')
    }
    for color_hex, label in (color_name_overrides or {}).items():
        color_hex = str(color_hex).strip().upper()
        if color_hex in TARGET_COLORS and isinstance(label, str) and label.strip():
            hue, layer_index, _ = TARGET_COLORS[color_hex]
            TARGET_COLORS[color_hex] = (hue, layer_index, label.strip())
    found_lb_hex.clear()
    if len(the_colors_limit) > 0:
        filtered_colors = {
            hex_code: value_tuple 
            for hex_code, value_tuple in TARGET_COLORS.items() 
            for hex_code, value_tuple in TARGET_COLORS.items() 
            if value_tuple[-1].lower() in the_colors_limit.lower()
        }
        # ensure light grey and black are always in the list 
        # these colors get defaulted to when no color is close enough to the target pixel
        filtered_colors['#B4B4B4'] = TARGET_COLORS['#B4B4B4']
        filtered_colors['#000000'] = TARGET_COLORS['#000000']
    else:
        filtered_colors = dict(TARGET_COLORS)
    # Add it to sys.modules cache and execute the code within the module
    sys.modules[module_name] = lightburn
    spec.loader.exec_module(lightburn)

    # Create the LightBurn object
    lb = lightburn.Lightburn()
    return filtered_colors, lb, lightburn


def normalize_vector_parameters(
    quantize_colors,
    min_island_area,
    simplification_factor,
    smoothing_radius,
    target_colors
):
    """
    Normalize parameters that may arrive from UI controls as either
    scalar values or single-item tuples/lists.
    """

    if isinstance(quantize_colors, (tuple, list)):
        quantize_colors = (
            quantize_colors[0]
            if quantize_colors
            else None
        )

    if quantize_colors is not None:
        quantize_colors = int(quantize_colors)

        max_allowable_colors = len(target_colors)

        if quantize_colors > max_allowable_colors:
            quantize_colors = max_allowable_colors

    if isinstance(min_island_area, (tuple, list)):
        min_island_area = (
            min_island_area[0]
            if min_island_area
            else 0
        )

    min_island_area = float(min_island_area)

    if isinstance(simplification_factor, (tuple, list)):
        simplification_factor = (
            simplification_factor[0]
            if simplification_factor
            else 0.0
        )

    simplification_factor = float(
        simplification_factor
    )

    if isinstance(smoothing_radius, (tuple, list)):
        smoothing_radius = (
            smoothing_radius[0]
            if smoothing_radius
            else 0.001
        )

    smoothing_radius = float(
        smoothing_radius
    )

    return (
        quantize_colors,
        min_island_area,
        simplification_factor,
        smoothing_radius
    )


def find_black_layer(target_colors):
    """
    Dynamically locate the black color and its LightBurn layer ID.
    """

    black_hex = next(
        (
            color_hex
            for color_hex, meta in target_colors.items()
            if (
                "black" in str(meta).lower()
                or color_hex == "#000000"
            )
        ),
        "#000000"
    )

    black_layer_id = target_colors.get(
        black_hex,
        [0, 0, "black"]
    )[1]

    return black_hex, black_layer_id


def preserve_saturated_palette_colors(
    source_img,
    quantized_img,
    target_colors,
    source_saturation_threshold=0.50,
    source_value_threshold=0.15,
    neutral_saturation_threshold=0.15,
    hue_weight=4.0,
    saturation_weight=1.0,
    value_weight=1.0,
):
    """Prevent saturated source colors from collapsing into neutral swatches.

    Pillow's fixed-palette quantizer uses RGB proximity.  A bright, moderately
    saturated blue can therefore be numerically closer to Light-Gray than to
    any available chromatic swatch, especially when Light-Blue or Slate-Blue
    is absent.  Reassign only those saturated pixels that the fixed-palette
    pass sent to a non-Black neutral swatch.  Hue-aware HSV distance keeps the
    replacement in the correct color family while still considering
    saturation and brightness.  The returned pixels remain exact official
    swatch RGB values, so all later geometry and LightBurn layer behavior is
    unchanged.
    """
    source_rgb = np.asarray(source_img.convert("RGB"), dtype=np.uint8)
    quantized_rgb = np.asarray(quantized_img.convert("RGB"), dtype=np.uint8).copy()
    if source_rgb.shape != quantized_rgb.shape:
        raise ValueError("Source and quantized palette images must have matching dimensions")

    candidate_swatches = []
    neutral_swatches = []
    for color_hex in target_colors:
        if color_hex.upper() in NON_IMAGE_SWATCHES:
            continue
        color_rgb = hex_to_rgb(color_hex)
        hue, saturation, value = colorsys.rgb_to_hsv(
            *(channel / 255.0 for channel in color_rgb)
        )
        swatch = (color_hex, color_rgb, hue * 360.0, saturation, value)
        if value < source_value_threshold:
            # Preserve intentional Black assignments; darkness is not a
            # neutral-color collapse.
            continue
        if saturation < neutral_saturation_threshold:
            neutral_swatches.append(swatch)
        else:
            candidate_swatches.append(swatch)

    if not neutral_swatches or not candidate_swatches:
        return quantized_img

    source_hsv = cv2.cvtColor(source_rgb, cv2.COLOR_RGB2HSV)
    source_hue = source_hsv[..., 0].astype(np.float32) * 2.0
    source_saturation = source_hsv[..., 1].astype(np.float32) / 255.0
    source_value = source_hsv[..., 2].astype(np.float32) / 255.0

    neutral_assignment = np.zeros(source_hue.shape, dtype=bool)
    for _, neutral_rgb, _, _, _ in neutral_swatches:
        neutral_assignment |= np.all(quantized_rgb == neutral_rgb, axis=2)

    correction_mask = (
        neutral_assignment
        & (source_saturation >= float(source_saturation_threshold))
        & (source_value >= float(source_value_threshold))
    )
    flat_indexes = np.flatnonzero(correction_mask)
    if not flat_indexes.size:
        return quantized_img

    affected_hue = source_hue.reshape(-1)[flat_indexes]
    affected_saturation = source_saturation.reshape(-1)[flat_indexes]
    affected_value = source_value.reshape(-1)[flat_indexes]
    best_distance = np.full(flat_indexes.size, np.inf, dtype=np.float32)
    best_rgb = np.zeros((flat_indexes.size, 3), dtype=np.uint8)

    for _, color_rgb, hue, saturation, value in candidate_swatches:
        hue_delta = np.abs(affected_hue - hue)
        hue_delta = np.minimum(hue_delta, 360.0 - hue_delta) / 180.0
        distance = (
            float(hue_weight) * hue_delta * hue_delta
            + float(saturation_weight) * (affected_saturation - saturation) ** 2
            + float(value_weight) * (affected_value - value) ** 2
        )
        replace = distance < best_distance
        best_distance[replace] = distance[replace]
        best_rgb[replace] = color_rgb

    quantized_rgb.reshape(-1, 3)[flat_indexes] = best_rgb
    printLogMessage(
        "Palette quantization preserved chroma for "
        f"{flat_indexes.size} saturated source pixels initially assigned "
        "to neutral swatches."
    )
    return Image.fromarray(quantized_rgb, mode="RGB")


def distinguish_blue_palette_shades(
    source_img,
    quantized_img,
    target_colors,
    hue_weight=4.0,
    saturation_weight=1.0,
    lightness_weight=1.0,
    source_saturation_threshold=0.20,
    neutral_saturation_threshold=0.15,
):
    """Separate darker Blue from lighter Periwinkle within the blue family.

    Fixed RGB palette quantization can prefer Periwinkle for nearly every blue
    in an illustration because Periwinkle's red and green channels place it
    closer to anti-aliased and moderately saturated source pixels.  Compare
    pixels already assigned to a true-blue swatch in HSL space so saturation
    and apparent tone can distinguish the active Blue and Periwinkle layers.

    Cyan and Teal intentionally stay outside this pass: they represent a
    different blue-green family and retain their existing assignments.
    """
    source_rgb = np.asarray(source_img.convert("RGB"), dtype=np.uint8)
    quantized_rgb = np.asarray(quantized_img.convert("RGB"), dtype=np.uint8).copy()
    if source_rgb.shape != quantized_rgb.shape:
        raise ValueError("Source and quantized palette images must have matching dimensions")

    blue_swatches = []
    neutral_swatches = []
    for color_hex in target_colors:
        if color_hex.upper() in NON_IMAGE_SWATCHES:
            continue
        color_rgb = hex_to_rgb(color_hex)
        hue, lightness, saturation = colorsys.rgb_to_hls(
            *(channel / 255.0 for channel in color_rgb)
        )
        hue *= 360.0
        # This range includes native Blue and Periwinkle while deliberately
        # excluding Cyan/Teal and violet/purple layers.
        if 210.0 <= hue <= 250.0 and saturation >= 0.15:
            blue_swatches.append((color_rgb, hue, saturation, lightness))
        elif saturation < neutral_saturation_threshold and lightness >= 0.15:
            neutral_swatches.append(color_rgb)

    if len(blue_swatches) < 2:
        return quantized_img

    blue_assignment = np.zeros(source_rgb.shape[:2], dtype=bool)
    for color_rgb, _, _, _ in blue_swatches:
        blue_assignment |= np.all(quantized_rgb == color_rgb, axis=2)
    if not np.any(blue_assignment):
        return quantized_img

    source_hls = cv2.cvtColor(source_rgb, cv2.COLOR_RGB2HLS)
    source_hue = source_hls[..., 0].astype(np.float32) * 2.0
    source_lightness = source_hls[..., 1].astype(np.float32) / 255.0
    source_saturation = source_hls[..., 2].astype(np.float32) / 255.0

    # A fixed RGB palette can occasionally place a subtly cool white or gray
    # on Periwinkle. Do not let the blue-family refinement lock those pixels
    # into a chromatic layer. When an actual neutral layer is available, give
    # low-saturation source pixels back to the nearest neutral RGB swatch.
    neutral_source = blue_assignment & (
        source_saturation < float(source_saturation_threshold)
    )
    neutral_indexes = np.flatnonzero(neutral_source)
    if neutral_indexes.size and neutral_swatches:
        source_flat = source_rgb.reshape(-1, 3).astype(np.float32)
        neutral_pixels = source_flat[neutral_indexes]
        neutral_palette = np.asarray(neutral_swatches, dtype=np.float32)
        distances = np.sum(
            (neutral_pixels[:, None, :] - neutral_palette[None, :, :]) ** 2,
            axis=2,
        )
        quantized_rgb.reshape(-1, 3)[neutral_indexes] = neutral_palette[
            np.argmin(distances, axis=1)
        ].astype(np.uint8)
        printLogMessage(
            "Palette quantization restored "
            f"{neutral_indexes.size} low-saturation source pixels from "
            "blue-family assignments to neutral swatches."
        )

    chromatic_blue_assignment = blue_assignment & (
        source_saturation >= float(source_saturation_threshold)
    )
    flat_indexes = np.flatnonzero(chromatic_blue_assignment)
    if not flat_indexes.size:
        return Image.fromarray(quantized_rgb, mode="RGB")

    affected_hue = source_hue.reshape(-1)[flat_indexes]
    affected_saturation = source_saturation.reshape(-1)[flat_indexes]
    affected_lightness = source_lightness.reshape(-1)[flat_indexes]
    best_distance = np.full(flat_indexes.size, np.inf, dtype=np.float32)
    best_rgb = np.zeros((flat_indexes.size, 3), dtype=np.uint8)

    for color_rgb, hue, saturation, lightness in blue_swatches:
        hue_delta = np.abs(affected_hue - hue)
        hue_delta = np.minimum(hue_delta, 360.0 - hue_delta) / 180.0
        distance = (
            float(hue_weight) * hue_delta * hue_delta
            + float(saturation_weight) * (affected_saturation - saturation) ** 2
            + float(lightness_weight) * (affected_lightness - lightness) ** 2
        )
        replace = distance < best_distance
        best_distance[replace] = distance[replace]
        best_rgb[replace] = color_rgb

    output_flat = quantized_rgb.reshape(-1, 3)
    changed = np.any(output_flat[flat_indexes] != best_rgb, axis=1)
    output_flat[flat_indexes] = best_rgb
    if np.any(changed):
        printLogMessage(
            "Palette quantization distinguished blue-family tone for "
            f"{int(np.count_nonzero(changed))} source pixels."
        )
    return Image.fromarray(quantized_rgb, mode="RGB")


def resolve_color_matching(settings=None):
    """Resolve safe user-facing quantization presets into numeric weights."""
    settings = settings or {}
    mode = str(settings.get("color_matching_mode") or "balanced").strip().lower()
    presets = {
        "balanced": {
            "preserve_chroma": True, "separate_blue_shades": True,
            "hue_weight": 4.0, "saturation_weight": 1.0, "lightness_weight": 1.0,
        },
        "hue": {
            "preserve_chroma": True, "separate_blue_shades": True,
            "hue_weight": 8.0, "saturation_weight": 1.0, "lightness_weight": 1.0,
        },
        "shades": {
            "preserve_chroma": True, "separate_blue_shades": True,
            "hue_weight": 2.0, "saturation_weight": 1.0, "lightness_weight": 4.0,
        },
        "closest": {
            "preserve_chroma": False, "separate_blue_shades": False,
            "hue_weight": 0.0, "saturation_weight": 0.0, "lightness_weight": 0.0,
        },
    }
    if mode in presets:
        return {"mode": mode, **presets[mode]}
    if mode != "custom":
        mode = "balanced"
        return {"mode": mode, **presets[mode]}

    def weight(name, default):
        try:
            value = float(settings.get(name, default))
        except (TypeError, ValueError):
            value = default
        if not math.isfinite(value):
            value = default
        return max(0.0, min(10.0, value))

    resolved = {
        "mode": "custom",
        "preserve_chroma": True,
        "separate_blue_shades": True,
        "hue_weight": weight("color_matching_hue_weight", 4.0),
        "saturation_weight": weight("color_matching_saturation_weight", 1.0),
        "lightness_weight": weight("color_matching_lightness_weight", 1.0),
    }
    if not sum(resolved[key] for key in (
        "hue_weight", "saturation_weight", "lightness_weight"
    )):
        return {"mode": "balanced", **presets["balanced"]}
    return resolved


def prepare_raster_image(
    raster_image_path,
    new_height,
    new_width,
    quantize_colors,
    target_colors=None,
    prevent_palette_black=False,
    color_matching=None,
):
    """
    Open, convert, resize, and optionally quantize the raster image.
    """

    printLogMessage(
        f"Opening raster image: {raster_image_path}"
    )

    img = Image.open(
        raster_image_path
    ).convert("RGB")

    orig_width, orig_height = img.size

    printLogMessage(
        f"Original Image Pixel Size: "
        f"{orig_width}, {orig_height}"
    )

    img = resize_to_specific_height_or_width(
        image=img,
        height=int(new_height),
        width=int(new_width)
    )

    if quantize_colors is not None:

        printLogMessage(
            f"Quantizing photo colors down to a "
            f"maximum pool of {quantize_colors} levels..."
        )

        active_swatches = list((target_colors or {}).keys())
        if active_swatches:
            # Quantize to the actual active LightBurn palette instead of an
            # unrelated adaptive palette. This prevents a later hue snap from
            # collapsing many generic quantization colors into Light-Gray.
            palette = Image.new("P", (1, 1))
            palette_values = []
            for color_hex in active_swatches[:256]:
                palette_values.extend(hex_to_rgb(color_hex))
            if prevent_palette_black:
                final_swatch = palette_values[-3:]
                padding_entries = 256 - len(active_swatches[:256])
                palette.putpalette(palette_values + final_swatch * padding_entries)
                source_img = img
                img = img.quantize(
                    colors=len(active_swatches[:256]),
                    palette=palette,
                    dither=Image.Dither.NONE,
                ).convert("RGB")
            else:
                palette.putpalette(palette_values + [0] * (768 - len(palette_values)))
                source_img = img
                img = img.quantize(palette=palette, dither=Image.Dither.NONE).convert("RGB")
            matching = resolve_color_matching(color_matching)
            if matching["preserve_chroma"]:
                img = preserve_saturated_palette_colors(
                    source_img, img, target_colors or {},
                    hue_weight=matching["hue_weight"],
                    saturation_weight=matching["saturation_weight"],
                    value_weight=matching["lightness_weight"],
                )
            if matching["separate_blue_shades"]:
                img = distinguish_blue_palette_shades(
                    source_img, img, target_colors or {},
                    hue_weight=matching["hue_weight"],
                    saturation_weight=matching["saturation_weight"],
                    lightness_weight=matching["lightness_weight"],
                )
            printLogMessage(
                f"Color matching mode: {matching['mode']} "
                f"(hue={matching['hue_weight']:.3g}, "
                f"saturation={matching['saturation_weight']:.3g}, "
                f"shade={matching['lightness_weight']:.3g})."
            )
            printLogMessage(
                f"Using {len(active_swatches)} active LightBurn swatches as the quantization palette."
            )
        else:
            img = img.quantize(
                colors=quantize_colors,
                method=0
            ).convert("RGB")

    return img


def classify_raster_pixels(
    img,
    target_colors,
    black_hex,
    ignore_background_hex,
    include_black=False,
    transparent=False,
    transparent_rgb_values=None,
    light_threshold=225,
    include_mask=None,
):
    """
    Convert raster pixels into 1x1 Shapely boxes grouped by color.

    Black pixels are intentionally skipped because the black layer is
    constructed later as a punched-out canvas.
    """

    width, height = img.size
    if include_mask is not None:
        include_mask = np.asarray(include_mask, dtype=bool)
        if include_mask.shape != (height, width):
            raise ValueError(
                "Artwork transparency mask does not match the prepared image dimensions."
            )

    pixel_boxes_by_color = defaultdict(list)

    printLogMessage(
        "Analyzing pixels and snapping colors..."
    )

    for y in range(height):

        for x in range(width):

            if include_mask is not None and not include_mask[y, x]:
                continue

            pixel_rgb = img.getpixel(
                (x, y)
            )

            if transparent_rgb_values is not None:
                # Black-and-white photo mode is quantized to two exact RGB
                # values.  Its transparent option removes the actual lighter
                # swatch, not merely pixels above an arbitrary brightness.
                if pixel_rgb in transparent_rgb_values:
                    continue
            elif transparent:
                luminance = 0.2126 * pixel_rgb[0] + 0.7152 * pixel_rgb[1] + 0.0722 * pixel_rgb[2]
                if luminance >= light_threshold:
                    continue

            closest_hex = get_closest_color(
                *pixel_rgb,
                target_colors
            )

            # Ignore designated background.
            if closest_hex == ignore_background_hex:
                continue

            # Do not construct black from raster pixels.
            #
            # Black will instead become:
            #
            #     canvas - all colored geometry
            #
            if closest_hex == black_hex and not include_black:
                continue

            pixel_poly = box(
                x,
                y,
                x + 1,
                y + 1
            )

            pixel_boxes_by_color[
                closest_hex
            ].append(
                pixel_poly
            )

    return pixel_boxes_by_color


def reassign_small_raster_islands(
    pixel_boxes_by_color,
    min_island_area,
    color_order=(),
    black_hex="#000000",
    fallback_to_black=True,
):
    """Transfer small raster components to the color sharing most pixel edges.

    The ownership decision is made on the exact classified pixel grid before
    smoothing, simplification, or abstract-filter geometry can introduce
    numerical ambiguity. Each pixel belongs to exactly one output color, so
    reclamation cannot create either a gap or a positive-area overlap.
    """
    empty_stats = {
        "components": 0,
        "pixels": 0,
        "neighbor_components": 0,
        "black_fallback_components": 0,
        "discarded_components": 0,
    }
    if min_island_area <= 0:
        return pixel_boxes_by_color, empty_stats

    owner_by_cell = {}
    box_by_cell = {}
    passthrough = defaultdict(list)
    ordered_colors = list(dict.fromkeys((*color_order, *pixel_boxes_by_color.keys())))
    color_rank = {color: index for index, color in enumerate(ordered_colors)}

    for color_hex, boxes in pixel_boxes_by_color.items():
        for item in boxes:
            min_x, min_y, max_x, max_y = item.bounds
            x = int(round(min_x))
            y = int(round(min_y))
            if (
                abs(min_x - x) > 1e-7
                or abs(min_y - y) > 1e-7
                or abs((max_x - min_x) - 1.0) > 1e-7
                or abs((max_y - min_y) - 1.0) > 1e-7
                or (x, y) in owner_by_cell
            ):
                # The production classifier emits unique unit boxes. Preserve
                # non-raster caller input rather than guessing its grid sides.
                passthrough[color_hex].append(item)
                continue
            owner_by_cell[(x, y)] = color_hex
            box_by_cell[(x, y)] = item

    visited = set()
    stats = dict(empty_stats)
    directions = ((-1, 0), (1, 0), (0, -1), (0, 1))

    component_by_cell = {}
    component_colors = []
    component_areas = []
    component_pixels = []
    for start_cell, source_color in owner_by_cell.items():
        if start_cell in visited:
            continue
        stack = [start_cell]
        visited.add(start_cell)
        component = []
        while stack:
            cell = stack.pop()
            component.append(cell)
            x, y = cell
            for dx, dy in directions:
                neighbor = (x + dx, y + dy)
                if (
                    neighbor not in visited
                    and owner_by_cell.get(neighbor) == source_color
                ):
                    visited.add(neighbor)
                    stack.append(neighbor)

        for cell in component:
            component_by_cell[cell] = len(component_colors)
        component_colors.append(source_color)
        component_areas.append(sum(box_by_cell[cell].area for cell in component))
        component_pixels.append(len(component))

    original_component_colors = tuple(component_colors)
    original_component_pixels = tuple(component_pixels)
    parents = list(range(len(component_colors)))
    component_neighbors = [defaultdict(int) for _ in component_colors]

    # Count shared sides between the original components once. The component
    # graph is contracted below as small regions change ownership, avoiding
    # repeated full-image connected-component scans.
    for (x, y), component_id in component_by_cell.items():
        for neighbor_cell in ((x + 1, y), (x, y + 1)):
            neighbor_id = component_by_cell.get(neighbor_cell)
            if neighbor_id is None or neighbor_id == component_id:
                continue
            component_neighbors[component_id][neighbor_id] += 1
            component_neighbors[neighbor_id][component_id] += 1

    def find(component_id):
        while parents[component_id] != component_id:
            parents[component_id] = parents[parents[component_id]]
            component_id = parents[component_id]
        return component_id

    def normalized_neighbors(component_id):
        component_id = find(component_id)
        neighbors = defaultdict(int)
        for neighbor_id, shared_side_count in component_neighbors[component_id].items():
            neighbor_root = find(neighbor_id)
            if neighbor_root != component_id:
                neighbors[neighbor_root] += shared_side_count
        component_neighbors[component_id] = neighbors
        return neighbors

    def contract(component_ids, target_color):
        roots = sorted({find(component_id) for component_id in component_ids})
        survivor = roots[0]
        root_set = set(roots)
        external_neighbors = defaultdict(int)
        for component_id in roots:
            for neighbor_id, shared_side_count in component_neighbors[component_id].items():
                neighbor_root = find(neighbor_id)
                if neighbor_root not in root_set:
                    external_neighbors[neighbor_root] += shared_side_count
        for component_id in roots[1:]:
            parents[component_id] = survivor
        component_colors[survivor] = target_color
        component_areas[survivor] = sum(component_areas[item] for item in roots)
        component_pixels[survivor] = sum(component_pixels[item] for item in roots)
        component_neighbors[survivor] = external_neighbors
        return survivor

    # Process the component graph deterministically. Every neighboring-color
    # transfer immediately contracts the source with all touching components
    # of the chosen target color. A later transfer therefore moves the whole
    # merged region instead of leaving behind pixels from an earlier transfer.
    # Each such operation removes at least one graph component, so adjacent
    # small components cannot swap colors forever or create new tiny islands.
    pending = list(range(len(component_colors)))
    pending_index = 0
    while pending_index < len(pending):
        component_id = find(pending[pending_index])
        pending_index += 1

        neighbors = normalized_neighbors(component_id)
        same_color_neighbors = [
            neighbor_id for neighbor_id in neighbors
            if component_colors[neighbor_id] == component_colors[component_id]
        ]
        while same_color_neighbors:
            component_id = contract(
                [component_id, *same_color_neighbors],
                component_colors[component_id],
            )
            neighbors = normalized_neighbors(component_id)
            same_color_neighbors = [
                neighbor_id for neighbor_id in neighbors
                if component_colors[neighbor_id] == component_colors[component_id]
            ]

        if component_areas[component_id] >= min_island_area:
            continue

        source_color = component_colors[component_id]
        shared_sides = defaultdict(int)
        for neighbor_id, shared_side_count in neighbors.items():
            neighbor_color = component_colors[neighbor_id]
            if neighbor_color != source_color:
                shared_sides[neighbor_color] += shared_side_count

        if shared_sides:
            target_color = min(
                shared_sides,
                key=lambda color: (
                    -shared_sides[color],
                    color_rank.get(color, len(color_rank)),
                    color,
                ),
            )
            target_neighbors = [
                neighbor_id for neighbor_id in neighbors
                if component_colors[neighbor_id] == target_color
            ]
            component_id = contract(
                [component_id, *target_neighbors],
                target_color,
            )
            stats["neighbor_components"] += 1
            if component_areas[component_id] < min_island_area:
                pending.append(component_id)
        elif fallback_to_black and source_color != black_hex:
            component_colors[component_id] = black_hex
            stats["black_fallback_components"] += 1
        elif not fallback_to_black:
            component_colors[component_id] = None
            stats["discarded_components"] += 1

    changed_components = []
    for component_id, original_color in enumerate(original_component_colors):
        final_color = component_colors[find(component_id)]
        if final_color != original_color:
            changed_components.append(component_id)
    stats["components"] = len(changed_components)
    stats["pixels"] = sum(
        original_component_pixels[component_id]
        for component_id in changed_components
    )

    reassigned = defaultdict(list)
    for color_hex in ordered_colors:
        reassigned[color_hex].extend(passthrough.get(color_hex, ()))
    for cell, source_color in owner_by_cell.items():
        target_color = component_colors[find(component_by_cell[cell])]
        if target_color is not None:
            reassigned[target_color].append(box_by_cell[cell])

    return defaultdict(
        list,
        {color: boxes for color, boxes in reassigned.items() if boxes},
    ), stats


def retain_dominant_foreground(pixel_boxes_by_color, img, settings):
    """Keep the largest connected non-background subject for powder-coat art."""
    rgb = np.asarray(img.convert("RGB"), dtype=np.float32)
    height, width = rgb.shape[:2]
    border = np.concatenate((rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]), axis=0)
    background = np.median(border, axis=0)
    distance = np.linalg.norm(rgb - background, axis=2)
    normalized = np.uint8(np.clip(distance / max(distance.max(), 1) * 255, 0, 255))
    _, mask = cv2.threshold(normalized, 0, 1, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    box_records = []
    for color, boxes in pixel_boxes_by_color.items():
        for item in boxes:
            x, y = int(item.bounds[0]), int(item.bounds[1])
            if 0 <= x < width and 0 <= y < height:
                box_records.append((color, item, x, y))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count <= 1:
        return pixel_boxes_by_color
    candidates = list(range(1, count))
    min_percent = _number(settings.get("foreground_min_percent"), .15, 0, 100)
    minimum_area = width * height * min_percent / 100
    eligible = [label for label in candidates if stats[label, cv2.CC_STAT_AREA] >= minimum_area]
    dominant = max(eligible or candidates, key=lambda label: stats[label, cv2.CC_STAT_AREA])
    retained = defaultdict(list)
    for color, item, x, y in box_records:
        if labels[y, x] == dominant:
            retained[color].append(item)
    printLogMessage(f"Powder-coat subject isolation retained {stats[dominant, cv2.CC_STAT_AREA]} foreground pixels.")
    return retained


# ============================================================================
# ABSTRACT FILTERS
# ============================================================================

def normalize_abstract_settings(abstract_filter, filter_parameters=None):
    supplied = {}
    if isinstance(abstract_filter, dict):
        supplied.update(abstract_filter)
        name = supplied.pop("name", supplied.pop("filter", "none"))
    else:
        name = abstract_filter or "none"
    if isinstance(filter_parameters, dict):
        supplied.update(filter_parameters)
    return registered_filter_settings(name, supplied)


def get_abstract_filter_manifest():
    return filter_manifest()


def apply_abstract_filter(geometry, abstract_filter, filter_parameters=None):
    if abstract_filter is None or geometry.is_empty:
        return geometry
    name, values = normalize_abstract_settings(abstract_filter, filter_parameters)
    return apply_registered_filter(name, geometry, values)


def remove_small_islands(
    geometry,
    min_island_area
):
    """
    Remove polygon fragments smaller than the requested area.
    """

    if (
        min_island_area <= 0
        or geometry.is_empty
    ):
        return geometry

    if geometry.geom_type == "Polygon":

        if geometry.area < min_island_area:

            return box(
                0,
                0,
                0,
                0
            )

        return geometry

    if geometry.geom_type in (
        "MultiPolygon",
        "GeometryCollection"
    ):

        valid_polys = [
            polygon
            for polygon in geometry.geoms
            if polygon.area >= min_island_area
        ]

        if valid_polys:

            return unary_union(
                valid_polys
            )

        return box(
            0,
            0,
            0,
            0
        )

    return geometry


def partition_small_islands(geometry, min_island_area):
    """Return retained geometry and the exact islands removed by cleanup."""
    empty = GeometryCollection()
    if min_island_area <= 0 or geometry.is_empty:
        return geometry, empty
    if geometry.geom_type == "Polygon":
        return (geometry, empty) if geometry.area >= min_island_area else (empty, geometry)
    if geometry.geom_type in ("MultiPolygon", "GeometryCollection"):
        retained = []
        removed = []
        for item in geometry.geoms:
            destination = retained if item.area >= min_island_area else removed
            destination.append(item)
        return (
            unary_union(retained) if retained else empty,
            unary_union(removed) if removed else empty,
        )
    return geometry, empty


def _geometry_object_count(geometry):
    """Count geometry components without logging individual objects."""
    if geometry is None or geometry.is_empty:
        return 0
    if geometry.geom_type in ("Polygon", "LineString"):
        return 1
    if hasattr(geometry, "geoms"):
        return sum(_geometry_object_count(item) for item in geometry.geoms)
    return 1


def process_color_geometry(
    boxes,
    min_island_area,
    simplification_factor,
    smoothing_radius,
    abstract_filter,
    filter_parameters=None,
    progress_context=None,
    collect_removed_islands=False,
):
    """Convert one color's pixel batch into finalized vector geometry."""
    filter_name, settings = normalize_abstract_settings(abstract_filter, filter_parameters)
    context = progress_context or "color layer"
    input_count = len(boxes)

    def stage(step, operation, state, geometry=None, count=None):
        object_count = count if count is not None else _geometry_object_count(geometry)
        printLogMessage(
            f"[{context}] Step {step}/6 {state}: {operation}; "
            f"batch objects {object_count}/{input_count} source objects."
        )

    stage(1, "same-color pixel union", "START", count=input_count)
    welded_layer = unary_union(boxes)
    stage(1, "same-color pixel union", "DONE", geometry=welded_layer)

    stage(2, "morphological smoothing", "START", geometry=welded_layer)
    final_geometry = welded_layer.buffer(smoothing_radius).buffer(-smoothing_radius)
    stage(2, "morphological smoothing", "DONE", geometry=final_geometry)

    stage(3, "small-island removal", "START", geometry=final_geometry)
    if collect_removed_islands:
        final_geometry, removed_islands = partition_small_islands(
            final_geometry, min_island_area
        )
    else:
        final_geometry = remove_small_islands(final_geometry, min_island_area)
        removed_islands = box(0, 0, 0, 0)
    stage(3, "small-island removal", "DONE", geometry=final_geometry)

    stage(4, "boundary simplification", "START", geometry=final_geometry)
    if simplification_factor > 0.0:
        final_geometry = final_geometry.simplify(
            simplification_factor, preserve_topology=True
        )
    stage(4, "boundary simplification", "DONE", geometry=final_geometry)

    stage(5, f"abstract filter '{filter_name}'", "START", geometry=final_geometry)
    final_geometry = apply_abstract_filter(
        final_geometry, abstract_filter, filter_parameters
    )
    stage(5, f"abstract filter '{filter_name}'", "DONE", geometry=final_geometry)

    stage(6, "final topology validation", "START", geometry=final_geometry)
    if not final_geometry.is_valid:
        printLogMessage(f"[{context}] Repairing invalid geometry after processing.")
        final_geometry = make_valid(final_geometry)
    stage(6, "final topology validation", "DONE", geometry=final_geometry)

    if collect_removed_islands:
        return final_geometry, removed_islands
    return final_geometry


def _raster_boxes_to_rectangles(boxes):
    """Convert unit pixel boxes into deterministic, non-overlapping run rectangles.

    Horizontal runs with identical extents are merged vertically. Every input
    pixel is represented exactly once, so the result cannot turn an outlined
    region into one enclosing filled polygon.
    """
    rows = defaultdict(list)
    for item in boxes:
        min_x, min_y, max_x, max_y = item.bounds
        if max_x - min_x == 1 and max_y - min_y == 1:
            rows[int(round(min_y))].append(int(round(min_x)))

    active = {}
    completed = []
    previous_y = None
    for y in sorted(rows):
        x_values = sorted(set(rows[y]))
        runs = []
        if x_values:
            run_start = run_end = x_values[0]
            for x in x_values[1:]:
                if x == run_end + 1:
                    run_end = x
                else:
                    runs.append((run_start, run_end + 1))
                    run_start = run_end = x
            runs.append((run_start, run_end + 1))

        if previous_y is None or y != previous_y + 1:
            completed.extend(active.values())
            active = {}

        next_active = {}
        for run in runs:
            if run in active:
                x_start, y_start, x_end, _ = active[run]
                next_active[run] = (x_start, y_start, x_end, y + 1)
            else:
                next_active[run] = (run[0], y, run[1], y + 1)
        completed.extend(
            rectangle for run, rectangle in active.items() if run not in next_active
        )
        active = next_active
        previous_y = y

    completed.extend(active.values())
    return [
        box(x_start, y_start, x_end, y_end)
        for x_start, y_start, x_end, y_end in completed
    ]


def build_source_black_component_layer(
    black_pixel_boxes,
    processed_layers,
    black_hex,
    worker_count=None,
    precision_grid=0.001,
    abstract_filter="none",
    filter_parameters=None,
    black_rectangles=None,
):
    """Build sparse source-derived Black geometry without a synthetic canvas.

    Black raster runs are deliberately kept as separate, hole-free rectangles.
    Filters that use one shared coordinate transform are applied to every Black
    rectangle before intersections with already-processed non-Black layers are
    removed concurrently. ``executor.map`` and source scan order make the
    assembled output deterministic.
    """
    if black_rectangles is None:
        black_rectangles = _raster_boxes_to_rectangles(black_pixel_boxes)
    else:
        black_rectangles = list(black_rectangles)
    if not black_rectangles:
        return GeometryCollection()

    def bounds_intersect(left, right):
        return not (
            left[2] < right[0] or right[2] < left[0]
            or left[3] < right[1] or right[3] < left[1]
        )

    def repair(geometry):
        if geometry.is_empty:
            return geometry
        if not geometry.is_valid:
            geometry = make_valid(geometry)
        return geometry.buffer(0)

    def polygonal_parts(geometry):
        if geometry.is_empty:
            return []
        if geometry.geom_type == "Polygon":
            return [geometry]
        if hasattr(geometry, "geoms"):
            parts = []
            for item in geometry.geoms:
                parts.extend(polygonal_parts(item))
            return parts
        return []

    # Some clipping filters can leave zero-area line or point artifacts beside
    # their valid polygons. GEOS precision-grid overlay rejects such mixed-
    # dimension operands. Black subtraction only concerns filled area, so use
    # a polygon-only copy for overlap math while leaving the exported colored
    # layer geometry itself untouched.
    colored_entries = []
    for color_hex, geometry in processed_layers.items():
        if color_hex == black_hex or geometry.is_empty:
            continue
        parts = polygonal_parts(geometry)
        if not parts:
            continue
        polygonal_geometry = repair(unary_union(parts))
        if not polygonal_geometry.is_empty:
            colored_entries.append((color_hex, polygonal_geometry))
    colored_geometries = [geometry for _, geometry in colored_entries]
    colored_bounds = [geometry.bounds for geometry in colored_geometries]

    def subtract_color_overlaps(result):
        result = repair(result)
        for color_geometry, color_bounds in zip(colored_geometries, colored_bounds):
            if result.is_empty or not bounds_intersect(result.bounds, color_bounds):
                continue
            if not result.intersects(color_geometry):
                continue
            result = result.difference(color_geometry, grid_size=precision_grid)
            result = repair(result)
        return result

    def remove_color_overlaps(rectangle):
        return subtract_color_overlaps(apply_abstract_filter(
            rectangle, abstract_filter, filter_parameters
        ))

    def process_component_batches(items, operation):
        """Process components in stable chunks with restrained progress logs."""
        items = list(items)
        item_count = len(items)
        if not items:
            return []

        show_batch_progress = item_count >= SOURCE_BLACK_PROGRESS_MIN_COMPONENTS
        batch_count = (
            min(SOURCE_BLACK_PROGRESS_BATCHES, item_count)
            if show_batch_progress
            else 1
        )
        batch_size = math.ceil(item_count / batch_count)
        results = []

        executor = None
        if worker_count > 1:
            executor = ThreadPoolExecutor(
                max_workers=worker_count, thread_name_prefix="source-black"
            )
        try:
            for batch_index, start in enumerate(
                range(0, item_count, batch_size), start=1
            ):
                batch = items[start:start + batch_size]
                if show_batch_progress:
                    printLogMessage(
                        f"Source-derived Black batch {batch_index}/{batch_count} "
                        f"START: processing {len(batch)} component(s)."
                    )
                if executor is not None:
                    batch_results = list(executor.map(operation, batch))
                else:
                    batch_results = [operation(item) for item in batch]
                results.extend(batch_results)
                if show_batch_progress:
                    printLogMessage(
                        f"Source-derived Black batch {batch_index}/{batch_count} "
                        f"DONE: processed {len(results)}/{item_count} component(s)."
                    )
        finally:
            if executor is not None:
                executor.shutdown(wait=True)
        return results

    if worker_count is None:
        try:
            worker_count = int(os.environ.get("RASTER_WORKER_PROCESSES", "1"))
        except (TypeError, ValueError):
            worker_count = 1
    worker_count = max(
        1, min(int(worker_count), os.cpu_count() or 1, len(black_rectangles))
    )
    printLogMessage(
        f"Source-derived Black: processing {len(black_rectangles)} exact raster "
        f"run rectangles through abstract filter '{abstract_filter or 'none'}' "
        f"with {worker_count} CPU worker(s)."
    )
    filter_name, _normalized_filter_settings = normalize_abstract_settings(
        abstract_filter, filter_parameters
    )
    filter_module = ABSTRACT_FILTER_MODULES.get(filter_name)
    source_black_transform = getattr(filter_module, "apply_source_black", None)
    if callable(source_black_transform):
        printLogMessage(
            f"Source-derived Black: applying one shared '{abstract_filter}' "
            "fragment field before parallel color-overlap subtraction."
        )
        transformed_components = list(source_black_transform(
            black_rectangles, filter_parameters or {}
        ))
        printLogMessage(
            f"Source-derived Black: shared '{abstract_filter}' fragment field "
            f"complete with {len(transformed_components)} component(s)."
        )
        results = process_component_batches(
            transformed_components, subtract_color_overlaps
        )
    else:
        results = process_component_batches(
            black_rectangles, remove_color_overlaps
        )

    components = []
    for result in results:
        components.extend(polygonal_parts(result))
    output = GeometryCollection(components)

    printLogMessage(
        "Source-derived Black overlap validation START: checking the assembled "
        f"Black layer against {len(colored_geometries)} non-Black layer(s)."
    )
    overlap_parts = []
    for color_geometry, color_bounds in zip(colored_geometries, colored_bounds):
        if bounds_intersect(output.bounds, color_bounds):
            overlap = output.intersection(color_geometry)
            if not overlap.is_empty and overlap.area > 0:
                overlap_parts.extend(polygonal_parts(overlap))

    overlap_geometry = unary_union(overlap_parts) if overlap_parts else GeometryCollection()
    overlap_area = overlap_geometry.area
    overlap_tolerance = precision_grid * precision_grid
    printLogMessage(
        "Source-derived Black overlap validation DONE: initial overlap area is "
        f"{overlap_area:.6f} square coordinate units."
    )

    if overlap_area > overlap_tolerance:
        if filter_name == "mosaic":
            printLogMessage(
                "Source-derived Black found a color overlap of "
                f"{overlap_area:.6f} square coordinate units; Mosaic assigns it "
                "to Black and removes it from the colored layers."
            )
            # Mosaic's independently clipped tiles produced visible seams when
            # the residual was removed from Black. Retain its tested ownership
            # rule, including the one-grid cutout that keeps Black continuous.
            overlap_cutout = repair(overlap_geometry.buffer(precision_grid))
            corrected_entries = []
            for color_hex, color_geometry in colored_entries:
                if bounds_intersect(color_geometry.bounds, overlap_cutout.bounds):
                    color_geometry = repair(color_geometry.difference(overlap_cutout))
                processed_layers[color_hex] = color_geometry
                if not color_geometry.is_empty:
                    corrected_entries.append((color_hex, color_geometry))

            colored_entries = corrected_entries
            colored_geometries = [geometry for _, geometry in colored_entries]
            colored_bounds = [geometry.bounds for geometry in colored_geometries]
        else:
            printLogMessage(
                "Source-derived Black found a color overlap of "
                f"{overlap_area:.6f} square coordinate units; preserving color "
                "and removing only the exact residual from Black."
            )
            # The residual is a numerical overlay artifact after the initial
            # color subtraction. Expanding it before cutting color creates a
            # visible seam, especially at ordinary cartoon boundaries. Remove
            # precisely the measured conflict from Black instead.
            output = repair(output.difference(overlap_geometry))

        remaining_parts = []
        for color_geometry, color_bounds in zip(colored_geometries, colored_bounds):
            if output.is_empty or not bounds_intersect(output.bounds, color_bounds):
                continue
            remaining = output.intersection(color_geometry)
            if not remaining.is_empty and remaining.area > 0:
                remaining_parts.extend(polygonal_parts(remaining))
        remaining_overlap = (
            unary_union(remaining_parts).area if remaining_parts else 0.0
        )
        if remaining_overlap > overlap_tolerance:
            raise ValueError(
                "source-derived Black residual-overlap correction failed: "
                f"{remaining_overlap}"
            )
        printLogMessage("Source-derived Black residual-overlap correction passed.")

    printLogMessage(
        "Source-derived Black validation passed: no positive-area overlap "
        f"with {len(colored_geometries)} non-Black layer(s)."
    )
    return output


def process_color_layers(
    pixel_boxes_by_color,
    target_colors,
    min_island_area,
    simplification_factor,
    smoothing_radius,
    abstract_filter,
    filter_parameters=None,
    collect_removed_islands=False,
):
    """
    Convert all raster color groups into finalized Shapely geometries.
    """

    processed_layers = {}
    filter_name, settings = normalize_abstract_settings(abstract_filter, filter_parameters)
    filter_module = ABSTRACT_FILTER_MODULES.get(filter_name)
    light_layers_only = bool(getattr(filter_module, "LIGHT_LAYERS_ONLY", False))
    light_threshold = _number(settings.get("light_threshold", 150), 150, 0, 255)
    invert_threshold = bool(settings.get("invert_threshold", False))

    def is_light_swatch(color_hex):
        """Use perceived brightness so dark artwork remains the foreground."""
        try:
            red, green, blue = (int(color_hex[index:index + 2], 16) for index in (1, 3, 5))
        except (TypeError, ValueError):
            return False
        brightness = .2126 * red + .7152 * green + .0722 * blue
        return brightness <= light_threshold if invert_threshold else brightness >= light_threshold

    total_layers = len(pixel_boxes_by_color)
    total_source_objects = sum(len(boxes) for boxes in pixel_boxes_by_color.values())

    printLogMessage(
        f"Beginning vector union math for "
        f"{total_layers} unique layers containing "
        f"{total_source_objects} source objects..."
    )

    layer_jobs = []
    for idx, (color_hex, boxes) in enumerate(pixel_boxes_by_color.items(), 1):
        if not boxes:
            continue

        layer_meta = target_colors.get(color_hex)
        if layer_meta is None:
            # Color snapping can produce a neutral gray even when the chosen
            # Material Library has no matching gray setting. Only geometry
            # backed by an actual LightBurn layer may be exported; skipping it
            # lets the synthetic black canvas occupy that space rather than
            # terminating the entire job with a KeyError.
            printLogMessage(
                f" -> Skipping {color_hex}: no matching Material Library "
                "setting was loaded for this color."
            )
            continue

        layer_id = layer_meta[1]
        layer_color_name = layer_meta[2]

        progress_context = (
            f"Color {idx}/{total_layers} {color_hex} / "
            f"Layer {layer_id} {layer_color_name}"
        )

        layer_filter = abstract_filter
        if light_layers_only and not is_light_swatch(color_hex):
            layer_filter = "none"
        layer_jobs.append((
            idx, color_hex, boxes, layer_filter, progress_context,
            layer_id, layer_color_name,
        ))

    def process_layer(job):
        idx, color_hex, boxes, layer_filter, progress_context, layer_id, layer_color_name = job
        printLogMessage(
            f" -> Merging color boundaries... "
            f"(Layer math step {idx}/{total_layers} - "
            f"Layer: {layer_id} [{layer_color_name}])"
        )
        processed_result = process_color_geometry(
            boxes=boxes,
            min_island_area=min_island_area,
            simplification_factor=simplification_factor,
            smoothing_radius=smoothing_radius,
            abstract_filter=layer_filter,
            filter_parameters=filter_parameters,
            progress_context=progress_context,
            collect_removed_islands=collect_removed_islands,
        )
        if collect_removed_islands:
            final_geometry, removed_islands = processed_result
        else:
            final_geometry, removed_islands = processed_result, None
        return color_hex, final_geometry, removed_islands, progress_context, len(boxes)

    try:
        configured_workers = int(os.environ.get("RASTER_WORKER_PROCESSES", "1"))
    except (TypeError, ValueError):
        configured_workers = 1
    worker_count = max(
        1, min(configured_workers, os.cpu_count() or 1, len(layer_jobs) or 1)
    )
    if (
        worker_count > 1
        and filter_name in MEMORY_INTENSIVE_FILTERS
        and total_source_objects >= MEMORY_INTENSIVE_FILTER_SERIAL_THRESHOLD
    ):
        printLogMessage(
            f"Memory safeguard: processing {filter_name} layers serially because "
            f"{total_source_objects} source objects meet the "
            f"{MEMORY_INTENSIVE_FILTER_SERIAL_THRESHOLD} object threshold."
        )
        worker_count = 1

    # Jobs now own the source batches; discard the mapping's duplicate list
    # references before geometry work begins.
    pixel_boxes_by_color.clear()

    removed_island_geometries = []
    if worker_count > 1:
        printLogMessage(
            f"Processing {len(layer_jobs)} independent color layers with "
            f"{worker_count} CPU workers."
        )
        with ThreadPoolExecutor(
            max_workers=worker_count, thread_name_prefix="raster-layer"
        ) as executor:
            completed_layers = list(executor.map(process_layer, layer_jobs))
    else:
        completed_layers = []
        for job_index, job in enumerate(layer_jobs):
            color_hex, final_geometry, removed_islands, progress_context, input_count = process_layer(job)
            processed_layers[color_hex] = final_geometry
            if removed_islands is not None and not removed_islands.is_empty:
                removed_island_geometries.append(removed_islands)
            printLogMessage(
                f"[{progress_context}] LAYER DONE: "
                f"{_geometry_object_count(final_geometry)} output objects from "
                f"{input_count} source objects."
            )
            # Release this potentially huge list of source pixel polygons
            # before starting the next layer.
            layer_jobs[job_index] = None

    # ``executor.map`` preserves submission order, keeping export and
    # serialization order identical to the former serial path.
    for color_hex, final_geometry, removed_islands, progress_context, input_count in completed_layers:
        processed_layers[color_hex] = final_geometry
        if removed_islands is not None and not removed_islands.is_empty:
            removed_island_geometries.append(removed_islands)
        printLogMessage(
            f"[{progress_context}] LAYER DONE: "
            f"{_geometry_object_count(final_geometry)} output objects from "
            f"{input_count} source objects."
        )

    # A small number of filters need the complete set of cleaned color layers
    # to perform a coherent reassignment. Existing geometry-only filters do
    # not expose this capability and therefore keep their exact prior path.
    remap_layers = getattr(filter_module, "remap_layers", None)
    if callable(remap_layers):
        printLogMessage(f"Applying cross-layer mapping for abstract filter '{filter_name}'...")
        settings["_progress_logger"] = printLogMessage
        processed_layers = remap_layers(processed_layers, target_colors, settings)
        printLogMessage(
            f"Cross-layer mapping produced {len(processed_layers)} calibrated output layers."
        )

    if collect_removed_islands:
        return processed_layers, removed_island_geometries
    return processed_layers


# ============================================================================
# BLACK BACKGROUND
# ============================================================================

def build_black_canvas(width, height, abstract_filter, filter_parameters=None):
    """Build the complete black canvas used for LightBurn nesting."""
    return apply_abstract_filter(
        box(0, 0, width, height),
        abstract_filter,
        filter_parameters
    )


def build_punched_black_layer(
    width,
    height,
    processed_layers,
    black_hex,
    abstract_filter,
    filter_parameters=None,
):
    """
    Build the black layer as the canvas minus all colored geometry.

    Invalid geometries are repaired and precision-snapped before subtraction.
    """

    canvas_frame = build_black_canvas(
        width,
        height,
        abstract_filter,
        filter_parameters
    )

    colored_geometries = []
    precision_grid = 0.001

    def topology_safe(geometry, label):
        """Repair polygon topology before a GEOS overlay operation."""
        if geometry.is_empty:
            return geometry
        if not geometry.is_valid:
            printLogMessage(f"Repairing invalid geometry for {label} before black-layer subtraction...")
            geometry = make_valid(geometry)
        # A zero-width buffer resolves residual touching-ring artifacts that
        # ``make_valid`` can retain in geometry collections.
        try:
            return geometry.buffer(0)
        except Exception as error:
            printLogMessage(f"Topology cleanup warning for {label}: {error}")
            return geometry

    cleanup_jobs = [
        (color_hex, geometry)
        for color_hex, geometry in processed_layers.items()
        if color_hex != black_hex and not geometry.is_empty
    ]

    def clean_color_geometry(job):
        color_hex, geometry = job
        return topology_safe(geometry, f"color {color_hex}")

    try:
        configured_workers = int(os.environ.get("RASTER_WORKER_PROCESSES", "1"))
    except (TypeError, ValueError):
        configured_workers = 1
    cleanup_workers = max(
        1, min(configured_workers, os.cpu_count() or 1, len(cleanup_jobs) or 1)
    )
    if cleanup_workers > 1:
        printLogMessage(
            f"Preparing {len(cleanup_jobs)} colored layers for black subtraction "
            f"with {cleanup_workers} CPU workers."
        )
        with ThreadPoolExecutor(
            max_workers=cleanup_workers, thread_name_prefix="black-cleanup"
        ) as executor:
            cleaned_geometries = list(executor.map(clean_color_geometry, cleanup_jobs))
    else:
        cleaned_geometries = [clean_color_geometry(job) for job in cleanup_jobs]

    # Preserve source-layer order because subtraction order affects topology.
    colored_geometries.extend(
        geometry for geometry in cleaned_geometries if not geometry.is_empty
    )

    if not colored_geometries:

        printLogMessage(
            "No colored geometry found; "
            "black layer remains a complete canvas."
        )

        return canvas_frame

    printLogMessage(
        f"Punching {len(colored_geometries)} "
        f"colored layer(s) out of black background..."
    )

    # Subtract one repaired layer at a time.  A combined union can create
    # invalid shared edges after abstract transforms, even when each input
    # geometry is valid on its own.  A tiny grid snap is visually invisible
    # at raster scale and makes the overlay operation deterministic.
    punched_black_layer = topology_safe(canvas_frame, "black canvas")
    total_punch_layers = len(colored_geometries)
    for punch_index, color_geometry in enumerate(colored_geometries, 1):
        punch_objects = _geometry_object_count(color_geometry)
        printLogMessage(
            f"[Black punch {punch_index}/{total_punch_layers}] START: "
            f"subtracting {punch_objects} geometry objects."
        )
        try:
            punched_black_layer = punched_black_layer.difference(
                color_geometry, grid_size=precision_grid
            )
        except Exception as error:
            printLogMessage(
                f"Retrying black punch-through after topology repair: {error}"
            )
            punched_black_layer = topology_safe(
                punched_black_layer, "partially punched black canvas"
            ).difference(
                topology_safe(color_geometry, "colored punch-through geometry"),
                grid_size=precision_grid
            )
        punched_black_layer = topology_safe(
            punched_black_layer, "partially punched black canvas"
        )
        printLogMessage(
            f"[Black punch {punch_index}/{total_punch_layers}] DONE: "
            f"subtracted {punch_objects} geometry objects; "
            f"black layer now has {_geometry_object_count(punched_black_layer)} objects."
        )

    printLogMessage(
        "Black layer successfully punched around "
        "all colored geometry."
    )

    return punched_black_layer

# ============================================================================
# SVG
# ============================================================================

def create_svg_root(
    width,
    height,
    new_width,
    new_height,
    scale_factor=1.0,
):
    """
    Create the root SVG element.

    ``width`` and ``height`` are the processed raster dimensions. Exported
    paths are scaled into millimetres, so the SVG viewport and physical size
    must use those same scaled dimensions rather than the optional raw form
    inputs (one of which is commonly blank or zero).
    """

    root = ET.Element(
        "svg",
        xmlns="http://www.w3.org/2000/svg",
        version="1.1"
    )

    physical_width = float(width) * float(scale_factor)
    physical_height = float(height) * float(scale_factor)
    width_value = format(physical_width, ".12g")
    height_value = format(physical_height, ".12g")

    root.set("viewBox", f"0 0 {width_value} {height_value}")

    root.set(
        "width",
        f"{width_value}mm"
    )

    root.set(
        "height",
        f"{height_value}mm"
    )

    return root


def add_geometry_to_svg(
    root,
    geometry,
    fill_color
):
    """
    Add Shapely geometry to the SVG tree.
    """

    if geometry.is_empty:
        return

    if geometry.geom_type == "Polygon":

        d_path = (
            "M "
            + " L ".join(
                [
                    f"{x:.3f},{y:.3f}"
                    for x, y
                    in geometry.exterior.coords
                ]
            )
            + " Z"
        )

        # Preserve interior holes.
        for interior in geometry.interiors:

            d_path += (
                " M "
                + " L ".join(
                    [
                        f"{x:.3f},{y:.3f}"
                        for x, y
                        in interior.coords
                    ]
                )
                + " Z"
            )

        ET.SubElement(
            root,
            "path",
            d=d_path,
            fill=fill_color,
            stroke="none"
        )

    elif geometry.geom_type == "LineString":
        coordinates = list(geometry.coords)
        if len(coordinates) >= 2:
            ET.SubElement(root, "path",
                d="M " + " L ".join(f"{x:.3f},{y:.3f}" for x, y in coordinates),
                fill="none", stroke=fill_color, **{"stroke-width": "0.1",
                "stroke-linecap": "round", "stroke-linejoin": "round"})

    elif geometry.geom_type in (
        "MultiPolygon",
        "MultiLineString",
        "GeometryCollection"
    ):

        for sub_geometry in geometry.geoms:

            add_geometry_to_svg(
                root,
                sub_geometry,
                fill_color
            )


# ============================================================================
# LIGHTBURN
# ============================================================================

def push_geometry_to_lightburn(
    geometry,
    color_hex,
    target_colors,
    lb_project_instance,
    override_layer_id=None
):
    """
    Convert Shapely geometry into LightBurn paths.

    ``override_layer_id`` writes the same closed paths to another LightBurn
    layer. The synthetic black canvas uses this to receive colored shapes as
    nested punch-through paths.
    """

    if geometry.is_empty:
        return

    layer_meta = target_colors[
        color_hex
    ]

    layer_id = override_layer_id if override_layer_id is not None else layer_meta[1]

    if geometry.geom_type == "Polygon":

        # --------------------------------------------------------------------
        # Exterior boundary
        # --------------------------------------------------------------------

        exterior_coords = [
            [
                round(x, 3),
                round(y, 3)
            ]
            for x, y
            in geometry.exterior.coords
        ]

        if exterior_coords:

            lb_shape = (
                lightburn.Path(
                    exterior_coords
                )
                .layer(layer_id)
            )

            lb_project_instance.add(
                lb_shape
            )

        # --------------------------------------------------------------------
        # Interior holes
        # --------------------------------------------------------------------

        for interior in geometry.interiors:

            interior_coords = [
                [
                    round(x, 3),
                    round(y, 3)
                ]
                for x, y
                in interior.coords
            ]

            if interior_coords:

                lb_hole = (
                    lightburn.Path(
                        interior_coords
                    )
                    .layer(layer_id)
                )

                lb_project_instance.add(
                    lb_hole
                )

    elif geometry.geom_type == "LineString":
        coordinates = [[round(x, 3), round(y, 3)] for x, y in geometry.coords]
        if len(coordinates) >= 2:
            lb_project_instance.add(lightburn.Path(coordinates).layer(layer_id))

    elif geometry.geom_type in (
        "MultiPolygon",
        "MultiLineString",
        "GeometryCollection"
    ):

        for sub_geometry in geometry.geoms:

            push_geometry_to_lightburn(
                sub_geometry,
                color_hex,
                target_colors,
                lb_project_instance,
                override_layer_id=layer_id
            )


# ============================================================================
# EXPORT
# ============================================================================

def export_processed_layers(
    processed_layers,
    target_colors,
    black_hex,
    scale_factor,
    root,
    lb_project_instance,
    punch_through_black=False,
    black_lightburn_geometry=None,
    export_lightburn=True,
):
    """
    Sort, scale, and export all finalized geometry to SVG and LightBurn.

    SVG uses the gap-only black geometry. LightBurn uses a complete black
    canvas with colored paths nested on the black layer so it can punch them
    through during fill processing.
    """

    printLogMessage(
        "Vector generation complete. "
        "Sorting and formatting log history..."
    )

    sorted_layers = sorted(
        processed_layers.items(),
        key=lambda item: target_colors[
            item[0]
        ][1]
    )

    printLogMessage(
        "=============================================="
    )

    printLogMessage(
        "      LAYER EXPORT AND PROCESS LOG SUMMARY"
    )

    printLogMessage(
        "=============================================="
    )

    exportable_layers = [
        (color_hex, geometry) for color_hex, geometry in sorted_layers
        if not geometry.is_empty
        or (color_hex == black_hex and black_lightburn_geometry is not None)
    ]
    total_export_layers = len(exportable_layers)

    for export_index, (color_hex, geometry) in enumerate(exportable_layers, 1):

        layer_meta = target_colors[
            color_hex
        ]

        layer_id = layer_meta[1]
        layer_color_name = layer_meta[2]
        geometry_count = _geometry_object_count(geometry)

        printLogMessage(
            f"[Export layer {export_index}/{total_export_layers}] START: "
            f"color {color_hex}, LightBurn layer {layer_id} {layer_color_name}; "
            f"batch objects {geometry_count}/{geometry_count}."
        )

        # --------------------------------------------------------------------
        # Apply global scale.
        # --------------------------------------------------------------------

        export_geometry = geometry

        if scale_factor != 1.0:

            printLogMessage(
                f"[Export layer {export_index}/{total_export_layers}] START: "
                f"scaling {geometry_count}/{geometry_count} objects by {scale_factor}x."
            )

            export_geometry = scale(
                export_geometry,
                xfact=scale_factor,
                yfact=scale_factor,
                origin=(0, 0)
            )
            printLogMessage(
                f"[Export layer {export_index}/{total_export_layers}] DONE: "
                f"scaled {geometry_count}/{geometry_count} objects."
            )

        # --------------------------------------------------------------------
        # SVG
        # --------------------------------------------------------------------

        printLogMessage(
            f"[Export layer {export_index}/{total_export_layers}] START: "
            f"writing {geometry_count}/{geometry_count} objects to the .svg file."
        )
        add_geometry_to_svg(
            root,
            export_geometry,
            color_hex
        )
        printLogMessage(
            f"[Export layer {export_index}/{total_export_layers}] DONE: "
            f"wrote {geometry_count}/{geometry_count} objects to the .svg file."
        )

        # --------------------------------------------------------------------
        # LightBurn
        # --------------------------------------------------------------------

        if export_lightburn and color_hex in target_colors:

            printLogMessage(
                f"[Export layer {export_index}/{total_export_layers}] START: "
                f"writing {geometry_count}/{geometry_count} objects to "
                f"LightBurn layer {layer_id} {layer_color_name}."
            )

            lightburn_geometry = export_geometry
            if color_hex == black_hex and black_lightburn_geometry is not None:
                lightburn_geometry = black_lightburn_geometry
                if scale_factor != 1.0:
                    lightburn_geometry = scale(
                        lightburn_geometry,
                        xfact=scale_factor,
                        yfact=scale_factor,
                        origin=(0, 0)
                    )

            push_geometry_to_lightburn(
                lightburn_geometry,
                color_hex,
                target_colors,
                lb_project_instance,
                override_layer_id=layer_id,
            )
            printLogMessage(
                f"[Export layer {export_index}/{total_export_layers}] DONE: "
                f"wrote {geometry_count}/{geometry_count} objects to "
                f"LightBurn layer {layer_id} {layer_color_name}."
            )

            if punch_through_black and color_hex != black_hex:
                printLogMessage(
                    f" -> Adding {layer_color_name} geometry to Black "
                    "Layer for LightBurn punch-through"
                )
                push_geometry_to_lightburn(
                    export_geometry,
                    color_hex,
                    target_colors,
                    lb_project_instance,
                    override_layer_id=target_colors[black_hex][1]
                )
        printLogMessage(
            f"[Export layer {export_index}/{total_export_layers}] LAYER DONE: "
            f"processed {geometry_count}/{geometry_count} objects for "
            f"color {color_hex}, layer {layer_id} {layer_color_name}."
        )

def save_vector_output(
    root,
    output_svg_path,
    lb_project_instance,
    export_lightburn=True,
    lightburn_note="",
):
    """
    Write SVG and LightBurn output files.
    """

    lightburn_object_count = len(getattr(lb_project_instance, "objects", []))
    svg_step = "1/2" if export_lightburn else "1/1"
    printLogMessage(
        f"[File serialization {svg_step}] START: writing the .svg file with "
        f"{len(root)} top-level objects to {output_svg_path}."
    )
    tree = ET.ElementTree(
        root
    )

    printLogMessage(
        f"Writing finalized scaled "
        f"zero-overlap .svg file to: "
        f"{output_svg_path}"
    )

    tree.write(
        output_svg_path,
        encoding="utf-8",
        xml_declaration=True
    )
    printLogMessage(
        f"[File serialization {svg_step}] DONE: wrote {len(root)}/{len(root)} "
        "top-level .svg file objects."
    )

    if not export_lightburn:
        printLogMessage(".svg file export complete. LightBurn project export was skipped for SVG-only mode.")
        return

    printLogMessage(
        f"[File serialization 2/2] START: writing "
        f"{lightburn_object_count}/{lightburn_object_count} LightBurn objects to "
        f"{output_svg_path}.lbrn2."
    )
    lightburn_path = output_svg_path + ".lbrn2"
    lb_project_instance.set_notes(lightburn_note, show_on_load=True)
    lb_project_instance.write(lightburn_path)
    lightburn_size = os.path.getsize(lightburn_path)
    if lightburn_size > LARGE_LIGHTBURN_PROJECT_BYTES:
        lb_project_instance.replace_notes_tail(
            lightburn_path,
            f"{LARGE_LIGHTBURN_PROJECT_WARNING}\n\n{lightburn_note}",
            show_on_load=True,
        )
        printLogMessage(
            "Added the large-project LightBurn warning to project Notes "
            f"because the file is {lightburn_size / 1_000_000:.2f} MB."
        )
    printLogMessage(
        f"[File serialization 2/2] DONE: wrote "
        f"{lightburn_object_count}/{lightburn_object_count} LightBurn objects."
    )

    printLogMessage(
        ".svg file and .lbrn2 file export complete."
    )

# ============================================================================
# MAIN DROP-IN REPLACEMENT
# ============================================================================


def raster_to_puzzle_and_lightburn(
    raster_image_path,
    output_svg_path,
    new_height,
    new_width,
    lb_project_instance,
    TARGET_COLORS,
    scale_factor=1.0,
    ignore_background_hex="#ffffff",
    # --- Adaptive Parameters for Non-Cartoon Images ---
    quantize_colors=None,
    min_island_area=0,
    simplification_factor=0.0,
    smoothing_radius=0.001,
    image_preset=None,
    abstract_filter=None,
    filter_parameters=None,
    color_matching=None,
    job_settings=None,
    export_lightburn=True,
    geometry_style="vectors",
    geometry_style_parameters=None,
    crop_shape="",
):
    """
    Parses a raster image, applies a structural vector scale_factor,
    saves a gapless SVG puzzle file, and pushes matching paths into
    LightBurn.

    The black layer is constructed as:

        BLACK CANVAS - ALL COLORED GEOMETRY

    This prevents colored shapes from existing underneath the black
    background layer.

    Includes:
        - color quantization
        - area filtering
        - path simplification
        - variable smoothing
        - abstract filters
        - SVG export
        - LightBurn export
    """

    # Quantization uses the real LightBurn layers that survived both palette
    # filtering and exact Material Library matching. Black-and-white photos
    # are the sole exception and deliberately reduce the source raster to two.
    quantize_colors = 2 if image_preset == "bw_dither_photograph" else len(TARGET_COLORS)

    # Keep this at the beginning of the pipeline so the console records the
    # effective values used by the job before raster processing begins.
    log_job_settings(
        **(job_settings or {}),
        input_raster_path=raster_image_path,
        output_svg_path=output_svg_path,
        requested_dimensions={"width": new_width, "height": new_height},
        scale_factor_mm=scale_factor,
        ignore_background_hex=ignore_background_hex,
        vector_settings={
            "quantize_colors": quantize_colors,
            "quantize_color_source": (
                "bw_dither_preset" if image_preset == "bw_dither_photograph"
                else "resolved_material_layers"
            ),
            "min_island_area": min_island_area,
            "simplification_factor": simplification_factor,
            "smoothing_radius": smoothing_radius,
        },
        abstract_filter=abstract_filter,
        abstract_filter_parameters=filter_parameters or {},
        lightburn_layers={
            color_hex: {"layer_id": metadata[1], "name": metadata[2]}
            for color_hex, metadata in TARGET_COLORS.items()
        },
    )

    # =========================================================================
    # 1. Normalize parameters
    # =========================================================================

    (
        quantize_colors,
        min_island_area,
        simplification_factor,
        smoothing_radius
    ) = normalize_vector_parameters(
        quantize_colors=quantize_colors,
        min_island_area=min_island_area,
        simplification_factor=simplification_factor,
        smoothing_radius=smoothing_radius,
        target_colors=TARGET_COLORS
    )

    # =========================================================================
    # 2. Locate black layer
    # =========================================================================

    black_hex, black_layer_id = (
        find_black_layer(
            TARGET_COLORS
        )
    )

    # The exporter resolves this same native black-layer ID when it emits
    # LightBurn hole-punch paths.
    _ = black_layer_id

    # =========================================================================
    # 3. Load and prepare raster
    # =========================================================================

    printLogMessage(
        "[Raster preparation 1/1] START: loading, resizing, and quantizing the source image."
    )
    filter_parameters = dict(filter_parameters or {})
    filter_name, normalized_filter_parameters = normalize_abstract_settings(
        abstract_filter, filter_parameters
    )
    geometry_style, normalized_geometry_parameters = geometry_styles.normalize(
        geometry_style, geometry_style_parameters, filter_name
    )
    routed_styles = geometry_styles.assigned_styles(
        geometry_style, normalized_geometry_parameters
    )
    mixed_krasnow = (
        geometry_style == geometry_styles.ROUTED_STYLE
        and geometry_styles.KRASNOW_STYLE in routed_styles
    )
    krasnow_mode = (
        filter_name == "krasnow_grating"
        or geometry_style == geometry_styles.KRASNOW_STYLE
        or mixed_krasnow
    )
    krasnow_parameters = (
        geometry_styles.parameters_for_style(
            geometry_style,
            normalized_geometry_parameters,
            geometry_styles.KRASNOW_STYLE,
        )
        if geometry_style in {
            geometry_styles.KRASNOW_STYLE, geometry_styles.ROUTED_STYLE
        }
        else filter_parameters
    )
    # Choose-by-Swatch always routes Black to ordinary vector geometry. Let
    # normal palette quantization decide which pixels Black owns in that mode;
    # the dedicated Krasnow source-darkness mask would otherwise turn dark,
    # chromatic artwork into Black before the swatch router sees it.
    mixed_vector_black = mixed_krasnow
    krasnow_preserve_black = (
        krasnow_mode
        and not mixed_krasnow
        and bool(_number(krasnow_parameters.get("preserve_black", 1), 1, 0, 1))
    )
    krasnow_grate_black = (
        krasnow_mode and not mixed_krasnow and not krasnow_preserve_black
    )
    if krasnow_preserve_black:
        printLogMessage(
            "Krasnow Color Grating: reserving below-Teal source darkness for "
            "the later Black mask; Black will not become a grating carrier."
        )
    elif krasnow_grate_black:
        printLogMessage(
            "Krasnow Color Grating: Preserve Black is off; Black will be "
            "quantized, grated, and assigned the Fauxlographic carrier recipe."
        )
    elif mixed_vector_black:
        printLogMessage(
            "Geometry Routing: Black uses normal palette quantization and "
            "remains mutually-exclusive vector geometry."
        )
    img = prepare_raster_image(
        raster_image_path=raster_image_path,
        new_height=new_height,
        new_width=new_width,
        quantize_colors=quantize_colors,
        # BW photo mode intentionally uses Pillow's adaptive two-color
        # reduction so its transparent-light-area option can inspect the two
        # actual source values. Every other preset uses real LightBurn swatches.
        target_colors=(None if image_preset == "bw_dither_photograph" else {
            color_hex: metadata for color_hex, metadata in TARGET_COLORS.items()
            if (
                color_hex.upper() not in NON_IMAGE_SWATCHES
                and (not krasnow_preserve_black or color_hex != black_hex)
            )
        }),
        prevent_palette_black=krasnow_preserve_black,
        color_matching=color_matching,
    )

    if krasnow_preserve_black:
        source_black_mask = load_resized_source_black_cutoff_mask(
            raster_image_path, img.size
        )
        img = restore_reserved_black(img, source_black_mask)

    width, height = img.size
    crop_shape = str(crop_shape or "").strip().lower()
    transparency_mask = None
    if crop_shape == "transparency":
        transparency_mask = load_resized_artwork_alpha_mask(
            raster_image_path, img.size
        )
        if not transparency_mask.any():
            raise ValueError(
                "Crop Transparency requires at least one non-transparent pixel."
            )
        crop_boundary = _mask_to_merged_geometry(transparency_mask)
    else:
        crop_boundary = artwork_crop_geometry(width, height, crop_shape)
    if crop_shape:
        printLogMessage(
            f"Artwork crop active: preserving the applied {crop_shape} boundary "
            "through SVG and LightBurn export."
        )
    printLogMessage(
        f"[Raster preparation 1/1] DONE: prepared {width * height}/{width * height} "
        f"pixels at {width}x{height}."
    )

    # Every color layer must use the same radial center and extent.  Keeping
    # this internal value shared prevents independently warped layers from
    # crossing or drifting apart at formerly common boundaries.
    filter_parameters["_canvas_bounds"] = (0, 0, width, height)
    filter_parameters["_scale_factor"] = scale_factor
    filter_module = ABSTRACT_FILTER_MODULES.get(filter_name)
    if bool(getattr(filter_module, "USES_SOURCE_COLOR", False)):
        filter_parameters["_source_color_image"] = prepare_raster_image(
            raster_image_path=raster_image_path,
            new_height=new_height,
            new_width=new_width,
            quantize_colors=None,
        ).convert("RGB")
        printLogMessage(
            f"{filter_name}: prepared the original source colors for optical mixing."
        )
    if (
        bool(getattr(filter_module, "USES_SOURCE_LUMINANCE", False))
        or geometry_styles.uses_source_luminance(
            geometry_style, normalized_geometry_parameters
        )
    ):
        source_luminance = prepare_raster_image(
            raster_image_path=raster_image_path,
            new_height=new_height,
            new_width=new_width,
            quantize_colors=None,
        ).convert("L")
        filter_parameters["_angle_image"] = source_luminance
        normalized_geometry_parameters["_angle_image"] = source_luminance
        printLogMessage(
            f"Prepared source luminance for {filter_name if bool(getattr(filter_module, 'USES_SOURCE_LUMINANCE', False)) else geometry_style}."
        )
    transparent_mode = (
        (image_preset == "bw_dither_photograph"
         and bool(filter_parameters.get("transparent", False)))
        or (filter_name == "xenoglyph" and bool(
            filter_parameters.get(
                "transparent",
                filter_parameters.get("light_areas_transparent", True)
            )
        ))
    )
    filter_preserves_source_black = bool(
        getattr(filter_module, "PRESERVE_SOURCE_BLACK", False)
    ) and not krasnow_grate_black
    filter_preserves_source_black = (
        filter_preserves_source_black
        or geometry_styles.preserves_source_black(
            geometry_style, normalized_geometry_parameters
        )
    )
    preserve_source_black = transparent_mode or filter_preserves_source_black
    source_black_requested = str_to_bool(
        os.environ.get("RASTER_SOURCE_BLACK_COMPONENTS", "false")
    )
    # These filters apply a deterministic, globally anchored transform to
    # every layer. Mosaic and Crystal clip against grids anchored at the
    # canvas origin, so processing the hole-free Black run rectangles yields
    # the same cell boundaries used by the colored layers. Filters whose
    # partition or displacement field depends on each geometry's bounds stay
    # on the punched-canvas path until they can share one precomputed field.
    source_black_compatible_filters = {
        "none", "wave", "shear", "spiral", "ripple", "mosaic", "crystal",
        "glitch", "deep_fryer",
    }
    source_black_mode = (
        source_black_requested
        and filter_name in source_black_compatible_filters
        and not preserve_source_black
    )
    if (
        source_black_requested
        and not source_black_mode
        and not filter_preserves_source_black
    ):
        printLogMessage(
            f"Source-derived Black experiment is not compatible with the selected "
            f"transparent or abstract-filter workflow '{filter_name}'; using the "
            "established punched-canvas pipeline."
        )
    transparent_rgb_values = None
    if image_preset == "bw_dither_photograph" and transparent_mode:
        # ``Image.quantize(colors=2)`` produces two exact source colors. Pick
        # the lighter one from this particular image so transparency follows
        # the displayed light-gray swatch even if it is below a fixed luma
        # cutoff (for example, on an overall dark photograph).
        palette_colors = {tuple(pixel) for pixel in img.getdata()}
        if len(palette_colors) > 1:
            lightest_color = max(
                palette_colors,
                key=lambda rgb: 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
            )
            transparent_rgb_values = {lightest_color}
            printLogMessage(
                "Transparent mode: removing the lighter quantized BW color "
                f"{lightest_color}."
            )

    # =========================================================================
    # 4. Convert pixels into color geometry buckets
    # =========================================================================

    printLogMessage(
        f"[Pixel classification 1/1] START: classifying "
        f"{width * height}/{width * height} pixels into color-layer batches."
    )
    pixel_boxes_by_color = classify_raster_pixels(
        img=img,
        target_colors=TARGET_COLORS,
        black_hex=black_hex,
        ignore_background_hex=ignore_background_hex,
        include_black=(
            krasnow_grate_black
            or
            mixed_vector_black
            or
            (preserve_source_black and not krasnow_mode)
            or source_black_mode
            or (
                min_island_area > 0
                and not transparent_mode
                and not filter_preserves_source_black
            )
        ),
        transparent=transparent_mode,
        transparent_rgb_values=transparent_rgb_values,
        include_mask=transparency_mask,
        light_threshold=_number(
            filter_parameters.get(
                "light_threshold",
                128 if image_preset == "bw_dither_photograph" else 225
            ),
            225, 128, 255
        )
    )
    classified_count = sum(len(boxes) for boxes in pixel_boxes_by_color.values())
    printLogMessage(
        f"[Pixel classification 1/1] DONE: classified {width * height}/{width * height} "
        f"pixels into {len(pixel_boxes_by_color)} layer batches containing "
        f"{classified_count} geometry objects."
    )

    geometry_min_island_area = min_island_area
    if min_island_area > 0 and not filter_preserves_source_black:
        pixel_boxes_by_color, island_stats = reassign_small_raster_islands(
            pixel_boxes_by_color=pixel_boxes_by_color,
            min_island_area=min_island_area,
            color_order=TARGET_COLORS.keys(),
            black_hex=black_hex,
            fallback_to_black=not transparent_mode,
        )
        # Cleanup is complete while ownership is still exact raster data.
        # Running the older per-layer deletion afterward would discard the
        # transferred footprint a second time.
        geometry_min_island_area = 0
        printLogMessage(
            "Minimum Island Area reassigned "
            f"{island_stats['pixels']} pixel(s) across "
            f"{island_stats['components']} component(s): "
            f"{island_stats['neighbor_components']} to the swatch sharing the "
            "most sides, "
            f"{island_stats['black_fallback_components']} to Black fallback, and "
            f"{island_stats['discarded_components']} to transparent fallback."
        )

        # The ordinary and source-derived Black builders consume Black
        # separately. It was included above only so it could participate in
        # the exact shared-side ownership decision.
        if (
            not preserve_source_black
            and not source_black_mode
            and not krasnow_grate_black
        ):
            pixel_boxes_by_color.pop(black_hex, None)

    # =========================================================================
    # 5. Process every colored layer
    # =========================================================================

    source_black_boxes = []
    source_black_pixel_count = 0
    if source_black_mode:
        raw_source_black_boxes = pixel_boxes_by_color.pop(black_hex, [])
        source_black_pixel_count = len(raw_source_black_boxes)
        source_black_boxes = _raster_boxes_to_rectangles(raw_source_black_boxes)
        del raw_source_black_boxes
        printLogMessage(
            f"Source-derived Black experiment compressed {source_black_pixel_count} "
            f"actual Black source pixels into {len(source_black_boxes)} exact run "
            "rectangles before non-Black layer processing."
        )

    processed_result = process_color_layers(
        pixel_boxes_by_color=pixel_boxes_by_color,
        target_colors=TARGET_COLORS,
        min_island_area=geometry_min_island_area,
        simplification_factor=simplification_factor,
        smoothing_radius=smoothing_radius,
        abstract_filter=abstract_filter,
        filter_parameters=filter_parameters,
        collect_removed_islands=source_black_mode,
    )
    if source_black_mode:
        processed_layers, removed_island_geometries = processed_result
        if removed_island_geometries:
            removed_area = sum(item.area for item in removed_island_geometries)
            source_black_boxes.extend(removed_island_geometries)
            printLogMessage(
                "Source-derived Black: reclaiming "
                f"{len(removed_island_geometries)} small-island cleanup batch(es) "
                f"covering {removed_area:.6f} square coordinate units."
            )
    else:
        processed_layers = processed_result

    if geometry_style != geometry_styles.NORMAL_STYLE:
        normalized_geometry_parameters.update({
            "_canvas_bounds": (0, 0, width, height),
            "_scale_factor": scale_factor,
            "_progress_logger": printLogMessage,
        })
        processed_layers = geometry_styles.apply(
            processed_layers,
            TARGET_COLORS,
            geometry_style,
            normalized_geometry_parameters,
            filter_name,
        )

    if krasnow_preserve_black:
        source_img = prepare_raster_image(
            raster_image_path=raster_image_path,
            new_height=new_height,
            new_width=new_width,
            quantize_colors=None,
        )
        processed_layers = replace_krasnow_black_layer(
            processed_layers,
            black_hex,
            source_img,
            reserved_black_mask=source_black_mask,
        )
        printLogMessage(
            "Krasnow Color Grating: preserved only the source pixels reserved "
            "before quantization as normal Black geometry."
        )

    # =========================================================================
    # 6. Build the BLACK layer around the colored geometry
    # =========================================================================

    black_lightburn_geometry = None
    source_black_active = False
    if source_black_mode:
        try:
            processed_layers[black_hex] = build_source_black_component_layer(
                black_pixel_boxes=(),
                black_rectangles=source_black_boxes,
                processed_layers=processed_layers,
                black_hex=black_hex,
                abstract_filter=abstract_filter,
                filter_parameters=filter_parameters,
            )
            source_black_active = True
            printLogMessage(
                "Source-derived Black experiment active: synthetic Black canvas "
                "and full-canvas punch-through skipped."
            )
        except Exception as error:
            printLogMessage(
                "Source-derived Black validation failed; automatically reverting "
                f"this job to the established punched-canvas pipeline: {error}"
            )

    if (
        not preserve_source_black
        and not source_black_active
        and not krasnow_grate_black
    ):
        black_lightburn_geometry = build_black_canvas(
            width=width,
            height=height,
            abstract_filter=abstract_filter,
            filter_parameters=filter_parameters
        )
        processed_layers[black_hex] = build_punched_black_layer(
            width=width,
            height=height,
            processed_layers=processed_layers,
            black_hex=black_hex,
            abstract_filter=abstract_filter,
            filter_parameters=filter_parameters,
        )

    elif transparent_mode:
        printLogMessage(
            "Transparent mode: light source areas remain transparent; no black canvas added."
        )
    elif filter_preserves_source_black:
        preservation_name = (
            geometry_styles.style_label(geometry_style)
            if geometry_styles.preserves_source_black(
                geometry_style, normalized_geometry_parameters
            ) else filter_name
        )
        printLogMessage(
            f"{preservation_name}: preserving source-derived Black geometry; "
            "no synthetic Black canvas or punch-through added."
        )
    elif krasnow_grate_black:
        printLogMessage(
            "Krasnow Color Grating: Black is a normal Holographic grating "
            "carrier; no Black canvas or punch-through added."
        )

    if crop_shape:
        processed_layers = {
            color_hex: geometry.intersection(crop_boundary)
            for color_hex, geometry in processed_layers.items()
        }
        if black_lightburn_geometry is not None:
            black_lightburn_geometry = black_lightburn_geometry.intersection(crop_boundary)
        printLogMessage(
            f"Artwork crop: clipped every output layer to the {crop_shape} boundary."
        )

    # =========================================================================
    # 7. Create SVG document
    # =========================================================================

    root = create_svg_root(
        width=width,
        height=height,
        new_width=new_width,
        new_height=new_height,
        scale_factor=scale_factor,
    )

    # =========================================================================
    # 8. Export SVG + LightBurn
    # =========================================================================

    export_processed_layers(
        processed_layers=processed_layers,
        target_colors=TARGET_COLORS,
        black_hex=black_hex,
        scale_factor=scale_factor,
        root=root,
        lb_project_instance=lb_project_instance,
        punch_through_black=(
            not preserve_source_black
            and not source_black_active
            and not krasnow_grate_black
        ),
        black_lightburn_geometry=black_lightburn_geometry,
        export_lightburn=export_lightburn,
    )

    # =========================================================================
    # 9. Save output files
    # =========================================================================

    lightburn_note = build_rasterizer_project_note(
        image_preset=image_preset,
        width=width,
        height=height,
        scale_factor=scale_factor,
        quantize_colors=quantize_colors,
        min_island_area=min_island_area,
        simplification_factor=simplification_factor,
        smoothing_radius=smoothing_radius,
        abstract_filter=filter_name,
        abstract_filter_parameters=normalized_filter_parameters,
        color_matching=color_matching,
        job_settings=job_settings,
        target_colors=TARGET_COLORS,
        geometry_style=geometry_style,
        geometry_style_parameters=normalized_geometry_parameters,
    )

    save_vector_output(
        root=root,
        output_svg_path=output_svg_path,
        lb_project_instance=lb_project_instance,
        export_lightburn=export_lightburn,
        lightburn_note=lightburn_note,
    )



