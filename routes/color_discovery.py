"""Iterative, photographed two-parameter color discovery experiments."""

import json
import math
import os
import tempfile
import uuid
from difflib import SequenceMatcher
from xml.etree import ElementTree as ET

import cv2
import numpy as np
from flask import current_app, jsonify, render_template, request, send_from_directory
from werkzeug.utils import secure_filename

from services import (
    HISTORY_TTL_SECONDS,
    LIGHTBURN_PALETTE_NAMES,
    bind_job_access,
    query_laser_community,
    redis_client,
    save_user_material_library,
    upload_task_artifact,
    valid_history_session,
)

from . import routes
from ._job_access import browser_job_session, issue_submission_auth_token, request_can_access_job
from .account import apply_entry_update, library_entries, mutate_library
from .holographic import (
    _calibration_base_layer,
    _exact_setting,
    _lightburn_module,
    _download_holographic_artifact,
    _ensure_holographic_artifact,
    _measure_grid_photo,
    _resolve_material_library,
    _validated_submission_identity,
)


PARAMETERS = {
    "speed": {"property": "speed", "label": "Speed", "unit": "mm/s", "minimum": .1, "maximum": 100000},
    "max_power": {"property": "maxPower", "label": "Maximum power", "unit": "%", "minimum": 0, "maximum": 100},
    "frequency": {"property": "frequency", "label": "Frequency", "unit": "Hz", "minimum": 1, "maximum": 5000000, "integer": True},
    "pulse_width": {"property": "QPulseWidth", "label": "Pulse width", "unit": "ns", "minimum": 0, "maximum": 10000},
    "passes": {"property": "numPasses", "label": "Passes", "unit": "", "minimum": 1, "maximum": 1000, "integer": True},
    "interval": {"property": "interval", "label": "Fill interval", "unit": "mm", "minimum": .001, "maximum": 10},
    "angle": {"property": "angle", "label": "Scan angle", "unit": "degrees", "minimum": 0, "maximum": 179.999},
    "min_power": {"property": "minPower", "label": "Minimum power", "unit": "%", "minimum": 0, "maximum": 100},
}
BASELINE_FIELDS = (
    "type", "minPower", "maxPower", "maxPower2", "speed", "frequency", "QPulseWidth",
    "interval", "angle", "numPasses", "anglePerPass", "crossHatch",
)


def _session_key(session_id):
    return f"color-discovery:{session_id}"


def _artifact_key(filename):
    return f"color-discovery-artifact:{os.path.basename(filename)}"


def _save_session(payload):
    redis_client.set(_session_key(payload["session_id"]), json.dumps(payload, separators=(",", ":")), ex=HISTORY_TTL_SECONDS)


def _load_session(session_id):
    if not request_can_access_job(session_id):
        raise PermissionError("This Color Discovery session is not available to this browser.")
    try:
        payload = json.loads(redis_client.get(_session_key(session_id)) or "{}")
    except (TypeError, json.JSONDecodeError):
        payload = {}
    if not payload:
        raise FileNotFoundError("That Color Discovery session has expired or no longer exists.")
    redis_client.expire(_session_key(session_id), HISTORY_TTL_SECONDS)
    return payload


def _store_artifact(owner_id, path):
    key = upload_task_artifact(owner_id, path, category="outputs", user_id=request.headers.get("x-amzn-oidc-identity", "").strip() or None)
    if key:
        redis_client.set(_artifact_key(path), key, ex=HISTORY_TTL_SECONDS)
        # Reuse the lab's durable artifact resolver; it is prefix-agnostic.
        redis_client.set(f"holographic-artifact:{os.path.basename(path)}", key, ex=HISTORY_TTL_SECONDS)


