"""Local-only Flask development and test application.

The deployed application uses the serverless web/API stack.  This Flask app is
not a production identity boundary and must not be exposed as a public service.
"""

import os

from flask import Flask

from routes import register_routes
from services import start_disk_cleanup_worker


def create_app():
    app = Flask(__name__)
    # Local jobs use workstation scratch space. Durable inputs and outputs may
    # still be mirrored to S3 when local development is configured for AWS.
    upload_folder = os.environ.get("UPLOAD_FOLDER", "./uploads")
    os.makedirs(upload_folder, exist_ok=True)
    app.config["UPLOAD_FOLDER"] = upload_folder
    # Local visitors receive a signed browser session for the daily free
    # allowance. The fallback is deliberately limited to this local-only app;
    # the deployed serverless application does not use Flask sessions.
    app.config["SECRET_KEY"] = os.environ.get("APP_SESSION_SECRET", "local-development-only-secret")
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["COGNITO_DOMAIN"] = os.environ.get("COGNITO_DOMAIN", "").strip()
    app.config["COGNITO_CLIENT_ID"] = os.environ.get("COGNITO_CLIENT_ID", "").strip()
    app.config["PUBLIC_APP_URL"] = os.environ.get("PUBLIC_APP_URL", "").rstrip("/")
    register_routes(app)
    return app


app = create_app()


if __name__ == "__main__":
    start_disk_cleanup_worker(app)
    app.run(host="0.0.0.0", port=8000, threaded=True, use_reloader=False, debug=False)
