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

from services import download_user_material_library, get_user_material_library

from . import routes


SWEEP_SETTINGS = {
    "none": None,
    "power": "maxPower",
    "speed": "speed",
    "frequency": "frequency",
    "pulse_width": "QPulseWidth",
    "passes": "numPasses",
}


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


def _numeric_setting(setting, name, default=0.0):
    """Read one LightBurn setting without letting malformed libraries break a grid."""
    try:
        return float(getattr(setting, name, default))
    except (TypeError, ValueError):
        return float(default)


def _grating_signature(setting, fill_interval_mm, scan_angle_degrees, override=None):
    """Describe the laser motion that produces one calibrated grating cell.

    LightBurn Material Libraries store MOPA frequency in Hz and scan speed in
    mm/s. The resulting pulse pitch in µm is therefore
    ``speed_mm_s / frequency_hz * 1000``: 300 mm/s / 300,000 Hz = 1 µm.
    The macro fill interval is deliberately separate; it controls neighbouring
    scan-line spacing and heat overlap.
    """
    override = override or {}
    speed_mm_s = _numeric_setting(setting, "speed")
    frequency_hz = _numeric_setting(setting, "frequency")
    property_name = SWEEP_SETTINGS.get(override.get("parameter"))
    if property_name == "speed":
        speed_mm_s = float(override["value"])
    elif property_name == "frequency":
        frequency_hz = float(override["value"])
    pulse_pitch_um = speed_mm_s / frequency_hz * 1000 if speed_mm_s > 0 and frequency_hz > 0 else None
    return {
        "scan_speed_mm_s": speed_mm_s,
        "pulse_frequency_hz": frequency_hz,
        "pulse_pitch_um": pulse_pitch_um,
        "pulse_width_ns": _numeric_setting(setting, "QPulseWidth"),
        "minimum_power_percent": _numeric_setting(setting, "minPower"),
        "maximum_power_percent": _numeric_setting(setting, "maxPower"),
        "passes": _numeric_setting(setting, "numPasses", 1),
        "fill_interval_mm": float(fill_interval_mm),
        "scan_direction_degrees": float(scan_angle_degrees) % 180,
        # The visible grating direction is normal to the scan travel direction.
        "grating_axis_degrees": (float(scan_angle_degrees) + 90) % 180,
    }


def _rgb_to_lab(rgb):
    """Return CIE-like Lab coordinates from an sRGB triplet for recipe matching."""
    sample = np.uint8([[[int(channel) for channel in rgb]]])
    lab = cv2.cvtColor(sample, cv2.COLOR_RGB2LAB)[0, 0]
    return [float(lab[0]) * 100 / 255, float(lab[1]) - 128, float(lab[2]) - 128]


def _svg_grid(path, columns, rows, cell_mm, intervals, angles):
    width, height = columns * cell_mm, rows * cell_mm
    root = ET.Element("svg", xmlns="http://www.w3.org/2000/svg", width=f"{width}mm",
                      height=f"{height}mm", viewBox=f"0 0 {width} {height}")
    ET.SubElement(root, "rect", x="0", y="0", width=str(width), height=str(height), fill="white")
    # High-contrast registration marks make the photographed grid far easier
    # to align than a thin cell border alone.  They sit in the outer corners,
    # away from the center sampling zones.
    mark_size = min(1.2, cell_mm * .12)
    for mark_x, mark_y in ((.2, .2), (width - mark_size - .2, .2), (.2, height - mark_size - .2), (width - mark_size - .2, height - mark_size - .2)):
        ET.SubElement(root, "rect", x=str(mark_x), y=str(mark_y), width=str(mark_size), height=str(mark_size), fill="#000")
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


def _rectify_grid_from_corners(photo, corners):
    corners = _order_corners(corners)
    top = np.linalg.norm(corners[1] - corners[0])
    bottom = np.linalg.norm(corners[2] - corners[3])
    left = np.linalg.norm(corners[3] - corners[0])
    right = np.linalg.norm(corners[2] - corners[1])
    target_width, target_height = max(300, round(max(top, bottom))), max(300, round(max(left, right)))
    destination = np.array([[0, 0], [target_width - 1, 0], [target_width - 1, target_height - 1], [0, target_height - 1]], dtype=np.float32)
    return cv2.warpPerspective(photo, cv2.getPerspectiveTransform(corners, destination), (target_width, target_height)), corners.tolist()


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


