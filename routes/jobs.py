"""Job submission, status, history, preview, and download routes."""

import glob
import json
import os
import threading
import time
import uuid

from flask import Response, current_app, jsonify, make_response, redirect, render_template, request, send_from_directory, session, stream_with_context
from PIL import Image, UnidentifiedImageError
from werkzeug.utils import secure_filename

from . import routes
from services import (
    ABSTRACT_FILTER_NAMES,
    HISTORY_TTL_SECONDS,
    add_history_entry,
    claim_daily_job,
    cleanup_redis_inflight,
    get_history_entries,
    long_running_script,
    enqueue_raster_job,
    normalize_dimension,
    parse_abstract_filter_parameters,
    parse_color_name_overrides,
    raster_queue_position,
    download_task_artifact,
    download_user_material_library,
    find_task_artifact,
    get_job_record,
    get_user_material_library,
    get_s3_artifact,
    get_job_owner,
    redis_client,
    record_user_job,
    record_setting_usage,
    resolve_material_setting_usage,
    save_user_material_library,
    tasks,
    upload_task_artifact,
    valid_history_session,
)


@routes.route("/upload", methods=["GET", "POST"])
def start_task():
    if request.method == "GET":
        return redirect("/")
    if "image" not in request.files or not request.files["image"].filename:
        return jsonify({"status": "error", "message": "Choose an artwork file"}), 400

    user_id = request.headers.get("x-amzn-oidc-identity", "").strip()
    anonymous_id = None
    if not user_id:
        anonymous_id = session.get("anonymous_quota_id")
        if not anonymous_id:
            anonymous_id = str(uuid.uuid4())
            session["anonymous_quota_id"] = anonymous_id

    task_id = str(uuid.uuid4())
    user_data = request.form.to_dict()
    user_data["new_width"] = str(normalize_dimension(user_data.get("new_width")))
    user_data["new_height"] = str(normalize_dimension(user_data.get("new_height")))
    history_session = (valid_history_session(user_data.get("history_session"))
        or valid_history_session(request.cookies.get("mopa_history_session")) or str(uuid.uuid4()))
    image_file = request.files["image"]
    material_settings = request.files.get("material_settings")
    usage_library = None
    try:
        with Image.open(image_file.stream) as image_probe:
            image_probe.verify()
    except (UnidentifiedImageError, OSError):
        return jsonify({
            "status": "error",
            "message": "The artwork file must be an image. It looks like a LightBurn Material Library may have been selected instead.",
        }), 400
    finally:
        image_file.stream.seek(0)
    base_name = secure_filename(image_file.filename)
    output_name = f"output_{task_id}_{base_name}"
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    image_path = os.path.join(upload_folder, f"{task_id}_{base_name}")
    image_file.save(image_path)
    try:
        image_key = upload_task_artifact(task_id, image_path, category="inputs", user_id=user_id or None)
    except RuntimeError as error:
        return jsonify({"status": "error", "message": str(error)}), 503
    material_cache_key = f"material-library:{history_session}"
    saved_library_id = str(user_data.get("saved_material_library_id", "")).strip()
    if material_settings and material_settings.filename:
        material_filename = secure_filename(material_settings.filename)
        material_settings_path = os.path.join(
            upload_folder, f"{task_id}_material_library_{material_filename}"
        )
        material_settings.save(material_settings_path)
        try:
            material_key = upload_task_artifact(
                task_id, material_settings_path, category="inputs", user_id=user_id or None
            )
        except RuntimeError as error:
            return jsonify({"status": "error", "message": str(error)}), 503
        redis_client.set(
            material_cache_key,
            json.dumps({"path": material_settings_path, "filename": material_filename, "key": material_key}),
            ex=HISTORY_TTL_SECONDS,
        )
        if user_id:
            try:
                usage_library = save_user_material_library(
                    user_id, material_settings_path, user_data.get("material", "")
                )
            except RuntimeError as error:
                return jsonify({"status": "error", "message": str(error)}), 503
    elif saved_library_id:
        if not user_id:
            return jsonify({"status": "error", "message": "Sign in to use a saved Material Library."}), 401
        try:
            saved_library = get_user_material_library(user_id, saved_library_id)
            if not saved_library:
                return jsonify({"status": "error", "message": "That saved Material Library is no longer available."}), 404
            material_filename = secure_filename(
                saved_library.get("original_name") or saved_library.get("name") or "library.clb"
            )
            material_settings_path = os.path.join(upload_folder, f"{task_id}_saved_material_{material_filename}")
            download_user_material_library(saved_library, material_settings_path)
            material_key = saved_library.get("s3_key")
            usage_library = saved_library
        except RuntimeError as error:
            return jsonify({"status": "error", "message": str(error)}), 503
    else:
        try:
            cached_material = json.loads(redis_client.get(material_cache_key) or "{}")
            material_settings_path = cached_material.get("path")
        except (TypeError, json.JSONDecodeError):
            cached_material = {}
            material_settings_path = None
        material_key = cached_material.get("key")
        if material_key and not os.path.isfile(material_settings_path or ""):
            material_settings_path = os.path.join(upload_folder, f"{task_id}_cached_material_{cached_material.get('filename', 'library.clb')}")
            try:
                download_task_artifact(material_key, material_settings_path)
            except RuntimeError as error:
                return jsonify({"status": "error", "message": str(error)}), 503
        if not material_settings_path or not os.path.isfile(material_settings_path):
            return jsonify({"status": "error", "message": "Choose a LightBurn Material Library file"}), 400
    try:
        submitted_preset = str(user_data.get("image_preset", "cartoon")).strip().lower()
        material_name = str(user_data.get("material", "stainless - steel")).strip().lower()
        if not material_name:
            raise ValueError("Choose or enter a material name")
        filter_name = submitted_preset.removeprefix("abstract_")
        if submitted_preset.startswith("abstract_") and filter_name not in ABSTRACT_FILTER_NAMES:
            raise ValueError("Unknown abstract filter")
        filter_parameters = parse_abstract_filter_parameters(
            user_data.get("abstract_filter_parameters", "{}")
        )
        color_name_overrides = parse_color_name_overrides(user_data.get("color_name_overrides", "{}"))
    except ValueError as error:
        return jsonify({"status": "error", "message": str(error)}), 400

    # Cognito-authenticated users have unlimited jobs.  Anonymous visitors use
    # a server-signed browser session and receive three accepted jobs per UTC
    # day; malformed uploads never consume an allowance.
    if anonymous_id:
        allowed, _remaining_jobs = claim_daily_job(f"anonymous:{anonymous_id}")
        if not allowed:
            return jsonify({
                "status": "error",
                "message": "Your three free Rasterizer jobs for today are used. Sign in for unlimited jobs, or return after 00:00 UTC.",
                "daily_limit": 3,
            }), 429

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
    run_parameters = {
        "pixel_size_mm": user_data.get("pixel_square_mm", "1"),
        "processing_width_px": user_data["new_width"],
        "processing_height_px": user_data["new_height"],
        "colors": [color.strip() for color in user_data.get("colors", "").split(",") if color.strip()],
        "selected_color_hexes": [
            color_hex for color_hex, color_name in color_name_overrides.items()
            if color_name.casefold() in {
                color.strip().casefold() for color in user_data.get("colors", "").split(",") if color.strip()
            }
        ],
        "color_name_overrides": color_name_overrides,
        "filter_parameters": filter_parameters,
    }
    resolved_settings = []
    try:
        # Capture the real setting each palette swatch resolves to while the
        # original Material Library is available locally. This applies to both
        # signed-in and guest jobs; shared telemetry excludes artwork, account
        # identity, and guest browser identifiers.
        resolved_settings = resolve_material_setting_usage(
            material_settings_path,
            material_name,
            run_parameters["colors"],
            color_name_overrides,
        )
    except Exception as error:
        # The worker retains the authoritative validation path. A library that
        # its telemetry reader cannot inspect must not reject an accepted job.
        current_app.logger.warning("Could not resolve Material Library usage for %s: %s", task_id, error)
    if user_id:
        try:
            record_user_job(user_id, task_id, base_name, submitted_preset, submitted_filter,
                            material_name, run_parameters,
                            input_keys=[key for key in (image_key, material_key) if key])
        except RuntimeError as error:
            return jsonify({"status": "error", "message": str(error)}), 503
    try:
        record_setting_usage(task_id, resolved_settings, usage_library)
    except RuntimeError as error:
        # Usage reporting is deliberately non-blocking for both account and
        # guest processing. The raster job remains fully usable.
        current_app.logger.warning("Could not record Material Library usage for %s: %s", task_id, error)
    add_history_entry(history_session, task_id, base_name, submitted_preset, submitted_filter,
                      material_name, run_parameters)
    history_files = get_history_entries(history_session)
    if not any(item.get("task_id") == task_id for item in history_files):
        history_files.insert(0, {"task_id": task_id, "source_name": base_name,
            "image_preset": submitted_preset,
            "abstract_filter": submitted_filter,
            "material_name": material_name,
            "run_parameters": run_parameters,
            "created_at": int(time.time()), "status": "pending",
            "svg_url": f"/download/{task_id}", "lightburn_url": f"/download-lbrn2/{task_id}"})
    if os.environ.get("RASTER_JOB_QUEUE_ENABLED", "false").lower() == "true":
        try:
            enqueue_raster_job(
                task_id, user_data, image_key, material_key, output_name,
                base_name, os.path.basename(material_settings_path), user_id or None,
            )
        except RuntimeError as error:
            redis_client.set(f"task:{task_id}:status", "failed", ex=HISTORY_TTL_SECONDS)
            redis_client.rpush(f"task:{task_id}:log", f"Could not queue raster job: {error}")
            return jsonify({"status": "error", "message": str(error)}), 503
    else:
        threading.Thread(target=long_running_script,
            args=(task_id, user_data, image_path, material_settings_path,
                  upload_folder, user_id or None, output_name)).start()
    response = make_response(render_template("loading.html", task_id=task_id,
        files=[f"/download-lbrn2/{task_id}", f"/download/{task_id}"],
        history_session=history_session, history_files=history_files, current_source_name=base_name,
        current_image_preset=submitted_preset,
        current_abstract_filter=submitted_filter, current_material_name=material_name,
        current_created_at=int(time.time())))
    response.set_cookie("mopa_history_session", history_session, max_age=HISTORY_TTL_SECONDS,
        secure=request.is_secure, httponly=True, samesite="Lax")
    return response


