import sys
import os
import importlib.util
import json
from PIL import Image
import colorsys
import math
import cv2
import numpy as np 
import svgwrite
import potrace
import xml.etree.ElementTree as ET
from collections import defaultdict
from shapely.geometry import Polygon, box, Point, MultiPoint, LineString, MultiLineString, GeometryCollection
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
    return_setting_layers=False,
):
    """
    This function:
        1) parses the material settings file
        2) filters the materials based on the limit colors passed in
        3) filters the lightburn layer TARGET_COLORS:
            to only include colors that exist in the material setings list
        4) returns the new lightburn layer TARGET_COLORS for use in pixel generation=
            this ensures that we only find the closest lightburn layer color that exists in our material settings
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
    required_layers = {}
    next_layer_index = max((metadata[1] for metadata in TARGET_COLORS.values()), default=-1) + 1
    selected_targets = {
        metadata[2].casefold(): (color_hex, metadata)
        for color_hex, metadata in TARGET_COLORS.items()
        if metadata[2].casefold() in {str(color).strip().casefold() for color in limit_colors}
    }
    for item in matching_settings:
        # LightBurn stores both an Entry description and a cut-setting name.
        # Accept either as the library-side label, then make the editable
        # palette label authoritative for the generated project layer name.
        library_labels = (getattr(item, "entryDesc", ""), getattr(item, "name", ""))
        target = next(
            (selected_targets.get(str(label or "").strip().casefold())
             for label in library_labels
             if str(label or "").strip().casefold() in selected_targets),
            None,
        )
        matching_required_name = next(
            (
                required_name
                for required_name in required_names
                if any(
                    required_name in str(label or "").strip().casefold()
                    for label in library_labels
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
            item.name = str(getattr(item, "entryDesc", "") or item.name).strip()
            required_layers[matching_required_name] = item.index
            lb.add_layer(item)
            material_layer_report["loaded"].append(item.name)
            printLogMessage(
                f"Additional filter setting '{item.name}' assigned to LightBurn layer {item.index}."
            )
            continue
        if target is None:
            material_layer_report["skipped"].append(str(getattr(item, "entryDesc", "") or item.name))
            continue

        target_hex, target_metadata = target
        if target_hex in matched_settings:
            existing_name = matched_settings[target_hex][2]
            skipped_name = str(getattr(item, "entryDesc", "") or item.name)
            material_layer_report["skipped"].append(skipped_name)
            printLogMessage(
                f"Material layer '{skipped_name}' skipped: '{existing_name}' already has "
                f"a setting assigned for LightBurn layer {target_metadata[1]}."
            )
            continue

        item.frequency = int(item.frequency)
        item.index = target_metadata[1]
        item.name = target_metadata[2]
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
        raise ValueError(f"Material settings file does not contain required filter setting: {requested}")
    return (matched_settings, required_layers) if return_setting_layers else matched_settings


def move_lightburn_layer_after(lb_project, layer_id, after_layer_id):
    """Move one configured LightBurn layer after another in execution order."""
    layers = getattr(lb_project, "_layers", None)
    if not isinstance(layers, list):
        return False
    layer = next((item for item in layers if getattr(item, "index", None) == layer_id), None)
    after_layer = next((item for item in layers if getattr(item, "index", None) == after_layer_id), None)
    if layer is None or after_layer is None or layer is after_layer:
        return False
    layers.remove(layer)
    layers.insert(layers.index(after_layer) + 1, layer)
    return True


def init_lightburn(the_colors_limit, color_name_overrides=None):
    """
        This Function:
            1) initializes lightburn module
            2) initiallizes the full list of lighburn layer colors
            3) filters the lightburn layer colors so it only contains colors in limit_colors list
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
        '#FFDB66': (46, 29, 'Light-Gold'),
        '#7A00FF': (268, 30, 'Holographic')
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

    # Create the lightburn object
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


def prepare_raster_image(
    raster_image_path,
    new_height,
    new_width,
    quantize_colors,
    target_colors=None
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
            palette.putpalette(palette_values + [0] * (768 - len(palette_values)))
            img = img.quantize(palette=palette, dither=Image.Dither.NONE).convert("RGB")
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
    light_threshold=225
):
    """
    Convert raster pixels into 1x1 Shapely boxes grouped by color.

    Black pixels are intentionally skipped because the black layer is
    constructed later as a punched-out canvas.
    """

    width, height = img.size

    pixel_boxes_by_color = defaultdict(list)

    printLogMessage(
        "Analyzing pixels and snapping colors..."
    )

    for y in range(height):

        for x in range(width):

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


