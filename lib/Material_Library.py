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
from shapely.geometry import Polygon, box, MultiPoint, LineString, MultiLineString
from shapely.ops import unary_union, voronoi_diagram, transform
from shapely.affinity import scale, affine_transform
from shapely.validation import make_valid
from svgelements import SVG, Path, Polygon as SVGPolygon
from datetime import datetime

# from vector_processing import raster_to_puzzle_and_lightburn


def printLogMessage(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)

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
        V = max(r, g, b)

        # 2. Apply Luminance Threshold Rules
        if V < 25:
            return "#000000"  # Black
        
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
            return "#B4B4B4" if v_float > 0.5 else "#000000"
            
        
        min_diff = 360
        closest_hex = ""

        # Iterate through target hues to find the minimum angular difference
        for hex_code, (target_hue, layer_index, layer_name) in TARGET_COLORS.items():
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

def parse_material_settings(lb, material_settings_path, limit_colors, TARGET_COLORS):
    """
    This function:
        1) parses the material settings file
        2) filters the materials based on the limit colors passed in
        3) filters the lightburn layer TARGET_COLORS:
            to only include colors that exist in the material setings list
        4) returns the new lightburn layer TARGET_COLORS for use in pixel generation=
            this ensures that we only find the closest lightburn layer color that exists in our material settings
    """
    new_color_settings = lb.parse_material_library(material_settings_path)
    matched_settings = {}
    for item in new_color_settings:
        if item.materialName == "colors - stainless steel":
            item.frequency = int(item.frequency)
            item.name = item.entryDesc
            if item.name.lower() in [cv[-1].lower() for cn,cv in TARGET_COLORS.items() if cv[-1].lower() in limit_colors]:
                target_item = [cv for cn,cv in TARGET_COLORS.items() if cv[-1].lower() == item.name.lower()] 
                target_touple = target_item[0]
                target_key = [cn for cn,cv in TARGET_COLORS.items() if cv[-1].lower() == item.name.lower()] 
                matched_settings[target_key[0]] = TARGET_COLORS[target_key[0]]
                item.index = target_touple[-2]
                lb.add_layer(item)
                printLogMessage(f"added Layer: {item.name}")

            else:
                printLogMessage(f"unable to add layer: {item.name}, name not in lightburn target colors")

    return matched_settings    

def init_lightburn(the_colors_limit):
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
        '#FFDB66': (46, 29, 'Light-Gold')
    }
    if len(the_colors_limit) > 0:
        filtered_colors = {
            hex_code: value_tuple 
            for hex_code, value_tuple in TARGET_COLORS.items() 
            for hex_code, value_tuple in TARGET_COLORS.items() 
            if value_tuple[-1].lower() in the_colors_limit.lower()
        }
        # ensure light grey and black are always in the list 
        # these colors get defaulted to when no color is close enough to the target pixel
        filtered_colors['#B4B4B4'] = (0, 8, 'Light-Gray')
        filtered_colors['#000000'] = (0, 0, 'Black')
    else:
        filtered_colors = TARGET_COLORS
        filtered_colors['#B4B4B4'] = (0, 8, 'Light-Gray')
        filtered_colors['#000000'] = (0, 0, 'Black')
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
    quantize_colors
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
    include_black=False
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

ABSTRACT_FILTER_DEFAULTS = {
    "wave": {"amplitude_x": 4, "amplitude_y": 4, "frequency_x": .1, "frequency_y": .1, "phase": 0},
    "voronoi": {"cell_size": 15, "jitter": .45, "gap": .8, "seed": 1},
    "shear": {"shear_x": .5, "shear_y": 0, "scale_x": 1, "scale_y": .8},
    "spiral": {"twist": 2.25, "falloff": 1, "center_x": .5, "center_y": .5},
    "mosaic": {"tile_size": 12, "gap": 1, "stagger": .5},
    "crystal": {"cell_size": 18, "gap": .7},
    "ripple": {"amplitude": 3, "frequency": .18, "phase": 0, "center_x": .5, "center_y": .5},
    "centerline": {"line_simplification": .35, "min_branch_length": 2},
    "tumbler": {"top_diameter_mm": 75, "middle_diameter_mm": 75,
                "bottom_diameter_mm": 70, "artwork_height_mm": 100,
                "wrap_angle": 180, "profile_curve": 0, "horizontal_anchor": .5,
                "material": "metal", "powdercoat_gap_mm": .35,
                "powdercoat_simplification_mm": .3, "foreground_min_percent": .15},
}