def _vault_entry_payloads(cells, material_name):
    """Turn measured cells into distinct, immediately matchable palette entries."""
    available = []
    for color_hex, description in LIGHTBURN_PALETTE_NAMES.items():
        available.append((_hex_rgb(color_hex), description))
    payloads = []
    for cell in cells:
        observed = _hex_rgb(cell.get("observed_hex"))
        if not observed or not available:
            raise ValueError("A selected cell does not contain a usable measured color.")
        palette_rgb, description = min(
            available,
            key=lambda item: sum((observed[channel] - item[0][channel]) ** 2 for channel in range(3)),
        )
        available.remove((palette_rgb, description))
        setting = dict(cell.get("setting") or {})
        setting_type = str(setting.pop("type", "Scan"))
        payloads.append({
            "material": material_name,
            "description": description,
            "type": setting_type if setting_type in {"Cut", "Scan", "Image", "Offset"} else "Scan",
            "settings": setting,
        })
    return payloads


def _number(value, fallback, minimum, maximum):
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = float(fallback)
    if not math.isfinite(value):
        value = float(fallback)
    return max(minimum, min(maximum, value))


def _serialize_setting(setting):
    values = {}
    for field in BASELINE_FIELDS:
        value = getattr(setting, field, None)
        if isinstance(value, (str, int, float, bool)):
            values[field] = value
    values.setdefault("type", "Scan")
    return values


def _normalize_baseline(values):
    if not isinstance(values, dict):
        raise ValueError("The discovery baseline must be a laser-setting object.")
    setting_type = str(values.get("type", "Scan"))
    if setting_type not in {"Cut", "Scan", "Offset"}:
        raise ValueError("The discovery baseline must use Line, Fill, or Offset Fill.")
    normalized = {"type": setting_type}
    defaults = {
        "minPower": 0, "maxPower": 30, "maxPower2": values.get("maxPower", 30),
        "speed": 1000, "frequency": 100000, "QPulseWidth": 100,
        "interval": .05, "angle": 0, "numPasses": 1, "anglePerPass": 0,
    }
    limits = {
        "minPower": (0, 100), "maxPower": (0, 100), "maxPower2": (0, 100),
        "speed": (.1, 100000), "frequency": (1, 5000000), "QPulseWidth": (0, 10000),
        "interval": (.001, 10), "angle": (0, 179.999), "numPasses": (1, 1000),
        "anglePerPass": (-180, 180),
    }
    for field, default in defaults.items():
        normalized[field] = _number(values.get(field), default, *limits[field])
    normalized["frequency"] = round(normalized["frequency"])
    normalized["numPasses"] = round(normalized["numPasses"])
    normalized["crossHatch"] = bool(values.get("crossHatch", False))
    if normalized["minPower"] > normalized["maxPower"]:
        raise ValueError("Minimum power cannot exceed maximum power in the starting setting.")
    return normalized


def _manual_baseline(form):
    setting_type = str(form.get("manual_type", "Scan"))
    if setting_type not in {"Cut", "Scan", "Offset"}:
        raise ValueError("Choose a supported Line, Fill, or Offset Fill operation.")
    return {
        "type": setting_type,
        "minPower": _number(form.get("manual_min_power"), 0, 0, 100),
        "maxPower": _number(form.get("manual_max_power"), 30, 0, 100),
        "maxPower2": _number(form.get("manual_max_power"), 30, 0, 100),
        "speed": _number(form.get("manual_speed"), 1000, .1, 100000),
        "frequency": round(_number(form.get("manual_frequency"), 100000, 1, 5000000)),
        "QPulseWidth": _number(form.get("manual_pulse_width"), 100, 0, 10000),
        "interval": _number(form.get("manual_interval"), .05, .001, 10),
        "angle": _number(form.get("manual_angle"), 0, 0, 179.999),
        "numPasses": round(_number(form.get("manual_passes"), 1, 1, 1000)),
        "crossHatch": False,
        "anglePerPass": 0,
    }


def _hex_rgb(value):
    value = str(value or "").strip().lstrip("#")
    if not value:
        return None
    if len(value) == 3:
        value = "".join(character * 2 for character in value)
    if len(value) != 6:
        raise ValueError("Target color must be a six-digit HEX color.")
    try:
        return [int(value[index:index + 2], 16) for index in (0, 2, 4)]
    except ValueError as error:
        raise ValueError("Target color must be a valid HEX color.") from error