@routes.route("/file-history/<session_id>")
def file_history(session_id):
    session_id = valid_history_session(session_id)
    if not session_id:
        return jsonify({"files": []}), 400
    return jsonify({"files": get_history_entries(session_id)})


@routes.route("/job-history")
def job_history():
    """Open the shared console in history mode for account or guest runs."""
    history_session = valid_history_session(request.cookies.get("mopa_history_session", "")) or ""
    history_files = get_history_entries(history_session) if history_session else []
    active_task_id = valid_history_session(request.args.get("task_id", "")) or ""
    if active_task_id:
        access_error = _job_access_error(active_task_id, browser_navigation=True)
        if access_error:
            return access_error
    active_file = next(
        (entry for entry in history_files if entry.get("task_id") == active_task_id), {}
    )
    return render_template(
        "loading.html", task_id=active_task_id, history_session=history_session,
        history_files=history_files, history_mode=True,
        current_source_name=active_file.get("source_name", "Holographic Artwork"),
        current_image_preset=active_file.get("image_preset", "holographic_artwork"),
        current_abstract_filter=active_file.get("abstract_filter", "none"),
        current_material_name=active_file.get("material_name", ""),
        current_created_at=active_file.get("created_at", int(time.time())),
    )


@routes.route("/task-status/<task_id>")
def task_status(task_id):
    access_error = _job_access_error(task_id)
    if access_error:
        return access_error
    log_key, status_key = f"task:{task_id}:log", f"task:{task_id}:status"
    status = redis_client.get(status_key)
    durable_job = None
    if not status:
        try:
            durable_job = get_job_record(task_id)
        except RuntimeError:
            durable_job = None
        status = (durable_job or {}).get("status") or "pending"
    queue = None
    if status == "pending":
        queue = raster_queue_position(task_id)
        if queue:
            position_key = f"task:{task_id}:queue-position"
            position_value = str(queue["position"])
            previous_position = redis_client.get(position_key)
            if previous_position != position_value:
                jobs_label = "job" if queue["jobs_ahead"] == 1 else "jobs"
                active_suffix = (
                    f"; {queue['active_jobs']} currently processing"
                    if queue["active_jobs"] else ""
                )
                redis_client.rpush(
                    log_key,
                    f"Queue position {queue['position']}: {queue['jobs_ahead']} "
                    f"{jobs_label} ahead{active_suffix}.",
                )
                redis_client.set(
                    position_key, position_value, ex=HISTORY_TTL_SECONDS
                )
    try:
        log_after = max(0, int(request.args.get("after", "0")))
    except (TypeError, ValueError):
        log_after = 0
    log_count = redis_client.llen(log_key)
    logs = redis_client.lrange(log_key, log_after, -1) if log_count > log_after else []
    if not logs and durable_job and durable_job.get("error_message"):
        logs = [f"Rasterizer job failed: {durable_job['error_message']}"]
    response = jsonify({
        "status": status.strip(),
        "logs": logs,
        "log_count": log_count,
        "queue": queue,
    })
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


