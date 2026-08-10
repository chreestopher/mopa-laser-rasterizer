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

def str_to_bool(value: str) -> bool:
    # Convert to lowercase and strip whitespace
    clean_val = value.strip().lower()
    
    # Return True if it matches truthy terms
    return clean_val in ("true", "1", "yes", "on", "t")

def resize_to_specific_height_or_width( image, width=0, height=0 ):
    if (height == 0 and width != 0):
        width_percent = float(width) / float(image.size[0])
        new_height = int(float(image.size[1]) * float(width_percent))
        print("resizing image to width: " + str(width) + " height: "+ str(new_height), flush=True)
        resized_img = image.resize((width, int(new_height)), Image.Resampling.LANCZOS)
    elif (width == 0 and height != 0) :
        height_percent = float(height) / float(image.size[1])
        new_width = int(float(image.size[0]) * float(height_percent))
        print("resizing image to width: " + str(new_width) + " height: "+ str(height), flush=True)
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
    print(input_image_path, output_svg_path, square_size_mm, new_width, new_height, flush=True)
    
    try:
        # Load the image and convert to RGB (to ensure consistent 3-channel access)
        img = Image.open(input_image_path).convert("RGB")
    except FileNotFoundError:
        print(f"Error: Input file not found at '{input_image_path}'", flush=True)
        return
    except Exception as e:
        print(f"Error loading image: {e}", flush=True)
        return

    img = resize_to_specific_height_or_width(image=img, height=int(new_height), width=int(new_width))
    width, height = img.size
    
    # Calculate the total SVG dimensions in millimeters
    svg_width_mm = width * square_size_mm
    svg_height_mm = height * square_size_mm
    
    # Constants for the SVG output
    STROKE_WIDTH_MM = 0.01

    print(f"Processing image: {width}x{height} pixels.", flush=True)
    print(f"Output SVG size: {svg_width_mm:.2f}mm x {svg_height_mm:.2f}mm.", flush=True)
    
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
            lb.add(lightburn.Square(square_size_mm, square_size_mm).layer(TARGET_COLORS[color][1]).translate(x_mm, y_mm))
            
    # 3. SVG Footer
    svg_content.append("</svg>")
    
    # Write the content to the file
    try:
        with open(output_svg_path, "w") as f:
            f.write("\n".join(svg_content))
        print(f"Success! SVG saved to '{output_svg_path}'", flush=True)
    except Exception as e:
        print(f"Error writing SVG file: {e}", flush=True)
    try:
        lb.write(output_svg_path +".lbrn2")
        print(f"Success! lbrn2 saved to "+ output_svg_path +".lbrn2", flush=True)
    except Exception as e:
        print(f"Error writing LightBurn file: {e}", flush=True)


def hex_to_rgb(hex_str):
    """Helper to convert #R_G_B or R_G_B hex string to a Numpy RGB tuple."""
    hex_str = hex_str.lstrip('#')
    return tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4))

def rgb_to_hex(rgb):
    """Converts an (R, G, B) tuple to a #RRGGBB hex string."""
    return '#{:02x}{:02x}{:02x}'.format(*rgb)

import re
import cv2
import numpy as np
import potrace
import svgwrite


import cv2
import numpy as np
import potrace
import svgwrite

import cv2
import numpy as np

#region todo: finish faster implementation with numpy arrays
# def trace_with_palette_mapping(
#     TARGET_COLORS, image_path, svg_output_path, MAX_DIMENSION=None
# ):
#     # Setup configuration variables
#     RESIZE_FACTOR = 1.0
#     TURD_SIZE = 10

#     # 1. Load and read image
#     img = cv2.imread(image_path)
#     if img is None:
#         raise FileNotFoundError(f"Could not open or read image: {image_path}")

#     img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
#     orig_h, orig_w, _ = img_rgb.shape
#     target_w, target_h = orig_w, orig_h

#     if RESIZE_FACTOR != 1.0:
#         target_w = int(orig_w * RESIZE_FACTOR)
#         target_h = int(orig_h * RESIZE_FACTOR)
#     if MAX_DIMENSION is not None and max(target_w, target_h) > MAX_DIMENSION:
#         scale = MAX_DIMENSION / float(max(target_w, target_h))
#         target_w = int(target_w * scale)
#         target_h = int(target_h * scale)
#     if (target_w, target_h) != (orig_w, orig_h):
#         print(
#             f"Resizing image from {orig_w}, {orig_h} to {target_w}, {target_h}",
#             flush=True,
#         )
#         img_rgb = cv2.resize(
#             img_rgb, (target_w, target_h), interpolation=cv2.INTER_AREA
#         )
#     else:
#         print(
#             f"Processing image at original dimension {orig_w}, {orig_h}",
#             flush=True,
#         )