def _rgb_lab(rgb):
    pixel = np.uint8([[[*rgb]]])
    lab = cv2.cvtColor(pixel, cv2.COLOR_RGB2LAB)[0, 0]
    return [float(lab[0]) * 100 / 255, float(lab[1]) - 128, float(lab[2]) - 128]


def _delta_e(left, right):
    return math.sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(left, right)))


def _community_candidates(user_id, laser, lens, material, target_rgb):
    if not user_id or not target_rgb or not any((laser, lens, material)):
        return []
    try:
        # Pull a reasonably related pool, then score fuzzy equipment similarity
        # locally. Comunity Set's public filters are intentionally exact for
        # laser/lens, which is too strict for discovery suggestions.
        rows = query_laser_community("", "", material, "", limit=300) if material else query_laser_community(laser, "", "", "", limit=300)
    except (RuntimeError, ValueError):
        return []
    target_lab = _rgb_lab(target_rgb)
    ranked = []
    for row in rows:
        try:
            rgb = _hex_rgb(row.get("swatch"))
            distance = _delta_e(target_lab, _rgb_lab(rgb))
        except (TypeError, ValueError):
            continue
        similarities = []
        for requested, observed in ((laser, row.get("laser_source")), (lens, row.get("lens")), (material, row.get("material"))):
            if requested:
                similarities.append(SequenceMatcher(None, str(requested).casefold(), str(observed or "").casefold()).ratio())
        setup_similarity = sum(similarities) / len(similarities) if similarities else 0
        ranked.append({
            **row, "delta_e": round(distance, 2),
            "setup_similarity": round(setup_similarity * 100),
            "recommendation_score": distance + (1 - setup_similarity) * 35,
        })
    return sorted(ranked, key=lambda item: item["recommendation_score"])[:5]


def _axis_values(parameter, low, high, count):
    spec = PARAMETERS[parameter]
    low = _number(low, spec["minimum"], spec["minimum"], spec["maximum"])
    high = _number(high, low, spec["minimum"], spec["maximum"])
    low, high = min(low, high), max(low, high)
    values = [low + (high - low) * index / max(1, count - 1) for index in range(count)]
    if spec.get("integer"):
        values = [round(value) for value in values]
    return values


def _setting_from_values(lightburn, baseline, index, name, overrides):
    layer = lightburn.Layer()
    for key, value in baseline.items():
        setattr(layer, key, value)
    for key, value in overrides.items():
        setattr(layer, PARAMETERS[key]["property"], value)
    layer.index, layer.name = index, name
    return layer


def _grid_guidance(cells, target_lab, x_parameter, y_parameter):
    valid = [cell for cell in cells if cell.get("observed_lab")]
    if not valid:
        return {"summary": "No cells could be measured reliably.", "recommended_cell": None}
    if target_lab:
        for cell in valid:
            cell["target_delta_e"] = round(_delta_e(cell["observed_lab"], target_lab), 2)
        best = min(valid, key=lambda cell: cell["target_delta_e"])
        summary = f"Cell {best['index']} is closest to the target (Delta E {best['target_delta_e']:.2f}). Refine around it, or keep it as the baseline and test a different parameter pair."
    else:
        center = [sum(cell["observed_lab"][axis] for cell in valid) / len(valid) for axis in range(3)]
        best = max(valid, key=lambda cell: _delta_e(cell["observed_lab"], center))
        summary = f"Cell {best['index']} contributes the most distinct measured color. Refine around it or test two different parameters from that baseline."
    return {"summary": summary, "recommended_cell": best["index"], "tested_parameters": [x_parameter, y_parameter]}


@routes.route("/color-discovery")
def color_discovery_lab():
    return render_template(
        "color_discovery.html",
        submission_auth_token=issue_submission_auth_token(),
        parameter_specs=PARAMETERS,
        lightburn_palette=[
            [str(name).strip().casefold(), color_hex]
            for color_hex, name in LIGHTBURN_PALETTE_NAMES.items()
        ],
    )