def _output_file(task_id, extension=None):
    pattern = f"output_{task_id}_*{extension or ''}"
    matches = glob.glob(os.path.join(current_app.config["UPLOAD_FOLDER"], pattern))
    if extension:
        return os.path.basename(matches[0]) if matches else None
    for file_path in matches:
        if not file_path.endswith(".lbrn2"):
            return os.path.basename(file_path)
    return None


def _job_access_error(task_id, browser_navigation=False):
    """Keep account-owned jobs private while leaving legacy guest jobs usable."""
    try:
        owner_id = get_job_owner(task_id)
    except RuntimeError:
        return jsonify({"status": "error", "message": "Could not verify job ownership."}), 503
    if owner_id and request.headers.get("x-amzn-oidc-identity", "").strip() != owner_id:
        if browser_navigation:
            return render_template("access_denied.html"), 403
        return jsonify({"status": "error", "message": "This job belongs to a different account."}), 403
    return None


def _s3_output_key(task_id, extension=None):
    try:
        return find_task_artifact(task_id, extension)
    except RuntimeError as error:
        current_app.logger.error("S3 output lookup failed for %s: %s", task_id, error)
        return None


def _stream_s3_download(key, as_attachment=True, mimetype=None, download_name=None):
    try:
        artifact = get_s3_artifact(key)
    except RuntimeError as error:
        return jsonify({"status": "error", "message": str(error)}), 503
    filename = download_name or os.path.basename(key)
    response = Response(stream_with_context(artifact["Body"].iter_chunks(chunk_size=1024 * 1024)),
                        mimetype=mimetype or artifact.get("ContentType") or "application/octet-stream")
    if as_attachment:
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _rasterized_lightburn_download_name(task_id, artifact_name):
    """Build a friendly download name without changing UUID-safe artifact storage."""
    source_name = ""
    try:
        source_name = (get_job_record(task_id) or {}).get("source_name") or ""
    except RuntimeError:
        # Guest jobs do not have a durable account record. Their UUID-prefixed
        # output artifact still safely retains the sanitized upload name.
        pass
    if not source_name:
        artifact_name = os.path.basename(artifact_name)
        prefix = f"output_{task_id}_"
        source_name = artifact_name[len(prefix):] if artifact_name.startswith(prefix) else artifact_name
        for suffix in (".vector.svg.lbrn2", ".lbrn2"):
            if source_name.lower().endswith(suffix):
                source_name = source_name[:-len(suffix)]
                break
    stem = os.path.splitext(os.path.basename(source_name))[0]
    return f"{secure_filename(stem) or 'rasterized-project'}.rasterized.lbrn2"