#     # 2. Reshape and convert image pixels to float32 for distance math
#     pixels = img_rgb.reshape(-1, 3).astype(np.float32)

#     # Convert TARGET_COLORS list of hex strings into a NumPy array of RGB values
#     # (Replaces old hex_to_rgb loop)
#     target_rgbs = np.array(
#         [[int(h.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)] for h in TARGET_COLORS],
#         dtype=np.float32,
#     )

#     # 3. Vectorized closest color calculation (No loops)
#     # Uses NumPy broadcasting to find the squared Euclidean distance
#     # shape: (num_pixels, 1, 3) - (1, num_colors, 3) -> (num_pixels, num_colors, 3)
#     differences = pixels[:, None, :] - target_rgbs[None, :, :]
#     distances = np.sum(differences**2, axis=2)

#     # Find the index of the closest target color for every pixel
#     closest_color_indices = np.argmin(distances, axis=1)

#     # 4. Map the pixels to the target colors and reconstruct the image
#     flattened_pixels = target_rgbs[closest_color_indices].astype(np.uint8)
#     flattened_img = flattened_pixels.reshape(target_h, target_w, 3)

#     print(
#         f"Color flattening complete. Proceeding with SVG generation...",
#         flush=True,
#     )

#     # 5. Pass flattened_img to your subprocess/SVG tracing tool below
#     # (Insert your potrace/vtracer call or remaining logic here)