PALETTE_LIMITING_FILTERS = {
    "wave", "voronoi", "shear", "spiral", "mosaic", "crystal", "ripple"
}

# Frontends can use this schema to build sliders without duplicating ranges.
# ``seed`` should be rendered as a number input plus a randomize button.
ABSTRACT_FILTER_CONTROLS = {
    "wave": (("amplitude_x", -50, 50, .5), ("amplitude_y", -50, 50, .5),
             ("frequency_x", .01, 1, .01), ("frequency_y", .01, 1, .01), ("phase", 0, 6.283, .05)),
    "voronoi": (("cell_size", 3, 100, 1), ("jitter", 0, .95, .01),
                ("gap", 0, 12, .1), ("seed", 0, 999999, 1)),
    "shear": (("shear_x", -2, 2, .05), ("shear_y", -2, 2, .05),
              ("scale_x", .25, 3, .05), ("scale_y", .25, 3, .05)),
    "spiral": (("twist", -8, 8, .1), ("falloff", .1, 5, .1),
               ("center_x", 0, 1, .01), ("center_y", 0, 1, .01)),
    "mosaic": (("tile_size", 2, 100, 1), ("gap", 0, 20, .1), ("stagger", 0, 1, .05)),
    "crystal": (("cell_size", 3, 120, 1), ("gap", 0, 20, .1)),
    "ripple": (("amplitude", -30, 30, .5), ("frequency", .01, 1, .01),
               ("phase", 0, 6.283, .05), ("center_x", 0, 1, .01), ("center_y", 0, 1, .01)),
    "centerline": (("line_simplification", 0, 3, .05), ("min_branch_length", 0, 30, 1)),
    "tumbler": (("top_diameter_mm", 20, 200, .1), ("middle_diameter_mm", 20, 200, .1),
                ("bottom_diameter_mm", 20, 200, .1), ("artwork_height_mm", 5, 300, 1),
                ("wrap_angle", 10, 360, 1), ("profile_curve", -1, 1, .05),
                ("horizontal_anchor", 0, 1, .05), ("powdercoat_gap_mm", 0, 3, .05),
                ("powdercoat_simplification_mm", 0, 3, .05),
                ("foreground_min_percent", 0, 5, .05)),
}

def get_abstract_filter_manifest():
    """Return JSON-ready filter defaults and slider metadata for the web UI."""
    return {
        name: {
            "defaults": dict(defaults),
            "controls": [dict(name=n, min=low, max=high, step=step)
                         for n, low, high, step in ABSTRACT_FILTER_CONTROLS[name]]
        }
        for name, defaults in ABSTRACT_FILTER_DEFAULTS.items()
    }


