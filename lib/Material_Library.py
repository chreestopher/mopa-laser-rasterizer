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
from shapely.geometry import Polygon, box, MultiPoint
from shapely.ops import unary_union, voronoi_diagram, transform
from shapely.affinity import scale, affine_transform
from svgelements import SVG, Path, Polygon as SVGPolygon
from datetime import datetime



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
    abstract_filter=None
):
    """
    Parses a raster image, converts it into consolidated vector layers,
    creates a black background layer with all colored geometry punched out,
    saves the resulting SVG, and pushes the corresponding geometry into
    LightBurn.

    The black layer is explicitly constructed as:

        black canvas - union(all colored layers)

    This guarantees that colored shapes do not exist underneath the black
    layer in the final geometry.

    Includes:
        - color quantization
        - minimum island filtering
        - morphological smoothing
        - Douglas-Peucker simplification
        - optional abstract transformations
        - SVG export
        - LightBurn export
    """

    # =========================================================================
    # --- PASS 0: Normalize Parameters ---
    # =========================================================================

    if isinstance(quantize_colors, (tuple, list)):
        quantize_colors = quantize_colors[0] if quantize_colors else None

    if quantize_colors is not None:
        quantize_colors = int(quantize_colors)
        max_allowable_colors = len(TARGET_COLORS)

        if quantize_colors > max_allowable_colors:
            quantize_colors = max_allowable_colors

    if isinstance(min_island_area, (tuple, list)):
        min_island_area = min_island_area[0] if min_island_area else 0

    min_island_area = float(min_island_area)

    if isinstance(simplification_factor, (tuple, list)):
        simplification_factor = (
            simplification_factor[0]
            if simplification_factor
            else 0.0
        )

    simplification_factor = float(simplification_factor)

    if isinstance(smoothing_radius, (tuple, list)):
        smoothing_radius = (
            smoothing_radius[0]
            if smoothing_radius
            else 0.001
        )

    smoothing_radius = float(smoothing_radius)

    # =========================================================================
    # --- PASS 1: Open / Resize / Quantize Raster ---
    # =========================================================================

    printLogMessage(f"Opening raster image: {raster_image_path}")

    img = Image.open(raster_image_path).convert("RGB")

    orig_width, orig_height = img.size

    printLogMessage(
        f"Original Image Pixel Size: {orig_width}, {orig_height}"
    )

    img = resize_to_specific_height_or_width(
        image=img,
        height=int(new_height),
        width=int(new_width)
    )

    # Reduce gradient colors if requested.
    if quantize_colors is not None:
        printLogMessage(
            f"Quantizing photo colors down to a maximum pool "
            f"of {quantize_colors} levels..."
        )

        img = img.quantize(
            colors=quantize_colors,
            method=0
        ).convert("RGB")

    width, height = img.size

    pixel_boxes_by_color = defaultdict(list)

    # Dynamically locate the black color and LightBurn layer.
    black_hex = next(
        (
            h
            for h, meta in TARGET_COLORS.items()
            if "black" in str(meta).lower() or h == "#000000"
        ),
        "#000000"
    )

    black_layer_id = TARGET_COLORS.get(
        black_hex,
        [0, 0, "black"]
    )[1]

    printLogMessage(
        f"Black background detected as {black_hex} "
        f"on LightBurn Layer ID {black_layer_id}"
    )

    # =========================================================================
    # --- PASS 1A: Build Pixel Maps for NON-BLACK Colors ---
    # =========================================================================

    printLogMessage(
        "Analyzing pixels and snapping colors..."
    )

    for y in range(height):
        for x in range(width):

            pixel_rgb = img.getpixel((x, y))

            closest_hex = get_closest_color(
                *pixel_rgb,
                TARGET_COLORS
            )

            # Ignore designated background color.
            if closest_hex == ignore_background_hex:
                continue

            # Black is NOT built from raster pixels.
            #
            # It will instead be generated geometrically as:
            #
            #     canvas - all colored geometry
            #
            if closest_hex == black_hex:
                continue

            pixel_poly = box(
                x,
                y,
                x + 1,
                y + 1
            )

            pixel_boxes_by_color[closest_hex].append(
                pixel_poly
            )

    # =========================================================================
    # --- SVG ROOT ---
    # =========================================================================

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

    # =========================================================================
    # --- SVG GEOMETRY EXPORT HELPER ---
    # =========================================================================

    def add_geom_to_svg(geom, fill_color):

        if geom.is_empty:
            return

        if geom.geom_type == "Polygon":

            d_path = (
                "M "
                + " L ".join(
                    [
                        f"{x:.3f},{y:.3f}"
                        for x, y in geom.exterior.coords
                    ]
                )
                + " Z"
            )

            # Preserve holes.
            for interior in geom.interiors:

                d_path += (
                    " M "
                    + " L ".join(
                        [
                            f"{x:.3f},{y:.3f}"
                            for x, y in interior.coords
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

        elif geom.geom_type in (
            "MultiPolygon",
            "GeometryCollection"
        ):

            for sub_geom in geom.geoms:
                add_geom_to_svg(
                    sub_geom,
                    fill_color
                )

    # =========================================================================
    # --- LIGHTBURN GEOMETRY EXPORT HELPER ---
    # =========================================================================

    def push_geom_to_lightburn(
        geom,
        color_hex,
        override_layer_id=None
    ):
        """
        Extracts coordinate paths from Shapely geometry and pipes them
        into the appropriate LightBurn layer.
        """

        if geom.is_empty:
            return

        layer_meta = TARGET_COLORS[color_hex]

        layer_id = (
            override_layer_id
            if override_layer_id is not None
            else layer_meta[1]
        )

        if geom.geom_type == "Polygon":

            # -------------------------------------------------------------
            # Exterior boundary
            # -------------------------------------------------------------

            exterior_coords = [
                [round(x, 3), round(y, 3)]
                for x, y in geom.exterior.coords
            ]

            if exterior_coords:

                lb_shape = (
                    lightburn.Path(exterior_coords)
                    .layer(layer_id)
                )

                lb_project_instance.add(
                    lb_shape
                )

            # -------------------------------------------------------------
            # Interior holes
            # -------------------------------------------------------------

            for interior in geom.interiors:

                interior_coords = [
                    [round(x, 3), round(y, 3)]
                    for x, y in interior.coords
                ]

                if interior_coords:

                    lb_hole = (
                        lightburn.Path(interior_coords)
                        .layer(layer_id)
                    )

                    lb_project_instance.add(
                        lb_hole
                    )

        elif geom.geom_type in (
            "MultiPolygon",
            "GeometryCollection"
        ):

            for sub_geom in geom.geoms:

                push_geom_to_lightburn(
                    sub_geom,
                    color_hex,
                    override_layer_id=layer_id
                )

    # =========================================================================
    # --- PASS 2: HEAVY VECTOR GEOMETRY CONSOLIDATION ---
    # =========================================================================

    processed_layers = {}

    printLogMessage(
        f"Beginning vector union math for "
        f"{len(pixel_boxes_by_color)} unique layers..."
    )

    for idx, (color_hex, boxes) in enumerate(
        pixel_boxes_by_color.items(),
        1
    ):

        if not boxes:
            continue

        layer_meta = TARGET_COLORS[color_hex]

        layer_id = layer_meta[1]
        layer_color_name = layer_meta[2]

        printLogMessage(
            f" -> Merging color boundaries... "
            f"(Layer math step {idx}/"
            f"{len(pixel_boxes_by_color)} - "
            f"Layer: {layer_id} "
            f"[{layer_color_name}])"
        )

        # ---------------------------------------------------------------------
        # Union all pixels belonging to this color.
        # ---------------------------------------------------------------------

        welded_layer = unary_union(boxes)

        # ---------------------------------------------------------------------
        # Morphological opening / smoothing.
        # ---------------------------------------------------------------------

        final_puzzle_piece = (
            welded_layer
            .buffer(smoothing_radius)
            .buffer(-smoothing_radius)
        )

        # ---------------------------------------------------------------------
        # Remove tiny islands.
        # ---------------------------------------------------------------------

        if min_island_area > 0:

            if final_puzzle_piece.geom_type == "Polygon":

                if final_puzzle_piece.area < min_island_area:

                    final_puzzle_piece = box(
                        0,
                        0,
                        0,
                        0
                    )

            elif final_puzzle_piece.geom_type in (
                "MultiPolygon",
                "GeometryCollection"
            ):

                valid_polys = [
                    p
                    for p in final_puzzle_piece.geoms
                    if p.area >= min_island_area
                ]

                if valid_polys:

                    final_puzzle_piece = unary_union(
                        valid_polys
                    )

                else:

                    final_puzzle_piece = box(
                        0,
                        0,
                        0,
                        0
                    )

        # ---------------------------------------------------------------------
        # Douglas-Peucker simplification.
        # ---------------------------------------------------------------------

        if simplification_factor > 0.0:

            final_puzzle_piece = (
                final_puzzle_piece.simplify(
                    simplification_factor,
                    preserve_topology=True
                )
            )

        # =========================================================================
        # --- ABSTRACT PRESET TRANSFORMATIONS ---
        # =========================================================================

        if (
            abstract_filter is not None
            and not final_puzzle_piece.is_empty
            and image_preset == "abstract"
        ):

            # -----------------------------------------------------------------
            # STRATEGY 1: Wavy Fluid Distortion
            # -----------------------------------------------------------------

            if str(abstract_filter).lower() == "wave":

                def wave_transform(x, y, z=None):

                    freq_x = 0.1
                    amp_x = 4.0

                    freq_y = 0.1
                    amp_y = 4.0

                    new_x = (
                        x
                        + math.sin(y * freq_y) * amp_x
                    )

                    new_y = (
                        y
                        + math.cos(x * freq_x) * amp_y
                    )

                    return (
                        new_x,
                        new_y
                    )

                final_puzzle_piece = transform(
                    wave_transform,
                    final_puzzle_piece
                )

            # -----------------------------------------------------------------
            # STRATEGY 2: Shattered Voronoi / Cellular Sharding
            # -----------------------------------------------------------------

            elif str(abstract_filter).lower() == "voronoi":

                bounds = final_puzzle_piece.bounds

                points = []

                step = 15

                for gx in range(
                    int(bounds[0]),
                    int(bounds[2]) + step,
                    step
                ):

                    for gy in range(
                        int(bounds[1]),
                        int(bounds[3]) + step,
                        step
                    ):

                        jiggle_x = (
                            (gx % 7) - 3.5
                        )

                        jiggle_y = (
                            (gy % 5) - 2.5
                        )

                        points.append(
                            (
                                gx + jiggle_x,
                                gy + jiggle_y
                            )
                        )

                if len(points) >= 3:

                    mp = MultiPoint(points)

                    vd = voronoi_diagram(mp)

                    final_puzzle_piece = (
                        final_puzzle_piece
                        .intersection(vd)
                    )

            # -----------------------------------------------------------------
            # STRATEGY 3: Directional Perspective Shear
            # -----------------------------------------------------------------

            elif str(abstract_filter).lower() == "shear":

                final_puzzle_piece = affine_transform(
                    final_puzzle_piece,
                    [
                        1.0,
                        0.5,
                        0.0,
                        0.8,
                        0.0,
                        0.0
                    ]
                )

        # ---------------------------------------------------------------------
        # Save finalized colored geometry.
        # ---------------------------------------------------------------------

        processed_layers[color_hex] = (
            final_puzzle_piece
        )

    # =========================================================================
    # --- PASS 3: BUILD THE BLACK BACKGROUND WITH HOLES ---
    # =========================================================================

    printLogMessage(
        "Building black background layer..."
    )

    # Start with the entire canvas.
    canvas_frame = box(
        0,
        0,
        width,
        height
    )

    # -------------------------------------------------------------------------
    # Apply the same abstract transformation to the black canvas.
    #
    # NOTE:
    # This preserves the behavior of the original function.
    # -------------------------------------------------------------------------

    if (
        abstract_filter is not None
        and not canvas_frame.is_empty
        and image_preset == "abstract"
    ):

        # ---------------------------------------------------------------------
        # WAVE
        # ---------------------------------------------------------------------

        if str(abstract_filter).lower() == "wave":

            def wave_transform(x, y, z=None):

                return (
                    x + math.sin(y * 0.1) * 4.0,
                    y + math.cos(x * 0.1) * 4.0
                )

            canvas_frame = transform(
                wave_transform,
                canvas_frame
            )

        # ---------------------------------------------------------------------
        # VORONOI
        # ---------------------------------------------------------------------

        elif str(abstract_filter).lower() == "voronoi":

            bounds = canvas_frame.bounds

            points = []

            for gx in range(
                int(bounds[0]),
                int(bounds[2]) + 15,
                15
            ):

                for gy in range(
                    int(bounds[1]),
                    int(bounds[3]) + 15,
                    15
                ):

                    points.append(
                        (
                            gx + (gx % 7) - 3.5,
                            gy + (gy % 5) - 2.5
                        )
                    )

            if len(points) >= 3:

                canvas_frame = (
                    canvas_frame.intersection(
                        voronoi_diagram(
                            MultiPoint(points)
                        )
                    )
                )

        # ---------------------------------------------------------------------
        # SHEAR
        # ---------------------------------------------------------------------

        elif str(abstract_filter).lower() == "shear":

            canvas_frame = affine_transform(
                canvas_frame,
                [
                    1.0,
                    0.5,
                    0.0,
                    0.8,
                    0.0,
                    0.0
                ]
            )

    # =========================================================================
    # --- THE IMPORTANT FIX ---
    #
    # Punch ALL finalized colored geometry out of the black background.
    #
    # This means the black layer contains only areas where there is no
    # colored geometry underneath it.
    # =========================================================================

    colored_geometries = [
        geom
        for color_hex, geom in processed_layers.items()
        if (
            color_hex != black_hex
            and not geom.is_empty
        )
    ]

    if colored_geometries:

        printLogMessage(
            f"Punching {len(colored_geometries)} "
            f"colored layer(s) out of black background..."
        )

        # Combine every colored layer into one geometry.
        all_colored_geometry = unary_union(
            colored_geometries
        )

        # Subtract all colored geometry from the black canvas.
        punched_black_layer = (
            canvas_frame.difference(
                all_colored_geometry
            )
        )

        processed_layers[black_hex] = (
            punched_black_layer
        )

        printLogMessage(
            "Black layer successfully punched around "
            "all colored geometry."
        )

    else:

        # No colored geometry exists, so the black layer remains
        # the complete canvas.
        processed_layers[black_hex] = (
            canvas_frame
        )

        printLogMessage(
            "No colored geometry found; "
            "black layer remains a complete canvas."
        )

    # =========================================================================
    # --- PASS 4: SORT FINISHED LAYERS BY LAYER ID ---
    # =========================================================================

    printLogMessage(
        "Vector generation complete. "
        "Sorting and formatting log history..."
    )

    sorted_layers = sorted(
        processed_layers.items(),
        key=lambda item: TARGET_COLORS[item[0]][1]
    )

    # =========================================================================
    # --- PASS 5: EXPORT SVG + LIGHTBURN ---
    # =========================================================================

    printLogMessage(
        "=============================================="
    )

    printLogMessage(
        "      LAYER EXPORT AND PROCESS LOG SUMMARY"
    )

    printLogMessage(
        "=============================================="
    )

    for color_hex, final_puzzle_piece in sorted_layers:

        if final_puzzle_piece.is_empty:
            continue

        layer_meta = TARGET_COLORS[color_hex]

        layer_id = layer_meta[1]
        layer_color_name = layer_meta[2]

        printLogMessage(
            f"Processing and welding layer "
            f"{layer_id} color: "
            f"{layer_color_name}"
        )

        # ---------------------------------------------------------------------
        # Apply final global scale.
        # ---------------------------------------------------------------------

        if scale_factor != 1.0:

            printLogMessage(
                f"Scaling {layer_color_name} geometry "
                f"by a factor of {scale_factor}x"
            )

            final_puzzle_piece = scale(
                final_puzzle_piece,
                xfact=scale_factor,
                yfact=scale_factor,
                origin=(0, 0)
            )

        # ---------------------------------------------------------------------
        # Export to SVG.
        # ---------------------------------------------------------------------

        add_geom_to_svg(
            final_puzzle_piece,
            color_hex
        )

        # ---------------------------------------------------------------------
        # Export to LightBurn.
        #
        # IMPORTANT:
        # We ONLY push the geometry to its native layer.
        #
        # The old code additionally copied every colored shape onto the black
        # layer. That behavior has been intentionally removed because the
        # black layer is now already geometrically punched around the colored
        # shapes.
        # ---------------------------------------------------------------------

        if color_hex in TARGET_COLORS:

            printLogMessage(
                f"Pushing scaled "
                f"{layer_color_name} geometry "
                f"into LightBurn Layer ID: "
                f"{layer_id}"
            )

            push_geom_to_lightburn(
                final_puzzle_piece,
                color_hex
            )

    # =========================================================================
    # --- SAVE FINAL FILES ---
    # =========================================================================

    tree = ET.ElementTree(root)

    printLogMessage(
        f"Writing finalized scaled zero-overlap SVG to: "
        f"{output_svg_path}"
    )

    tree.write(
        output_svg_path,
        encoding="utf-8",
        xml_declaration=True
    )

    lb.write(
        output_svg_path + ".lbrn2"
    )

    printLogMessage(
        "SVG and LightBurn export complete."
    )

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
    file_path = "/app/lib/lightburn.py"

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
    
    quantize_colors=PHOTO_TYPE_PRESETS[image_preset]["quantize_colors"],        # Keeps original target palette colors intact
    min_island_area=PHOTO_TYPE_PRESETS[image_preset]["min_island_area"],           # Retains small details and sharp lines
    simplification_factor=PHOTO_TYPE_PRESETS[image_preset]["simplification_factor"],   # Retains crisp pixel-perfect boundaries
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
        abstract_filter=abstract_filter
    )