def _crop_and_resize_image(image, crop, max_edge):
    """Apply user-selected percentage crop margins and optional analysis size."""
    height, width = image.shape[:2]
    left = round(width * crop["left"] / 100)
    right = round(width * (100 - crop["right"]) / 100)
    top = round(height * crop["top"] / 100)
    bottom = round(height * (100 - crop["bottom"]) / 100)
    cropped = image[top:bottom, left:right]
    if cropped.size == 0:
        raise ValueError("Crop margins leave no image area to analyze.")
    height, width = cropped.shape[:2]
    if max_edge and max(height, width) > max_edge:
        scale = max_edge / max(height, width)
        cropped = cv2.resize(cropped, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
    return cropped


def _measure_grid_photo(photo_path, grid, rotation_degrees=0, crop=None, max_edge=0, manual_corners=None, manual_sample_points=None, reference_correction=None):
    photo = cv2.imread(photo_path, cv2.IMREAD_COLOR)
    if photo is None:
        raise ValueError("The saved grid photo could not be opened for analysis.")
    crop = crop or {"left": 0, "top": 0, "right": 0, "bottom": 0}
    if manual_corners:
        rectified, corners = _rectify_grid_from_corners(photo, manual_corners)
        correction = "manual_corners"
    else:
        photo = _crop_and_resize_image(photo, crop, max_edge)
        photo = _rotate_image(photo, rotation_degrees)
    # Once the operator supplies a crop, it is an intentional declaration of
    # the grid bounds.  Do not let automatic contour detection replace that
    # choice with a nearby photo edge or reflection.
        if any(crop.values()):
            rectified, correction, corners = photo, "manual_crop", None
        else:
            rectified, correction, corners = _rectify_grid(photo)
    rows, columns = int(grid["rows"]), int(grid["columns"])
    height, width = rectified.shape[:2]
    intervals, angles = grid["intervals_mm"], grid["angles_degrees"]
    recipe_signatures = grid.get("grating_recipe_signatures") or []
    cells = []
    manual_sample_points = manual_sample_points or {}
    preview = rectified.copy()
    for index in range(rows * columns):
        row, column = divmod(index, columns)
        x0, x1 = round(column * width / columns), round((column + 1) * width / columns)
        y0, y1 = round(row * height / rows), round((row + 1) * height / rows)
        # Avoid the engraved border and label, which are not representative of
        # the cell's structural color.
        point = manual_sample_points.get(str(index + 1))
        if point:
            center_x, center_y = round(float(point[0]) * width), round(float(point[1]) * height)
            radius_x, radius_y = max(2, round((x1 - x0) * .14)), max(2, round((y1 - y0) * .14))
            sample = rectified[max(y0, center_y - radius_y):min(y1, center_y + radius_y), max(x0, center_x - radius_x):min(x1, center_x + radius_x)]
        else:
            pad_x, pad_y = max(1, round((x1 - x0) * .22)), max(1, round((y1 - y0) * .25))
            sample = rectified[y0 + pad_y:y1 - pad_y, x0 + pad_x:x1 - pad_x]
        if sample.size == 0:
            raise ValueError("The detected grid is too small to sample reliably.")
        median_bgr = np.median(sample.reshape(-1, 3), axis=0).astype(np.uint8)
        median_rgb = [int(median_bgr[2]), int(median_bgr[1]), int(median_bgr[0])]
        if reference_correction:
            median_rgb = [int(np.clip(channel * scale, 0, 255)) for channel, scale in zip(median_rgb, reference_correction)]
        observed_lab = _rgb_to_lab(median_rgb)
        sample_hsv = cv2.cvtColor(sample, cv2.COLOR_BGR2HSV)
        median_hsv = cv2.cvtColor(np.uint8([[median_bgr]]), cv2.COLOR_BGR2HSV)[0, 0]
        saturation = float(np.median(sample_hsv[:, :, 1])) / 255
        brightness = float(np.median(sample_hsv[:, :, 2])) / 255
        uniformity = max(0., 1 - float(np.mean(np.std(sample.reshape(-1, 3), axis=0))) / 85)
        confidence = round(100 * (.35 * saturation + .30 * brightness + .35 * uniformity))
        quality_flags = []
        if saturation < .12:
            quality_flags.append("low color saturation")
        if brightness < .16:
            quality_flags.append("very dark")
        if uniformity < .55:
            quality_flags.append("uneven sample")
        cells.append({
            "index": index + 1, "row": row + 1, "column": column + 1,
            "interval_mm": intervals[index], "angle_degrees": angles[index],
            "observed_rgb": median_rgb,
            "observed_lab": observed_lab,
            "observed_hex": "#{:02X}{:02X}{:02X}".format(*median_rgb),
            "observed_hsv_opencv": [int(value) for value in median_hsv],
            "confidence": confidence,
            "quality_flags": quality_flags,
            "manual_sample_point": point,
            "laser_setting_override": (
                {"parameter": grid["sweep"]["parameter"], "value": grid["sweep"]["values"][index]}
                if grid.get("sweep", {}).get("parameter") else None
            ),
            "grating_signature": recipe_signatures[index] if index < len(recipe_signatures) else {},
        })
        cv2.rectangle(preview, (x0, y0), (x1, y1), (40, 240, 135), 2)
        cv2.putText(preview, str(index + 1), (x0 + 8, y0 + 25), cv2.FONT_HERSHEY_SIMPLEX, .75, (40, 240, 135), 2, cv2.LINE_AA)
    return cells, preview, correction, corners


def _load_recipe_profile(profile_file):
    try:
        profile = json.load(profile_file)
    except json.JSONDecodeError as error:
        raise ValueError(f"Recipe profile is not valid JSON: {error}") from error
    recipes = profile.get("recipes")
    grid = profile.get("grid", {})
    if profile.get("kind") != "holographic_calibration_profile" or not isinstance(recipes, list) or not recipes:
        raise ValueError("Upload a saved Holographic Etching recipe profile with at least one kept recipe.")
    if not grid.get("material") or not grid.get("setting_description"):
        raise ValueError("The recipe profile does not contain its original Material Library setting reference.")
    for recipe in recipes:
        if not isinstance(recipe.get("observed_rgb"), list) or len(recipe["observed_rgb"]) != 3:
            raise ValueError("A recipe profile contains an invalid observed color.")
    return profile


def _nearest_recipe(pixel, recipes):
    """Choose the calibrated structural-color recipe closest in Lab space."""
    target_lab = _rgb_to_lab(pixel)
    return min(
        recipes,
        key=lambda recipe: sum(
            (channel - reference) ** 2
            for channel, reference in zip(target_lab, recipe.get("observed_lab") or _rgb_to_lab(recipe["observed_rgb"]))
        ),
    )


def _merge_recipe_pixels(layer_map, recipe_count):
    """Greedily combine same-recipe pixels into non-overlapping rectangles."""
    height, width = layer_map.shape
    visited = np.zeros((height, width), dtype=bool)
    rectangles = {index: [] for index in range(recipe_count)}
    for y in range(height):
        for x in range(width):
            if visited[y, x]:
                continue
            recipe_index = layer_map[y, x]
            rectangle_width = 1
            while x + rectangle_width < width and not visited[y, x + rectangle_width] and layer_map[y, x + rectangle_width] == recipe_index:
                rectangle_width += 1
            rectangle_height = 1
            while y + rectangle_height < height:
                next_row = layer_map[y + rectangle_height, x:x + rectangle_width]
                if visited[y + rectangle_height, x:x + rectangle_width].any() or not np.all(next_row == recipe_index):
                    break
                rectangle_height += 1
            visited[y:y + rectangle_height, x:x + rectangle_width] = True
            rectangles[int(recipe_index)].append((x, y, rectangle_width, rectangle_height))
    return rectangles


def _write_holographic_svg(path, width, height, recipes_by_name, pixel_mm):
    root = ET.Element("svg", xmlns="http://www.w3.org/2000/svg", width=f"{width * pixel_mm}mm",
                      height=f"{height * pixel_mm}mm", viewBox=f"0 0 {width * pixel_mm} {height * pixel_mm}")
    for name, coordinates in recipes_by_name.items():
        recipe = coordinates["recipe"]
        group = ET.SubElement(root, "g", id=f"recipe_{recipe['index']}", fill=recipe["observed_hex"])
        for x, y, rectangle_width, rectangle_height in coordinates["rectangles"]:
            ET.SubElement(group, "rect", x=str(x * pixel_mm), y=str(y * pixel_mm),
                          width=str(rectangle_width * pixel_mm), height=str(rectangle_height * pixel_mm))
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _build_holographic_exports(upload_folder, art_file, profile_file, material_file, max_dimension, pixel_mm):
    profile = _load_recipe_profile(profile_file)
    try:
        image = Image.open(art_file.stream).convert("RGB")
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("Upload a readable artwork image, such as JPG or PNG.") from error
    image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
    pixels = np.asarray(image)
    if not pixels.size:
        raise ValueError("Artwork image has no usable pixels.")

    task_id = str(uuid.uuid4())
    material_path = os.path.join(upload_folder, f"{task_id}_holographic_{secure_filename(material_file.filename)}")
    material_file.save(material_path)
    lightburn = _lightburn_module()
    grid = profile["grid"]
    base_setting = _calibration_base_layer(_exact_setting(
        lightburn, material_path, grid["material"], grid["setting_description"]
    ))
    recipes_by_name = {}
    project = lightburn.Lightburn()
    for layer_index, recipe in enumerate(profile["recipes"]):
        setting = copy(base_setting)
        setting.index = layer_index
        setting.name = recipe["name"]
        setting.interval = float(recipe["interval_mm"])
        setting.angle = float(recipe["angle_degrees"])
        override = recipe.get("laser_setting_override") or {}
        if override.get("parameter") in SWEEP_SETTINGS and SWEEP_SETTINGS[override["parameter"]]:
            value = override.get("value")
            if override["parameter"] in {"frequency", "passes"}:
                value = round(float(value))
            setattr(setting, SWEEP_SETTINGS[override["parameter"]], value)
        setting.subLayers = []
        project.add_layer(setting)
        recipes_by_name[recipe["name"]] = {"recipe": recipe, "layer_index": layer_index, "rectangles": []}

    layer_map = np.empty(pixels.shape[:2], dtype=np.int16)
    for y, row in enumerate(pixels):
        for x, pixel in enumerate(row):
            recipe = _nearest_recipe(pixel, profile["recipes"])
            layer_map[y, x] = recipes_by_name[recipe["name"]]["layer_index"]
    rectangles_by_layer = _merge_recipe_pixels(layer_map, len(profile["recipes"]))
    for bucket in recipes_by_name.values():
        bucket["rectangles"] = rectangles_by_layer[bucket["layer_index"]]
        for x, y, rectangle_width, rectangle_height in bucket["rectangles"]:
            project.add(lightburn.Square(rectangle_width * pixel_mm, rectangle_height * pixel_mm,
                                        x=x * pixel_mm, y=y * pixel_mm).layer(bucket["layer_index"]))

    stem = f"holographic_art_{task_id}"
    svg_name, lbrn_name = f"{stem}.svg", f"{stem}.lbrn2"
    _write_holographic_svg(os.path.join(upload_folder, svg_name), pixels.shape[1], pixels.shape[0], recipes_by_name, pixel_mm)
    project.write(os.path.join(upload_folder, lbrn_name))
    metadata_name = f"{stem}.json"
    with open(os.path.join(upload_folder, metadata_name), "w", encoding="utf-8") as metadata_file:
        json.dump({
            "kind": "holographic_art_export", "recipe_profile_name": profile.get("profile_name"),
            "source_pixels": {"width": int(pixels.shape[1]), "height": int(pixels.shape[0])},
            "pixel_size_mm": pixel_mm, "physical_size_mm": [pixels.shape[1] * pixel_mm, pixels.shape[0] * pixel_mm],
            "vector_rectangles": sum(len(bucket["rectangles"]) for bucket in recipes_by_name.values()),
            "source_pixel_count": int(pixels.shape[0] * pixels.shape[1]),
            "color_mapping": {
                "method": "nearest_measured_recipe_cie_lab",
                "note": "Each artwork pixel is assigned to the perceptually nearest measured diffraction recipe.",
            },
            "recipes": [{
                "name": recipe["name"], "interval_mm": recipe["interval_mm"],
                "angle_degrees": recipe["angle_degrees"],
                "observed_rgb": recipe["observed_rgb"],
                "observed_lab": recipe.get("observed_lab") or _rgb_to_lab(recipe["observed_rgb"]),
                "grating_signature": recipe.get("grating_signature", {}),
            } for recipe in profile["recipes"]],
        }, metadata_file, indent=2)
    return svg_name, lbrn_name, metadata_name, pixels.shape[1], pixels.shape[0], sum(
        len(bucket["rectangles"]) for bucket in recipes_by_name.values()
    )


@routes.route("/holographic-etching/calibration-grid", methods=["POST"])
def calibration_grid():
    library = request.files.get("material_settings")
    saved_library_id = str(request.form.get("saved_material_library_id", "")).strip()
    material = str(request.form.get("material", "")).strip()
    description = str(request.form.get("setting_description", "")).strip()
    laser_source = str(request.form.get("laser_source", "")).strip()
    if not material or not description or (not saved_library_id and (not library or not library.filename)):
        return jsonify({"status": "error", "message": "Choose a saved Material Library or upload one, then provide its material name and setting Description."}), 400
    try:
        columns = max(2, min(6, int(request.form.get("columns", 4))))
        rows = max(2, min(6, int(request.form.get("rows", 4))))
        cell_mm = max(4, min(30, float(request.form.get("cell_mm", 12))))
        interval_low = max(.01, min(.5, float(request.form.get("interval_low", .045))))
        interval_high = max(interval_low, min(.5, float(request.form.get("interval_high", .07))))
        lens_field_mm = max(1, min(1000, float(request.form.get("lens_field_mm", 110))))
        sweep_key = str(request.form.get("sweep_parameter", "none"))
        if sweep_key not in SWEEP_SETTINGS:
            raise ValueError("Unknown laser-setting sweep.")
        sweep_low = float(request.form.get("sweep_low", 0))
        sweep_high = float(request.form.get("sweep_high", sweep_low))
    except ValueError:
        return jsonify({"status": "error", "message": "Calibration grid dimensions and intervals must be numbers."}), 400

    task_id = str(uuid.uuid4())
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    if saved_library_id:
        user_id = request.headers.get("x-amzn-oidc-identity", "").strip()
        if not user_id:
            return jsonify({"status": "error", "message": "Sign in to use a saved Material Library, or upload a one-off library file."}), 401
        try:
            saved_library = get_user_material_library(user_id, saved_library_id)
            if not saved_library:
                return jsonify({"status": "error", "message": "That saved Material Library is unavailable or belongs to another account."}), 404
            saved_name = secure_filename(saved_library.get("original_name") or saved_library.get("name") or "material-library.clb")
            library_path = os.path.join(upload_folder, f"{task_id}_calibration_saved_{saved_name}")
            download_user_material_library(saved_library, library_path)
        except RuntimeError as error:
            current_app.logger.exception("Could not retrieve saved holographic calibration library")
            return jsonify({"status": "error", "message": str(error)}), 503
    else:
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
    sweep_values = [sweep_low + (sweep_high - sweep_low) * index / max(count - 1, 1) for index in range(count)]
    recipe_signatures = []
    stem = f"holographic_calibration_{task_id}"
    svg_name, lbrn_name = f"{stem}.svg", f"{stem}.lbrn2"
    try:
        _svg_grid(os.path.join(upload_folder, svg_name), columns, rows, cell_mm, intervals, angles)
        project = lightburn.Lightburn()
        fiducial_layer_index = count
        fiducial_setting = copy(base_setting)
        fiducial_setting.index = fiducial_layer_index
        fiducial_setting.name = "Calibration alignment fiducials"
        fiducial_setting.subLayers = []
        project.add_layer(fiducial_setting)
        fiducial_size = min(1.2, cell_mm * .12)
        for fiducial_x, fiducial_y in ((.2, .2), (columns * cell_mm - fiducial_size - .2, .2), (.2, rows * cell_mm - fiducial_size - .2), (columns * cell_mm - fiducial_size - .2, rows * cell_mm - fiducial_size - .2)):
            project.add(lightburn.Square(fiducial_size, fiducial_size, x=fiducial_x, y=fiducial_y).layer(fiducial_layer_index))
        for index, (interval, angle) in enumerate(zip(intervals, angles)):
            setting = copy(base_setting)
            setting.index = index
            setting.name = f"Holo {index + 1:02d} {angle:g}deg {interval:.3f}mm"
            setting.interval = interval
            setting.angle = angle
            if SWEEP_SETTINGS[sweep_key]:
                value = round(sweep_values[index]) if sweep_key in {"frequency", "passes"} else sweep_values[index]
                setattr(setting, SWEEP_SETTINGS[sweep_key], value)
            signature = _grating_signature(
                setting, interval, angle,
                {"parameter": sweep_key, "value": value} if SWEEP_SETTINGS[sweep_key] else None,
            )
            signature["cell_index"] = index + 1
            recipe_signatures.append(signature)
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
                "grating_recipe_signatures": recipe_signatures,
                "sweep": {
                    "parameter": sweep_key if SWEEP_SETTINGS[sweep_key] else None,
                    "lightburn_property": SWEEP_SETTINGS[sweep_key],
                    "values": sweep_values if SWEEP_SETTINGS[sweep_key] else [],
                },
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
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    try:
        rotation_degrees = max(-180, min(180, float(request.form.get("rotation_degrees", 0))))
        crop = {
            edge: max(0, min(45, float(request.form.get(f"crop_{edge}", 0))))
            for edge in ("left", "top", "right", "bottom")
        }
        if crop["left"] + crop["right"] >= 90 or crop["top"] + crop["bottom"] >= 90:
            raise ValueError("Opposing crop margins must leave visible image area.")
        max_edge = max(0, min(6000, int(request.form.get("max_edge", 1800))))
        manual_corners_raw = str(request.form.get("manual_corners", "")).strip()
        manual_samples_raw = str(request.form.get("manual_sample_points", "")).strip()
        reference_values = [str(request.form.get(f"reference_{channel}", "")).strip() for channel in ("r", "g", "b")]
        manual_corners = None
        if manual_corners_raw:
            normalized_corners = json.loads(manual_corners_raw)
            if (not isinstance(normalized_corners, list) or len(normalized_corners) != 4
                    or any(not isinstance(corner, list) or len(corner) != 2 for corner in normalized_corners)):
                raise ValueError("Four grid corners are required.")
            manual_corners = normalized_corners
        manual_sample_points = json.loads(manual_samples_raw) if manual_samples_raw else {}
        if not isinstance(manual_sample_points, dict):
            raise ValueError("Manual sample points must be a cell map.")
        reference_correction = None
        if any(reference_values):
            if not all(reference_values):
                raise ValueError("Enter all three neutral-reference RGB values, or leave them all blank.")
            observed_reference = [float(value) for value in reference_values]
            if any(value <= 0 for value in observed_reference):
                raise ValueError("Neutral-reference RGB values must be above zero.")
            reference_correction = [220 / value for value in observed_reference]
    except (ValueError, TypeError, json.JSONDecodeError):
        return jsonify({"status": "error", "message": "Rotation, crop margins, and analysis size must be valid numbers."}), 400
    try:
        profile_path = _profile_metadata_path(upload_folder, profile_id)
        with open(profile_path, encoding="utf-8") as profile_file:
            profile = json.load(profile_file)
        if manual_corners is not None:
            source = cv2.imread(os.path.join(upload_folder, profile["grid_photo"]), cv2.IMREAD_COLOR)
            if source is None:
                raise ValueError("The saved grid photo could not be opened for analysis.")
            height, width = source.shape[:2]
            manual_corners = [
                [max(0, min(width - 1, float(corner[0]) * width)), max(0, min(height - 1, float(corner[1]) * height))]
                for corner in manual_corners
            ]
        cells, preview, correction, corners = _measure_grid_photo(
            os.path.join(upload_folder, profile["grid_photo"]), profile["grid"], rotation_degrees, crop, max_edge, manual_corners, manual_sample_points, reference_correction
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
        "source_crop_percent": crop,
        "analysis_max_edge_px": max_edge,
        "manual_grid_corners": corners if correction == "manual_corners" else None,
        "manual_sample_points": manual_sample_points,
        "neutral_reference_correction": reference_correction,
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
        "crop": crop,
        "cells": cells,
        "message": "Grid sampled. Review the numbered preview, then keep this profile as the measured recipe source.",
    })


