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
from shapely.geometry import Polygon, box
from shapely.ops import unary_union
from shapely.affinity import scale
from svgelements import SVG, Path, Polygon as SVGPolygon
from datetime import datetime

def printLogMessage(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)

def raster_to_puzzle_and_lightburn(raster_image_path, output_svg_path, new_height, new_width, lb_project_instance, TARGET_COLORS, scale_factor=1.0, ignore_background_hex="#ffffff"):
    """
    Parses a raster image, applies a structural vector scale_factor, saves a gapless SVG puzzle file, 
    and pushes matching paths into LightBurn.
    Forces LightBurn to handle the cutout subtraction natively by overlaying all non-black 
    foreground geometries directly onto the black cutting layer without generating a duplicate solid background.
    """
    printLogMessage(f"Opening raster image: {raster_image_path}")
    img = Image.open(raster_image_path).convert("RGB")
    orig_width, orig_height = img.size
    printLogMessage(f"Original Image Pixel Size: {orig_width}, {orig_height}")
    
    img = resize_to_specific_height_or_width(image=img, height=int(new_height), width=int(new_width))
    width, height = img.size
    
    pixel_boxes_by_color = defaultdict(list)
    
    # Dynamically locate the black hex and its corresponding Layer ID
    black_hex = next((h for h, meta in TARGET_COLORS.items() if "black" in str(meta).lower() or h == "#000000"), "#000000")
    black_layer_id = TARGET_COLORS.get(black_hex, [0, 0, "black"])[1]
    
    printLogMessage("Analyzing pixels and snapping colors...")
    
    # --- PASS 1: Build pixel maps for NON-BLACK colors ONLY ---
    for y in range(height):
        for x in range(width):
            pixel_rgb = img.getpixel((x, y))
            closest_hex = get_closest_color(*pixel_rgb, TARGET_COLORS)
            if closest_hex == ignore_background_hex:
                continue
                
            # CRITICAL FIX: Skip collecting black pixels to eliminate the duplicate solid backing box
            if closest_hex == black_hex:
                continue
                
            pixel_poly = box(x, y, x + 1, y + 1)
            pixel_boxes_by_color[closest_hex].append(pixel_poly)

    # Rebuild standard flat SVG structure
    root = ET.Element('svg', xmlns="http://w3.org", version="1.1")
    root.set('viewBox', f"0 0 {new_width} {new_height}")
    root.set('width', f"{str(width)}mm")
    root.set('height', f"{str(height)}mm")

    def add_geom_to_svg(geom, fill_color):
        if geom.is_empty:
            return
        if geom.geom_type == 'Polygon':
            d_path = "M " + " L ".join([f"{x:.3f},{y:.3f}" for x, y in geom.exterior.coords]) + " Z"
            for interior in geom.interiors:
                d_path += " M " + " L ".join([f"{x:.3f},{y:.3f}" for x, y in interior.coords]) + " Z"
            ET.SubElement(root, 'path', d=d_path, fill=fill_color, stroke="none")
        elif geom.geom_type in ('MultiPolygon', 'GeometryCollection'):
            for sub_geom in geom.geoms:
                add_geom_to_svg(sub_geom, fill_color)

    def push_geom_to_lightburn(geom, color_hex, override_layer_id=None):
        """Extracts coordinate paths from Shapely geometry and pipes them into a designated LightBurn layer."""
        if geom.is_empty:
            return
            
        layer_meta = TARGET_COLORS[color_hex]
        layer_id = override_layer_id if override_layer_id is not None else layer_meta[1]
        layer_color_name = layer_meta[2]
        
        if geom.geom_type == 'Polygon':
            exterior_coords = [[round(x, 3), round(y, 3)] for x, y in geom.exterior.coords]
            if exterior_coords:
                lb_shape = lightburn.Path(exterior_coords).layer(layer_id)
                lb_project_instance.add(lb_shape)
            for interior in geom.interiors:
                interior_coords = [[round(x, 3), round(y, 3)] for x, y in interior.coords]
                if interior_coords:
                    lb_hole = lightburn.Path(interior_coords).layer(layer_id)
                    lb_project_instance.add(lb_hole)
        elif geom.geom_type in ('MultiPolygon', 'GeometryCollection'):
            for sub_geom in geom.geoms:
                push_geom_to_lightburn(sub_geom, color_hex, override_layer_id=layer_id)

    # --- PASS 2: Heavy Vector Geometry Consolidation ---
    processed_layers = {}
    printLogMessage(f"Beginning vector union math for {len(pixel_boxes_by_color)} unique layers...")
    
    for idx, (color_hex, boxes) in enumerate(pixel_boxes_by_color.items(), 1):
        if not boxes:
            continue
        
        layer_meta = TARGET_COLORS[color_hex]
        layer_id = layer_meta[1]
        layer_color_name = layer_meta[2]
        
        printLogMessage(f" -> Merging color boundaries... (Layer math step {idx}/{len(pixel_boxes_by_color)} - Layer: {layer_id} [{layer_color_name}])")
        
        welded_layer = unary_union(boxes)
        final_puzzle_piece = welded_layer.buffer(0.001).buffer(-0.001)
        processed_layers[color_hex] = final_puzzle_piece

    printLogMessage("Vector generation complete. Sorting and formatting log history...")

    # --- PASS 3: Sort the finished layers by Layer ID ---
    sorted_layers = sorted(
        processed_layers.items(),
        key=lambda item: TARGET_COLORS[item[0]][1]
    )

    # --- PASS 4: Log, Scale, and Export in Order ---
    printLogMessage("==============================================")
    printLogMessage("      LAYER EXPORT AND PROCESS LOG SUMMARY     ")
    printLogMessage("==============================================")
    for color_hex, final_puzzle_piece in sorted_layers:
        if final_puzzle_piece.is_empty:
            continue
            
        layer_meta = TARGET_COLORS[color_hex]
        layer_id = layer_meta[1]
        layer_color_name = layer_meta[2]
        
        printLogMessage(f"Processing and welding layer {layer_id} color: {layer_color_name}")
        
        if scale_factor != 1.0:
            printLogMessage(f"Scaling {layer_color_name} geometry by a factor of {scale_factor}x")
            final_puzzle_piece = scale(final_puzzle_piece, xfact=scale_factor, yfact=scale_factor, origin=(0, 0))
            
        # Export Option 1: Add to SVG Tree
        add_geom_to_svg(final_puzzle_piece, color_hex)
        
        # Export Option 2: Push to LightBurn
        if color_hex in TARGET_COLORS:
            # 1. Push the shape to its native colored layer
            printLogMessage(f"Pushing scaled {layer_color_name} geometry into LightBurn Layer ID: {layer_id}")
            push_geom_to_lightburn(final_puzzle_piece, color_hex)
            
            # 2. Push it directly onto the black layer to trigger native cutout holes
            printLogMessage(f" -> Overlaying cutout path onto Black Layer ID: {black_layer_id}")
            push_geom_to_lightburn(final_puzzle_piece, color_hex, override_layer_id=black_layer_id)

    # Save SVG to disk
    tree = ET.ElementTree(root)
    printLogMessage(f"Writing finalized scaled zero-overlap SVG to: {output_svg_path}")
    tree.write(output_svg_path, encoding='utf-8', xml_declaration=True)
    lb.write(output_svg_path + ".lbrn2")

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
    raster_to_puzzle_and_lightburn(INPUT_FILE, the_output_file, new_height, new_width, lb, TARGET_COLORS, square_mm)
