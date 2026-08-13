"""Experimental structural-color calibration-grid exports."""

import importlib.util
import json
import math
import os
import sys
import uuid
from copy import copy
from xml.etree import ElementTree as ET

import cv2
import numpy as np
from flask import current_app, jsonify, request, send_from_directory
from PIL import Image, UnidentifiedImageError
from werkzeug.utils import secure_filename

from . import routes


def _lightburn_module():
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "lib", "lightburn.py")
    spec = importlib.util.spec_from_file_location("holographic_lightburn", path)
    module = importlib.util.module_from_spec(spec)
    # The LightBurn writer defines dataclasses, which require their module to
    # be registered before execution.
    sys.modules[spec.name] = module
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


def _calibration_base_layer(setting):
    """Use one concrete scan layer from a multi-sublayer library entry.

    LightBurn stores Offset Fill settings as child cut settings.  A diffraction
    grid needs one unambiguous starting layer, so select the first child in the
    order the Material Library defines it.
    """
    sublayers = getattr(setting, "subLayers", None) or []
    if not sublayers:
        return setting

    selected = copy(sublayers[0])
    # Keep the selected library entry identifiable in the exported project and
    # metadata, while deliberately leaving the remaining Offset Fill children
    # out of the calibration export.
    selected.materialName = getattr(setting, "materialName", "")
    selected.entryDesc = getattr(setting, "entryDesc", "")
    selected.subLayers = []
    return selected


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
        # Keep the grating lines clipped inside their own calibration cell.
        # ``SubElement`` needs an element name as well as its attributes.
        lines = ET.SubElement(group, "g", **{"clip-path": f"url(#{clip_id})"})
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


def _calibration_metadata_path(upload_folder, calibration_id):
    """Return the known metadata path for a calibration grid identifier."""
    if not calibration_id or any(character not in "0123456789abcdef-" for character in calibration_id.lower()):
        raise ValueError("Choose a calibration grid created by this lab.")
    return os.path.join(upload_folder, f"holographic_calibration_{calibration_id}.json")


def _profile_metadata_path(upload_folder, profile_id):
    if not profile_id or any(character not in "0123456789abcdef-" for character in profile_id.lower()):
        raise ValueError("Choose a calibration profile created by this lab.")
    return os.path.join(upload_folder, f"holographic_profile_{profile_id}.json")


def _order_corners(points):
    """Order four points as top-left, top-right, bottom-right, bottom-left."""
    points = np.asarray(points, dtype=np.float32).reshape(4, 2)
    sums = points.sum(axis=1)
    differences = np.diff(points, axis=1).reshape(-1)
    return np.array([
        points[np.argmin(sums)], points[np.argmin(differences)],
        points[np.argmax(sums)], points[np.argmax(differences)],
    ], dtype=np.float32)


def _rectify_grid(photo):
    """Find the largest rectangular candidate and return a bird's-eye grid view.

    This is a deliberately conservative first pass.  When a clear border cannot
    be found, the original image is retained and marked for manual crop support
    rather than pretending an unreliable perspective correction succeeded.
    """
    height, width = photo.shape[:2]
    working = cv2.resize(photo, (1200, max(1, round(height * 1200 / width)))) if width > 1200 else photo.copy()
    scale_x, scale_y = width / working.shape[1], height / working.shape[0]
    gray = cv2.cvtColor(working, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 45, 140)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    candidates = []
    for contour in cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)[0]:
        area = cv2.contourArea(contour)
        if area < working.shape[0] * working.shape[1] * .06:
            continue
        polygon = cv2.approxPolyDP(contour, .025 * cv2.arcLength(contour, True), True)
        if len(polygon) == 4 and cv2.isContourConvex(polygon):
            candidates.append((area, polygon.reshape(4, 2)))
    if not candidates:
        return photo, "not_found", None

    _, corners = max(candidates, key=lambda candidate: candidate[0])
    corners = _order_corners(corners * np.array([scale_x, scale_y], dtype=np.float32))
    top = np.linalg.norm(corners[1] - corners[0])
    bottom = np.linalg.norm(corners[2] - corners[3])
    left = np.linalg.norm(corners[3] - corners[0])
    right = np.linalg.norm(corners[2] - corners[1])
    target_width, target_height = max(300, round(max(top, bottom))), max(300, round(max(left, right)))
    destination = np.array([[0, 0], [target_width - 1, 0], [target_width - 1, target_height - 1], [0, target_height - 1]], dtype=np.float32)
    return cv2.warpPerspective(photo, cv2.getPerspectiveTransform(corners, destination), (target_width, target_height)), "rectified", corners.tolist()


