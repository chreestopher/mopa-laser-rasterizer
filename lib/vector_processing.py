import math
import xml.etree.ElementTree as ET
from collections import defaultdict

from PIL import Image

from shapely.geometry import box, MultiPoint
from shapely.ops import unary_union, transform, voronoi_diagram
from shapely.affinity import affine_transform, scale
import lightburn

from datetime import datetime 
def printLogMessage(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)

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
    ignore_background_hex
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
            if closest_hex == black_hex:
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


# ============================================================================
# ABSTRACT FILTERS
# ============================================================================

def apply_wave_filter(geometry):
    """
    Apply the original wavy fluid distortion.
    """

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

    return transform(
        wave_transform,
        geometry
    )


def apply_voronoi_filter(geometry):
    """
    Apply the original cellular/Voronoi sharding effect.
    """

    bounds = geometry.bounds

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

        return geometry.intersection(vd)

    return geometry


def apply_shear_filter(geometry):
    """
    Apply the original directional perspective shear/glitch skew.
    """

    return affine_transform(
        geometry,
        [
            1.0,
            0.5,
            0.0,
            0.8,
            0.0,
            0.0
        ]
    )


def apply_abstract_filter(
    geometry,
    abstract_filter
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
        or image_preset != "abstract"
    ):
        return geometry

    filter_name = str(
        abstract_filter
    ).lower()

    if filter_name == "wave":

        return apply_wave_filter(
            geometry
        )

    if filter_name == "voronoi":

        return apply_voronoi_filter(
            geometry
        )

    if filter_name == "shear":

        return apply_shear_filter(
            geometry
        )

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
    abstract_filter
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

    final_geometry = apply_abstract_filter(
        final_geometry,
        abstract_filter
    )

    return final_geometry


def process_color_layers(
    pixel_boxes_by_color,
    target_colors,
    min_island_area,
    simplification_factor,
    smoothing_radius,
    abstract_filter
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
            abstract_filter=abstract_filter
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
    abstract_filter
):
    """
    Build the black layer as the canvas minus all colored geometry.

    This is the critical zero-overlap operation:

        BLACK = CANVAS - ALL COLORED GEOMETRY
    """

    canvas_frame = box(
        0,
        0,
        width,
        height
    )

    # Apply the same abstract transformation that the original
    # function applied to the black canvas.
    canvas_frame = apply_abstract_filter(
        canvas_frame,
        abstract_filter
    )

    colored_geometries = [
        geometry
        for color_hex, geometry
        in processed_layers.items()
        if (
            color_hex != black_hex
            and not geometry.is_empty
        )
    ]

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

    # Combine all colored geometry into one geometry.
    all_colored_geometry = unary_union(
        colored_geometries
    )

    # THE IMPORTANT OPERATION:
    #
    # Remove every colored shape from the black canvas.
    #
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

    elif geometry.geom_type in (
        "MultiPolygon",
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

    elif geometry.geom_type in (
        "MultiPolygon",
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
    abstract_filter=None
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

    # =========================================================================
    # 4. Convert pixels into color geometry buckets
    # =========================================================================

    pixel_boxes_by_color = (
        classify_raster_pixels(
            img=img,
            target_colors=TARGET_COLORS,
            black_hex=black_hex,
            ignore_background_hex=ignore_background_hex
        )
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
        abstract_filter=abstract_filter
    )

    # =========================================================================
    # 6. Build the BLACK layer around the colored geometry
    # =========================================================================

    processed_layers[
        black_hex
    ] = build_punched_black_layer(
        width=width,
        height=height,
        processed_layers=processed_layers,
        black_hex=black_hex,
        abstract_filter=abstract_filter
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
