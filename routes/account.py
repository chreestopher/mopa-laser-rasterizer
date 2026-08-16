"""Authenticated preferences, Material Libraries, and Holographic Recipes."""

import os
import tempfile
import json
import io
from copy import deepcopy
from xml.etree import ElementTree as ET

from flask import jsonify, request, send_file
from werkzeug.utils import secure_filename

from lib.lightburn import Lightburn

from services import (
    ABSTRACT_FILTER_NAMES,
    delete_user_material_library,
    delete_user_holographic_recipe,
    download_user_holographic_recipe,
    download_user_material_library,
    get_user_material_library,
    get_user_holographic_recipe,
    list_user_holographic_recipes,
    list_user_material_libraries,
    get_user_preferences,
    get_user_job_history,
    normalize_dimension,
    save_user_preferences,
    save_user_material_library,
    save_user_holographic_recipe,
    rename_user_material_library,
    update_user_material_library_file,
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
            str(color).upper() for color in colors[:64]
            if len(str(color)) == 7 and str(color).startswith("#")
        ]
    overrides = payload.get("color_name_overrides")
    if isinstance(overrides, dict):
        clean["color_name_overrides"] = {
            str(color).upper(): str(name).strip()[:80]
            for color, name in list(overrides.items())[:64]
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


def setting_values(setting):
    """Serialize the meaningful primitive values from one LightBurn setting."""
    hidden = {"materialName", "entryDesc", "entryThickness", "entryNoThickTitle", "subLayers"}
    values = {}
    for key, value in vars(setting).items():
        if key in hidden or value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            values[key] = value
    if getattr(setting, "subLayers", None):
        values["subLayers"] = [setting_values(layer) for layer in setting.subLayers]
    return values


def library_entries(path, include_settings=False):
    """Return a compact, safe-to-display summary of a LightBurn library."""
    settings = Lightburn().parse_material_library(path)
    entries, material_names = [], []
    for entry_id, setting in enumerate(settings):
        material_name = str(getattr(setting, "materialName", "") or "").strip()
        if material_name and material_name not in material_names:
            material_names.append(material_name)
        entry = {
            "material": material_name,
            "description": str(getattr(setting, "entryDesc", "") or "").strip(),
            "type": str(getattr(setting, "type", "") or "").strip(),
        }
        if include_settings:
            entry["settings"] = setting_values(setting)
            entry["entry_id"] = entry_id
        entries.append(entry)
    entries.sort(key=lambda entry: (
        entry["material"].casefold(), entry["type"].casefold(), entry["description"].casefold(),
    ))
    return {"entry_count": len(entries), "material_names": material_names, "entries": entries[:500]}


def uploaded_library_files():
    files = request.files.getlist("libraries")
    if not files:
        raise ValueError("Choose one or more LightBurn Material Library files.")
    if len(files) > 10:
        raise ValueError("Upload up to 10 Material Library files at a time.")
    clean = []
    for file in files:
        filename = secure_filename(file.filename or "")
        if not filename or os.path.splitext(filename)[1].lower() not in {".clb", ".lbmat", ".lbrn"}:
            raise ValueError("Material Libraries must be .clb, .lbmat, or .lbrn files.")
        clean.append((file, filename))
    return clean


def holographic_recipe_summary(path):
    with open(path, encoding="utf-8") as recipe_file:
        payload = json.load(recipe_file)
    recipes = payload.get("recipes")
    if payload.get("kind") != "holographic_calibration_profile" or not isinstance(recipes, list) or not recipes:
        raise ValueError("Choose a Holographic Etching Recipe JSON file with at least one saved recipe.")
    return {
        "profile_name": str(payload.get("profile_name") or "").strip()[:160],
        "recipe_count": len(recipes),
        "material": str(payload.get("grid", {}).get("material") or "").strip()[:160],
    }


@routes.route("/account/holographic-recipes", methods=["GET", "POST"])
def holographic_recipes():
    user_id = authenticated_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Sign in to use saved Holographic Recipes."}), 401
    try:
        if request.method == "GET":
            return jsonify({"status": "ok", "recipes": [{
                "recipe_id": recipe.get("recipe_id"),
                "name": recipe.get("name", "Holographic Recipe"),
                "original_name": recipe.get("original_name", ""),
                "metadata": recipe.get("metadata", {}),
                "created_at": recipe.get("created_at"),
            } for recipe in list_user_holographic_recipes(user_id)]})
        upload = request.files.get("recipe")
        filename = secure_filename(upload.filename if upload else "")
        if not upload or not filename or os.path.splitext(filename)[1].lower() != ".json":
            raise ValueError("Choose a Holographic Etching Recipe JSON file.")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as temp_file:
            temp_path = temp_file.name
        try:
            upload.save(temp_path)
            metadata = holographic_recipe_summary(temp_path)
            recipe = save_user_holographic_recipe(
                user_id, temp_path, request.form.get("name") or metadata.get("profile_name"),
                metadata=metadata, source_filename=filename,
            )
            return jsonify({"status": "ok", "recipe": recipe}), 201
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
    except (RuntimeError, OSError, ValueError, json.JSONDecodeError) as error:
        return jsonify({"status": "error", "message": str(error)}), 400


@routes.route("/account/holographic-recipes/<recipe_id>", methods=["GET", "DELETE"])
def holographic_recipe_detail(recipe_id):
    user_id = authenticated_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Sign in to manage Holographic Recipes."}), 401
    try:
        recipe = get_user_holographic_recipe(user_id, recipe_id)
        if not recipe:
            return jsonify({"status": "error", "message": "That Holographic Recipe no longer exists."}), 404
        if request.method == "DELETE":
            delete_user_holographic_recipe(user_id, recipe_id)
            return jsonify({"status": "ok"})
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as temp_file:
            temp_path = temp_file.name
        try:
            download_user_holographic_recipe(recipe, temp_path)
            with open(temp_path, "rb") as recipe_file:
                contents = recipe_file.read()
            return send_file(
                io.BytesIO(contents), as_attachment=True,
                download_name=recipe.get("original_name") or "holographic-recipe.json",
                mimetype="application/json",
            )
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
    except RuntimeError as error:
        return jsonify({"status": "error", "message": str(error)}), 400


def filtered_material_library(source_path, destination_path, selected_materials):
    tree = ET.parse(source_path)
    root = tree.getroot()
    selected = {str(material).strip() for material in selected_materials}
    for material in root.findall("Material"):
        if str(material.attrib.get("name", "")).strip() not in selected:
            root.remove(material)
    tree.write(destination_path, encoding="utf-8", xml_declaration=True)


def all_xml_entries(root):
    return [(material, entry) for material in root.findall("Material") for entry in material.findall("Entry")]


def setting_value(value):
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def apply_entry_update(root, entry_id, payload, creating=False):
    material_name = str(payload.get("material", "")).strip()
    description = str(payload.get("description", "")).strip()
    setting_type = str(payload.get("type", "Scan")).strip()
    values = payload.get("settings", {})
    if not material_name or not description or setting_type not in {"Cut", "Scan", "Image", "Offset"}:
        raise ValueError("Material, Description, and a valid setting Type are required.")
    if not isinstance(values, dict) or len(values) > 80:
        raise ValueError("Settings must be a small object.")
    entries = all_xml_entries(root)
    if creating:
        entry = ET.Element("Entry", {"Thickness": "0", "Desc": description, "NoThickTitle": "1"})
    else:
        if entry_id < 0 or entry_id >= len(entries):
            raise ValueError("That Material Library entry no longer exists.")
        old_material, entry = entries[entry_id]
        old_material.remove(entry)
    target = next((material for material in root.findall("Material") if material.attrib.get("name") == material_name), None)
    if target is None:
        target = ET.SubElement(root, "Material", {"name": material_name})
    entry.attrib["Desc"] = description
    entry.attrib.setdefault("Thickness", "0")
    entry.attrib.setdefault("NoThickTitle", "1")
    cut = entry.find("CutSetting")
    if cut is None:
        cut = ET.SubElement(entry, "CutSetting")
    cut.attrib["type"] = setting_type
    for child in list(cut):
        if child.tag != "SubLayer":
            cut.remove(child)
    defaults = {"index": "0", "name": "", "minPower": "0", "maxPower": "100", "speed": "100"}
    defaults.update({str(key): setting_value(value) for key, value in values.items() if str(key) and isinstance(value, (str, int, float, bool))})
    for key, value in defaults.items():
        ET.SubElement(cut, key, {"Value": value})
    target.append(entry)
    for material in list(root.findall("Material")):
        if not material.findall("Entry"):
            root.remove(material)


def mutate_library(user_id, library_id, callback):
    library = get_user_material_library(user_id, library_id)
    if not library:
        return None
    with tempfile.NamedTemporaryFile(suffix=".clb", delete=False) as temp_file:
        temp_path = temp_file.name
    try:
        download_user_material_library(library, temp_path)
        tree = ET.parse(temp_path)
        callback(tree.getroot())
        tree.write(temp_path, encoding="utf-8", xml_declaration=True)
        summary = library_entries(temp_path)
        update_user_material_library_file(user_id, library_id, temp_path, summary)
        return summary
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def selected_settings_library(user_id, selections, material_name):
    """Build a valid LightBurn library containing only account-owned selections."""
    if not isinstance(selections, list) or not selections or len(selections) > 500:
        raise ValueError("Select between 1 and 500 Material Library settings.")
    material_name = str(material_name or "").strip()
    if not material_name or len(material_name) > 160:
        raise ValueError("Provide a Material Name between 1 and 160 characters.")

    requested = {}
    for selection in selections:
        if not isinstance(selection, dict):
            raise ValueError("The selected settings are invalid.")
        library_id = str(selection.get("library_id", "")).strip()
        entry_id = selection.get("entry_id")
        if not library_id or not isinstance(entry_id, int) or entry_id < 0:
            raise ValueError("The selected settings are invalid.")
        requested.setdefault(library_id, set()).add(entry_id)

    target_root = ET.Element("LightBurnLibrary")
    target_material = ET.SubElement(target_root, "Material", {"name": material_name})
    temp_paths = []
    try:
        for library_id, entry_ids in requested.items():
            library = get_user_material_library(user_id, library_id)
            if not library:
                raise ValueError("One of the selected Material Libraries no longer exists.")
            with tempfile.NamedTemporaryFile(suffix=".clb", delete=False) as temp_file:
                temp_path = temp_file.name
            temp_paths.append(temp_path)
            download_user_material_library(library, temp_path)
            entries = all_xml_entries(ET.parse(temp_path).getroot())
            for entry_id in sorted(entry_ids):
                if entry_id >= len(entries):
                    raise ValueError("One of the selected settings no longer exists.")
                target_material.append(deepcopy(entries[entry_id][1]))
        if not target_material.findall("Entry"):
            raise ValueError("Select at least one Material Library setting.")
        return target_root
    finally:
        for temp_path in temp_paths:
            if os.path.exists(temp_path):
                os.remove(temp_path)


@routes.route("/account/material-libraries/selected-settings", methods=["POST"])
def selected_material_library_settings():
    """Copy or export selected settings while preserving LightBurn XML intact."""
    user_id = authenticated_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Sign in to manage Material Libraries."}), 401
    payload = request.get_json(silent=True) or {}
    action = str(payload.get("action", "")).strip()
    try:
        root = selected_settings_library(user_id, payload.get("selections"), payload.get("material_name"))
        with tempfile.NamedTemporaryFile(suffix=".clb", delete=False) as temp_file:
            output_path = temp_file.name
        try:
            ET.ElementTree(root).write(output_path, encoding="utf-8", xml_declaration=True)
            summary = library_entries(output_path)
            material_name = str(payload.get("material_name")).strip()
            if action == "copy_existing":
                target_library_id = str(payload.get("target_library_id", "")).strip()
                if not target_library_id:
                    raise ValueError("Choose the library that should receive these settings.")
                source_material = root.find("Material")
                source_entries = list(source_material) if source_material is not None else []

                def append_selected_entries(target_root):
                    destination = next(
                        (item for item in target_root.findall("Material") if item.attrib.get("name") == material_name),
                        None,
                    )
                    if destination is None:
                        destination = ET.SubElement(target_root, "Material", {"name": material_name})
                    destination.extend(deepcopy(source_entries))

                result = mutate_library(user_id, target_library_id, append_selected_entries)
                if result is None:
                    return jsonify({"status": "error", "message": "The destination Material Library no longer exists."}), 404
                return jsonify({"status": "ok", "summary": result})
            if action == "copy_new":
                name = str(payload.get("new_library_name", "")).strip()
                if not name or len(name) > 160:
                    raise ValueError("Give the new Material Library a name between 1 and 160 characters.")
                library = save_user_material_library(
                    user_id, output_path, material_name, summary=summary, display_name=name,
                    source_filename=f"{secure_filename(name) or 'rasterizer-material-library'}.clb",
                )
                return jsonify({"status": "ok", "library": library})
            if action == "export":
                filename = f"{secure_filename(material_name) or 'rasterizer-material-settings'}.clb"
                with open(output_path, "rb") as export_file:
                    return send_file(io.BytesIO(export_file.read()), mimetype="application/xml",
                                     as_attachment=True, download_name=filename)
            raise ValueError("Choose an action for the selected settings.")
        finally:
            if os.path.exists(output_path):
                os.remove(output_path)
    except (RuntimeError, OSError, ValueError, ET.ParseError) as error:
        return jsonify({"status": "error", "message": str(error)}), 400


@routes.route("/account/material-libraries/preview", methods=["POST"])
def preview_material_libraries():
    user_id = authenticated_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Sign in to manage Material Libraries."}), 401
    temp_paths = []
    try:
        previews = []
        for index, (file, filename) in enumerate(uploaded_library_files()):
            with tempfile.NamedTemporaryFile(suffix=os.path.splitext(filename)[1], delete=False) as temp_file:
                temp_path = temp_file.name
            temp_paths.append(temp_path)
            file.save(temp_path)
            summary = library_entries(temp_path)
            if not summary["entry_count"]:
                raise ValueError(f"{filename} contains no LightBurn Material Library entries.")
            previews.append({"index": index, "filename": filename, "summary": summary})
        return jsonify({"status": "ok", "libraries": previews})
    except (RuntimeError, OSError, ValueError, ET.ParseError) as error:
        return jsonify({"status": "error", "message": str(error)}), 400
    finally:
        for temp_path in temp_paths:
            if os.path.exists(temp_path):
                os.remove(temp_path)


@routes.route("/account/material-libraries/new", methods=["POST"])
def new_material_library():
    user_id = authenticated_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Sign in to create a Material Library."}), 401
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    if not name or len(name) > 160:
        return jsonify({"status": "error", "message": "Library names must be between 1 and 160 characters."}), 400
    with tempfile.NamedTemporaryFile(suffix=".clb", delete=False) as temp_file:
        temp_path = temp_file.name
    try:
        ET.ElementTree(ET.Element("LightBurnLibrary")).write(temp_path, encoding="utf-8", xml_declaration=True)
        library = save_user_material_library(user_id, temp_path, "", summary=library_entries(temp_path),
                                             display_name=name, source_filename=f"{secure_filename(name) or 'material-library'}.clb")
        return jsonify({"status": "ok", "library": library}), 201
    except (RuntimeError, OSError, ValueError, ET.ParseError) as error:
        return jsonify({"status": "error", "message": str(error)}), 400
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@routes.route("/account/material-libraries", methods=["GET", "POST"])
def material_libraries():
    user_id = authenticated_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Sign in to use saved Material Libraries."}), 401
    try:
        if request.method == "POST":
            try:
                library_names = json.loads(request.form.get("library_names", "{}"))
                selected_by_file = json.loads(request.form.get("selected_materials", "{}"))
            except json.JSONDecodeError as error:
                raise ValueError("The selected library information is invalid.") from error
            if not isinstance(library_names, dict) or not isinstance(selected_by_file, dict):
                raise ValueError("The selected library information is invalid.")
            uploaded = []
            for index, (file, filename) in enumerate(uploaded_library_files()):
                selected_materials = selected_by_file.get(str(index), [])
                if not isinstance(selected_materials, list) or not selected_materials:
                    raise ValueError(f"Choose at least one material from {filename}.")
                display_name = str(library_names.get(str(index), os.path.splitext(filename)[0])).strip()
                with tempfile.NamedTemporaryFile(suffix=os.path.splitext(filename)[1], delete=False) as temp_file:
                    temp_path = temp_file.name
                with tempfile.NamedTemporaryFile(suffix=os.path.splitext(filename)[1], delete=False) as filtered_file:
                    filtered_path = filtered_file.name
                try:
                    file.save(temp_path)
                    filtered_material_library(temp_path, filtered_path, selected_materials)
                    summary = library_entries(filtered_path)
                    if not summary["entry_count"]:
                        raise ValueError(f"{filename} contains no selected Material Library entries.")
                    library = save_user_material_library(
                        user_id, filtered_path,
                        ", ".join(summary["material_names"])[:160], summary=summary,
                        display_name=display_name, source_filename=filename,
                    )
                    library["summary"] = summary
                    uploaded.append(library)
                finally:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                    if os.path.exists(filtered_path):
                        os.remove(filtered_path)
            return jsonify({"status": "ok", "libraries": uploaded}), 201
        libraries = list_user_material_libraries(user_id)
        return jsonify({"status": "ok", "libraries": [
            {
                "library_id": item.get("library_id"),
                "name": item.get("name", "Saved Material Library"),
                "material_name": item.get("material_name", ""),
                "laser_source": item.get("laser_source", ""),
                "lens_field_of_view": item.get("lens_field_of_view", ""),
                "notes": item.get("notes", ""),
                "summary": item.get("summary", {}),
            }
            for item in libraries
        ]})
    except (RuntimeError, OSError, ValueError, ET.ParseError) as error:
        return jsonify({"status": "error", "message": str(error)}), 400


@routes.route("/account/material-libraries/<library_id>", methods=["GET", "PATCH", "DELETE"])
def material_library_detail(library_id):
    user_id = authenticated_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Sign in to manage Material Libraries."}), 401
    try:
        if request.method == "DELETE":
            if not delete_user_material_library(user_id, library_id):
                return jsonify({"status": "error", "message": "That Material Library no longer exists."}), 404
            return jsonify({"status": "ok"})
        if request.method == "PATCH":
            payload = request.get_json(silent=True) or {}
            if not rename_user_material_library(
                user_id, library_id, payload.get("name"),
                payload.get("laser_source"), payload.get("lens_field_of_view"), payload.get("notes"),
            ):
                return jsonify({"status": "error", "message": "That Material Library no longer exists."}), 404
            return jsonify({
                "status": "ok", "name": str(payload.get("name")).strip(),
                "laser_source": str(payload.get("laser_source") or "").strip(),
                "lens_field_of_view": str(payload.get("lens_field_of_view") or "").strip(),
                "notes": str(payload.get("notes") or "").strip(),
            })
        library = get_user_material_library(user_id, library_id)
        if not library:
            return jsonify({"status": "error", "message": "That Material Library no longer exists."}), 404
        with tempfile.NamedTemporaryFile(suffix=os.path.splitext(library.get("name", ""))[1], delete=False) as temp_file:
            temp_path = temp_file.name
        try:
            download_user_material_library(library, temp_path)
            return jsonify({"status": "ok", "library": {"library_id": library_id, "name": library.get("name", "Material Library"), "laser_source": library.get("laser_source", ""), "lens_field_of_view": library.get("lens_field_of_view", ""), "notes": library.get("notes", ""), "summary": library_entries(temp_path, include_settings=True)}})
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
    except (RuntimeError, OSError, ValueError, ET.ParseError) as error:
        return jsonify({"status": "error", "message": f"Could not read this Material Library: {error}"}), 400


@routes.route("/account/material-libraries/<library_id>/entries", methods=["POST"])
@routes.route("/account/material-libraries/<library_id>/entries/<int:entry_id>", methods=["PATCH"])
def edit_material_library_entry(library_id, entry_id=None):
    user_id = authenticated_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Sign in to edit Material Libraries."}), 401
    payload = request.get_json(silent=True) or {}
    try:
        summary = mutate_library(
            user_id, library_id,
            lambda root: apply_entry_update(root, entry_id, payload, creating=request.method == "POST"),
        )
        if summary is None:
            return jsonify({"status": "error", "message": "That Material Library no longer exists."}), 404
        return jsonify({"status": "ok", "summary": summary})
    except (RuntimeError, OSError, ValueError, ET.ParseError) as error:
        return jsonify({"status": "error", "message": str(error)}), 400


@routes.route("/account/jobs")
def jobs():
    user_id = authenticated_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Sign in to use account job history."}), 401
    try:
        return jsonify({"status": "ok", "files": get_user_job_history(user_id)})
    except RuntimeError as error:
        return jsonify({"status": "error", "message": str(error)}), 400
