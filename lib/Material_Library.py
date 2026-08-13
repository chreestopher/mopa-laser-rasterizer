"""Compatibility CLI for the modular raster-to-vector pipeline.

Flask continues to execute this filename. All processing lives in
``vector_processing`` and individual modules under ``abstract_filters``.
"""
import json
import os
import sys

# Support deployment with this file under lib/ and modules either beside it
# or one project directory above it.
MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(MODULE_DIR)
for path in (MODULE_DIR, PROJECT_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

import vector_processing


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 9:
        raise SystemExit(
            "Usage: Material_Library.py INPUT OUTPUT PIXEL_MM WIDTH HEIGHT "
            "MATERIAL_LIBRARY COLORS PRESET FILTER [FILTER_JSON]"
        )

    (input_file, output_file, square_mm, new_width, new_height,
     material_library_file, limit_colors, image_preset, abstract_filter) = argv[:9]
    new_width = new_width.strip() or "0"
    new_height = new_height.strip() or "0"
    filter_parameters = {}
    if len(argv) > 9 and argv[9].strip():
        try:
            filter_parameters = json.loads(argv[9])
            if not isinstance(filter_parameters, dict):
                raise ValueError("filter parameters must be a JSON object")
        except (json.JSONDecodeError, ValueError) as error:
            raise SystemExit(f"Invalid abstract filter parameters: {error}")

    if image_preset.startswith("abstract_"):
        abstract_filter = image_preset.removeprefix("abstract_")
        image_preset = "abstract"
    if image_preset not in vector_processing.PHOTO_TYPE_PRESETS:
        raise SystemExit(f"Unknown image preset: {image_preset}")
    preset = vector_processing.PHOTO_TYPE_PRESETS[image_preset]
    vector_processing.image_preset = image_preset

    limit_list = [item.strip() for item in limit_colors.split(",") if item.strip()]
    target_colors, lb, lightburn_module = vector_processing.init_lightburn(limit_colors)
    # Keep the exporter dependency explicit at the compatibility boundary.
    # init_lightburn also registers it internally for direct API callers.
    vector_processing.lightburn = lightburn_module
    target_colors["#B4B4B4"] = (0, 8, "Light-Gray")
    target_colors["#000000"] = (0, 0, "Black")
    if len(limit_list) <= 1:
        limit_list = [value[-1].lower() for value in target_colors.values()]
    limit_list.extend(("black", "light-gray"))
    material_layer_report = {"loaded": [], "skipped": []}
    target_colors = vector_processing.parse_material_settings(
        lb,
        material_library_file,
        limit_list,
        target_colors,
        material_layer_report=material_layer_report,
    )

    vector_settings = dict(preset)
    for name in ("min_island_area", "simplification_factor", "smoothing_radius"):
        if name in filter_parameters:
            vector_settings[name] = filter_parameters[name]

    vector_processing.raster_to_puzzle_and_lightburn(
        raster_image_path=input_file,
        output_svg_path=f"{output_file}.vector.svg",
        new_height=new_height,
        new_width=new_width,
        lb_project_instance=lb,
        TARGET_COLORS=target_colors,
        scale_factor=float(square_mm),
        ignore_background_hex="#ffffff",
        quantize_colors=vector_settings["quantize_colors"],
        min_island_area=vector_settings["min_island_area"],
        simplification_factor=vector_settings["simplification_factor"],
        smoothing_radius=vector_settings["smoothing_radius"],
        image_preset=image_preset,
        abstract_filter=abstract_filter,
        filter_parameters=filter_parameters,
        job_settings={
            "image_preset": image_preset,
            "preset_settings": vector_settings,
            "material_library_path": material_library_file,
            "requested_limit_colors": limit_colors or "all",
            "effective_limit_colors": limit_list,
            "material_library_layers": material_layer_report,
        },
    )


if __name__ == "__main__":
    main()
