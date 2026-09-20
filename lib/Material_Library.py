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


def user_input_error(message):
    """Give the worker a distinct exit code without changing the visible error line."""
    print(str(message), file=sys.stderr, flush=True)
    raise SystemExit(2)


def selected_material_color_names(limit_colors, target_colors):
    """Keep the submitted swatch set exact, including one-swatch jobs."""
    selected = [item.strip() for item in str(limit_colors or "").split(",") if item.strip()]
    if selected:
        return selected
    return [metadata[2] for metadata in target_colors.values()]


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 10:
        user_input_error(
            "Usage: Material_Library.py INPUT OUTPUT PIXEL_MM WIDTH HEIGHT "
            "MATERIAL_LIBRARY MATERIAL COLORS PRESET FILTER [FILTER_JSON] [PALETTE_NAMES_JSON] "
            "[SVG_ONLY] [COLOR_MATCHING_JSON] [VALIDATE_ONLY] [GEOMETRY_STYLE] [GEOMETRY_JSON] [CROP_SHAPE]"
        )

    (input_file, output_file, square_mm, new_width, new_height,
     material_library_file, material_name, limit_colors, image_preset, abstract_filter) = argv[:10]
    new_width = new_width.strip() or "0"
    new_height = new_height.strip() or "0"
    filter_parameters = {}
    color_name_overrides = {}
    color_matching = {}
    geometry_style = argv[15].strip().lower() if len(argv) > 15 and argv[15].strip() else "vectors"
    geometry_style_parameters = {}
    crop_shape = argv[17].strip().lower() if len(argv) > 17 else ""
    if crop_shape not in {"", "rectangle", "square", "oval", "circle", "transparency"}:
        user_input_error("Invalid artwork crop shape")
    svg_only = len(argv) > 12 and argv[12].strip().lower() in ("true", "1", "yes", "on")
    # Accept the former argv[13]=validate-only layout for compatibility while
    # reserving argv[13] for the new, independent color-matching object.
    legacy_validate_arg = len(argv) > 13 and argv[13].strip().lower() in ("true", "1", "yes", "on")
    validate_only = legacy_validate_arg or (
        len(argv) > 14 and argv[14].strip().lower() in ("true", "1", "yes", "on")
    )
    if len(argv) > 10 and argv[10].strip():
        try:
            filter_parameters = json.loads(argv[10])
            if not isinstance(filter_parameters, dict):
                raise ValueError("filter parameters must be a JSON object")
        except (json.JSONDecodeError, ValueError) as error:
            user_input_error(f"Invalid abstract filter parameters: {error}")
    if len(argv) > 11 and argv[11].strip():
        try:
            color_name_overrides = json.loads(argv[11])
            if not isinstance(color_name_overrides, dict):
                raise ValueError("palette names must be a JSON object")
        except (json.JSONDecodeError, ValueError) as error:
            user_input_error(f"Invalid palette names: {error}")
    if len(argv) > 13 and argv[13].strip() and not legacy_validate_arg:
        try:
            color_matching = json.loads(argv[13])
            if not isinstance(color_matching, dict):
                raise ValueError("color matching settings must be a JSON object")
        except (json.JSONDecodeError, ValueError) as error:
            user_input_error(f"Invalid color matching settings: {error}")
    if len(argv) > 16 and argv[16].strip():
        try:
            geometry_style_parameters = json.loads(argv[16])
            if not isinstance(geometry_style_parameters, dict):
                raise ValueError("geometry style parameters must be a JSON object")
        except (json.JSONDecodeError, ValueError) as error:
            user_input_error(f"Invalid geometry style parameters: {error}")

    if image_preset.startswith("abstract_"):
        abstract_filter = image_preset.removeprefix("abstract_")
        image_preset = "abstract"
    if image_preset not in vector_processing.PHOTO_TYPE_PRESETS:
        user_input_error(f"Unknown image preset: {image_preset}")
    preset = vector_processing.PHOTO_TYPE_PRESETS[image_preset]
    vector_processing.image_preset = image_preset

    target_colors, lb, lightburn_module = vector_processing.init_lightburn(
        limit_colors, color_name_overrides=color_name_overrides
    )
    # Keep the exporter dependency explicit at the compatibility boundary.
    # init_lightburn also registers it internally for direct API callers.
    vector_processing.lightburn = lightburn_module
    limit_list = selected_material_color_names(limit_colors, target_colors)
    material_layer_report = {"loaded": [], "skipped": []}
    filter_module = vector_processing.ABSTRACT_FILTER_MODULES.get(abstract_filter)
    try:
        geometry_style, geometry_style_parameters = vector_processing.geometry_styles.normalize(
            geometry_style, geometry_style_parameters, abstract_filter
        )
    except ValueError as error:
        user_input_error(error)
    geometry_module = vector_processing.geometry_styles.module_for_style(geometry_style)
    routed_styles = vector_processing.geometry_styles.assigned_styles(
        geometry_style, geometry_style_parameters
    )
    routed_krasnow = (
        vector_processing.geometry_styles.KRASNOW_STYLE in routed_styles
        and geometry_style == vector_processing.geometry_styles.ROUTED_STYLE
    )
    setting_module = (
        vector_processing.geometry_styles.module_for_style(
            vector_processing.geometry_styles.KRASNOW_STYLE
        )
        if routed_krasnow
        else geometry_module
        if getattr(geometry_module, "SETTING_NAME", None)
        else filter_module
    )
    setting_parameters = (
        vector_processing.geometry_styles.parameters_for_style(
            geometry_style,
            geometry_style_parameters,
            vector_processing.geometry_styles.KRASNOW_STYLE,
        )
        if routed_krasnow
        else geometry_style_parameters if setting_module is geometry_module
        else filter_parameters
    )
    required_setting = getattr(setting_module, "SETTING_NAME", None)
    required_setting_aliases = (
        {required_setting: tuple(getattr(setting_module, "SETTING_ALIASES", ()))}
        if required_setting
        else {}
    )
    if svg_only:
        filter_setting_layers = {}
        material_layer_report.update({"mode": "svg_only", "loaded": [], "skipped": []})
        print("SVG-only mode: using the complete default Rasterizer palette; Material Library loading is skipped.", flush=True)
    else:
        try:
            target_colors, filter_setting_layers = vector_processing.parse_material_settings(
                lb,
                material_library_file,
                limit_list,
                target_colors,
                material_name=material_name,
                material_layer_report=material_layer_report,
                required_setting_names=[required_setting] if required_setting else [],
                required_setting_aliases=required_setting_aliases,
                return_setting_layers=True,
            )
        except ValueError as error:
            # A missing material is an expected user-input error.  The parser has
            # already emitted the useful material list, so avoid adding a Python
            # traceback to the task console.
            user_input_error(error)
    if required_setting and not svg_only:
        setting_layer_id = filter_setting_layers[required_setting.casefold()]
        setting_parameters["_setting_layer_id"] = setting_layer_id
        if routed_krasnow:
            geometry_style_parameters[
                vector_processing.geometry_styles.KRASNOW_STYLE
            ]["_setting_layer_id"] = setting_layer_id
        if not bool(
            getattr(setting_module, "REPLICATE_SETTING_TO_OUTPUT_LAYERS", False)
        ):
            layer_color = getattr(setting_module, "LAYER_COLOR", "#FEFEFE").upper()
            layer_name = getattr(setting_module, "LAYER_NAME", required_setting)
            target_colors[layer_color] = (0, setting_layer_id, layer_name)
            vector_processing.NON_IMAGE_SWATCHES.add(layer_color)
            for layer in getattr(lb, "_layers", []):
                if getattr(layer, "index", None) == setting_layer_id:
                    layer.name = layer_name
                    break

    configure_output_layers = getattr(setting_module, "configure_output_layers", None)
    if callable(configure_output_layers) and not svg_only:
        try:
            output_target_colors = (
                vector_processing.geometry_styles.target_colors_for_style(
                    target_colors,
                    geometry_style_parameters,
                    vector_processing.geometry_styles.KRASNOW_STYLE,
                )
                if routed_krasnow
                else target_colors
            )
            configure_output_layers(lb, output_target_colors, setting_parameters)
        except ValueError as error:
            user_input_error(error)

    vector_settings = dict(preset)
    vector_settings.update(getattr(filter_module, "VECTOR_DEFAULTS", {}))
    vector_settings.update(getattr(geometry_module, "VECTOR_DEFAULTS", {}))
    vector_settings.update(
        vector_processing.geometry_styles.vector_settings_for_style(
            geometry_style, geometry_style_parameters
        )
    )
    for name in ("min_island_area", "simplification_factor", "smoothing_radius"):
        if name in filter_parameters:
            vector_settings[name] = filter_parameters[name]

    if validate_only:
        # Exercise the same image decoding, dimension handling, palette setup,
        # Material Library parsing, and filter-setting validation as a real run,
        # but stop before expensive geometry construction. Guest quota is claimed
        # only after this exits successfully.
        vector_processing.prepare_raster_image(
            raster_image_path=input_file,
            new_height=new_height,
            new_width=new_width,
            quantize_colors=vector_settings["quantize_colors"],
            target_colors=target_colors,
            color_matching=color_matching,
        )
        float(square_mm)
        print("Guest input validation complete; processing may begin.", flush=True)
        return

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
        color_matching=color_matching,
        job_settings={
            "image_preset": image_preset,
            "preset_settings": vector_settings,
            "material_library_path": material_library_file,
            "selected_material": material_name,
            "palette_names": {metadata[2]: color_hex for color_hex, metadata in target_colors.items()},
            "requested_limit_colors": limit_colors or "all",
            "effective_limit_colors": limit_list,
            "material_library_layers": material_layer_report,
            "artwork_crop_shape": crop_shape or "none",
        },
        export_lightburn=not svg_only,
        geometry_style=geometry_style,
        geometry_style_parameters=geometry_style_parameters,
        crop_shape=crop_shape,
    )


if __name__ == "__main__":
    main()