def _rotate_image(image, degrees):
    """Rotate without clipping the calibration sheet's corners."""
    if not degrees:
        return image
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), degrees, 1)
    cosine, sine = abs(matrix[0, 0]), abs(matrix[0, 1])
    rotated_width = round(height * sine + width * cosine)
    rotated_height = round(height * cosine + width * sine)
    matrix[0, 2] += rotated_width / 2 - width / 2
    matrix[1, 2] += rotated_height / 2 - height / 2
    return cv2.warpAffine(image, matrix, (rotated_width, rotated_height), borderMode=cv2.BORDER_REPLICATE)


def _measure_grid_photo(photo_path, grid, rotation_degrees=0):
    photo = cv2.imread(photo_path, cv2.IMREAD_COLOR)
    if photo is None:
        raise ValueError("The saved grid photo could not be opened for analysis.")
    photo = _rotate_image(photo, rotation_degrees)
    rectified, correction, corners = _rectify_grid(photo)
    rows, columns = int(grid["rows"]), int(grid["columns"])
    height, width = rectified.shape[:2]
    intervals, angles = grid["intervals_mm"], grid["angles_degrees"]
    cells = []
    preview = rectified.copy()
    for index in range(rows * columns):
        row, column = divmod(index, columns)
        x0, x1 = round(column * width / columns), round((column + 1) * width / columns)
        y0, y1 = round(row * height / rows), round((row + 1) * height / rows)
        # Avoid the engraved border and label, which are not representative of
        # the cell's structural color.
        pad_x, pad_y = max(1, round((x1 - x0) * .22)), max(1, round((y1 - y0) * .25))
        sample = rectified[y0 + pad_y:y1 - pad_y, x0 + pad_x:x1 - pad_x]
        if sample.size == 0:
            raise ValueError("The detected grid is too small to sample reliably.")
        median_bgr = np.median(sample.reshape(-1, 3), axis=0).astype(np.uint8)
        median_rgb = [int(median_bgr[2]), int(median_bgr[1]), int(median_bgr[0])]
        median_hsv = cv2.cvtColor(np.uint8([[median_bgr]]), cv2.COLOR_BGR2HSV)[0, 0]
        cells.append({
            "index": index + 1, "row": row + 1, "column": column + 1,
            "interval_mm": intervals[index], "angle_degrees": angles[index],
            "observed_rgb": median_rgb,
            "observed_hex": "#{:02X}{:02X}{:02X}".format(*median_rgb),
            "observed_hsv_opencv": [int(value) for value in median_hsv],
        })
        cv2.rectangle(preview, (x0, y0), (x1, y1), (40, 240, 135), 2)
        cv2.putText(preview, str(index + 1), (x0 + 8, y0 + 25), cv2.FONT_HERSHEY_SIMPLEX, .75, (40, 240, 135), 2, cv2.LINE_AA)
    return cells, preview, correction, corners


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
        matched_setting = _exact_setting(lightburn, library_path, material, description)
        base_setting = _calibration_base_layer(matched_setting)
        if base_setting is not matched_setting:
            current_app.logger.info(
                "Holographic calibration: using the first of %s sublayers for '%s'.",
                len(matched_setting.subLayers),
                description,
            )
    except (OSError, ValueError, ET.ParseError) as error:
        return jsonify({"status": "error", "message": str(error)}), 400

    count = columns * rows
    intervals = [interval_low + (interval_high - interval_low) * index / max(count - 1, 1) for index in range(count)]
    angles = [180 * index / max(count - 1, 1) for index in range(count)]
    stem = f"holographic_calibration_{task_id}"
    svg_name, lbrn_name = f"{stem}.svg", f"{stem}.lbrn2"
    try:
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
    except Exception as error:
        current_app.logger.exception("Holographic calibration-grid export failed")
        return jsonify({
            "status": "error",
            "message": f"Could not build the calibration grid: {error}",
        }), 500
    return jsonify({"status": "completed", "calibration_id": task_id,
                    "svg_url": f"/holographic-etching/download/{svg_name}",
                    "lightburn_url": f"/holographic-etching/download/{lbrn_name}"})


