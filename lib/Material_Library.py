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
    if len(argv) < 10:
        raise SystemExit(
            "Usage: Material_Library.py INPUT OUTPUT PIXEL_MM WIDTH HEIGHT "
            "MATERIAL_LIBRARY MATERIAL COLORS PRESET FILTER [FILTER_JSON] [PALETTE_NAMES_JSON]"
        )

    (input_file, output_file, square_mm, new_width, new_height,
     material_library_file, material_name, limit_colors, image_preset, abstract_filter) = argv[:10]
    new_width = new_width.strip() or "0"
    new_height = new_height.strip() or "0"
    filter_parameters = {}
    color_name_overrides = {}
    if len(argv) > 10 and argv[10].strip():
        try:
            filter_parameters = json.loads(argv[10])
            if not isinstance(filter_parameters, dict):
                raise ValueError("filter parameters must be a JSON object")
        except (json.JSONDecodeError, ValueError) as error:
            raise SystemExit(f"Invalid abstract filter parameters: {error}")
    if len(argv) > 11 and argv[11].strip():
        try:
            color_name_overrides = json.loads(argv[11])
            if not isinstance(color_name_overrides, dict):
                raise ValueError("palette names must be a JSON object")
        except (json.JSONDecodeError, ValueError) as error:
            raise SystemExit(f"Invalid palette names: {error}")

    if image_preset.startswith("abstract_"):
        abstract_filter = image_preset.removeprefix("abstract_")
        image_preset = "abstract"
    if image_preset not in vector_processing.PHOTO_TYPE_PRESETS:
        raise SystemExit(f"Unknown image preset: {image_preset}")
    required_setting_names = []
    if abstract_filter == "holographic_space":
        required_setting_names.append(str(filter_parameters.get("setting_name", "holographic")).strip())
    preset = vector_processing.PHOTO_TYPE_PRESETS[image_preset]
    vector_processing.image_preset = image_preset

    limit_list = [item.strip() for item in limit_colors.split(",") if item.strip()]
    target_colors, lb, lightburn_module = vector_processing.init_lightburn(
        limit_colors, color_name_overrides=color_name_overrides
    )
    # Keep the exporter dependency explicit at the compatibility boundary.
    # init_lightburn also registers it internally for direct API callers.
    vector_processing.lightburn = lightburn_module
    if len(limit_list) <= 1:
        limit_list = [value[-1].lower() for value in target_colors.values()]
    limit_list.extend(("black", "light-gray"))
    material_layer_report = {"loaded": [], "skipped": []}
    try:
        target_colors, filter_setting_layers = vector_processing.parse_material_settings(
            lb,
            material_library_file,
            limit_list,
            target_colors,
            material_name=material_name,
            material_layer_report=material_layer_report,
            required_setting_names=required_setting_names,
            return_setting_layers=True,
        )
    except ValueError as error:
        # A missing material is an expected user-input error.  The parser has
        # already emitted the useful material list, so avoid adding a Python
        # traceback to the task console.
        raise SystemExit(str(error))
    if required_setting_names:
        filter_parameters["_setting_layer_id"] = filter_setting_layers[required_setting_names[0].casefold()]

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
            "selected_material": material_name,
            "palette_names": {metadata[2]: color_hex for color_hex, metadata in target_colors.items()},
            "requested_limit_colors": limit_colors or "all",
            "effective_limit_colors": limit_list,
            "material_library_layers": material_layer_report,
        },
    )


if __name__ == "__main__":
    main()
