"""Compatibility CLI for the modular raster-to-vector pipeline.

Flask continues to execute this filename. All processing lives in
``vector_processing`` and individual modules under ``abstract_filters``.
"""
import json
import os
import sys
from copy import copy

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
    if abstract_filter == "holographic_space":
        abstract_filter = "holographic"
    if image_preset not in vector_processing.PHOTO_TYPE_PRESETS:
        raise SystemExit(f"Unknown image preset: {image_preset}")
    required_setting_names = []
    if abstract_filter == "holographic":
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
        holographic_layer_id = filter_parameters["_setting_layer_id"]
        holographic_layer = next(
            (layer for layer in lb._layers if getattr(layer, "index", None) == holographic_layer_id),
            None,
        )
        if holographic_layer is None:
            raise SystemExit("Holographic Material Library setting was not added to the LightBurn project.")

        fill_mode = str(filter_parameters.get("fill_mode", "from_setting")).strip().lower()
        if fill_mode not in {"from_setting", "fill", "offset_fill"}:
            raise SystemExit("Holographic Fill Mode must be Fill, Offset Fill, or From Setting.")

        # Offset Fill material settings store their individual scan passes as
        # child layers.  The lab uses the first concrete pass; use that same
        # pass for an explicit Offset Fill choice and for From Setting when
        # the chosen library entry is an Offset Fill setting.
        sublayers = getattr(holographic_layer, "subLayers", None) or []
        use_offset_fill = fill_mode == "offset_fill" or (
            fill_mode == "from_setting" and bool(sublayers)
        )
        if use_offset_fill and sublayers:
            scan_layer = copy(sublayers[0])
            scan_layer.index = holographic_layer_id
            scan_layer.name = holographic_layer.name
            scan_layer.materialName = getattr(holographic_layer, "materialName", "")
            scan_layer.entryDesc = getattr(holographic_layer, "entryDesc", "")
            scan_layer.subLayers = []
            lb._layers[lb._layers.index(holographic_layer)] = scan_layer
            holographic_layer = scan_layer

        if use_offset_fill and not sublayers:
            vector_processing.printLogMessage(
                "Holographic Offset Fill requested, but the setting has no sublayer; using its direct settings."
            )
        # The Holographic filter owns the operation mode.  Force Scan/Fill so
        # a library entry saved as Cut/Line still completes as a grating while
        # retaining its compatible power, speed, frequency, and pulse values.
        holographic_layer.type = "Scan"

        # Preserve the selected Fill/Scan setting's interval, angle, power,
        # speed, frequency, pulse width, and passes without adjustment.
        vector_processing.move_lightburn_layer_after(
            lb,
            target_colors["#000000"][1],
            holographic_layer_id,
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
            "selected_material": material_name,
            "palette_names": {metadata[2]: color_hex for color_hex, metadata in target_colors.items()},
            "requested_limit_colors": limit_colors or "all",
            "effective_limit_colors": limit_list,
            "material_library_layers": material_layer_report,
        },
    )


if __name__ == "__main__":
    main()