@routes.route("/color-discovery/session", methods=["POST"])
def create_color_discovery_session():
    user_id, auth_failure = _validated_submission_identity()
    if auth_failure:
        return auth_failure
    form = request.form
    session_id = str(uuid.uuid4())
    source_mode = str(form.get("source_mode", "manual"))
    try:
        if source_mode == "manual":
            baseline = _normalize_baseline(_manual_baseline(form))
            source_label = "Manual starting setting"
        else:
            history_session = valid_history_session(form.get("history_session")) or valid_history_session(request.cookies.get("mopa_history_session"))
            path = _resolve_material_library(
                session_id, request.files.get("material_settings"), str(form.get("saved_material_library_id", "")).strip(),
                history_session, str(form.get("material", "")).strip(),
                guest_library_id=str(form.get("guest_material_library_id", "")).strip(),
            )
            setting = _exact_setting(_lightburn_module(), path, form.get("material", ""), form.get("setting_description", ""))
            baseline = _normalize_baseline(_serialize_setting(_calibration_base_layer(setting)))
            source_label = f"{form.get('material')} / {form.get('setting_description')}"
        target_rgb = _hex_rgb(form.get("target_color"))
    except (OSError, PermissionError, FileNotFoundError, RuntimeError, ValueError) as error:
        return jsonify({"status": "error", "message": str(error)}), 400
    bind_job_access(session_id, user_id=user_id or None, browser_session=browser_job_session(create=True))
    community = _community_candidates(
        user_id, str(form.get("laser_source", "")).strip(), str(form.get("lens", "")).strip(),
        str(form.get("material", "")).strip(), target_rgb,
    )
    payload = {
        "kind": "color_discovery_session", "session_id": session_id,
        "mode": "target" if target_rgb else "explore", "target_rgb": target_rgb,
        "target_hex": "#{:02X}{:02X}{:02X}".format(*target_rgb) if target_rgb else None,
        "machine": {"laser_source": str(form.get("laser_source", ""))[:160], "lens": str(form.get("lens", ""))[:160]},
        "material": str(form.get("material", ""))[:160], "finish": str(form.get("finish", ""))[:160],
        "baseline": baseline, "baseline_source": source_label, "community_candidates": community,
        "grids": [], "saved_recipes": [],
    }
    _save_session(payload)
    return jsonify({"status": "ok", "session": payload})


