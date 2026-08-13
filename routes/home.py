"""Static-page routes."""

from flask import current_app, render_template

from . import routes


@routes.route("/")
def index():
    return current_app.send_static_file("index.html")


@routes.route("/holographic-etching")
def holographic_etching():
    """Dedicated workspace for the structural-color engraving workflow."""
    return render_template("holographic_etching.html")
