import sys
import os
import importlib.util
import json
from PIL import Image
import colorsys

def resize_to_specific_height_or_width( image, width=0, height=0 ):
    if (height == 0 and width != 0):
        width_percent = float(width) / float(image.size[0])
        new_height = int(float(image.size[1]) * float(width_percent))
        print("resizing image to width: " + str(width) + " height: "+ str(new_height))
        resized_img = image.resize((width, int(new_height)), Image.Resampling.LANCZOS)
    elif (width == 0 and height != 0) :
        height_percent = float(height) / float(image.size[1])
        new_width = int(float(image.size[0]) * float(height_percent))
        print("resizing image to width: " + str(new_width) + " height: "+ str(height))
        resized_img = image.resize((int(new_width),int(height) ), Image.Resampling.LANCZOS)
    else:
        return image
    return resized_img

def get_closest_color(r, g, b):
    """
    Determines the output color based on the input pixel's value (luminance) and hue.
    """
    # 1. Calculate Value (V) for thresholding (using max component for simplicity)
    V = max(r, g, b)

    # 2. Apply Luminance Threshold Rules
    if V < 25:
        return "#000000"  # Black
    
    if (V > 200):
        return "#B4B4B4"  # Light Gray

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
            #print(f"closest hex to {hex_code}: {closest_hex}")
            
    return closest_hex

def generate_pixel_svg(input_image_path, output_svg_path, square_size_mm=0.25, new_width=0, new_height=0):
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
    print(input_image_path, output_svg_path, square_size_mm, new_width, new_height)
    
    try:
        # Load the image and convert to RGB (to ensure consistent 3-channel access)
        img = Image.open(input_image_path).convert("RGB")
    except FileNotFoundError:
        print(f"Error: Input file not found at '{input_image_path}'")
        return
    except Exception as e:
        print(f"Error loading image: {e}")
        return

    img = resize_to_specific_height_or_width(image=img, height=int(new_height), width=int(new_width))
    width, height = img.size
    
    # Calculate the total SVG dimensions in millimeters
    svg_width_mm = width * square_size_mm
    svg_height_mm = height * square_size_mm
    
    # Constants for the SVG output
    STROKE_WIDTH_MM = 0.01

    print(f"Processing image: {width}x{height} pixels.")
    print(f"Output SVG size: {svg_width_mm:.2f}mm x {svg_height_mm:.2f}mm.")
    
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
            color = get_closest_color(r, g, b)
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
        print(f"Success! SVG saved to '{output_svg_path}'")
    except Exception as e:
        print(f"Error writing SVG file: {e}")
    try:
        lb.write(output_svg_path +".lbrn2")
        print(f"Success! lbrn2 saved to "+ output_svg_path +".lbrn2")
    except Exception as e:
        print(f"Error writing LightBurn file: {e}")

