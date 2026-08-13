"""Experimental structural-color calibration-grid exports."""

import importlib.util
import json
import math
import os
import uuid
from copy import copy
from xml.etree import ElementTree as ET

from flask import current_app, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

from . import routes


def _lightburn_module():
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "lib", "lightburn.py")
    spec = importlib.util.spec_from_file_location("holographic_lightburn", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _exact_setting(lightburn, library_path, material_name, description):
    material_key = material_name.strip().casefold()
    description_key = description.strip().casefold()
    settings = lightburn.Lightburn().parse_material_library(library_path)
    for setting in settings:
        if (str(getattr(setting, "materialName", "") or "").strip().casefold() == material_key
                and str(getattr(setting, "entryDesc", "") or "").strip().casefold() == description_key):
            return setting
    raise ValueError(
        "No Material Library setting matched that material name and Description field."
    )


def _svg_grid(path, columns, rows, cell_mm, intervals, angles):
    width, height = columns * cell_mm, rows * cell_mm
    root = ET.Element("svg", xmlns="http://www.w3.org/2000/svg", width=f"{width}mm",
                      height=f"{height}mm", viewBox=f"0 0 {width} {height}")
    ET.SubElement(root, "rect", x="0", y="0", width=str(width), height=str(height), fill="white")
    for index, (interval, angle) in enumerate(zip(intervals, angles)):
        column, row = index % columns, index // columns
        x, y = column * cell_mm, row * cell_mm
        group = ET.SubElement(root, "g", id=f"cell_{index:02d}")
        ET.SubElement(group, "rect", x=str(x), y=str(y), width=str(cell_mm), height=str(cell_mm),
                      fill="none", stroke="#000", **{"stroke-width": ".1"})
        clip_id = f"clip_{index}"
        defs = ET.SubElement(group, "defs")
        clip = ET.SubElement(defs, "clipPath", id=clip_id)
        ET.SubElement(clip, "rect", x=str(x), y=str(y), width=str(cell_mm), height=str(cell_mm))
        lines = ET.SubElement(group, **{"clip-path": f"url(#{clip_id})"})
        radians = math.radians(angle)
        dx, dy = math.cos(radians), math.sin(radians)
        normal_x, normal_y = -dy, dx
        reach = cell_mm * 1.5
        offset = -reach
        while offset <= reach:
            cx, cy = x + cell_mm / 2 + normal_x * offset, y + cell_mm / 2 + normal_y * offset
            ET.SubElement(lines, "line", x1=str(cx - dx * reach), y1=str(cy - dy * reach),
                          x2=str(cx + dx * reach), y2=str(cy + dy * reach), stroke="#000",
                          **{"stroke-width": ".01"})
            offset += interval
        label = f"{index + 1:02d}  {angle:g}deg / {interval:.3f}mm"
        ET.SubElement(group, "text", x=str(x + 1), y=str(y + cell_mm - 1), fill="#000",
                      **{"font-size": "2.2", "font-family": "monospace"}).text = label
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


@routes.route("/holographic-etching/calibration-grid", methods=["POST"])
def calibration_grid():
    library = request.files.get("material_settings")
    material = str(request.form.get("material", "")).strip()
    description = str(request.form.get("setting_description", "")).strip()
    laser_source = str(request.form.get("laser_source", "")).strip()
    if not library or not library.filename or not material or not description:
        return jsonify({"status": "error", "message": "Provide a Material Library, material name, and setting Description."}), 400
    try:
        columns = max(2, min(6, int(request.form.get("columns", 4))))
        rows = max(2, min(6, int(request.form.get("rows", 4))))
        cell_mm = max(4, min(30, float(request.form.get("cell_mm", 12))))
        interval_low = max(.01, min(.5, float(request.form.get("interval_low", .045))))
        interval_high = max(interval_low, min(.5, float(request.form.get("interval_high", .07))))
        lens_field_mm = max(1, min(1000, float(request.form.get("lens_field_mm", 110))))
    except ValueError:
        return jsonify({"status": "error", "message": "Calibration grid dimensions and intervals must be numbers."}), 400

    task_id = str(uuid.uuid4())
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    library_path = os.path.join(upload_folder, f"{task_id}_calibration_{secure_filename(library.filename)}")
    library.save(library_path)
    try:
        lightburn = _lightburn_module()
        base_setting = _exact_setting(lightburn, library_path, material, description)
    except (OSError, ValueError, ET.ParseError) as error:
        return jsonify({"status": "error", "message": str(error)}), 400

    count = columns * rows
    intervals = [interval_low + (interval_high - interval_low) * index / max(count - 1, 1) for index in range(count)]
    angles = [180 * index / max(count - 1, 1) for index in range(count)]
    stem = f"holographic_calibration_{task_id}"
    svg_name, lbrn_name = f"{stem}.svg", f"{stem}.lbrn2"
    _svg_grid(os.path.join(upload_folder, svg_name), columns, rows, cell_mm, intervals, angles)
    project = lightburn.Lightburn()
    for index, (interval, angle) in enumerate(zip(intervals, angles)):
        setting = copy(base_setting)
        setting.index = index
        setting.name = f"Holo {index + 1:02d} {angle:g}deg {interval:.3f}mm"
        setting.interval = interval
        setting.angle = angle
        project.add_layer(setting)
        project.add(lightburn.Square(cell_mm, cell_mm, x=(index % columns) * cell_mm,
                                    y=(index // columns) * cell_mm).layer(index))
    project.write(os.path.join(upload_folder, lbrn_name))
    with open(os.path.join(upload_folder, f"{stem}.json"), "w", encoding="utf-8") as metadata_file:
        json.dump({
            "kind": "holographic_calibration_grid", "material": material,
            "setting_description": description, "laser_source": laser_source,
            "lens_field_of_view_mm": lens_field_mm, "columns": columns, "rows": rows,
            "cell_size_mm": cell_mm, "interval_range_mm": [interval_low, interval_high],
            "angles_degrees": angles, "intervals_mm": intervals,
        }, metadata_file, indent=2)
    return jsonify({"status": "completed", "svg_url": f"/holographic-etching/download/{svg_name}",
                    "lightburn_url": f"/holographic-etching/download/{lbrn_name}"})


@routes.route("/holographic-etching/download/<filename>")
def download_calibration_file(filename):
    if not filename.startswith("holographic_calibration_"):
        return jsonify({"status": "error", "message": "Unknown calibration file."}), 404
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename, as_attachment=True)
