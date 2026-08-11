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
    Parses a raster image, applies a structural vector scale_factor,
    saves a gapless SVG puzzle file, and pushes matching paths into LightBurn.
    """
    printLogMessage(f"Opening raster image: {raster_image_path}")
    img = Image.open(raster_image_path).convert("RGB")
    img = resize_to_specific_height_or_width(image=img, height=int(new_height), width=int(new_width))
    width, height = img.size
    
    pixel_boxes_by_color = defaultdict(list)
    
    printLogMessage("Analyzing pixels and snapping colors...")
    for y in range(height):
        for x in range(width):
            pixel_rgb = img.getpixel((x, y))
            closest_hex = get_closest_color(*pixel_rgb, TARGET_COLORS)
            
            if closest_hex == ignore_background_hex:
                continue
                
            pixel_poly = box(x, y, x + 1, y + 1)
            pixel_boxes_by_color[closest_hex].append(pixel_poly)

    # # Calculate new target viewport canvas dimensions for the SVG file
    # scaled_width = width * scale_factor
    # scaled_height = height * scale_factor

    # Rebuild standard flat SVG structure
    root = ET.Element('svg', xmlns="http://w3.org", version="1.1")
    root.set('viewBox', f"0 0 {width} {height}")
    root.set('width', str(width))
    root.set('height', str(height))

    def add_geom_to_svg(geom, fill_color):
        if geom.is_empty:
            return
        if geom.geom_type == 'Polygon':
            # Use up to 3 decimal places for highly accurate precision resizing scaling
            d_path = "M " + " L ".join([f"{x:.3f},{y:.3f}" for x, y in geom.exterior.coords]) + " Z"
            for interior in geom.interiors:
                d_path += " M " + " L ".join([f"{x:.3f},{y:.3f}" for x, y in interior.coords]) + " Z"
            ET.SubElement(root, 'path', d=d_path, fill=fill_color, stroke="none")
        elif geom.geom_type in ('MultiPolygon', 'GeometryCollection'):
            for sub_geom in geom.geoms:
                add_geom_to_svg(sub_geom, fill_color)

    def push_geom_to_lightburn(geom, layer_id):
        """Extracts coordinate paths from Shapely geometry and pipes them into LightBurn."""
        if geom.is_empty:
            return
        layer_meta = TARGET_COLORS[color_hex]
        layer_id = layer_meta[1]
        layer_color_name = layer_meta[2]
        if geom.geom_type == 'Polygon':
            # 1. Process the outer boundary loop
            exterior_coords = [[round(x, 3), round(y, 3)] for x, y in geom.exterior.coords]
            if exterior_coords:
                lb_shape = lightburn.Path(exterior_coords).layer(layer_id)
                lb_project_instance.add(lb_shape)
            # 2. Process any inner cutout holes on the exact same layer ID
            for interior in geom.interiors:
                interior_coords = [[round(x, 3), round(y, 3)] for x, y in interior.coords]
                if interior_coords:
                    lb_hole = lightburn.Path(interior_coords).layer(layer_id)
                    lb_project_instance.add(lb_hole)
                
        elif geom.geom_type in ('MultiPolygon', 'GeometryCollection'):
            printLogMessage(f"Add {len(geom.geoms)} shapes on Layer: {layer_id} color: {layer_color_name}")
            for sub_geom in geom.geoms:
                push_geom_to_lightburn(sub_geom, layer_id)

    # Process, scale, and export geometries
    for color_hex, boxes in pixel_boxes_by_color.items():
        layer_meta = TARGET_COLORS[color_hex]
        layer_id = layer_meta[1]
        layer_color_name = layer_meta[2]
        printLogMessage(f"Processing and welding layer {layer_id}  color: {layer_color_name}")
        
        # 1. Weld individual pixel boundaries
        welded_layer = unary_union(boxes)
        final_puzzle_piece = welded_layer.buffer(0.001).buffer(-0.001)
        
        # 2. Apply Unified Scale Factor (Scaling from the top-left origin)
        if scale_factor != 1.0:
            printLogMessage(f"Scaling {layer_color_name} geometry by a factor of {scale_factor}x")
            final_puzzle_piece = scale(final_puzzle_piece, xfact=scale_factor, yfact=scale_factor, origin=(0, 0))
        
        # Export Option 1: Add to SVG Tree
        add_geom_to_svg(final_puzzle_piece, color_hex)
               
        # Export Option 2: Push to LightBurn
        if color_hex in TARGET_COLORS:
            layer_meta = TARGET_COLORS[color_hex]
            layer_id = layer_meta[1]
            layer_color_name = layer_meta[2]
            printLogMessage(f"Pushing scaled {layer_color_name} geometry into LightBurn Layer ID: {layer_id}")
            push_geom_to_lightburn(final_puzzle_piece, layer_id)

    # Save SVG to disk
    tree = ET.ElementTree(root)
    printLogMessage(f"Writing finalized scaled zero-overlap SVG to: {output_svg_path}")
    tree.write(output_svg_path, encoding='utf-8', xml_declaration=True)
    lb.write(output_svg_path +".lbrn2")

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

def get_closest_color(r, g, b, TARGET_COLORS):
    """
    Determines the output color based on the input pixel's value (luminance) and hue.
    """
    # 1. Calculate Value (V) for thresholding (using max component for simplicity)
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

    my_color = closest_hex
    return my_color

def generate_pixel_svg(TARGET_COLORS, input_image_path, output_svg_path, square_size_mm=0.25, new_width=0, new_height=0):
    """
    Loads an image, processes pixels, and generates an SVG file and lightbhurn file
    
    Args:
        input_image_path (str): Path to the source image file.
        output_svg_path (str): Path where the SVG file will be saved.
        square_size_mm (float): The size of each square in millimeters.
        new_width: New Width to resize the image to, respecting the aspect ratio
        new_height: New Height to resize the image to, respecting the aspect ratio
            * only one of new_width or new_height can be used at a time
    """
    printLogMessage((input_image_path, output_svg_path, square_size_mm, new_width, new_height))
    
    try:
        # Load the image and convert to RGB (to ensure consistent 3-channel access)
        img = Image.open(input_image_path).convert("RGB")
    except FileNotFoundError:
        printLogMessage(f"Error: Input file not found at '{input_image_path}'")
        return
    except Exception as e:
        printLogMessage(f"Error loading image: {e}")
        return

    img = resize_to_specific_height_or_width(image=img, height=int(new_height), width=int(new_width))
    width, height = img.size
    
    # Calculate the total SVG dimensions in millimeters
    svg_width_mm = width * square_size_mm
    svg_height_mm = height * square_size_mm
    
    # Constants for the SVG output
    STROKE_WIDTH_MM = 0.01

    printLogMessage(f"Processing image: {width}x{height} pixels.")
    printLogMessage(f"Output SVG size: {svg_width_mm:.2f}mm x {svg_height_mm:.2f}mm.")
    
    svg_content = []

    # 1. SVG Header
    svg_content.append(f"""<svg width="{svg_width_mm}mm" height="{svg_height_mm}mm" viewBox="0 0 {svg_width_mm} {svg_height_mm}" xmlns="http://www.w3.org/2000/svg">""")
    
    # 2. Generate Rectangles
    # Iterate over all pixels
    for y in range(height):
        for x in range(width):
            # Get RGB tuple for the current pixel
            r, g, b = img.getpixel((x, y))
            
            # Determine the color based on the rules
            color = get_closest_color(r, g, b, TARGET_COLORS)
            # Calculate the position of the square in millimeters
            x_mm = x * square_size_mm
            y_mm = y * square_size_mm
            
            # Generate the SVG <rect> element
            rect = (
                f'<rect x="{x_mm:.4f}" y="{y_mm:.4f}" width="{square_size_mm:.4f}" height="{square_size_mm:.4f}" '
                f'fill="{color}" stroke="{color}" stroke-width="{STROKE_WIDTH_MM:.4f}" />'
            )
            svg_content.append(rect)
            lb.add(lightburn.Square(square_size_mm, square_size_mm).layer( TARGET_COLORS[color][1] ).translate(x_mm, y_mm))
            
    # 3. SVG Footer
    svg_content.append("</svg>")
    
    # Write the content to the file
    try:
        with open(output_svg_path, "w") as f:
            f.write("\n".join(svg_content))
        printLogMessage(f"Success! SVG saved to '{output_svg_path}'")
    except Exception as e:
        printLogMessage(f"Error writing SVG file: {e}")

    try:
        lb.write(output_svg_path +".lbrn2")
        printLogMessage(f"Success! lbrn2 saved to "+ output_svg_path +".lbrn2")
    except Exception as e:
        printLogMessage(f"Error writing LightBurn file: {e}")


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
    vectorize = str_to_bool(sys.argv[8]) 
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
    if vectorize:
        #trace_with_palette_mapping(TARGET_COLORS, INPUT_FILE, the_output_file, int(max_dimension))
        raster_to_puzzle_and_lightburn(INPUT_FILE, the_output_file, new_height, new_width, lb, TARGET_COLORS, square_mm)
    else:
        generate_pixel_svg(TARGET_COLORS, INPUT_FILE, the_output_file, square_mm, new_width, new_height)