#     return flattened_img
#endregion todonew
def trace_with_palette_mapping( TARGET_COLORS, image_path, svg_output_path, MAX_DIMENSION=None ):
    # Setup configuration variables
    RESIZE_FACTOR = 1.0
    TURD_SIZE = 10

    # 1. Load and read image
    img = cv2.imread(image_path)
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    orig_h, orig_w, _ = img_rgb.shape
    target_w, target_h = orig_w, orig_h

    if RESIZE_FACTOR != 1.0:
        target_w = int(orig_w * RESIZE_FACTOR)
        target_h = int(orig_h * RESIZE_FACTOR)
    if MAX_DIMENSION is not None and max(target_w, target_h) > MAX_DIMENSION:
        scale = MAX_DIMENSION / float(max(target_w, target_h))
        target_w = int(target_w * scale)
        target_h = int(target_h * scale)
    if (target_w, target_h) != (orig_w, orig_h):
        print(
            f"Resizing image from {orig_w}, {orig_h} to {target_w}, {target_h}",
            flush=True,
        )
        img_rgb = cv2.resize(
            img_rgb, (target_w, target_h), interpolation=cv2.INTER_AREA
        )
    else:
        print(
            f"Processing image at original dimension {orig_w}, {orig_h}",
            flush=True,
        )

    # 2. Extract unique colors present in the original image to build a cache
    pixels = img_rgb.reshape(-1, 3)
    unique_src_colors = np.unique(pixels, axis=0)

    # 3. Build a fast lookup dictionary using your get_closest_color function
    color_lut = {}
    for color in unique_src_colors:
        src_hex = rgb_to_hex(color)
        src_color = hex_to_rgb(src_hex)
        r, g, b = src_color

        close_color = get_closest_color(r, g, b, TARGET_COLORS)
        target_hex = close_color
        color_lut[tuple(color)] = hex_to_rgb(target_hex)

    # 4. Apply the color mapping to flatten the entire image
    flattened_img = np.zeros_like(img_rgb)
    for src_rgb, target_rgb in color_lut.items():
        mask = (img_rgb == src_rgb).all(axis=-1)
        flattened_img[mask] = target_rgb

    # 5. Initialize SVG canvas
    dwg = svgwrite.Drawing(svg_output_path, size=(target_w, target_h))

    # 6. Extract unique target colors that actually ended up in the flattened image
    final_palette_colors = np.unique(flattened_img.reshape(-1, 3), axis=0)

    # 7. Trace each individual color layer
    for color in final_palette_colors:
        hex_color = "#{:02x}{:02x}{:02x}".format(*color)

        if hex_color.lower() == "#ffffff":
            continue
        init_color = hex_to_rgb(hex_color)
        initr, initg, initb = init_color
        lb_color = get_closest_color(initr, initg, initb, TARGET_COLORS)

        # Create binary mask for this specific allowed palette color
        mask = cv2.inRange(flattened_img, color, color)

        # Use morphology to close tiny gaps created by flattening smooth gradients
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        # Convert the clean mask to a Potrace bitmap
        bitmap = potrace.Bitmap(mask > 0)

        # Trace paths with smooth curves (alphamax=1.0) and ignore noise (turdsize=15)
        path = bitmap.trace(
            turnpolicy=potrace.TURNPOLICY_MINORITY,
            alphamax=1.0,
            turdsize=TURD_SIZE,
        )

        # 8. Build the SVG path string and LightBurn data geometry concurrently
        svg_path_data = ""
        lb_points = []

        for curve in path:
            start = curve.start_point
            svg_path_data += f"M {start[0]:.4f},{start[1]:.4f} "

            # Append the absolute starting position tracking node
            lb_points.append((start[0], start[1]))

            for segment in curve:
                end = segment.end_point

                if segment.is_corner:
                    c = segment.c
                    svg_path_data += (
                        f"L {c[0]:.4f},{c[1]:.4f} L {end[0]:.4f},{end[1]:.4f} "
                    )

                    # Gather corner vector anchors
                    lb_points.append((c[0], c[1]))
                    lb_points.append((end[0], end[1]))
                else:
                    c1 = segment.c1
                    c2 = segment.c2
                    svg_path_data += f"C {c1[0]:.4f},{c1[1]:.4f} {c2[0]:.4f},{c2[1]:.4f} {end[0]:.4f},{end[1]:.4f} "

                    # Interpolate the Bezier curve into straight linear subdivisions for LightBurn path arrays
                    # This ensures curve smoothness without requiring native curve builders
                    STEPS = 12
                    for step in range(1, STEPS + 1):
                        t = step / STEPS
                        # Standard Cubic Bezier mathematical calculation
                        x_t = (
                            (1 - t) ** 3 * start[0]
                            + 3 * (1 - t) ** 2 * t * c1[0]
                            + 3 * (1 - t) * t**2 * c2[0]
                            + t**3 * end[0]
                        )
                        y_t = (
                            (1 - t) ** 3 * start[1]
                            + 3 * (1 - t) ** 2 * t * c1[1]
                            + 3 * (1 - t) * t**2 * c2[1]
                            + t**3 * end[1]
                        )
                        lb_points.append((x_t, y_t))

                # Update the starting node reference for the next consecutive segment tracking loop
                start = end

            svg_path_data += "Z "

        # Write data layers to both vector canvases sequentially
        if svg_path_data:
            # 1. Add path to the standard SVG object canvas instance
            dwg.add(dwg.path(d=svg_path_data, fill=hex_color, stroke="none"))

            # 2. Instantiate LightBurn path cleanly with our compiled coordinate array
            # If your custom lightburn module requires an alternative geometry constructor
            # (like lightburn.Path(d=svg_path_data)), swap this instantiation safely.
            lb_shape = lightburn.Path(lb_points).layer(
                TARGET_COLORS[lb_color][1]
            )
            lb.add(lb_shape)

    try:
        # Save final vector file
        dwg.save()
    except Exception as e:
        print(f"Error writing SVG file: {e}", flush=True)

    print(
        f"Vector tracing complete. Output saved to: {svg_output_path}",
        flush=True,
    )
    try:
        lb.write(svg_output_path + ".lbrn2")
        print(
            f"Success! lbrn2 saved to " + svg_output_path + ".lbrn2",
            flush=True,
        )
    except Exception as e:
        print(f"Error writing LightBurn file: {e}", flush=True)

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
                print(f"added Layer: {item.name}", flush=True)

            else:
                print(f"unable to add layer: {item.name}, name not in lightburn target colors", flush=True)

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
    print(f"\nusing material library settings: {material_library_file}", flush=True)
    print(f"\nusing colors: {the_limit_colors}", flush=True)
    TARGET_COLORS , lb, lightburn = init_lightburn(the_limit_colors)
    TARGET_COLORS['#B4B4B4'] = (0, 8, 'Light-Gray')
    TARGET_COLORS['#000000'] = (0, 0, 'Black')
    if len(the_limit_colors_list) <= 1:
        the_limit_colors_list = [cv[-1].lower() for cn,cv in TARGET_COLORS.items()]
    the_limit_colors_list.append("black")
    the_limit_colors_list.append("light-gray")
    print(f"\nusing TARGET_COLORS: {TARGET_COLORS}", flush=True)
    print(f"\nusing LIMIT COLORS: {','.join(the_limit_colors_list)}", flush=True)

    TARGET_COLORS = parse_material_settings(lb, material_library_file, the_limit_colors_list, TARGET_COLORS)
    if vectorize:
        trace_with_palette_mapping(TARGET_COLORS, INPUT_FILE, f"{OUTPUT_FILE}.vector.svg", int(max_dimension))
    else:
        generate_pixel_svg(TARGET_COLORS, INPUT_FILE, f"{OUTPUT_FILE}.svg", square_mm, new_width, new_height)