@routes.route("/color-discovery/grid", methods=["POST"])
def build_color_discovery_grid():
    _user_id, auth_failure = _validated_submission_identity()
    if auth_failure:
        return auth_failure
    try:
        session = _load_session(str(request.form.get("session_id", "")))
        baseline = _normalize_baseline(json.loads(request.form.get("baseline", "{}")) if request.form.get("baseline") else session["baseline"])
        x_parameter, y_parameter = str(request.form.get("x_parameter", "speed")), str(request.form.get("y_parameter", "frequency"))
        if x_parameter not in PARAMETERS or y_parameter not in PARAMETERS or x_parameter == y_parameter:
            raise ValueError("Choose two different supported sweep parameters.")
        columns = max(2, min(6, int(request.form.get("columns", 5))))
        rows = max(2, min(6, int(request.form.get("rows", 5))))
        if rows * columns > 29:
            raise ValueError("A discovery grid may contain at most 29 cells.")
        total_width_mm = _number(request.form.get("grid_width_mm"), 100, 40, 500)
        total_length_mm = _number(request.form.get("grid_length_mm"), 100, 40, 500)
        x_values = _axis_values(x_parameter, request.form.get("x_low"), request.form.get("x_high"), columns)
        y_values = _axis_values(y_parameter, request.form.get("y_low"), request.form.get("y_high"), rows)
        for x_value in x_values:
            for y_value in y_values:
                candidate = dict(baseline)
                candidate[PARAMETERS[x_parameter]["property"]] = x_value
                candidate[PARAMETERS[y_parameter]["property"]] = y_value
                if float(candidate.get("minPower", 0)) > float(candidate.get("maxPower", 100)):
                    raise ValueError("This sweep would create cells whose minimum power exceeds maximum power.")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, PermissionError, FileNotFoundError) as error:
        return jsonify({"status": "error", "message": str(error)}), 400

    grid_id = str(uuid.uuid4())
    lightburn = _lightburn_module()
    project = lightburn.Lightburn()
    label = _setting_from_values(lightburn, baseline, 0, "Discovery labels", {})
    label.type = "Cut"
    project.add_layer(label)
    top_mm, right_mm, gap_mm = 7.0, 35.0, 1.5
    # The operator-entered dimensions describe the actual test-cell matrix.
    # Labels sit outside that area and must not silently consume its width or
    # length (for example, a 75 mm grid must retain 75 mm of test cells).
    matrix_width, matrix_height = total_width_mm, total_length_mm
    cell_width_mm = (matrix_width - (columns - 1) * gap_mm) / columns
    cell_height_mm = (matrix_height - (rows - 1) * gap_mm) / rows
    if cell_width_mm < 4 or cell_height_mm < 4:
        return jsonify({
            "status": "error",
            "message": "That overall size leaves cells smaller than 4 mm. Increase the grid dimensions or reduce its rows and columns.",
        }), 400
    pitch_x, pitch_y = cell_width_mm + gap_mm, cell_height_mm + gap_mm
    project.add(lightburn.Text(1.2, f"COLOR DISCOVERY {grid_id[:8]}", x=.5, y=1).layer(0))
    cells = []
    for column, value in enumerate(x_values):
        project.add(lightburn.Text(.85, f"{PARAMETERS[x_parameter]['label']} {value:g}", x=column * pitch_x, y=4).layer(0))
    for row, value in enumerate(y_values):
        project.add(lightburn.Text(.85, f"{PARAMETERS[y_parameter]['label']} {value:g}", x=matrix_width + 1, y=top_mm + row * pitch_y).layer(0))
    for row, y_value in enumerate(y_values):
        for column, x_value in enumerate(x_values):
            index = row * columns + column + 1
            overrides = {x_parameter: x_value, y_parameter: y_value}
            name = f"Discovery {index:02d} {x_parameter}={x_value:g} {y_parameter}={y_value:g}"
            layer = _setting_from_values(lightburn, baseline, index, name, overrides)
            project.add_layer(layer)
            x = column * pitch_x + cell_width_mm / 2
            y = top_mm + row * pitch_y + cell_height_mm / 2
            project.add(lightburn.Square(cell_width_mm, cell_height_mm, x=x, y=y).layer(index))
            complete = _serialize_setting(layer)
            cells.append({"index": index, "row": row + 1, "column": column + 1, "overrides": overrides, "setting": complete})
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    filename = f"color_discovery_{session['session_id']}_{grid_id}.lbrn2"
    path = os.path.join(upload_folder, filename)
    try:
        project.write(path)
        _store_artifact(session["session_id"], path)
    except OSError as error:
        return jsonify({"status": "error", "message": f"Could not write the discovery grid: {error}"}), 500
    grid = {
        "grid_id": grid_id, "parent_cell": request.form.get("parent_cell") or None,
        "x_parameter": x_parameter, "y_parameter": y_parameter, "x_values": x_values, "y_values": y_values,
        "columns": columns, "rows": rows, "cell_size_mm": min(cell_width_mm, cell_height_mm),
        "cell_width_mm": cell_width_mm, "cell_height_mm": cell_height_mm,
        "cell_gap_mm": gap_mm, "grid_width_mm": matrix_width, "grid_height_mm": matrix_height,
        "total_width_mm": matrix_width + right_mm,
        "total_length_mm": top_mm + matrix_height,
        "top_label_band_mm": top_mm,
        "right_label_band_mm": right_mm, "left_grid_margin_mm": 0,
        "intervals_mm": [cell["setting"].get("interval", 0) for cell in cells],
        "angles_degrees": [cell["setting"].get("angle", 0) for cell in cells],
        "grating_recipe_signatures": [{"setting": cell["setting"], "overrides": cell["overrides"]} for cell in cells],
        "cells": cells, "lightburn_filename": filename,
    }
    session["grids"].append(grid)
    _save_session(session)
    return jsonify({"status": "ok", "grid": grid, "lightburn_url": f"/color-discovery/download/{filename}"})


