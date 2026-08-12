import os
import threading
import uuid
import subprocess
import multiprocessing
import time
import json
from flask import Flask, render_template, jsonify, request, send_from_directory, redirect
from werkzeug.utils import secure_filename
import redis
import boto3
from botocore.exceptions import ClientError

redis_client = redis.Redis(
    host=os.environ.get('REDIS_HOST', 'localhost'),
    port=int(os.environ.get('REDIS_PORT', 6379)),
    decode_responses=True # Automatically decodes Redis bytes into Python strings
)


# Initialize the S3 client
s3_client = boto3.client('s3')

BUCKET_NAME = 'mopa-laser-rasterizer.com'

ABSTRACT_FILTER_NAMES = {
    "none", "wave", "voronoi", "shear", "spiral", "mosaic",
    "crystal", "ripple"
}


def parse_abstract_filter_parameters(raw_value):
    """Validate the small JSON object supplied by the abstract-filter UI."""
    if not raw_value:
        return {}
    try:
        parameters = json.loads(raw_value)
    except json.JSONDecodeError as error:
        raise ValueError("Abstract filter settings are not valid JSON") from error
    if not isinstance(parameters, dict) or len(parameters) > 12:
        raise ValueError("Abstract filter settings must be a small object")
    clean = {}
    for key, value in parameters.items():
        if not isinstance(key, str) or not key.replace("_", "").isalnum():
            raise ValueError("An abstract filter setting has an invalid name")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Abstract filter setting '{key}' must be numeric")
        clean[key] = value
    return clean

def upload_local_file(local_file_path: str, object_key: str):
  """Uploads an existing file from disk to S3."""
  try:
    s3_client.upload_file(local_file_path, BUCKET_NAME, object_key)
    print(f'Successfully uploaded {local_file_path} to {object_key}')
  except ClientError as e:
    print(f'Error uploading file: {e}')


def download_s3_file(object_key: str, local_download_path: str):
  """Downloads an S3 object down to the local disk/pod storage."""
  try:
    s3_client.download_file(BUCKET_NAME, object_key, local_download_path)
    print(f'Successfully downloaded {object_key} to {local_download_path}')
  except ClientError as e:
    print(f'Error downloading file: {e}')

def start_disk_cleanup_worker(app, redis_client, interval_seconds=3600):
    """
    Launches a background thread that periodically scans the upload directory
    and deletes files whose tracking keys have expired from Redis.
    """
    def cleanup_loop():
        # Wait a moment for the application to fully stabilize on boot
        time.sleep(10)
        
        while True:
            try:
                upload_folder = app.config.get('UPLOAD_FOLDER')
                if not upload_folder or not os.path.exists(upload_folder):
                    time.sleep(interval_seconds)
                    continue

                print("[Disk-Cleanup] Starting periodic disk scan...", flush=True)
                
                # 1. List all files currently sitting in the uploads directory
                all_files = os.listdir(upload_folder)
                
                for filename in all_files:
                    # Ignore system or hidden files
                    if filename.startswith('.'):
                        continue
                        
                    # Extract the task_id from filenames like: "task_id.log", "task_id.status", or the output file
                    # If your output file uses a specific pattern, match it here.
                    # Assuming task_id can be extracted by splitting the first part of the filename:
                    task_id = filename.split('_')[0]
                    
                    # 2. Check if the master status key still exists in Redis
                    redis_status_key = f"task:{task_id}:status"
                    
                    # If the key is gone from Redis, it either hit the 7-day TTL or was deleted on the 3rd download
                    if not redis_client.exists(redis_status_key):
                        file_path = os.path.join(upload_folder, filename)
                        
                        try:
                            if os.path.isfile(file_path):
                                os.remove(file_path)
                                print(f"[Disk-Cleanup] Successfully purged orphaned file: {filename}", flush=True)
                        except Exception as file_err:
                            print(f"[Disk-Cleanup] Failed to delete {filename}: {str(file_err)}", flush=True)
                            
            except Exception as e:
                print(f"[Disk-Cleanup] CRITICAL WORKER EXCEPTION: {str(e)}", flush=True)
                
            # Sleep until the next cycle (default: 1 hour)
            time.sleep(interval_seconds)

    # Run as a daemon thread so it doesn't block the main Flask process from shutting down cleanly
    cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
    cleanup_thread.start()