def _number(value, default, low=None, high=None):
    """Coerce and clamp untrusted UI values."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = float(default)
    if not math.isfinite(value):
        value = float(default)
    return min(high, max(low, value)) if low is not None and high is not None else value


def normalize_abstract_settings(abstract_filter, filter_parameters=None):
    supplied = {}
    if isinstance(abstract_filter, dict):
        supplied.update(abstract_filter)
        name = supplied.pop("name", supplied.pop("filter", "none"))
    else:
        name = abstract_filter or "none"
    if isinstance(filter_parameters, dict):
        supplied.update(filter_parameters)
    name = str(name).strip().lower()
    settings = dict(ABSTRACT_FILTER_DEFAULTS.get(name, {}))
    settings.update(supplied)
    return name, settings


def apply_wave_filter(geometry, s):
    ax = _number(s.get("amplitude_x"), 4, -200, 200)
    ay = _number(s.get("amplitude_y"), 4, -200, 200)
    fx = _number(s.get("frequency_x"), .1, .001, 5)
    fy = _number(s.get("frequency_y"), .1, .001, 5)
    # Keep the warp one-to-one so layers cannot fold across each other.
    ax = max(-.9 / fy, min(.9 / fy, ax))
    ay = max(-.9 / fx, min(.9 / fx, ay))
    phase = _number(s.get("phase"), 0, -100, 100)
    return transform(lambda x, y, z=None: (x + math.sin(y * fy + phase) * ax,
                                           y + math.cos(x * fx + phase) * ay), geometry)


def _cell_union(geometry, cells, gap):
    pieces = []
    for cell in cells:
        tile = cell.buffer(-gap / 2, join_style=2) if gap else cell
        clipped = geometry.intersection(tile)
        if not clipped.is_empty:
            pieces.append(clipped)
    return unary_union(pieces) if pieces else geometry.intersection(box(0, 0, 0, 0))


def apply_voronoi_filter(geometry, s):
    bounds = geometry.bounds
    step = _number(s.get("cell_size"), 15, 3, 500)
    jitter = _number(s.get("jitter"), .45, 0, .95)
    gap = _number(s.get("gap"), .8, 0, step * .45)
    rng = np.random.default_rng(int(_number(s.get("seed"), 1, -2147483648, 2147483647)))
    points = [(x * step + rng.uniform(-jitter, jitter) * step,
               y * step + rng.uniform(-jitter, jitter) * step)
              for x in range(math.floor(bounds[0] / step) - 2, math.ceil(bounds[2] / step) + 3)
              for y in range(math.floor(bounds[1] / step) - 2, math.ceil(bounds[3] / step) + 3)]
    cells = voronoi_diagram(MultiPoint(points), envelope=box(*bounds).buffer(step * 2)).geoms
    return _cell_union(geometry, cells, gap)


def apply_shear_filter(geometry, s):
    sx, sy = _number(s.get("scale_x"), 1, .05, 10), _number(s.get("scale_y"), .8, .05, 10)
    shx, shy = _number(s.get("shear_x"), .5, -5, 5), _number(s.get("shear_y"), 0, -5, 5)
    if abs(sx * sy - shx * shy) < .01:
        sy += .01
    return affine_transform(geometry, [sx, shx, shy, sy, 0, 0])


def _center(geometry, s):
    canvas_bounds = s.get("_canvas_bounds")
    x1, y1, x2, y2 = canvas_bounds if canvas_bounds and len(canvas_bounds) == 4 else geometry.bounds
    cx = x1 + (x2 - x1) * _number(s.get("center_x"), .5, -1, 2)
    cy = y1 + (y2 - y1) * _number(s.get("center_y"), .5, -1, 2)
    radius = max(math.hypot(x - cx, y - cy) for x, y in ((x1, y1), (x2, y1), (x2, y2), (x1, y2))) or 1
    return cx, cy, radius


def apply_spiral_filter(geometry, s):
    cx, cy, radius = _center(geometry, s)
    twist = _number(s.get("twist"), 2.25, -20, 20) * math.pi
    falloff = _number(s.get("falloff"), 1, .05, 8)
    def warp(x, y, z=None):
        dx, dy = x - cx, y - cy
        r = math.hypot(dx, dy)
        a = math.atan2(dy, dx) + twist * (r / radius) ** falloff
        return cx + r * math.cos(a), cy + r * math.sin(a)
    return transform(warp, geometry)


def apply_ripple_filter(geometry, s):
    cx, cy, _ = _center(geometry, s)
    amp = _number(s.get("amplitude"), 3, -100, 100)
    freq = _number(s.get("frequency"), .18, .001, 5)
    amp = max(-.95 / freq, min(.95 / freq, amp))
    phase = _number(s.get("phase"), 0, -100, 100)
    def warp(x, y, z=None):
        dx, dy = x - cx, y - cy
        r = math.hypot(dx, dy)
        ratio = max(0, r + amp * math.sin(r * freq + phase)) / r if r else 1
        return cx + dx * ratio, cy + dy * ratio
    return transform(warp, geometry)


def apply_mosaic_filter(geometry, s):
    x1, y1, x2, y2 = geometry.bounds
    size = _number(s.get("tile_size"), 12, 2, 500)
    gap = _number(s.get("gap"), 1, 0, size * .8)
    stagger = _number(s.get("stagger"), .5, 0, 1)
    cells = (box(col * size + (row & 1) * stagger * size, row * size,
                 col * size + (row & 1) * stagger * size + size, row * size + size)
             for row in range(math.floor(y1 / size) - 1, math.ceil(y2 / size) + 2)
             for col in range(math.floor(x1 / size) - 2, math.ceil(x2 / size) + 2))
    return _cell_union(geometry, cells, gap)


def apply_crystal_filter(geometry, s):
    x1, y1, x2, y2 = geometry.bounds
    size = _number(s.get("cell_size"), 18, 3, 500)
    height = size * math.sqrt(3) / 2
    gap = _number(s.get("gap"), .7, 0, size * .35)
    cells = []
    for row in range(math.floor(y1 / height) - 2, math.ceil(y2 / height) + 3):
        for col in range(math.floor(x1 / size) - 2, math.ceil(x2 / size) + 3):
            x, y = col * size + (row & 1) * size / 2, row * height
            cells.extend((Polygon(((x, y), (x + size, y), (x + size / 2, y + height))),
                          Polygon(((x, y), (x + size / 2, y - height), (x + size, y)))))
    return _cell_union(geometry, cells, gap)


def apply_tumbler_filter(geometry, s):
    """
    Unwrap artwork onto a variable-diameter rotary surface.

    Each row spans the same requested angular sweep. Its physical width is
    therefore local_circumference * wrap_angle / 360. Top/middle/bottom
    diameters describe the vessel profile; profile_curve adds a smooth bulge
    or waist between those measured stations.
    """
    bounds = s.get("_canvas_bounds") or geometry.bounds
    x1, y1, x2, y2 = bounds
    source_width, source_height = max(x2 - x1, 1e-9), max(y2 - y1, 1e-9)
    pixel_mm = _number(s.get("_scale_factor"), 1, .0001, 1000)
    top = _number(s.get("top_diameter_mm"), 75, 1, 1000)
    middle = _number(s.get("middle_diameter_mm"), 75, 1, 1000)
    bottom = _number(s.get("bottom_diameter_mm"), 70, 1, 1000)
    height_mm = _number(s.get("artwork_height_mm"), source_height * pixel_mm, .1, 5000)
    angle_fraction = _number(s.get("wrap_angle"), 180, 1, 360) / 360.0
    curve = _number(s.get("profile_curve"), 0, -1, 1)
    anchor = _number(s.get("horizontal_anchor"), .5, 0, 1)

    def diameter_at(t):
        # Quadratic interpolation through the three user measurements.
        if t <= .5:
            u = t * 2
            diameter = top + (middle - top) * u
        else:
            u = (t - .5) * 2
            diameter = middle + (bottom - middle) * u
        diameter += curve * min(top, middle, bottom) * .12 * math.sin(math.pi * t)
        return max(1, diameter)

    def unwrap(x, y, z=None):
        t = min(1, max(0, (y - y1) / source_height))
        target_width_px = math.pi * diameter_at(t) * angle_fraction / pixel_mm
        maximum_width_px = math.pi * max(top, middle, bottom) * (1 + max(0, curve) * .12) * angle_fraction / pixel_mm
        normalized_x = (x - x1) / source_width
        new_x = x1 + anchor * (maximum_width_px - target_width_px) + normalized_x * target_width_px
        new_y = y1 + t * height_mm / pixel_mm
        return new_x, new_y

    return transform(unwrap, geometry)


def apply_abstract_filter(
    geometry,
    abstract_filter,
    filter_parameters=None
):
    """
    Apply the selected abstract filter.

    The original function depends on the existing global
    `image_preset`, so that dependency is intentionally preserved
    here to keep this a true drop-in replacement.
    """

    if (
        abstract_filter is None
        or geometry.is_empty
    ):
        return geometry

    filter_name, settings = normalize_abstract_settings(abstract_filter, filter_parameters)

    if filter_name == "wave":

        return apply_wave_filter(
            geometry, settings
        )

    if filter_name == "voronoi":

        return apply_voronoi_filter(
            geometry, settings
        )

    if filter_name == "shear":

        return apply_shear_filter(
            geometry, settings
        )

    if filter_name == "spiral":
        return apply_spiral_filter(geometry, settings)

    if filter_name == "mosaic":
        return apply_mosaic_filter(geometry, settings)

    if filter_name in ("crystal", "tessellation", "triangles"):
        return apply_crystal_filter(geometry, settings)

    if filter_name in ("ripple", "topographic"):
        return apply_ripple_filter(geometry, settings)

    if filter_name == "tumbler":
        return apply_tumbler_filter(geometry, settings)

    return geometry


# ============================================================================
# GEOMETRY CLEANUP
# ============================================================================

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
    filter_parameters=None
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
        return boxes_to_centerlines(boxes, settings)

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

    if filter_name == "tumbler" and settings.get("material") == "powdercoat":
        pixel_mm = _number(settings.get("_scale_factor"), 1, .0001, 1000)
        gap = _number(settings.get("powdercoat_gap_mm"), .35, 0, 20) / pixel_mm
        powder_simplification = _number(
            settings.get("powdercoat_simplification_mm"), .3, 0, 20
        ) / pixel_mm
        if gap:
            final_geometry = final_geometry.buffer(-gap / 2, join_style=2)
        if powder_simplification and not final_geometry.is_empty:
            final_geometry = final_geometry.simplify(
                powder_simplification, preserve_topology=True
            )

    # ------------------------------------------------------------------------
    # 5. Apply abstract transformation.
    # ------------------------------------------------------------------------

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

    return final_geometry


def process_color_layers(
    pixel_boxes_by_color,
    target_colors,
    min_island_area,
    simplification_factor,
    smoothing_radius,
    abstract_filter,
    filter_parameters=None
):
    """
    Convert all raster color groups into finalized Shapely geometries.
    """

    processed_layers = {}

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

        layer_meta = target_colors[
            color_hex
        ]

        layer_id = layer_meta[1]
        layer_color_name = layer_meta[2]

        printLogMessage(
            f" -> Merging color boundaries... "
            f"(Layer math step {idx}/"
            f"{total_layers} - "
            f"Layer: {layer_id} "
            f"[{layer_color_name}])"
        )

        final_geometry = process_color_geometry(
            boxes=boxes,
            min_island_area=min_island_area,
            simplification_factor=simplification_factor,
            smoothing_radius=smoothing_radius,
            abstract_filter=abstract_filter,
            filter_parameters=filter_parameters
        )

        processed_layers[
            color_hex
        ] = final_geometry

    return processed_layers


# ============================================================================
# BLACK BACKGROUND
# ============================================================================

def build_punched_black_layer(
    width,
    height,
    processed_layers,
    black_hex,
    abstract_filter,
    filter_parameters=None
):
    """
    Build the black layer as the canvas minus all colored geometry.

    Invalid geometries are repaired before the union operation.
    """

    canvas_frame = box(
        0,
        0,
        width,
        height
    )

    canvas_frame = apply_abstract_filter(
        canvas_frame,
        abstract_filter,
        filter_parameters
    )

    colored_geometries = []

    for color_hex, geometry in processed_layers.items():

        if color_hex == black_hex:
            continue

        if geometry.is_empty:
            continue

        # ------------------------------------------------------------
        # Repair invalid geometry before attempting the union.
        # ------------------------------------------------------------

        if not geometry.is_valid:

            printLogMessage(
                f"Repairing invalid geometry for color "
                f"{color_hex} before black-layer subtraction..."
            )

            geometry = make_valid(
                geometry
            )

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

    # ------------------------------------------------------------
    # Combine all repaired colored geometry.
    # ------------------------------------------------------------

    all_colored_geometry = unary_union(
        colored_geometries
    )

    # ------------------------------------------------------------
    # Subtract colored geometry from black canvas.
    # ------------------------------------------------------------

    punched_black_layer = (
        canvas_frame.difference(
            all_colored_geometry
        )
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
    lb_project_instance
):
    """
    Convert Shapely geometry into LightBurn paths.

    Geometry is always pushed to its native color layer.

    IMPORTANT:
    This function no longer supports the old behavior of copying colored
    geometry onto the black layer. The black layer is now already punched
    geometrically.
    """

    if geometry.is_empty:
        return

    layer_meta = target_colors[
        color_hex
    ]

    layer_id = layer_meta[1]

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
                lb_project_instance
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
    lb_project_instance
):
    """
    Sort, scale, and export all finalized geometry to SVG and LightBurn.
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

        if geometry.is_empty:
            continue

        layer_meta = target_colors[
            color_hex
        ]

        layer_id = layer_meta[1]
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

            push_geometry_to_lightburn(
                export_geometry,
                color_hex,
                target_colors,
                lb_project_instance
            )

        # --------------------------------------------------------------------
        # IMPORTANT:
        #
        # There is deliberately NO:
        #
        #     if color_hex != black_hex:
        #         push_geometry_to_lightburn(... black_layer ...)
        #
        # anymore.
        #
        # The black layer itself already contains the holes.
        # --------------------------------------------------------------------


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
    abstract_filter=None,
    filter_parameters=None
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

    filter_name, normalized_filter_settings = normalize_abstract_settings(
        abstract_filter, filter_parameters
    )
    if filter_name in PALETTE_LIMITING_FILTERS:
        quantize_colors = max(2, len(TARGET_COLORS))
        printLogMessage(
            f"{filter_name.title()} filter using all {len(TARGET_COLORS)} "
            "colors available after UI and material-library filtering."
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

    # `black_layer_id` is retained here for compatibility/logging/debugging.
    # The actual export now uses the native layer ID from TARGET_COLORS.
    _ = black_layer_id

    # =========================================================================
    # 3. Load and prepare raster
    # =========================================================================

    img = prepare_raster_image(
        raster_image_path=raster_image_path,
        new_height=new_height,
        new_width=new_width,
        quantize_colors=quantize_colors
    )

    width, height = img.size

    # Every color layer must use the same radial center and extent.  Keeping
    # this internal value shared prevents independently warped layers from
    # crossing or drifting apart at formerly common boundaries.
    filter_parameters = dict(filter_parameters or {})
    filter_parameters["_canvas_bounds"] = (0, 0, width, height)
    filter_parameters["_scale_factor"] = scale_factor
    filter_name, _ = normalize_abstract_settings(abstract_filter, filter_parameters)
    centerline_mode = filter_name == "centerline"

    # =========================================================================
    # 4. Convert pixels into color geometry buckets
    # =========================================================================

    pixel_boxes_by_color = (
        classify_raster_pixels(
            img=img,
            target_colors=TARGET_COLORS,
            black_hex=black_hex,
            ignore_background_hex=ignore_background_hex,
            include_black=centerline_mode
        )

    )

    if filter_name == "tumbler" and filter_parameters.get("material") == "powdercoat":
        pixel_boxes_by_color = retain_dominant_foreground(
            pixel_boxes_by_color, img, filter_parameters
        )

    # =========================================================================
    # 5. Process every colored layer
    # =========================================================================

    processed_layers = process_color_layers(
        pixel_boxes_by_color=pixel_boxes_by_color,
        target_colors=TARGET_COLORS,
        min_island_area=min_island_area,
        simplification_factor=simplification_factor,
        smoothing_radius=smoothing_radius,
        abstract_filter=abstract_filter,
        filter_parameters=filter_parameters
    )

    # =========================================================================
    # 6. Build the BLACK layer around the colored geometry
    # =========================================================================

    if not centerline_mode:
        processed_layers[black_hex] = build_punched_black_layer(
            width=width,
            height=height,
            processed_layers=processed_layers,
            black_hex=black_hex,
            abstract_filter=abstract_filter,
            filter_parameters=filter_parameters
        )

    else:
        printLogMessage("Centerline mode: exporting source-color medial axes as open paths.")

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
        lb_project_instance=lb_project_instance
    )

    # =========================================================================
    # 9. Save output files
    # =========================================================================

    save_vector_output(
        root=root,
        output_svg_path=output_svg_path,
        lb_project_instance=lb_project_instance
    )