@routes.route("/download/<task_id>")
def download_file(task_id):
    access_error = _job_access_error(task_id, browser_navigation=True)
    if access_error:
        return access_error
    s3_key = _s3_output_key(task_id)
    if s3_key:
        return _stream_s3_download(s3_key, mimetype="image/svg+xml" if s3_key.endswith(".svg") else None)
    image_file = _output_file(task_id)
    if not image_file:
        return jsonify({"status": "error", "message": "Processed image file not found on disk"}), 404
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], image_file, as_attachment=True,
        download_name=image_file, mimetype="image/svg+xml" if image_file.endswith(".svg") else None)


@routes.route("/download-svg/<task_id>")
def download_svg(task_id):
    """Download the exact SVG output for any shared-history job type."""
    access_error = _job_access_error(task_id, browser_navigation=True)
    if access_error:
        return access_error
    s3_key = _s3_output_key(task_id, ".svg")
    if s3_key:
        return _stream_s3_download(s3_key, mimetype="image/svg+xml")
    candidates = (
        glob.glob(os.path.join(current_app.config["UPLOAD_FOLDER"], f"holographic_art_{task_id}.svg"))
        + glob.glob(os.path.join(current_app.config["UPLOAD_FOLDER"], f"output_{task_id}_*.svg"))
    )
    if not candidates:
        return jsonify({"status": "error", "message": "SVG file not found"}), 404
    filename = os.path.basename(candidates[0])
    return send_from_directory(
        current_app.config["UPLOAD_FOLDER"], filename, as_attachment=True,
        download_name=filename, mimetype="image/svg+xml",
    )


