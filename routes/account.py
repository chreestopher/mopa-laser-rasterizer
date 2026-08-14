"""Authenticated, durable account preferences."""

from flask import jsonify, request

from services import (
    ABSTRACT_FILTER_NAMES,
    list_user_material_libraries,
    get_user_preferences,
    normalize_dimension,
    save_user_preferences,
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


@routes.route("/account/material-libraries")
def material_libraries():
    user_id = authenticated_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Sign in to use saved Material Libraries."}), 401
    try:
        libraries = list_user_material_libraries(user_id)
        return jsonify({"status": "ok", "libraries": [
            {
                "library_id": item.get("library_id"),
                "name": item.get("name", "Saved Material Library"),
                "material_name": item.get("material_name", ""),
            }
            for item in libraries
        ]})
    except RuntimeError as error:
        return jsonify({"status": "error", "message": str(error)}), 400