app = Flask(__name__)

# Configure a directory to save the uploaded files
UPLOAD_FOLDER = './uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Shared multi-process dictionary manager
manager = multiprocessing.Manager()
tasks = manager.dict()

@app.route('/')
def index():
    return app.send_static_file('index.html')


def long_running_script(task_id, data, image_path, material_settings_path):
    """Background thread runs the script and streams flat root logs to shared memory."""
    try:
        # Redis Key Definitions instead of file paths
        redis_log_key = f"task:{task_id}:log"
        redis_status_key = f"task:{task_id}:status"
        redis_download_key = f"task:{task_id}:downloads" # New download tracker key

        # Set status to processing in Redis
        redis_client.set(redis_status_key, "processing")
        
        # CRITICAL: Set 7-day TTL (in seconds) on keys when introduced so they auto-delete
        seven_days_in_seconds = 7 * 24 * 60 * 60
        redis_client.expire(redis_status_key, seven_days_in_seconds)
        redis_client.expire(redis_log_key, seven_days_in_seconds)


        square_mm = data.get('pixel_square_mm', '1')
        new_width = data.get('new_width', '100')
        new_height = data.get('new_height', '100')
        colors = data.get('colors', '')
        image_preset = data.get('image_preset', "cartoon")
        abstract_filter = str(data.get('abstract_filter', "none")).strip().lower()
        if image_preset != "abstract" or abstract_filter not in ABSTRACT_FILTER_NAMES:
            abstract_filter = "none"
        filter_parameters = parse_abstract_filter_parameters(
            data.get('abstract_filter_parameters', '{}')
        )
        
        output_filename = tasks[f"{task_id}_filename"]
        output_file_path = os.path.join(app.config['UPLOAD_FOLDER'], output_filename)

        print(f"[Thread-{task_id}] Launching Material_Library.py subprocess...", flush=True)

        # Launch the subprocess with unbuffered output and merged streams
        process = subprocess.Popen(
            [
                "python", "-u", 
                "lib/Material_Library.py", 
                image_path, 
                output_file_path, 
                str(square_mm), 
                str(new_width), 
                str(new_height), 
                material_settings_path, 
                str(colors), 
                image_preset,
                abstract_filter,
                json.dumps(filter_parameters, separators=(",", ":"))
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Merges stderr into stdout cleanly
            text=True
        )

        # Redis Key Definitions instead of file paths
        redis_log_key = f"task:{task_id}:log"
        redis_status_key = f"task:{task_id}:status"

        # Set status to processing in Redis
        redis_client.set(redis_status_key, "processing")

        print(f"[Thread-{task_id}] Subprocess loop active...", flush=True)

        current_line = []
        
        # We loop exactly as before, appending lines directly to a Redis list
        while True:
            char = process.stdout.read(1)
            
            if not char and process.poll() is not None:
                break
            
            if char:
                if char == '\n' or char == '\r':
                    line_text = "".join(current_line).strip()
                    if line_text:
                        print(f"[Subprocess Stream]: {line_text}", flush=True)
                        
                        # CRITICAL: Append the log line directly to Redis List
                        redis_client.rpush(redis_log_key, line_text)
                        
                    current_line = []
                else:
                    current_line.append(char)

        if current_line:
            line_text = "".join(current_line).strip()
            if line_text:
                redis_client.rpush(redis_log_key, line_text)

        return_code = process.wait()
        
        # Update status in Redis
        if return_code == 0:
            redis_client.set(redis_status_key, "completed")
        else:
            redis_client.set(redis_status_key, "failed")

    except Exception as e:
        print(f"[Thread-{task_id}] CRITICAL THREAD EXCEPTION: {str(e)}", flush=True)
        tasks[f"{task_id}_status"] = "failed"
        tasks[f"{task_id}_error"] = str(e)



@app.route('/upload', methods=['GET', 'POST'])
def start_task():

    """Entry point for file uploads and task initialization."""
    if request.method == 'GET':
        return redirect('/')

    if 'image' not in request.files or 'material_settings' not in request.files:
        return jsonify({"status": "error", "message": "Missing required files"}), 400

    image_file = request.files['image']
    material_settings = request.files['material_settings']

    if image_file.filename == '' or material_settings.filename == '':
        return jsonify({"status": "error", "message": "Empty file names uploaded"}), 400

    task_id = str(uuid.uuid4())
    
    base_name = secure_filename(image_file.filename) 
    
    # Grab the true base name to match your subprocess extension modifications
    custom_output_name = f"output_{task_id}_{base_name}"
    img_filename = f"{task_id}_{base_name}"
    mat_filename = f"{task_id}_{secure_filename(material_settings.filename)}"
    
    image_path = os.path.join(app.config['UPLOAD_FOLDER'], img_filename)
    material_settings_path = os.path.join(app.config['UPLOAD_FOLDER'], mat_filename)

    image_file.save(image_path)
    material_settings.save(material_settings_path)

    user_data = request.form.to_dict()
    try:
        filter_name = str(user_data.get('abstract_filter', 'none')).strip().lower()
        if filter_name not in ABSTRACT_FILTER_NAMES:
            raise ValueError("Unknown abstract filter")
        parse_abstract_filter_parameters(
            user_data.get('abstract_filter_parameters', '{}')
        )
    except ValueError as error:
        return jsonify({"status": "error", "message": str(error)}), 400

    # Clear top-level keys initialize cleanly
    tasks[f"{task_id}_status"] = "pending"
    tasks[f"{task_id}_logs"] = ["Waiting to start..."]
    tasks[f"{task_id}_filename"] = custom_output_name
    tasks[f"{task_id}_error"] = None

    thread = threading.Thread(
        target=long_running_script, 
        args=(task_id, user_data, image_path, material_settings_path)
    )
    thread.start()
    download_urls = [
        f"/download-lbrn2/{task_id}",
        f"/download/{task_id}"
    ]        
    return render_template(
        'loading.html', 
        task_id=task_id, 
        files=download_urls 
    )



@app.route('/task-status/<task_id>')
def task_status(task_id):
    """Endpoint for JavaScript to check task completion, pulling clean values out of flat keys."""

    redis_log_key = f"task:{task_id}:log"
    redis_status_key = f"task:{task_id}:status"

    status = "pending"
    logs = []
    
    # Read status from Redis
    redis_status = redis_client.get(redis_status_key)
    if redis_status is not None:
        status = redis_status.strip()
            
    # Read logs from Redis list (0 to -1 fetches all elements)
    if redis_client.exists(redis_log_key):
        logs = redis_client.lrange(redis_log_key, 0, -1)
            
    return jsonify({
        "status": status,
        "logs": logs
    })

@app.route('/download/<task_id>')
def download_file(task_id):
    """Locates and downloads the main image file produced by the subprocess."""
    import glob
    search_pattern = os.path.join(app.config['UPLOAD_FOLDER'], f"output_{task_id}_*")
    matching_files = glob.glob(search_pattern)
    
    image_file = None
    for file_path in matching_files:
        if not file_path.endswith('.lbrn2'):
            image_file = os.path.basename(file_path)
            break
            
    if not image_file:
        return jsonify({"status": "error", "message": "Processed image file not found on disk"}), 404
        
    mimetype = 'image/svg+xml' if image_file.endswith('.svg') else None
        
    return send_from_directory(
        directory=app.config['UPLOAD_FOLDER'],
        path=image_file,
        as_attachment=True,              
        download_name=image_file,
        mimetype=mimetype
    )

def cleanup_reddis_inflight(task_id):
    redis_log_key = f"task:{task_id}:log"
    redis_status_key = f"task:{task_id}:status"
    redis_download_key = f"task:{task_id}:downloads"

    # 1. Increment download count (Starts at 1 if key didn't exist)
    download_count = redis_client.incr(redis_download_key)

    # Ensure the counter key also inherits the 7-day TTL if it's the first download
    if download_count == 1:
        redis_client.expire(redis_download_key, 7 * 24 * 60 * 60)

    # 2. Check if this is the 3rd download
    if download_count >= 3:
        # Delete all keys associated with this task ID immediately
        redis_client.delete(redis_status_key, redis_log_key, redis_download_key)
        print(f"[Redis Cleanup]: Task keys for {task_id} purged after 3 downloads.", flush=True)

@app.route('/list-downloads/<task_id>')
def listdownloads(task_id):
    """Locates and downloads returns the filenames."""
    # import glob

    # search_pattern = os.path.join(app.config['UPLOAD_FOLDER'], f"output_{task_id}_*.lbrn2")
    # matching_files = glob.glob(search_pattern)
    
    # if not matching_files:
    #     return jsonify({"status": "error", "message": "LightBurn file (.lbrn2) not found on disk"}), 404
        
    return render_template(
        'loading.html', 
        status='success', 
        files=[f'/download-lbrn2/{task_id}', f'/download/{task_id}']
    ), 200


@app.route('/download-lbrn2/<task_id>')
def download_lbrn2(task_id):
    """Locates and downloads the matching LightBurn vector layout file."""
    import glob

    search_pattern = os.path.join(app.config['UPLOAD_FOLDER'], f"output_{task_id}_*.lbrn2")
    matching_files = glob.glob(search_pattern)
    
    if not matching_files:
        return jsonify({"status": "error", "message": "LightBurn file (.lbrn2) not found on disk"}), 404
        
    lbrn2_file = os.path.basename(matching_files[0])
    cleanup_reddis_inflight(task_id)
    return send_from_directory(
        directory=app.config['UPLOAD_FOLDER'],
        path=lbrn2_file,
        as_attachment=True,              
        download_name=lbrn2_file
    )


@app.route('/view-image/<task_id>')
def view_image(task_id):
    """Dynamically finds and serves the preview file (e.g., .jpg.svg) with correct vector headers."""
    import glob
    search_pattern = os.path.join(app.config['UPLOAD_FOLDER'], f"output_{task_id}_*")
    matching_files = glob.glob(search_pattern)
    
    image_file = None
    for file_path in matching_files:
        if not file_path.endswith('.lbrn2'):
            image_file = os.path.basename(file_path)
            break
            
    if not image_file:
        return jsonify({"status": "error", "message": "Preview asset not found on disk"}), 404

    # Convert to lowercase to handle extensions like .PNG or .JPEG
    #mimetype = 'image/svg+xml' if image_file.lower().endswith('.svg') else None
    filename_lower = image_file.lower()
    mime_type = None
    if 'svg' in filename_lower:
        mime_type = "image/svg+xml"
    elif filename_lower.endswith(".png"):
        mime_type = "image/png"
    elif filename_lower.endswith(".jpg", ".jpeg"):
        mime_type = "image/jpeg"
    elif filename_lower.endswith(".gif"):
        mime_type = "image/gif"
    elif filename_lower.endswith(".webp"):
        mime_type = "image/webp"
    else:
        None

    return send_from_directory(
        directory=app.config['UPLOAD_FOLDER'], 
        path=image_file,
        mimetype=mime_type
    )


@app.route('/success/<task_id>')
def success_page(task_id):
    """Renders the dedicated confirmation results template screen."""
    return render_template('success.html', task_id=task_id)


if __name__ == '__main__':
    # Start the worker to check every 1 hour (3600 seconds)
    start_disk_cleanup_worker(app, redis_client, interval_seconds=3600)
    app.run(host='0.0.0.0', port=8000, threaded=True, use_reloader=False, debug=False)
