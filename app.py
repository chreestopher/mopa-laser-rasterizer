"""Flask application bootstrap and server configuration."""

import os

from flask import Flask

from routes import register_routes
from services import start_disk_cleanup_worker


def create_app():
    app = Flask(__name__)
    # Active jobs use node-local scratch space. Durable inputs and outputs are
    # mirrored to S3 by the job service, so this directory need not be shared
    # between Kubernetes workers.
    upload_folder = os.environ.get("UPLOAD_FOLDER", "./uploads")
    os.makedirs(upload_folder, exist_ok=True)
    app.config["UPLOAD_FOLDER"] = upload_folder
    register_routes(app)
    return app


app = create_app()


if __name__ == "__main__":
    start_disk_cleanup_worker(app)
    app.run(host="0.0.0.0", port=8000, threaded=True, use_reloader=False, debug=False)