def _convert_for_json(o):
    if isinstance(o, dict):
        return {k: _convert_for_json(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_convert_for_json(x) for x in o]
    if hasattr(o, "__dict__"):
        return {k: _convert_for_json(v) for k, v in vars(o).items()}
    if isinstance(o, (str, int, float, bool)) or o is None:
        return o
    return str(o)

def parse_material_settings(material_settings_path):
    new_color_settings = lb.parse_material_library(material_settings_path)

    for item in new_color_settings:
        if item.materialName == "colors - stainless steel":
            item.frequency = int(item.frequency)
            item.name = item.entryDesc
            match item.name.lower():
                case "black-2":
                    item.name = "black"
                    item.index = 0
                    lb.add_layer(item)
                    print(f"added Layer: {item.name}")
                case "blue":
                    item.index = 1
                    lb.add_layer(item)
                    print(f"added Layer: {item.name}")
                case "red":
                    item.index = 2
                    lb.add_layer(item)
                    print(f"added Layer: {item.name}")
                case "green":
                    item.index = 3
                    lb.add_layer(item)
                    print(f"added Layer: {item.name}")
                case "gold": #yellow
                    item.index = 4
                    lb.add_layer(item)
                    print(f"added Layer: {item.name}")
                case "orange":
                    item.index = 5
                    lb.add_layer(item)
                    print(f"added Layer: {item.name}")                    
                case "irridescent-green":
                    print(f"irridescent-green added as cyan with original index {item.index},{vars(item)}")
                    item.index = 6
                    lb.add_layer(item)
                    print(f"added Layer: {item.name}")                    
                case "purple":
                    item.index = 7
                    lb.add_layer(item)
                    print(f"added Layer: {item.name}")
                case "white-2":
                    item.name= "white-2"
                    item.index = 8
                    lb.add_layer(item)
                    print(f"added Layer: {item.name}")
                case "grey":
                    item.name= "light-gray"
                    item.index = 8
                    lb.add_layer(item)
                    print(f"added Layer: {item.name}")
                case "dark-blue":
                    item.name= item.name.lower()
                    item.index = 9
                    lb.add_layer(item)                
                    print(f"added Layer: {item.name}")
                case "dark-red":
                    item.name= item.name.lower()
                    item.index = 10
                    lb.add_layer(item)
                    print(f"added Layer: {item.name}")
                case "green-dark":
                    item.name= "dark-green"
                    item.index = 11
                    lb.add_layer(item)
                    print(f"added Layer: {item.name}")
                case "dark-yellow":
                    item.name= item.name.lower()
                    item.index = 12
                    lb.add_layer(item)
                    print(f"added Layer: {item.name}")
                case "dark-orange":
                    item.name= item.name.lower()
                    item.index = 13
                    lb.add_layer(item)
                    print(f"added Layer: {item.name}")
                case "blue-grey":
                    item.name= "light-blue"
                    item.index = 14
                    lb.add_layer(item)
                    print(f"added Layer: {item.name}")
                case "dark-magenta":
                    item.name= item.name.lower()
                    item.index = 15
                    lb.add_layer(item)
                    print(f"added Layer: {item.name}")
                case "medium-gray":
                    item.name= item.name.lower()
                    item.index = 16
                    lb.add_layer(item)
                    print(f"added Layer: {item.name}")
                case "slate-blue":
                    item.name= item.name.lower()
                    item.index = 17
                    lb.add_layer(item)
                    print(f"added Layer: {item.name}")
                case "rose":
                    item.name= item.name.lower()
                    item.index = 18
                    lb.add_layer(item)
                    print(f"added Layer: {item.name}")
                case "periwinkle-blue":
                    item.name= item.name.lower()
                    item.index = 19
                    lb.add_layer(item)
                    print(f"added Layer: {item.name}")
                case "raspberry":
                    item.name= item.name.lower()
                    item.index = 20
                    lb.add_layer(item)
                    print(f"added Layer: {item.name}")
                case "sage-green":
                    item.name= item.name.lower()
                    item.index = 21
                    lb.add_layer(item)
                    print(f"added Layer: {item.name}")
                case "peach":
                    item.name= item.name.lower()
                    item.index = 22
                    lb.add_layer(item)
                    print(f"added Layer: {item.name}")
                case "pink":
                    item.name= "light-pink"
                    item.index = 23
                    lb.add_layer(item)
                    print(f"added Layer: {item.name}")
                case "orchid-pink":
                    item.name= item.name.lower()
                    item.index = 24
                    lb.add_layer(item)
                    print(f"added Layer: {item.name}")
                case "purple-2":
                    item.name= "deep-purple"
                    item.index = 25
                    lb.add_layer(item)
                    print(f"added Layer: {item.name}")
                case "rust-brown":
                    item.name= item.name.lower()
                    item.index = 26
                    lb.add_layer(item)
                    print(f"added Layer: {item.name}")
                case "teal":
                    item.name= item.name.lower()
                    item.index = 27
                    lb.add_layer(item)
                    print(f"added Layer: {item.name}")    
                case "bright-mint-green":
                    item.name= item.name.lower()
                    item.index = 28
                    lb.add_layer(item)
                    print(f"added Layer: {item.name}")
                case "light-gold":
                    item.name= item.name.lower()
                    item.index = 29
                    lb.add_layer(item)
                    print(f"added Layer: {item.name}")
                case _:
                    print(f"unable to add layer {item.entryDesc}")


# Define the module name and its exact absolute file path
module_name = "lightburn"
file_path = "/app/lib/lightburn.py"

# Create a module spec from the file location
spec = importlib.util.spec_from_file_location(module_name, file_path)
lightburn = importlib.util.module_from_spec(spec)
TARGET_COLORS = {
    '#000000': (0, 0, 'Black'),
    '#0000FF': (240, 1, 'Blue'),
    '#FF0000': (0, 2, 'Red'),
    '#00E000': (120, 3, 'Green'),
    '#D0D000': (60, 4, 'Yellow'),
    '#FF8000': (30, 5, 'Orange'),
    '#00E0E0': (180, 6, 'Cyan'),
    '#FF00FF': (300, 7, 'Magenta'),
    '#B4B4B4': (0, 8, 'Light-Gray'),
    '#0000A0': (240, 9, 'Dark-Blue'),
    '#A00000': (0, 10, 'Dark-Red'),
    '#00A000': (120, 11, 'Dark-Green'),
    '#A0A000': (60, 12, 'Dark-Yellow'),
    '#C08000': (40, 13, 'Dark-Orange'),
    '#00A0FF': (202, 14, 'Light-Blue'),
    '#A000A0': (300, 15, 'Dark-Magenta'),
    '#808080': (0, 16, 'Medium-Gray'),
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
# TARGET_COLORS = {
#     # HEX: HUE (0-360)
#     "#000000": (0, 0, "black"),
#     "#0000FF": (240, 1, "blue"),
#     "#FF0000": (0, 2, "red"),   # Red
#     "#00E000": (120,3, "green"),
#     "#D0D000": (60, 4, "yellow"),
#     "#FF8000": (30, 5, "orange"),
# #    "#C08000": 40, # Dark Orange/Brown
#     "#00E0E0": (150,6, "cyan"),
#     "#FF00FF": (300, 7, "purple"),
#     # "#BB7784": 330, # Rose Pink
#     "#B4B4B4": (1, 8, "light-gray"),
# }
lightburn_indexes = {}
for k, v in TARGET_COLORS.items():
    lightburn_indexes[k]=v[2]

color_settings = {}
# Add it to sys.modules cache and execute the code within the module
sys.modules[module_name] = lightburn
spec.loader.exec_module(lightburn)

# Create the lightburn object
lb = lightburn.Lightburn()


if __name__ == "__main__":
    INPUT_FILE = sys.argv[1]
    OUTPUT_FILE=sys.argv[2]
    square_mm=float(sys.argv[3])
    new_width=sys.argv[4]
    new_height=sys.argv[5]
    material_library_file=sys.argv[6]
    print(f"using material library settings: {material_library_file}")
    parse_material_settings(material_library_file)
    generate_pixel_svg(INPUT_FILE, OUTPUT_FILE, square_mm, new_width, new_height)