@routes.route("/holographic-etching/calibration-profile", methods=["POST"])
def save_calibration_profile():
    """Store the captured grid photograph and its measurement context.

    Image analysis is intentionally not performed here yet.  Saving the exact
    source grid, photograph, and viewing conditions gives the later analyzer a
    stable, self-contained calibration record to work from.
    """
    photo = request.files.get("grid_photo")
    calibration_id = str(request.form.get("calibration_id", "")).strip()
    profile_name = str(request.form.get("profile_name", "")).strip()
    if not photo or not photo.filename or not calibration_id or not profile_name:
        return jsonify({"status": "error", "message": "Provide a grid photo, calibration grid ID, and profile name."}), 400

    upload_folder = current_app.config["UPLOAD_FOLDER"]
    try:
        grid_metadata_path = _calibration_metadata_path(upload_folder, calibration_id)
        with open(grid_metadata_path, encoding="utf-8") as metadata_file:
            grid_metadata = json.load(metadata_file)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return jsonify({"status": "error", "message": f"Calibration grid could not be found: {error}"}), 404

    try:
        photo_image = Image.open(photo.stream)
        photo_image.verify()
        photo.stream.seek(0)
    except (UnidentifiedImageError, OSError):
        return jsonify({"status": "error", "message": "Upload a readable image of the finished grid, such as a JPG or PNG."}), 400

    profile_id = str(uuid.uuid4())
    extension = os.path.splitext(secure_filename(photo.filename))[1].lower() or ".image"
    photo_name = f"holographic_profile_{profile_id}_grid{extension}"
    profile_name_on_disk = f"holographic_profile_{profile_id}.json"
    photo.save(os.path.join(upload_folder, photo_name))
    profile = {
        "kind": "holographic_calibration_profile",
        "status": "awaiting_analysis",
        "profile_id": profile_id,
        "profile_name": profile_name,
        "grid_photo": photo_name,
        "grid_calibration_id": calibration_id,
        "grid": grid_metadata,
        "capture": {
            "phone_or_camera": str(request.form.get("camera", "")).strip(),
            "camera_distance_mm": str(request.form.get("distance_mm", "")).strip(),
            "viewing_angle_degrees": str(request.form.get("viewing_angle", "")).strip(),
            "lighting": str(request.form.get("lighting", "")).strip(),
            "notes": str(request.form.get("capture_notes", "")).strip(),
        },
        "analysis": {
            "state": "pending",
            "message": "Ready for grid-photo measurement.",
            "cells": [],
        },
    }
    with open(os.path.join(upload_folder, profile_name_on_disk), "w", encoding="utf-8") as profile_file:
        json.dump(profile, profile_file, indent=2)
    current_app.logger.info("Saved holographic calibration profile %s from grid %s.", profile_id, calibration_id)
    return jsonify({
        "status": "saved",
        "profile_id": profile_id,
        "profile_url": f"/holographic-etching/download/{profile_name_on_disk}",
        "message": "Calibration photo and conditions saved. It is ready for measurement.",
    })


@routes.route("/holographic-etching/analyze-calibration", methods=["POST"])
def analyze_calibration_profile():
    """Measure visible cell colors from a saved calibration-grid photograph."""
    profile_id = str(request.form.get("profile_id", "")).strip()
    try:
        rotation_degrees = max(-180, min(180, float(request.form.get("rotation_degrees", 0))))
    except ValueError:
        return jsonify({"status": "error", "message": "Photo rotation must be a number of degrees."}), 400
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    try:
        profile_path = _profile_metadata_path(upload_folder, profile_id)
        with open(profile_path, encoding="utf-8") as profile_file:
            profile = json.load(profile_file)
        cells, preview, correction, corners = _measure_grid_photo(
            os.path.join(upload_folder, profile["grid_photo"]), profile["grid"], rotation_degrees
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        current_app.logger.exception("Holographic calibration analysis failed")
        return jsonify({"status": "error", "message": f"Calibration analysis could not run: {error}"}), 400

    preview_name = f"holographic_profile_{profile_id}_analysis.jpg"
    if not cv2.imwrite(os.path.join(upload_folder, preview_name), preview):
        return jsonify({"status": "error", "message": "Could not save the analyzed grid preview."}), 500
    profile["status"] = "measured"
    profile["analysis"] = {
        "state": "measured",
        "message": "Cell colors were sampled from the photograph. Confirm the numbered preview before using these values for recipe mapping.",
        "perspective_correction": correction,
        "source_rotation_degrees": rotation_degrees,
        "detected_grid_corners": corners,
        "preview": preview_name,
        "cells": cells,
    }
    with open(profile_path, "w", encoding="utf-8") as profile_file:
        json.dump(profile, profile_file, indent=2)
    current_app.logger.info("Measured %s holographic calibration cells for profile %s.", len(cells), profile_id)
    return jsonify({
        "status": "measured",
        "profile_id": profile_id,
        "profile_url": f"/holographic-etching/download/{os.path.basename(profile_path)}",
        "preview_url": f"/holographic-etching/preview/{preview_name}",
        "correction": correction,
        "rotation_degrees": rotation_degrees,
        "cells": cells,
        "message": "Grid sampled. Review the numbered preview, then keep this profile as the measured recipe source.",
    })


@routes.route("/holographic-etching/preview/<filename>")
def preview_calibration_file(filename):
    if not filename.startswith("holographic_profile_"):
        return jsonify({"status": "error", "message": "Unknown calibration preview."}), 404
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename)


@routes.route("/holographic-etching/download/<filename>")
def download_calibration_file(filename):
    if not (filename.startswith("holographic_calibration_") or filename.startswith("holographic_profile_")):
        return jsonify({"status": "error", "message": "Unknown calibration file."}), 404
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename, as_attachment=True)