def boxes_to_centerlines(boxes, settings):
    """Reduce a raster color region to open, one-pixel-wide medial-axis paths."""
    if not boxes:
        return MultiLineString([])
    min_x = math.floor(min(item.bounds[0] for item in boxes))
    min_y = math.floor(min(item.bounds[1] for item in boxes))
    max_x = math.ceil(max(item.bounds[2] for item in boxes))
    max_y = math.ceil(max(item.bounds[3] for item in boxes))
    mask = np.zeros((max_y - min_y + 2, max_x - min_x + 2), dtype=np.uint8)
    for item in boxes:
        x, y = int(item.bounds[0]) - min_x + 1, int(item.bounds[1]) - min_y + 1
        mask[y, x] = 255

    # Morphological skeletonization uses only core OpenCV and converges to a
    # true one-pixel center axis without requiring opencv-contrib/ximgproc.
    skeleton = np.zeros_like(mask)
    working = mask.copy()
    element = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    while cv2.countNonZero(working):
        eroded = cv2.erode(working, element)
        opened = cv2.dilate(eroded, element)
        skeleton = cv2.bitwise_or(skeleton, cv2.subtract(working, opened))
        working = eroded

    pixels = {(int(x), int(y)) for y, x in np.argwhere(skeleton > 0)}
    if not pixels:
        return MultiLineString([])
    offsets = ((-1, -1), (0, -1), (1, -1), (-1, 0),
               (1, 0), (-1, 1), (0, 1), (1, 1))
    neighbors = {p: {q for dx, dy in offsets if (q := (p[0] + dx, p[1] + dy)) in pixels}
                 for p in pixels}
    visited = set()
    lines = []

    def edge(a, b):
        return tuple(sorted((a, b)))

    def follow(start, nxt):
        path = [start, nxt]
        visited.add(edge(start, nxt))
        previous, current = start, nxt
        while len(neighbors[current]) == 2:
            candidates = [p for p in neighbors[current] if p != previous]
            if not candidates or edge(current, candidates[0]) in visited:
                break
            previous, current = current, candidates[0]
            path.append(current)
            visited.add(edge(previous, current))
        return path

    endpoints = [p for p in pixels if len(neighbors[p]) != 2]
    for start in endpoints:
        for nxt in neighbors[start]:
            if edge(start, nxt) not in visited:
                lines.append(follow(start, nxt))
    # Closed loops have no endpoint/junction, so collect their remaining edge.
    for start in pixels:
        for nxt in neighbors[start]:
            if edge(start, nxt) not in visited:
                lines.append(follow(start, nxt))

    tolerance = _number(settings.get("line_simplification"), .35, 0, 10)
    minimum = _number(settings.get("min_branch_length"), 2, 0, 1000)
    result = []
    for points in lines:
        if len(points) < 2:
            continue
        line = LineString([(x + min_x - .5, y + min_y - .5) for x, y in points])
        if tolerance:
            line = line.simplify(tolerance, preserve_topology=False)
        if line.length >= minimum and len(line.coords) >= 2:
            result.append(line)
    return MultiLineString(result) if result else MultiLineString([])


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


def process_color_geometry(
    boxes,
    min_island_area,
    simplification_factor,
    smoothing_radius,
    abstract_filter,
    filter_parameters=None,
    return_source_geometry=False,
):
    """
    Convert a collection of pixel boxes into finalized vector geometry.

    Processing order intentionally matches the original function:

        1. Union pixels
        2. Morphological smoothing
        3. Remove tiny islands
        4. Douglas-Peucker simplification
        5. Abstract transformation
    """

    filter_name, settings = normalize_abstract_settings(abstract_filter, filter_parameters)
    if filter_name == "centerline":
        return ABSTRACT_FILTER_MODULES["centerline"].process_boxes(
            boxes, settings, boxes_to_centerlines
        )

    # ------------------------------------------------------------------------
    # 1. Weld all same-color pixels together.
    # ------------------------------------------------------------------------

    welded_layer = unary_union(
        boxes
    )

    # ------------------------------------------------------------------------
    # 2. Morphological opening / smoothing.
    # ------------------------------------------------------------------------

    final_geometry = (
        welded_layer
        .buffer(smoothing_radius)
        .buffer(-smoothing_radius)
    )

    # ------------------------------------------------------------------------
    # 3. Remove tiny noise islands.
    # ------------------------------------------------------------------------

    final_geometry = remove_small_islands(
        final_geometry,
        min_island_area
    )

    # ------------------------------------------------------------------------
    # 4. Simplify jagged raster edges.
    # ------------------------------------------------------------------------

    if simplification_factor > 0.0:

        final_geometry = (
            final_geometry.simplify(
                simplification_factor,
                preserve_topology=True
            )
        )

    # ------------------------------------------------------------------------
    # 5. Apply abstract transformation.
    # ------------------------------------------------------------------------

    source_geometry = final_geometry
    final_geometry = apply_abstract_filter(
        final_geometry,
        abstract_filter,
        filter_parameters
    )

    # Final topology repair before this geometry is used
    # anywhere else in the pipeline.
    if not final_geometry.is_valid:

        printLogMessage(
            "Repairing invalid geometry after processing..."
        )

        final_geometry = make_valid(
            final_geometry
        )

    return (final_geometry, source_geometry) if return_source_geometry else final_geometry


