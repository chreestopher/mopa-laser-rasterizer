"""Automatic route discovery for the application.

Add a module to this package and decorate its view functions with ``@routes.route``.
The module is imported automatically when the application starts.
"""

import importlib
import pkgutil

from flask import Blueprint


routes = Blueprint("routes", __name__)


def register_routes(app):
    """Import every route module, then attach the shared blueprint once."""
    for module in pkgutil.iter_modules(__path__):
        if not module.ispkg and not module.name.startswith("_"):
            importlib.import_module(f"{__name__}.{module.name}")
    app.register_blueprint(routes)