if __name__ == "__main__":
    INPUT_FILE = sys.argv[1]
    OUTPUT_FILE=sys.argv[2]
    square_mm=float(sys.argv[3])
    new_width=sys.argv[4]
    new_height=sys.argv[5]
    material_library_file=sys.argv[6]
    the_limit_colors = sys.argv[7]    
    max_dimension = max(new_width, new_height)
    image_preset= sys.argv[8]
    abstract_filter = sys.argv[9]
    filter_parameters = {}
    if len(sys.argv) > 10 and sys.argv[10].strip():
        try:
            filter_parameters = json.loads(sys.argv[10])
            if not isinstance(filter_parameters, dict):
                raise ValueError("filter parameters must be a JSON object")
        except (json.JSONDecodeError, ValueError) as error:
            raise SystemExit(f"Invalid abstract filter parameters: {error}")
    
    quantize_colors=PHOTO_TYPE_PRESETS[image_preset]["quantize_colors"]        # Keeps original target palette colors intact
    min_island_area=PHOTO_TYPE_PRESETS[image_preset]["min_island_area"]           # Retains small details and sharp lines
    simplification_factor=PHOTO_TYPE_PRESETS[image_preset]["simplification_factor"]   # Retains crisp pixel-perfect boundaries
    smoothing_radius=PHOTO_TYPE_PRESETS[image_preset]["smoothing_radius"]       # Baseline vector weld setting    
    
    the_limit_colors_list = [item.strip() for item in the_limit_colors.split(",")]
    printLogMessage(f"\nusing material library settings: {material_library_file}")
    printLogMessage(f"\nusing colors: {the_limit_colors}")
    TARGET_COLORS , lb, lightburn = init_lightburn(the_limit_colors)
    TARGET_COLORS['#B4B4B4'] = (0, 8, 'Light-Gray')
    TARGET_COLORS['#000000'] = (0, 0, 'Black')
    if len(the_limit_colors_list) <= 1:
        the_limit_colors_list = [cv[-1].lower() for cn,cv in TARGET_COLORS.items()]
    the_limit_colors_list.append("black")
    the_limit_colors_list.append("light-gray")
    the_output_file = f"{OUTPUT_FILE}.vector.svg"
    printLogMessage(f"\nusing TARGET_COLORS: {TARGET_COLORS}")
    printLogMessage(f"\nusing LIMIT COLORS: {','.join(the_limit_colors_list)}")
    TARGET_COLORS = parse_material_settings(lb, material_library_file, the_limit_colors_list, TARGET_COLORS)
    raster_to_puzzle_and_lightburn(
        raster_image_path=INPUT_FILE,
        output_svg_path=the_output_file,
        new_height=new_height,
        new_width=new_width,
        lb_project_instance=lb,
        TARGET_COLORS=TARGET_COLORS,
        scale_factor=float(square_mm),
        ignore_background_hex="#ffffff",
        quantize_colors=quantize_colors,
        min_island_area=min_island_area,
        simplification_factor=simplification_factor,
        smoothing_radius=smoothing_radius,
        abstract_filter=abstract_filter,
        filter_parameters=filter_parameters
    )
