"""Flask application bootstrap and server configuration."""

import os

from flask import Flask

from routes import register_routes
from services import start_disk_cleanup_worker


def create_app():
    app = Flask(__name__)
    upload_folder = "./uploads"
    os.makedirs(upload_folder, exist_ok=True)
    app.config["UPLOAD_FOLDER"] = upload_folder
    register_routes(app)
    return app


app = create_app()


if __name__ == "__main__":
    start_disk_cleanup_worker(app)
    app.run(host="0.0.0.0", port=8000, threaded=True, use_reloader=False, debug=False)
