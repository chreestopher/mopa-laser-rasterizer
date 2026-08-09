import os
import threading
import uuid
import subprocess
import multiprocessing

from flask import Flask, render_template, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

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
        tasks[f"{task_id}_status"] = "processing"

        square_mm = data.get('pixel_square_mm', '1')
        new_width = data.get('new_width', '100')
        new_height = data.get('new_height', '100')
        colors = data.get('colors', '')
        vectorize_string = data.get('vectorize', 'false')
        
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
                str(vectorize_string)
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Merges stderr into stdout cleanly
            text=True
        )

        # Read the stdout stream line-by-line in real time
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            
            if line:
                cleaned_line = line.strip()
                if cleaned_line:
                    print(f"[Subprocess Stream]: {cleaned_line}", flush=True)
                    
                    # Safely update the shared list
                    current_logs = tasks.get(f"{task_id}_logs", [])
                    current_logs.append(cleaned_line)
                    tasks[f"{task_id}_logs"] = current_logs

        # FIX: Safely wait for exit code without trying to re-read exhausted streams
        return_code = process.wait()
        print(f"[Thread-{task_id}] Subprocess exited with return code: {return_code}", flush=True)
        
        if return_code == 0:
            tasks[f"{task_id}_status"] = "completed"
        else:
            tasks[f"{task_id}_status"] = "failed"
            tasks[f"{task_id}_error"] = f"Script exited with error code {return_code}."

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
    
    return render_template('loading.html', task_id=task_id)


@app.route('/task-status/<task_id>')
def task_status(task_id):
    """Endpoint for JavaScript to check task completion, pulling clean values out of flat keys."""
    status = tasks.get(f"{task_id}_status", "pending")
    logs = tasks.get(f"{task_id}_logs", ["Initializing workspace..."])
    error = tasks.get(f"{task_id}_error", None)

    return jsonify({
        "status": status,
        "current_log": logs,
        "error": error
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


@app.route('/download-lbrn2/<task_id>')
def download_lbrn2(task_id):
    """Locates and downloads the matching LightBurn vector layout file."""
    import glob
    search_pattern = os.path.join(app.config['UPLOAD_FOLDER'], f"output_{task_id}_*.lbrn2")
    matching_files = glob.glob(search_pattern)
    
    if not matching_files:
        return jsonify({"status": "error", "message": "LightBurn file (.lbrn2) not found on disk"}), 404
        
    lbrn2_file = os.path.basename(matching_files[0])
    
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

    mimetype = 'image/svg+xml' if '.svg' in image_file.lower() else None

    return send_from_directory(
        directory=app.config['UPLOAD_FOLDER'], 
        path=image_file,
        mimetype=mimetype
    )


@app.route('/success/<task_id>')
def success_page(task_id):
    """Renders the dedicated confirmation results template screen."""
    return render_template('success.html', task_id=task_id)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, threaded=True, use_reloader=False, debug=False)