@routes.route("/color-discovery/analyze", methods=["POST"])
def analyze_color_discovery_grid():
    _user_id, auth_failure = _validated_submission_identity()
    if auth_failure:
        return auth_failure
    photo = request.files.get("grid_photo")
    try:
        session = _load_session(str(request.form.get("session_id", "")))
        grid = next(item for item in session["grids"] if item["grid_id"] == str(request.form.get("grid_id", "")))
        if not photo or not photo.filename:
            raise ValueError("Choose a photograph of the engraved grid.")
    except (StopIteration, PermissionError, FileNotFoundError, ValueError) as error:
        return jsonify({"status": "error", "message": str(error) or "That grid was not found."}), 400
    extension = os.path.splitext(photo.filename)[1].lower() if os.path.splitext(photo.filename)[1] else ".jpg"
    if extension not in {".jpg", ".jpeg", ".png", ".webp"}:
        return jsonify({"status": "error", "message": "Upload a JPG, PNG, or WebP grid photograph."}), 400
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    photo_name = f"color_discovery_{session['session_id']}_{grid['grid_id']}_photo{extension}"
    photo_path = os.path.join(upload_folder, photo_name)
    photo.save(photo_path)
    try:
        cells, preview, correction, _corners = _measure_grid_photo(photo_path, grid, 0, {"left": 0, "top": 0, "right": 0, "bottom": 0}, 1800)
    except (KeyError, TypeError, ValueError) as error:
        return jsonify({"status": "error", "message": f"Could not measure this grid photo: {error}"}), 400
    for measured, source in zip(cells, grid["cells"]):
        measured["setting"] = source["setting"]
        measured["overrides"] = source["overrides"]
    target_lab = _rgb_lab(session["target_rgb"]) if session.get("target_rgb") else None
    guidance = _grid_guidance(cells, target_lab, grid["x_parameter"], grid["y_parameter"])
    preview_name = f"color_discovery_{session['session_id']}_{grid['grid_id']}_analysis.jpg"
    cv2.imwrite(os.path.join(upload_folder, preview_name), preview)
    grid["analysis"] = {"cells": cells, "guidance": guidance, "preview": preview_name, "correction": correction}
    _save_session(session)
    _store_artifact(session["session_id"], photo_path)
    _store_artifact(session["session_id"], os.path.join(upload_folder, preview_name))
    return jsonify({"status": "ok", "cells": cells, "guidance": guidance, "preview_url": f"/color-discovery/preview/{preview_name}"})


@routes.route("/color-discovery/save-recipes", methods=["POST"])
def save_color_discovery_recipes():
    _user_id, auth_failure = _validated_submission_identity()
    if auth_failure:
        return auth_failure
    try:
        session = _load_session(str(request.form.get("session_id", "")))
        grid = next(item for item in session["grids"] if item["grid_id"] == str(request.form.get("grid_id", "")))
        selected = {int(value) for value in json.loads(request.form.get("selected_cells", "[]"))}
        measured = {cell["index"]: cell for cell in grid.get("analysis", {}).get("cells", [])}
        recipes = []
        for index in selected:
            if index not in measured:
                continue
            cell = measured[index]
            recipes.append({"recipe_id": str(uuid.uuid4()), "grid_id": grid["grid_id"], "cell_index": index, "setting": cell["setting"], "observed_hex": cell["observed_hex"], "observed_lab": cell["observed_lab"], "confidence": cell["confidence"]})
        if not recipes:
            raise ValueError("Select at least one measured cell.")
    except (StopIteration, PermissionError, FileNotFoundError, ValueError, TypeError, json.JSONDecodeError) as error:
        return jsonify({"status": "error", "message": str(error) or "That grid was not found."}), 400
    session["saved_recipes"].extend(recipes)
    _save_session(session)
    return jsonify({"status": "ok", "recipes": recipes, "saved_count": len(session["saved_recipes"])})


