import os
import threading
import uuid
import subprocess

# FIX: Added secure_filename and imported all Flask tools cleanly
from flask import Flask, render_template, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__)

# Configure a directory to save the uploaded files
UPLOAD_FOLDER = './uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Dictionary to hold the state of background tasks
tasks = {}

@app.route('/')
def index():
    return app.send_static_file('index.html')


def long_running_script(task_id, data, image_path, material_settings_path):
    """Background thread runs the image processing script safely without blocking Flask."""
    try:
        # Update status to processing immediately when the thread executes
        tasks[task_id] = {"status": "processing", "progress": 50, "error": None}

        # Safely extract standard form strings with defaults
        square_mm = data.get('pixel_square_mm', '1')
        new_width = data.get('new_width', '100')
        new_height = data.get('new_height', '100')
        colors = data.get('colors', '')
        vectorize_string = data.get('vectorize', 'false')

        # Define explicit output path using the session task ID
        output_file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"output_{task_id}.png")

        print(f"[Thread-{task_id}] Launching Material_Library.py subprocess...")

        # Run the processing script as an independent OS process to beat CPU limits
        result_of_script = subprocess.run(
            [
                "python", 
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
            capture_output=True, 
            text=True,
            check=True  # Raises an exception if the subprocess fails internally
        )
        
        print(f"[Thread-{task_id}] Script STDOUT:", result_of_script.stdout)
        print(f"[Thread-{task_id}] Script STDERR:", result_of_script.stderr)        
        
        # Mark task completed
        tasks[task_id] = {"status": "completed", "progress": 100, "error": None}

    except subprocess.CalledProcessError as e:
        print(f"[Thread-{task_id}] Subprocess runtime error! Stderr: {e.stderr}")
        tasks[task_id] = {"status": "failed", "progress": 0, "error": f"Script failed: {e.stderr}"}
    except Exception as e:
        print(f"[Thread-{task_id}] General exception in thread: {str(e)}")
        tasks[task_id] = {"status": "failed", "progress": 0, "error": str(e)}


@app.route('/upload', methods=['POST'])
def start_task():
    """Entry point for file uploads and task initialization."""
    if 'image' not in request.files or 'material_settings' not in request.files:
        return jsonify({"status": "error", "message": "Missing required files"}), 400

    image_file = request.files['image']
    material_settings = request.files['material_settings']

    if image_file.filename == '' or material_settings.filename == '':
        return jsonify({"status": "error", "message": "Empty file names uploaded"}), 400

    task_id = str(uuid.uuid4())
    
    img_filename = f"{task_id}_{secure_filename(image_file.filename)}"
    mat_filename = f"{task_id}_{secure_filename(material_settings.filename)}"
    
    image_path = os.path.join(app.config['UPLOAD_FOLDER'], img_filename)
    material_settings_path = os.path.join(app.config['UPLOAD_FOLDER'], mat_filename)

    image_file.save(image_path)
    material_settings.save(material_settings_path)
    print(f"Successfully saved files for Task {task_id}")

    user_data = request.form.to_dict()
    
    tasks[task_id] = {"status": "pending", "progress": 0, "error": None}

    thread = threading.Thread(
        target=long_running_script, 
        args=(task_id, user_data, image_path, material_settings_path)
    )
    thread.start()
    
    return render_template('loading.html', task_id=task_id)


@app.route('/task-status/<task_id>')
def task_status(task_id):
    """Endpoint for JavaScript to check task completion."""
    task = tasks.get(task_id, {"status": "pending", "progress": 0, "error": None})
    return jsonify(task)


@app.route('/download/<task_id>')
def download_file(task_id):
    """Securely serves the processed output file for a specific task ID."""
    filename = f"output_{task_id}.png"
    try:
        return send_from_directory(
            directory=app.config['UPLOAD_FOLDER'],
            path=filename,
            as_attachment=True,              
            download_name=f"rasterized_{task_id}.png"
        )
    except FileNotFoundError:
        return jsonify({"status": "error", "message": "Processed file not found on disk"}), 404


@app.route('/view-image/<task_id>')
def view_image(task_id):
    """Serves the image to the HTML <img> preview tag safely."""
    filename = f"output_{task_id}.png"
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/success/<task_id>')
def success_page(task_id):
    """Renders the dedicated success HTML file, passing along template variables."""
    return render_template('success.html', task_id=task_id)


if __name__ == '__main__':
    # Fallback if run without Gunicorn directly
    app.run(host='0.0.0.0', port=8000, threaded=True, use_reloader=False, debug=False)