@routes.route("/holographic-etching/save-recipes", methods=["POST"])
def save_holographic_recipes():
    """Persist the operator's chosen calibration cells as a reusable palette."""
    profile_id = str(request.form.get("profile_id", "")).strip()
    try:
        selected = json.loads(str(request.form.get("recipes", "[]")))
        if not isinstance(selected, list) or not selected:
            raise ValueError("Keep at least one measured swatch.")
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        return jsonify({"status": "error", "message": f"Recipe selections are invalid: {error}"}), 400

    upload_folder = current_app.config["UPLOAD_FOLDER"]
    try:
        profile_path = _profile_metadata_path(upload_folder, profile_id)
        with open(profile_path, encoding="utf-8") as profile_file:
            profile = json.load(profile_file)
        cells = {int(cell["index"]): cell for cell in profile["analysis"]["cells"]}
        recipes = []
        used_names = set()
        for item in selected:
            index = int(item["index"])
            if index not in cells:
                raise ValueError(f"Cell {index} is not part of this profile.")
            name = str(item.get("name", "")).strip() or f"Holographic {index:02d}"
            unique_name = name.casefold()
            if unique_name in used_names:
                raise ValueError("Recipe names must be unique.")
            used_names.add(unique_name)
            recipes.append({"name": name, **cells[index]})
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        return jsonify({"status": "error", "message": f"Could not save recipes: {error}"}), 400

    profile["status"] = "recipe_palette_ready"
    profile["recipes"] = recipes
    similar_pairs = []
    for left_index, left in enumerate(recipes):
        for right in recipes[left_index + 1:]:
            distance = round(math.sqrt(sum((int(a) - int(b)) ** 2 for a, b in zip(left["observed_rgb"], right["observed_rgb"]))), 1)
            if distance < 28:
                similar_pairs.append({"recipes": [left["name"], right["name"]], "rgb_distance": distance})
    weak_recipes = [recipe["name"] for recipe in recipes if recipe.get("confidence", 100) < 45 or recipe.get("quality_flags")]
    profile["palette_diagnostics"] = {"similar_pairs": similar_pairs, "weak_recipes": weak_recipes}
    with open(profile_path, "w", encoding="utf-8") as profile_file:
        json.dump(profile, profile_file, indent=2)
    current_app.logger.info("Saved %s holographic recipes for profile %s.", len(recipes), profile_id)
    return jsonify({
        "status": "saved",
        "recipe_count": len(recipes),
        "profile_url": f"/holographic-etching/download/{os.path.basename(profile_path)}",
        "palette_diagnostics": profile["palette_diagnostics"],
        "message": f"Saved {len(recipes)} holographic recipe(s) into this calibration profile.",
    })


