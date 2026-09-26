"""Compatibility CLI for the modular raster-to-vector pipeline.

Flask continues to execute this filename. All processing lives in
``vector_processing`` and individual modules under ``abstract_filters``.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed

from PIL import Image

# Support deployment with this file under lib/ and modules either beside it
# or one project directory above it.
MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(MODULE_DIR)
for path in (MODULE_DIR, PROJECT_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

import vector_processing


MAX_STANDARD_PROCESSING_AXIS = 1600
MAX_HIGH_RES_PANEL_PIXELS = 40_000_000


def panel_processing_dimensions(panel_tiling, pixel_mm):
    assembled_width_mm, assembled_height_mm = vector_processing.panel_tiling_dimensions(panel_tiling)
    return (
        max(1, round(assembled_width_mm / pixel_mm)),
        max(1, round(assembled_height_mm / pixel_mm)),
    )


def high_resolution_panel_plan(panel_tiling, pixel_mm):
    """Return bounded per-panel dimensions for an oversized assembled canvas."""
    assembled_width_px, assembled_height_px = panel_processing_dimensions(panel_tiling, pixel_mm)
    tile_width_px = max(1, round(panel_tiling["tile_width_mm"] / pixel_mm))
    tile_height_px = max(1, round(panel_tiling["tile_height_mm"] / pixel_mm))
    if max(tile_width_px, tile_height_px) > MAX_STANDARD_PROCESSING_AXIS:
        raise ValueError(
            "Each high-resolution panel must fit within 1,600 processing pixels on each axis. "
            "Increase Pixel size or use smaller tile dimensions."
        )
    total_tile_pixels = (
        tile_width_px * tile_height_px
        * panel_tiling["columns"] * panel_tiling["rows"]
    )
    if total_tile_pixels > MAX_HIGH_RES_PANEL_PIXELS:
        raise ValueError(
            "This high-resolution panel layout exceeds the 40-million processed-pixel job limit. "
            "Increase Pixel size, reduce the tile count, or use smaller tiles."
        )
    return {
        "assembled_width_px": assembled_width_px,
        "assembled_height_px": assembled_height_px,
        "tile_width_px": tile_width_px,
        "tile_height_px": tile_height_px,
        "total_tile_pixels": total_tile_pixels,
        "oversized": max(assembled_width_px, assembled_height_px) > MAX_STANDARD_PROCESSING_AXIS,
    }


def _extract_single_panel_archive(archive_path, destination, stem):
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        source_svg = "tile-01-r01-c01.svg"
        source_lbrn = f"{source_svg}.lbrn2"
        if source_svg not in names:
            raise ValueError("A high-resolution panel worker did not produce its SVG tile.")
        with archive.open(source_svg) as source, open(os.path.join(destination, f"{stem}.svg"), "wb") as output:
            shutil.copyfileobj(source, output)
        if source_lbrn in names:
            with archive.open(source_lbrn) as source, open(os.path.join(destination, f"{stem}.svg.lbrn2"), "wb") as output:
                shutil.copyfileobj(source, output)


def run_high_resolution_panel_job(argv, panel_tiling, pixel_mm, plan):
    """Render oversized panel layouts as bounded child processes in one task."""
    input_file, output_file = argv[0], argv[1]
    temp_dir = tempfile.mkdtemp(prefix="high-resolution-panels-", dir=os.path.dirname(output_file) or None)
    render_dir = os.path.join(temp_dir, "rendered")
    os.makedirs(render_dir)
    manifest = {
        "format": "mopa-rasterizer-panel-tiles-v2",
        "processing_mode": "independent-high-resolution-panels",
        "layout": panel_tiling,
        "assembled_size_mm": dict(zip(("width", "height"), vector_processing.panel_tiling_dimensions(panel_tiling))),
        "assembled_size_px": {
            "width": plan["assembled_width_px"],
            "height": plan["assembled_height_px"],
        },
        "tile_processing_px": {
            "width": plan["tile_width_px"],
            "height": plan["tile_height_px"],
        },
        "tiles": [],
    }
    workbed_center_x = panel_tiling["workbed_width_mm"] / 2
    workbed_center_y = panel_tiling["workbed_height_mm"] / 2
    workbed_x = workbed_center_x - panel_tiling["tile_width_mm"] / 2
    workbed_y = workbed_center_y - panel_tiling["tile_height_mm"] / 2
    jobs = []
    try:
        with Image.open(input_file) as opened:
            source = opened.convert("RGBA")
        assembled_width_mm, assembled_height_mm = vector_processing.panel_tiling_dimensions(panel_tiling)
        for sequence, (row, column) in enumerate(vector_processing._ordered_panel_tiles(panel_tiling), 1):
            source_x_mm = column * (panel_tiling["tile_width_mm"] + panel_tiling["gap_x_mm"])
            source_y_mm = row * (panel_tiling["tile_height_mm"] + panel_tiling["gap_y_mm"])
            extent = (
                source.width * source_x_mm / assembled_width_mm,
                source.height * source_y_mm / assembled_height_mm,
                source.width * (source_x_mm + panel_tiling["tile_width_mm"]) / assembled_width_mm,
                source.height * (source_y_mm + panel_tiling["tile_height_mm"]) / assembled_height_mm,
            )
            tile_image = source.transform(
                (plan["tile_width_px"], plan["tile_height_px"]),
                Image.Transform.EXTENT,
                extent,
                resample=Image.Resampling.BICUBIC,
            )
            stem = f"tile-{sequence:02d}-r{row + 1:02d}-c{column + 1:02d}"
            tile_input = os.path.join(temp_dir, f"{stem}.png")
            tile_output = os.path.join(render_dir, stem)
            tile_image.save(tile_input, format="PNG")
            child = list(argv)
            child[0] = tile_input
            child[1] = tile_output
            child[3] = str(plan["tile_width_px"])
            child[4] = str(plan["tile_height_px"])
            child_panel = dict(panel_tiling)
            child_panel.update({"columns": 1, "rows": 1, "gap_x_mm": 0, "gap_y_mm": 0})
            while len(child) <= 19:
                child.append("")
            child[17] = "transparency" if child[17] in {"oval", "circle", "transparency"} else child[17]
            child[19] = json.dumps(child_panel, separators=(",", ":"))
            jobs.append((sequence, row, column, stem, source_x_mm, source_y_mm, child))
        del source

        parallelism = max(1, min(int(os.environ.get("RASTER_PANEL_PROCESSES", "2")), 4, len(jobs)))
        print(
            f"High-resolution Panel Tiling: processing {len(jobs)} tiles with "
            f"{parallelism} concurrent panel process(es); assembled canvas is "
            f"{plan['assembled_width_px']}x{plan['assembled_height_px']} pixels.",
            flush=True,
        )

        def render(job):
            *_, child = job
            result = subprocess.run(
                [sys.executable, "-u", os.path.abspath(__file__), *child],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
            return job, result

        completed = {}
        with ThreadPoolExecutor(max_workers=parallelism) as executor:
            futures = [executor.submit(render, job) for job in jobs]
            for future in as_completed(futures):
                job, result = future.result()
                sequence, row, column, stem, source_x_mm, source_y_mm, _ = job
                for line in result.stdout.splitlines():
                    print(f"[{stem}] {line}", flush=True)
                if result.returncode:
                    raise ValueError(
                        f"High-resolution panel {sequence} (row {row + 1}, column {column + 1}) "
                        f"failed with exit code {result.returncode}."
                    )
                child_archive = os.path.join(render_dir, f"{stem}.panel-tiles.zip")
                _extract_single_panel_archive(child_archive, temp_dir, stem)
                completed[sequence] = {
                    "sequence": sequence,
                    "row": row + 1,
                    "column": column + 1,
                    "source_origin_mm": {"x": source_x_mm, "y": source_y_mm},
                    "workbed_center_mm": {"x": workbed_center_x, "y": workbed_center_y},
                    "workbed_origin_mm": {"x": workbed_x, "y": workbed_y},
                    "svg": f"{stem}.svg",
                    "lightburn": f"{stem}.svg.lbrn2" if os.path.exists(os.path.join(temp_dir, f"{stem}.svg.lbrn2")) else None,
                }
        manifest["tiles"] = [completed[index] for index in sorted(completed)]
        with open(os.path.join(temp_dir, "panel-manifest.json"), "w", encoding="utf-8") as output:
            json.dump(manifest, output, indent=2)
        vector_processing._write_panel_assembly_map(os.path.join(temp_dir, "panel-assembly.svg"), panel_tiling)
        assembly_path = f"{output_file}.panel-assembly.svg"
        vector_processing._write_panel_assembly_map(assembly_path, panel_tiling)
        archive_path = f"{output_file}.panel-tiles.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(os.listdir(temp_dir)):
                path = os.path.join(temp_dir, name)
                if os.path.isfile(path):
                    archive.write(path, arcname=name)
        print(f"High-resolution Panel Tiling complete: wrote {archive_path} and {assembly_path}.", flush=True)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


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
            "[SVG_ONLY] [COLOR_MATCHING_JSON] [VALIDATE_ONLY] [GEOMETRY_STYLE] [GEOMETRY_JSON] [CROP_SHAPE] [WHITE_IS] [PANEL_TILING_JSON]"
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
    white_is = argv[18].strip().lower() if len(argv) > 18 else "engraved"
    if white_is not in {"engraved", "unengraved"}:
        user_input_error("Choose whether White is engraved or unengraved")
    panel_tiling = {}
    high_resolution_panel = None
    if len(argv) > 19 and argv[19].strip():
        try:
            panel_tiling = vector_processing.normalize_panel_tiling(json.loads(argv[19]))
        except (json.JSONDecodeError, ValueError) as error:
            user_input_error(f"Invalid Panel Tiling settings: {error}")
    if panel_tiling.get("enabled"):
        try:
            pixel_mm = float(square_mm)
        except (TypeError, ValueError):
            user_input_error("Pixel size must be a number before Panel Tiling can calculate the assembled artwork size")
        try:
            high_resolution_panel = high_resolution_panel_plan(panel_tiling, pixel_mm)
        except ValueError as error:
            user_input_error(error)
        new_width = str(high_resolution_panel["assembled_width_px"])
        new_height = str(high_resolution_panel["assembled_height_px"])
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

    if high_resolution_panel and high_resolution_panel["oversized"]:
        if validate_only:
            try:
                with Image.open(input_file) as source:
                    source.verify()
            except Exception as error:
                user_input_error(f"The high-resolution panel artwork could not be decoded: {error}")
            print(
                "Guest high-resolution panel validation complete; every tile fits the "
                "1,600-pixel per-axis limit and the total workload is within the job budget.",
                flush=True,
            )
            return
        run_high_resolution_panel_job(argv, panel_tiling, float(square_mm), high_resolution_panel)
        return

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
            "white_is": white_is,
            "panel_tiling": panel_tiling,
        },
        export_lightburn=not svg_only,
        geometry_style=geometry_style,
        geometry_style_parameters=geometry_style_parameters,
        crop_shape=crop_shape,
        white_is=white_is,
        panel_tiling=panel_tiling,
    )


if __name__ == "__main__":
    main()
