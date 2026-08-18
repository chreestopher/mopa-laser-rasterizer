"""Authenticated preferences, Material Libraries, and Holographic Recipes."""

import os
import tempfile
import json
import io
import math
from copy import deepcopy
from xml.etree import ElementTree as ET

from flask import jsonify, request, send_file
from werkzeug.utils import secure_filename

from lib.lightburn import Lightburn

from services import (
    ABSTRACT_FILTER_NAMES,
    LIGHTBURN_PALETTE_NAMES,
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
    preserved_layer_identity = {
        child.tag: child.attrib.get("Value", "")
        for child in cut
        if child.tag in {"index", "name"}
    }
    for child in list(cut):
        if child.tag != "SubLayer":
            cut.remove(child)
    defaults = {"index": "0", "name": "", "minPower": "0", "maxPower": "100", "speed": "100"}
    defaults.update(preserved_layer_identity)
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
        summary = library_entries(temp_path, include_settings=True)
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


def material_coupon_project(library_root, material_name="Material Library Settings",
                            coupon_width_mm=100.0, coupon_length_mm=100.0,
                            cell_size_mm=10.0, column_gap_mm=2.0, label_space_mm=6.0):
    """Build a compact LightBurn test grid from selected library entries."""
    entries = all_xml_entries(library_root)
    if not entries:
        raise ValueError("Select at least one Material Library setting.")
    if len(entries) > 29:
        raise ValueError("A labeled LightBurn coupon can contain no more than 29 selected settings.")
    try:
        coupon_width_mm = float(coupon_width_mm)
        coupon_length_mm = float(coupon_length_mm)
    except (TypeError, ValueError) as error:
        raise ValueError("Coupon width and length must be numbers in millimeters.") from error
    if not 10 <= coupon_width_mm <= 1000 or not 10 <= coupon_length_mm <= 1000:
        raise ValueError("Coupon width and length must each be between 10 and 1000 mm.")

    project = ET.Element("LightBurnProject", {
        "AppVersion": "2.1.04", "FormatVersion": "1", "MaterialHeight": "0",
        "MirrorX": "False", "MirrorY": "True", "AskForSendName": "True",
    })
    columns = min(10, max(1, math.ceil(math.sqrt(len(entries)))))
    rows = math.ceil(len(entries) / columns)
    horizontal_pitch = cell_size_mm + column_gap_mm
    vertical_pitch = cell_size_mm + label_space_mm
    native_width = columns * cell_size_mm + max(0, columns - 1) * column_gap_mm
    native_length = 8 + (rows - 1) * vertical_pitch + label_space_mm / 2 + cell_size_mm
    scale_x = coupon_width_mm / native_width
    scale_y = coupon_length_mm / native_length

    def transform(x, y):
        return f"{scale_x:g} 0 0 {scale_y:g} {x * scale_x:g} {y * scale_y:g}"

    def fitted_text_height(text, available_width, preferred_height):
        # Arial's typical glyph width is roughly 0.6 times its height. Keep
        # titles and labels inside the coupon before the whole card is scaled.
        estimated_units = max(1.0, len(str(text)) * 0.62)
        return min(preferred_height, available_width / estimated_units)

    # Layer zero is LightBurn's black layer. Reuse the selected Black recipe
    # when available; otherwise copy the first selected recipe so labels have
    # explicit, inspectable parameters rather than invented laser settings.
    black_entry = next(
        (entry for _material, entry in entries
         if str(entry.attrib.get("Desc", "")).strip().casefold() == "black"),
        entries[0][1],
    )
    label_layer = deepcopy(black_entry.find("CutSetting"))
    label_index = label_layer.find("index")
    if label_index is None:
        label_index = ET.Element("index")
        label_layer.insert(0, label_index)
    label_index.attrib["Value"] = "0"
    label_name = label_layer.find("name")
    if label_name is None:
        label_name = ET.Element("name")
        label_layer.insert(1, label_name)
    label_name.attrib["Value"] = "Coupon labels"
    project.append(label_layer)

    objects = []
    title_text = str(material_name)[:120]
    title = ET.Element("Shape", {
        "Type": "Text", "ShapeID": "0", "CutIndex": "0",
        "Font": "Arial,-1,100,5,50,0,0,0,0,0", "Str": title_text,
        "H": f"{fitted_text_height(title_text, native_width, 3):g}", "LS": "0", "LnS": "0", "Ah": "0", "Av": "1",
        "Weld": "1", "HasBackupPath": "0",
    })
    title.attrib["Ah"] = "1"
    ET.SubElement(title, "XForm").text = transform(native_width / 2, 3)
    objects.append(title)
    boundary = ET.Element("Shape", {
        "Type": "Rect", "ShapeID": "1", "CutIndex": "0",
        "W": f"{native_width:g}", "H": f"{native_length:g}", "Cr": "0",
    })
    ET.SubElement(boundary, "XForm").text = transform(native_width / 2, native_length / 2)
    objects.append(boundary)

    for layer_index, (_material, entry) in enumerate(entries):
        cut_setting = entry.find("CutSetting")
        if cut_setting is None:
            continue
        layer = deepcopy(cut_setting)
        index_element = layer.find("index")
        if index_element is None:
            index_element = ET.Element("index")
            layer.insert(0, index_element)
        cut_index = layer_index + 1
        index_element.attrib["Value"] = str(cut_index)
        name_element = layer.find("name")
        if name_element is None:
            name_element = ET.Element("name")
            layer.insert(1, name_element)
        name_element.attrib["Value"] = str(entry.attrib.get("Desc") or f"Coupon {layer_index + 1}")[:80]
        project.append(layer)

        row, column = divmod(layer_index, columns)
        x = cell_size_mm / 2 + column * horizontal_pitch
        label_y = 8 + row * vertical_pitch
        cell_y = label_y + label_space_mm / 2 + cell_size_mm / 2
        label_text = str(entry.attrib.get("Desc") or f"Cell {layer_index + 1}")[:80]
        label = ET.Element("Shape", {
            "Type": "Text", "ShapeID": str(layer_index * 2 + 2), "CutIndex": "0",
            "Font": "Arial,-1,100,5,50,0,0,0,0,0", "Str": str(entry.attrib.get("Desc") or f"Cell {layer_index + 1}")[:80],
            "H": f"{fitted_text_height(label_text, horizontal_pitch, 2):g}", "LS": "0", "LnS": "0", "Ah": "1", "Av": "1",
            "Weld": "1", "HasBackupPath": "0",
        })
        ET.SubElement(label, "XForm").text = transform(x, label_y)
        objects.append(label)
        shape = ET.Element("Shape", {
            "Type": "Rect", "ShapeID": str(layer_index * 2 + 3), "CutIndex": str(cut_index),
            "W": f"{cell_size_mm:g}", "H": f"{cell_size_mm:g}", "Cr": "0",
        })
        ET.SubElement(shape, "XForm").text = transform(x, cell_y)
        objects.append(shape)
    project.extend(objects)
    return project


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
            if action == "coupon":
                coupon_root = material_coupon_project(
                    root, material_name=material_name,
                    coupon_width_mm=payload.get("coupon_width_mm"),
                    coupon_length_mm=payload.get("coupon_length_mm"),
                )
                coupon_data = ET.tostring(coupon_root, encoding="utf-8", xml_declaration=True)
                filename = f"{secure_filename(material_name) or 'rasterizer-material'}-coupon.lbrn2"
                return send_file(io.BytesIO(coupon_data), mimetype="application/xml",
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
                "laser_community": item.get("laser_community") is True,
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
            existing_library = get_user_material_library(user_id, library_id)
            if not existing_library:
                return jsonify({"status": "error", "message": "That Material Library no longer exists."}), 404
            laser_community = existing_library.get("laser_community") is True or payload.get("laser_community") is True
            community_summary = None
            if laser_community:
                with tempfile.NamedTemporaryFile(suffix=".clb", delete=False) as community_file:
                    community_path = community_file.name
                try:
                    download_user_material_library(existing_library, community_path)
                    community_summary = library_entries(community_path, include_settings=True)
                finally:
                    if os.path.exists(community_path):
                        os.remove(community_path)
            if not rename_user_material_library(
                user_id, library_id, payload.get("name"),
                payload.get("laser_source"), payload.get("lens_field_of_view"), payload.get("notes"),
                laser_community,
                community_summary,
            ):
                return jsonify({"status": "error", "message": "That Material Library no longer exists."}), 404
            return jsonify({
                "status": "ok", "name": str(payload.get("name")).strip(),
                "laser_source": str(payload.get("laser_source") or "").strip(),
                "lens_field_of_view": str(payload.get("lens_field_of_view") or "").strip(),
                "notes": str(payload.get("notes") or "").strip(),
                "laser_community": laser_community,
            })
        library = get_user_material_library(user_id, library_id)
        if not library:
            return jsonify({"status": "error", "message": "That Material Library no longer exists."}), 404
        with tempfile.NamedTemporaryFile(suffix=os.path.splitext(library.get("name", ""))[1], delete=False) as temp_file:
            temp_path = temp_file.name
        try:
            download_user_material_library(library, temp_path)
            return jsonify({"status": "ok", "library": {"library_id": library_id, "name": library.get("name", "Material Library"), "laser_source": library.get("laser_source", ""), "lens_field_of_view": library.get("lens_field_of_view", ""), "notes": library.get("notes", ""), "laser_community": library.get("laser_community") is True, "summary": library_entries(temp_path, include_settings=True)}})
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