@routes.route("/holographic-etching/build-artwork", methods=["POST"])
def build_holographic_artwork():
    artwork = request.files.get("artwork")
    profile_file = request.files.get("recipe_profile")
    material_file = request.files.get("material_settings")
    if not all((artwork, artwork.filename, profile_file, profile_file.filename, material_file, material_file.filename)):
        return jsonify({"status": "error", "message": "Provide artwork, a saved recipe profile, and the matching Material Library file."}), 400
    try:
        max_dimension = max(8, min(1600, int(request.form.get("max_dimension", 96))))
        pixel_mm = max(.05, min(5, float(request.form.get("pixel_mm", .5))))
    except ValueError:
        return jsonify({"status": "error", "message": "Processing resolution and pixel size must be numbers."}), 400
    try:
        svg_name, lbrn_name, metadata_name, width, height, rectangle_count = _build_holographic_exports(
            current_app.config["UPLOAD_FOLDER"], artwork, profile_file, material_file, max_dimension, pixel_mm
        )
    except (OSError, ValueError, ET.ParseError, KeyError, TypeError) as error:
        current_app.logger.exception("Holographic artwork export failed")
        return jsonify({"status": "error", "message": f"Could not build holographic artwork: {error}"}), 400
    return jsonify({
        "status": "completed", "source_width": width, "source_height": height, "rectangle_count": rectangle_count,
        "svg_url": f"/holographic-etching/download/{svg_name}",
        "lightburn_url": f"/holographic-etching/download/{lbrn_name}",
        "metadata_url": f"/holographic-etching/download/{metadata_name}",
    })


@routes.route("/holographic-etching/profile-photo/<profile_id>")
def calibration_profile_photo(profile_id):
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    try:
        with open(_profile_metadata_path(upload_folder, profile_id), encoding="utf-8") as profile_file:
            profile = json.load(profile_file)
        photo_name = os.path.basename(profile["grid_photo"])
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return jsonify({"status": "error", "message": "Calibration profile photo was not found."}), 404
    return send_from_directory(upload_folder, photo_name)


@routes.route("/holographic-etching/preview/<filename>")
def preview_calibration_file(filename):
    if not filename.startswith("holographic_profile_"):
        return jsonify({"status": "error", "message": "Unknown calibration preview."}), 404
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename)


@routes.route("/holographic-etching/download/<filename>")
def download_calibration_file(filename):
    if not (filename.startswith("holographic_calibration_") or filename.startswith("holographic_profile_") or filename.startswith("holographic_art_")):
        return jsonify({"status": "error", "message": "Unknown calibration file."}), 404
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename, as_attachment=True)
