"""Authenticated, durable account preferences and Material Libraries."""

import os
import tempfile
from xml.etree import ElementTree as ET

from flask import jsonify, request
from werkzeug.utils import secure_filename

from lib.lightburn import Lightburn

from services import (
    ABSTRACT_FILTER_NAMES,
    delete_user_material_library,
    download_user_material_library,
    get_user_material_library,
    list_user_material_libraries,
    get_user_preferences,
    get_user_job_history,
    normalize_dimension,
    save_user_preferences,
    save_user_material_library,
)

from . import routes


def authenticated_user_id():
    """Return the ALB-provided Cognito subject for this trusted backend hop."""
    return request.headers.get("x-amzn-oidc-identity", "").strip() or None


def clean_preferences(payload):
    if not isinstance(payload, dict):
        raise ValueError("Preferences must be an object.")
    clean = {}
    material = str(payload.get("material", "")).strip()
    if material:
        clean["material"] = material[:160]
    preset = str(payload.get("image_preset", "")).strip().lower()
    if preset and (preset in {"cartoon", "photograph", "bw_dither_photograph"} or
                   preset.removeprefix("abstract_") in ABSTRACT_FILTER_NAMES):
        clean["image_preset"] = preset
    for key in ("pixel_square_mm", "new_width", "new_height"):
        value = payload.get(key)
        if value is None:
            continue
        if key.startswith("new_"):
            clean[key] = normalize_dimension(value)
        else:
            try:
                clean[key] = max(.0625, min(100, float(value)))
            except (TypeError, ValueError):
                continue
    colors = payload.get("selected_color_hexes")
    if isinstance(colors, list):
        clean["selected_color_hexes"] = [
            str(color).upper() for color in colors[:30]
            if len(str(color)) == 7 and str(color).startswith("#")
        ]
    overrides = payload.get("color_name_overrides")
    if isinstance(overrides, dict):
        clean["color_name_overrides"] = {
            str(color).upper(): str(name).strip()[:80]
            for color, name in list(overrides.items())[:30]
            if len(str(color)) == 7 and str(color).startswith("#") and str(name).strip()
        }
    parameters = payload.get("abstract_filter_parameters")
    if isinstance(parameters, dict):
        clean["abstract_filter_parameters"] = {
            str(key)[:64]: value for key, value in list(parameters.items())[:30]
            if isinstance(value, (bool, int, float))
        }
    return clean


@routes.route("/account/preferences", methods=["GET", "PUT"])
def preferences():
    user_id = authenticated_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Sign in to use account settings."}), 401
    try:
        if request.method == "GET":
            return jsonify({"status": "ok", "preferences": get_user_preferences(user_id)})
        preferences = clean_preferences(request.get_json(silent=True))
        save_user_preferences(user_id, preferences)
        return jsonify({"status": "ok", "preferences": preferences})
    except (RuntimeError, ValueError) as error:
        return jsonify({"status": "error", "message": str(error)}), 400


def library_entries(path):
    """Return a compact, safe-to-display summary of a LightBurn library."""
    settings = Lightburn().parse_material_library(path)
    entries, material_names = [], []
    for setting in settings:
        material_name = str(getattr(setting, "materialName", "") or "").strip()
        if material_name and material_name not in material_names:
            material_names.append(material_name)
        entries.append({
            "material": material_name,
            "description": str(getattr(setting, "entryDesc", "") or "").strip(),
            "type": str(getattr(setting, "type", "") or "").strip(),
        })
    entries.sort(key=lambda entry: (
        entry["material"].casefold(), entry["type"].casefold(), entry["description"].casefold(),
    ))
    return {"entry_count": len(entries), "material_names": material_names, "entries": entries[:500]}


@routes.route("/account/material-libraries", methods=["GET", "POST"])
def material_libraries():
    user_id = authenticated_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Sign in to use saved Material Libraries."}), 401
    try:
        if request.method == "POST":
            files = request.files.getlist("libraries")
            if not files:
                return jsonify({"status": "error", "message": "Choose one or more LightBurn Material Library files."}), 400
            if len(files) > 10:
                return jsonify({"status": "error", "message": "Upload up to 10 Material Library files at a time."}), 400
            uploaded = []
            for file in files:
                filename = secure_filename(file.filename or "")
                if not filename or os.path.splitext(filename)[1].lower() not in {".clb", ".lbmat", ".lbrn"}:
                    return jsonify({"status": "error", "message": "Material Libraries must be .clb, .lbmat, or .lbrn files."}), 400
                with tempfile.NamedTemporaryFile(suffix=os.path.splitext(filename)[1], delete=False) as temp_file:
                    temp_path = temp_file.name
                try:
                    file.save(temp_path)
                    summary = library_entries(temp_path)
                    if not summary["entry_count"]:
                        return jsonify({"status": "error", "message": f"{filename} contains no LightBurn Material Library entries."}), 400
                    library = save_user_material_library(
                        user_id, temp_path,
                        ", ".join(summary["material_names"])[:160], summary=summary,
                    )
                    library["summary"] = summary
                    uploaded.append(library)
                finally:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
            return jsonify({"status": "ok", "libraries": uploaded}), 201
        libraries = list_user_material_libraries(user_id)
        return jsonify({"status": "ok", "libraries": [
            {
                "library_id": item.get("library_id"),
                "name": item.get("name", "Saved Material Library"),
                "material_name": item.get("material_name", ""),
                "summary": item.get("summary", {}),
            }
            for item in libraries
        ]})
    except (RuntimeError, OSError, ValueError, ET.ParseError) as error:
        return jsonify({"status": "error", "message": str(error)}), 400


@routes.route("/account/material-libraries/<library_id>", methods=["GET", "DELETE"])
def material_library_detail(library_id):
    user_id = authenticated_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Sign in to manage Material Libraries."}), 401
    try:
        if request.method == "DELETE":
            if not delete_user_material_library(user_id, library_id):
                return jsonify({"status": "error", "message": "That Material Library no longer exists."}), 404
            return jsonify({"status": "ok"})
        library = get_user_material_library(user_id, library_id)
        if not library:
            return jsonify({"status": "error", "message": "That Material Library no longer exists."}), 404
        with tempfile.NamedTemporaryFile(suffix=os.path.splitext(library.get("name", ""))[1], delete=False) as temp_file:
            temp_path = temp_file.name
        try:
            download_user_material_library(library, temp_path)
            return jsonify({"status": "ok", "library": {"library_id": library_id, "name": library.get("name", "Material Library"), "summary": library_entries(temp_path)}})
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
    except (RuntimeError, OSError, ValueError, ET.ParseError) as error:
        return jsonify({"status": "error", "message": f"Could not read this Material Library: {error}"}), 400


@routes.route("/account/jobs")
def jobs():
    user_id = authenticated_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Sign in to use account job history."}), 401
    try:
        return jsonify({"status": "ok", "files": get_user_job_history(user_id)})
    except RuntimeError as error:
        return jsonify({"status": "error", "message": str(error)}), 400
