"""Static-page routes."""

from flask import current_app

from . import routes


@routes.route("/")
def index():
    return current_app.send_static_file("index.html")