@routes.route("/color-discovery/save-to-material-vault", methods=["POST"])
def save_color_discovery_to_material_vault():
    user_id, auth_failure = _validated_submission_identity()
    if auth_failure:
        return auth_failure
    if not user_id:
        return jsonify({"status": "error", "message": "Sign in to save discovered colors to the Material Vault."}), 401
    temp_path = None
    try:
        session = _load_session(str(request.form.get("session_id", "")))
        grid = next(item for item in session["grids"] if item["grid_id"] == str(request.form.get("grid_id", "")))
        selected = {int(value) for value in json.loads(request.form.get("selected_cells", "[]"))}
        measured = {cell["index"]: cell for cell in grid.get("analysis", {}).get("cells", [])}
        cells = [measured[index] for index in sorted(selected) if index in measured]
        if not cells:
            raise ValueError("Select at least one measured cell.")
        material_name = str(request.form.get("material_name", "")).strip()
        if not material_name or len(material_name) > 160:
            raise ValueError("Choose a Material Name between 1 and 160 characters.")
        entry_payloads = _vault_entry_payloads(cells, material_name)
        target_library_id = str(request.form.get("target_library_id", "")).strip()
        new_library_name = str(request.form.get("new_library_name", "")).strip()

        def append_entries(root):
            for payload in entry_payloads:
                apply_entry_update(root, None, payload, creating=True)

        if target_library_id:
            summary = mutate_library(user_id, target_library_id, append_entries)
            if summary is None:
                return jsonify({"status": "error", "message": "That Material Library no longer exists."}), 404
            library = {"library_id": target_library_id}
        else:
            if not new_library_name or len(new_library_name) > 160:
                raise ValueError("Give the new Material Library a name between 1 and 160 characters.")
            root = ET.Element("LightBurnLibrary")
            append_entries(root)
            with tempfile.NamedTemporaryFile(suffix=".clb", delete=False) as temp_file:
                temp_path = temp_file.name
            ET.ElementTree(root).write(temp_path, encoding="utf-8", xml_declaration=True)
            summary = library_entries(temp_path, include_settings=True)
            library = save_user_material_library(
                user_id, temp_path, material_name, summary=summary, display_name=new_library_name,
                source_filename=f"{secure_filename(new_library_name) or 'color-discovery-library'}.clb",
            )
        return jsonify({
            "status": "ok", "library": library, "summary": summary,
            "saved_count": len(entry_payloads),
            "descriptions": [payload["description"] for payload in entry_payloads],
        })
    except (StopIteration, PermissionError, FileNotFoundError, RuntimeError, OSError,
            ValueError, TypeError, json.JSONDecodeError, ET.ParseError) as error:
        return jsonify({"status": "error", "message": str(error) or "That grid was not found."}), 400
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


@routes.route("/color-discovery/session/<session_id>")
def color_discovery_session(session_id):
    try:
        return jsonify({"status": "ok", "session": _load_session(session_id)})
    except PermissionError as error:
        return jsonify({"status": "error", "message": str(error)}), 403
    except FileNotFoundError as error:
        return jsonify({"status": "error", "message": str(error)}), 404


@routes.route("/color-discovery/download/<filename>")
def download_color_discovery(filename):
    filename = os.path.basename(filename)
    parts = filename.split("_")
    if not filename.startswith("color_discovery_") or len(parts) < 4:
        return jsonify({"status": "error", "message": "Invalid discovery artifact."}), 404
    session_id = parts[2]
    if not request_can_access_job(session_id):
        return jsonify({"status": "error", "message": "This artifact is not available to this browser."}), 403
    try:
        return _download_holographic_artifact(current_app.config["UPLOAD_FOLDER"], filename)
    except (FileNotFoundError, RuntimeError):
        return jsonify({"status": "error", "message": "Discovery artifact not found."}), 404


@routes.route("/color-discovery/preview/<filename>")
def preview_color_discovery(filename):
    filename = os.path.basename(filename)
    parts = filename.split("_")
    if not filename.startswith("color_discovery_") or len(parts) < 4 or not request_can_access_job(parts[2]):
        return jsonify({"status": "error", "message": "Preview not found."}), 404
    try:
        path = _ensure_holographic_artifact(current_app.config["UPLOAD_FOLDER"], filename)
    except (FileNotFoundError, RuntimeError):
        return jsonify({"status": "error", "message": "Preview not found."}), 404
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], os.path.basename(path))