def _raster_boxes_to_rectangles(boxes):
    """Convert unit pixel boxes into exact, non-overlapping rectangles."""
    remaining = set()
    for item in boxes:
        min_x, min_y, max_x, max_y = item.bounds
        if max_x - min_x == 1 and max_y - min_y == 1:
            remaining.add((int(round(min_x)), int(round(min_y))))

    rectangles = []
    while remaining:
        x, y = min(remaining, key=lambda point: (point[1], point[0]))
        width = 1
        while (x + width, y) in remaining:
            width += 1
        height = 1
        while all((x + offset, y + height) in remaining for offset in range(width)):
            height += 1
        for row in range(height):
            for column in range(width):
                remaining.remove((x + column, y + row))
        rectangles.append((x, y, width, height))

    def merge_rows(items):
        merged = []
        for item in sorted(items, key=lambda value: (value[1], value[3], value[0])):
            if merged:
                px, py, pw, ph = merged[-1]
                x, y, width, height = item
                if y == py and height == ph and x == px + pw:
                    merged[-1] = (px, py, pw + width, height)
                    continue
            merged.append(item)
        return merged

    def merge_columns(items):
        merged = []
        for item in sorted(items, key=lambda value: (value[0], value[2], value[1])):
            if merged:
                px, py, pw, ph = merged[-1]
                x, y, width, height = item
                if x == px and width == pw and y == py + ph:
                    merged[-1] = (px, py, width, ph + height)
                    continue
            merged.append(item)
        return merged

    while True:
        previous_count = len(rectangles)
        rectangles = merge_columns(merge_rows(rectangles))
        if len(rectangles) == previous_count:
            return [box(x, y, x + width, y + height) for x, y, width, height in rectangles]


def process_color_layers(
    pixel_boxes_by_color,
    target_colors,
    min_island_area,
    simplification_factor,
    smoothing_radius,
    abstract_filter,
    filter_parameters=None,
    punch_layers=None,
    layer_overrides=None,
):
    """
    Convert all raster color groups into finalized Shapely geometries.
    """

    processed_layers = {}
    filter_name, settings = normalize_abstract_settings(abstract_filter, filter_parameters)
    filter_module = ABSTRACT_FILTER_MODULES.get(filter_name)
    light_layers_only = bool(getattr(filter_module, "LIGHT_LAYERS_ONLY", False))
    punch_source_geometry = bool(getattr(filter_module, "PUNCH_SOURCE_GEOMETRY", False))
    setting_parameter = getattr(filter_module, "SETTING_NAME_PARAMETER", None)
    setting_layer_id = (filter_parameters or {}).get("_setting_layer_id")
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

    total_layers = len(
        pixel_boxes_by_color
    )

    printLogMessage(
        f"Beginning vector union math for "
        f"{total_layers} unique layers..."
    )

    for idx, (color_hex, boxes) in enumerate(
        pixel_boxes_by_color.items(),
        1
    ):

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

        printLogMessage(
            f" -> Merging color boundaries... "
            f"(Layer math step {idx}/"
            f"{total_layers} - "
            f"Layer: {layer_id} "
            f"[{layer_color_name}])"
        )

        layer_filter = abstract_filter
        if light_layers_only and not is_light_swatch(color_hex):
            layer_filter = "none"

        use_source_punch = punch_source_geometry and layer_filter != "none"
        result = process_color_geometry(
            boxes=boxes,
            min_island_area=min_island_area,
            simplification_factor=simplification_factor,
            smoothing_radius=smoothing_radius,
            abstract_filter=layer_filter,
            filter_parameters=filter_parameters,
            return_source_geometry=use_source_punch,
        )
        if use_source_punch:
            final_geometry, source_geometry = result
        else:
            final_geometry = result
            source_geometry = final_geometry

        processed_layers[
            color_hex
        ] = final_geometry
        if punch_layers is not None:
            punch_layers[color_hex] = source_geometry
        if layer_overrides is not None and layer_filter != "none" and setting_parameter and setting_layer_id is not None:
            layer_overrides[color_hex] = setting_layer_id

    return processed_layers


