"""Job submission, status, history, preview, and download routes."""

import glob
import os
import threading
import time
import uuid

from flask import current_app, jsonify, make_response, redirect, render_template, request, send_from_directory
from werkzeug.utils import secure_filename

from . import routes
from services import (
    ABSTRACT_FILTER_NAMES,
    HISTORY_TTL_SECONDS,
    add_history_entry,
    cleanup_redis_inflight,
    get_history_entries,
    long_running_script,
    normalize_dimension,
    parse_abstract_filter_parameters,
    parse_color_name_overrides,
    redis_client,
    tasks,
    valid_history_session,
)


@routes.route("/upload", methods=["GET", "POST"])
def start_task():
    if request.method == "GET":
        return redirect("/")
    if "image" not in request.files or "material_settings" not in request.files:
        return jsonify({"status": "error", "message": "Missing required files"}), 400
    image_file, material_settings = request.files["image"], request.files["material_settings"]
    if not image_file.filename or not material_settings.filename:
        return jsonify({"status": "error", "message": "Empty file names uploaded"}), 400

    task_id = str(uuid.uuid4())
    base_name = secure_filename(image_file.filename)
    output_name = f"output_{task_id}_{base_name}"
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    image_path = os.path.join(upload_folder, f"{task_id}_{base_name}")
    material_settings_path = os.path.join(upload_folder, f"{task_id}_{secure_filename(material_settings.filename)}")
    image_file.save(image_path)
    material_settings.save(material_settings_path)

    user_data = request.form.to_dict()
    user_data["new_width"] = str(normalize_dimension(user_data.get("new_width")))
    user_data["new_height"] = str(normalize_dimension(user_data.get("new_height")))
    history_session = (valid_history_session(user_data.get("history_session"))
        or valid_history_session(request.cookies.get("mopa_history_session")) or str(uuid.uuid4()))
    try:
        submitted_preset = str(user_data.get("image_preset", "cartoon")).strip().lower()
        material_name = str(user_data.get("material", "stainless - steel")).strip().lower()
        if not material_name:
            raise ValueError("Choose or enter a material name")
        filter_name = submitted_preset.removeprefix("abstract_")
        if submitted_preset.startswith("abstract_") and filter_name not in ABSTRACT_FILTER_NAMES:
            raise ValueError("Unknown abstract filter")
        parse_abstract_filter_parameters(user_data.get("abstract_filter_parameters", "{}"))
        parse_color_name_overrides(user_data.get("color_name_overrides", "{}"))
    except ValueError as error:
        return jsonify({"status": "error", "message": str(error)}), 400

    tasks[f"{task_id}_status"] = "pending"
    tasks[f"{task_id}_logs"] = ["Waiting to start..."]
    tasks[f"{task_id}_filename"] = output_name
    tasks[f"{task_id}_error"] = None
    # Register the status before recording history.  Otherwise the history
    # reader can see a brand-new entry before its worker starts and mistake it
    # for an expired task.
    redis_client.set(f"task:{task_id}:status", "pending", ex=HISTORY_TTL_SECONDS)
    submitted_preset = str(user_data.get("image_preset", "cartoon")).strip().lower()
    submitted_filter = (
        submitted_preset.removeprefix("abstract_")
        if submitted_preset.startswith("abstract_") else None
    )
    add_history_entry(history_session, task_id, base_name, submitted_preset, submitted_filter, material_name)
    history_files = get_history_entries(history_session)
    if not any(item.get("task_id") == task_id for item in history_files):
        history_files.insert(0, {"task_id": task_id, "source_name": base_name,
            "image_preset": submitted_preset,
            "abstract_filter": submitted_filter,
            "material_name": material_name,
            "created_at": int(time.time()), "status": "pending",
            "svg_url": f"/download/{task_id}", "lightburn_url": f"/download-lbrn2/{task_id}"})
    threading.Thread(target=long_running_script,
        args=(task_id, user_data, image_path, material_settings_path, upload_folder)).start()
    response = make_response(render_template("loading.html", task_id=task_id,
        files=[f"/download-lbrn2/{task_id}", f"/download/{task_id}"],
        history_session=history_session, history_files=history_files, current_source_name=base_name,
        current_image_preset=submitted_preset,
        current_abstract_filter=submitted_filter, current_material_name=material_name))
    response.set_cookie("mopa_history_session", history_session, max_age=HISTORY_TTL_SECONDS,
        secure=request.is_secure, httponly=True, samesite="Lax")
    return response


@routes.route("/file-history/<session_id>")
def file_history(session_id):
    session_id = valid_history_session(session_id)
    if not session_id:
        return jsonify({"files": []}), 400
    return jsonify({"files": get_history_entries(session_id)})


@routes.route("/task-status/<task_id>")
def task_status(task_id):
    log_key, status_key = f"task:{task_id}:log", f"task:{task_id}:status"
    status = redis_client.get(status_key) or "pending"
    logs = redis_client.lrange(log_key, 0, -1) if redis_client.exists(log_key) else []
    return jsonify({"status": status.strip(), "logs": logs})


def _output_file(task_id, extension=None):
    pattern = f"output_{task_id}_*{extension or ''}"
    matches = glob.glob(os.path.join(current_app.config["UPLOAD_FOLDER"], pattern))
    if extension:
        return os.path.basename(matches[0]) if matches else None
    for file_path in matches:
        if not file_path.endswith(".lbrn2"):
            return os.path.basename(file_path)
    return None


@routes.route("/download/<task_id>")
def download_file(task_id):
    image_file = _output_file(task_id)
    if not image_file:
        return jsonify({"status": "error", "message": "Processed image file not found on disk"}), 404
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], image_file, as_attachment=True,
        download_name=image_file, mimetype="image/svg+xml" if image_file.endswith(".svg") else None)


@routes.route("/list-downloads/<task_id>")
def list_downloads(task_id):
    return render_template("loading.html", status="success",
        files=[f"/download-lbrn2/{task_id}", f"/download/{task_id}"]), 200


@routes.route("/download-lbrn2/<task_id>")
def download_lbrn2(task_id):
    filename = _output_file(task_id, ".lbrn2")
    if not filename:
        return jsonify({"status": "error", "message": "LightBurn file (.lbrn2) not found on disk"}), 404
    cleanup_redis_inflight(task_id)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename, as_attachment=True, download_name=filename)


@routes.route("/view-image/<task_id>")
def view_image(task_id):
    filename = _output_file(task_id)
    if not filename:
        return jsonify({"status": "error", "message": "Preview asset not found on disk"}), 404
    lower = filename.lower()
    mimetype = ("image/svg+xml" if "svg" in lower else "image/png" if lower.endswith(".png")
        else "image/jpeg" if lower.endswith((".jpg", ".jpeg")) else "image/gif" if lower.endswith(".gif")
        else "image/webp" if lower.endswith(".webp") else None)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename, mimetype=mimetype)


@routes.route("/success/<task_id>")
def success_page(task_id):
    return render_template("success.html", task_id=task_id)