@routes.route("/list-downloads/<task_id>")
def list_downloads(task_id):
    access_error = _job_access_error(task_id, browser_navigation=True)
    if access_error:
        return access_error
    return render_template("loading.html", status="success",
        files=[f"/download-lbrn2/{task_id}", f"/download/{task_id}"]), 200


@routes.route("/download-lbrn2/<task_id>")
def download_lbrn2(task_id):
    access_error = _job_access_error(task_id, browser_navigation=True)
    if access_error:
        return access_error
    s3_key = _s3_output_key(task_id, ".lbrn2")
    if s3_key:
        cleanup_redis_inflight(task_id)
        return _stream_s3_download(
            s3_key, download_name=_rasterized_lightburn_download_name(task_id, s3_key)
        )
    filename = _output_file(task_id, ".lbrn2")
    if not filename:
        return jsonify({"status": "error", "message": "LightBurn file (.lbrn2) not found on disk"}), 404
    cleanup_redis_inflight(task_id)
    return send_from_directory(
        current_app.config["UPLOAD_FOLDER"], filename, as_attachment=True,
        download_name=_rasterized_lightburn_download_name(task_id, filename),
    )


@routes.route("/view-image/<task_id>")
def view_image(task_id):
    access_error = _job_access_error(task_id, browser_navigation=True)
    if access_error:
        return access_error
    s3_key = _s3_output_key(task_id)
    if s3_key:
        lower = s3_key.lower()
        mimetype = ("image/svg+xml" if "svg" in lower else "image/png" if lower.endswith(".png")
            else "image/jpeg" if lower.endswith((".jpg", ".jpeg")) else "image/gif" if lower.endswith(".gif")
            else "image/webp" if lower.endswith(".webp") else None)
        return _stream_s3_download(s3_key, as_attachment=False, mimetype=mimetype)
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