# ============================================================================
# BLACK BACKGROUND
# ============================================================================

def build_black_canvas(width, height, abstract_filter, filter_parameters=None):
    """Build the complete black canvas used for LightBurn nesting."""
    filter_name, _ = normalize_abstract_settings(abstract_filter, filter_parameters)
    filter_module = ABSTRACT_FILTER_MODULES.get(filter_name)
    if bool(getattr(filter_module, "PRESERVE_BLACK_CANVAS", False)):
        return box(0, 0, width, height)
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
    punch_layers=None,
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

    for color_hex, geometry in (punch_layers or processed_layers).items():

        if color_hex == black_hex:
            continue

        if geometry.is_empty:
            continue

        geometry = topology_safe(geometry, f"color {color_hex}")

        if not geometry.is_empty:
            colored_geometries.append(
                geometry
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
    for color_geometry in colored_geometries:
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
    new_height
):
    """
    Create the root SVG element.

    The SVG namespace and dimensions intentionally match the
    original function.
    """

    root = ET.Element(
        "svg",
        xmlns="http://w3.org",
        version="1.1"
    )

    root.set(
        "viewBox",
        f"0 0 {new_width} {new_height}"
    )

    root.set(
        "width",
        f"{str(width)}mm"
    )

    root.set(
        "height",
        f"{str(height)}mm"
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
    layer_overrides=None,
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

    for color_hex, geometry in sorted_layers:

        if geometry.is_empty and not (
            color_hex == black_hex and black_lightburn_geometry is not None
        ):
            continue

        layer_meta = target_colors[
            color_hex
        ]

        layer_id = (layer_overrides or {}).get(color_hex, layer_meta[1])
        layer_color_name = layer_meta[2]

        printLogMessage(
            f"Processing and welding layer "
            f"{layer_id} color: "
            f"{layer_color_name}"
        )

        # --------------------------------------------------------------------
        # Apply global scale.
        # --------------------------------------------------------------------

        export_geometry = geometry

        if scale_factor != 1.0:

            printLogMessage(
                f"Scaling {layer_color_name} geometry "
                f"by a factor of {scale_factor}x"
            )

            export_geometry = scale(
                geometry,
                xfact=scale_factor,
                yfact=scale_factor,
                origin=(0, 0)
            )

        # --------------------------------------------------------------------
        # SVG
        # --------------------------------------------------------------------

        add_geometry_to_svg(
            root,
            export_geometry,
            color_hex
        )

        # --------------------------------------------------------------------
        # LightBurn
        # --------------------------------------------------------------------

        if color_hex in target_colors:

            printLogMessage(
                f"Pushing scaled "
                f"{layer_color_name} geometry "
                f"into LightBurn Layer ID: "
                f"{layer_id}"
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

def save_vector_output(
    root,
    output_svg_path,
    lb_project_instance
):
    """
    Write SVG and LightBurn output files.
    """

    tree = ET.ElementTree(
        root
    )

    printLogMessage(
        f"Writing finalized scaled "
        f"zero-overlap SVG to: "
        f"{output_svg_path}"
    )

    tree.write(
        output_svg_path,
        encoding="utf-8",
        xml_declaration=True
    )

    lb_project_instance.write(
        output_svg_path + ".lbrn2"
    )

    printLogMessage(
        "SVG and LightBurn export complete."
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
    job_settings=None
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
            if color_hex.upper() not in NON_IMAGE_SWATCHES
        })
    )

    width, height = img.size

    # Every color layer must use the same radial center and extent.  Keeping
    # this internal value shared prevents independently warped layers from
    # crossing or drifting apart at formerly common boundaries.
    filter_parameters = dict(filter_parameters or {})
    filter_parameters["_canvas_bounds"] = (0, 0, width, height)
    filter_parameters["_scale_factor"] = scale_factor
    filter_name, _ = normalize_abstract_settings(abstract_filter, filter_parameters)
    filter_module = ABSTRACT_FILTER_MODULES.get(filter_name)
    centerline_mode = filter_name == "centerline"
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
    keep_black_parameter = getattr(filter_module, "KEEP_SOURCE_BLACK_PARAMETER", None)
    keep_source_black = bool(
        keep_black_parameter and filter_parameters.get(keep_black_parameter, False)
    )
    background_generator = bool(getattr(filter_module, "BACKGROUND_GENERATOR", False))
    preserve_background_transparency = bool(
        getattr(filter_module, "PRESERVE_BACKGROUND_TRANSPARENCY", False)
    )
    preserve_source_black = (
        centerline_mode or transparent_mode or keep_source_black
        or preserve_background_transparency
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

    if centerline_mode:
        # Quantized filled color regions cannot produce faithful line art.
        # Select dark source-image outlines first, then trace them only on the
        # user's black LightBurn layer.
        source_img = prepare_raster_image(
            raster_image_path=raster_image_path,
            new_height=new_height,
            new_width=new_width,
            quantize_colors=None,
        )
        pixel_boxes_by_color = {
            black_hex: ABSTRACT_FILTER_MODULES["centerline"].line_art_boxes(
                source_img, filter_parameters
            )
        }
    else:
        pixel_boxes_by_color = classify_raster_pixels(
            img=img,
            target_colors=TARGET_COLORS,
            black_hex=black_hex,
            ignore_background_hex=ignore_background_hex,
            include_black=preserve_source_black,
            transparent=transparent_mode,
            transparent_rgb_values=transparent_rgb_values,
            light_threshold=_number(
                filter_parameters.get(
                    "light_threshold",
                    128 if image_preset == "bw_dither_photograph" else 225
                ),
                225, 128, 255
            )
        )
        if background_generator:
            pixel_boxes_by_color = retain_dominant_foreground(
                pixel_boxes_by_color, img, filter_parameters
            )

    # =========================================================================
    # 5. Process every colored layer
    # =========================================================================

    punch_layers = {}
    layer_overrides = {}
    processed_layers = process_color_layers(
        pixel_boxes_by_color=pixel_boxes_by_color,
        target_colors=TARGET_COLORS,
        min_island_area=min_island_area,
        simplification_factor=simplification_factor,
        smoothing_radius=smoothing_radius,
        abstract_filter=abstract_filter,
        filter_parameters=filter_parameters,
        punch_layers=punch_layers,
        layer_overrides=layer_overrides,
    )

    if background_generator:
        setting_layer_id = filter_parameters.get("_setting_layer_id")
        layer_color = str(getattr(filter_module, "LAYER_COLOR", "#FEFEFE")).upper()
        if setting_layer_id is None or layer_color not in TARGET_COLORS:
            raise ValueError("Sacred requires the holographic Material Library setting")
        subject_geometry = unary_union([
            geometry for geometry in processed_layers.values() if not geometry.is_empty
        ])
        background_geometry = filter_module.background_geometry(
            subject_geometry, filter_parameters
        )
        if not background_geometry.is_empty:
            processed_layers[layer_color] = background_geometry
            punch_layers[layer_color] = background_geometry
            layer_overrides[layer_color] = setting_layer_id

    # =========================================================================
    # 6. Build the BLACK layer around the colored geometry
    # =========================================================================

    black_lightburn_geometry = None
    if not preserve_source_black:
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
            punch_layers=punch_layers,
        )

    elif centerline_mode:
        printLogMessage("Centerline Drawing: exporting dark source-image outlines as thin closed black ribbons.")
    elif transparent_mode:
        printLogMessage(
            "Transparent mode: light source areas remain transparent; no black canvas added."
        )
    elif keep_source_black:
        printLogMessage(
            "Holographic Keep Black: preserving dark source-image geometry on the Black setting."
        )

    # =========================================================================
    # 7. Create SVG document
    # =========================================================================

    root = create_svg_root(
        width=width,
        height=height,
        new_width=new_width,
        new_height=new_height
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
        punch_through_black=not preserve_source_black,
        black_lightburn_geometry=black_lightburn_geometry,
        layer_overrides=layer_overrides,
    )

    # =========================================================================
    # 9. Save output files
    # =========================================================================

    save_vector_output(
        root=root,
        output_svg_path=output_svg_path,
        lb_project_instance=lb_project_instance
    )



