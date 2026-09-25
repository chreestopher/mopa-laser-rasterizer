#!/usr/bin/env python3
"""Render production documentation content as static serverless staging pages."""

import re
import sys
import types
import ast
from pathlib import Path

from jinja2 import Environment, FileSystemLoader


repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

# routes.docs owns the canonical documentation catalog, but its runtime route
# declarations import Flask.  Static deployment only needs the catalog, so use
# tiny import stubs instead of making the deployment host install the web app.
flask_stub = types.ModuleType("flask")
for symbol in ("Response", "current_app", "render_template", "request", "send_file"):
    setattr(flask_stub, symbol, object())
sys.modules.setdefault("flask", flask_stub)
werkzeug_stub = types.ModuleType("werkzeug")
werkzeug_utils_stub = types.ModuleType("werkzeug.utils")
werkzeug_utils_stub.secure_filename = lambda value: value
sys.modules.setdefault("werkzeug", werkzeug_stub)
sys.modules.setdefault("werkzeug.utils", werkzeug_utils_stub)


def _abstract_filter_manifest():
    """Read filter metadata without importing optional geometry libraries."""
    result = {}
    filters_root = repo_root / "lib" / "abstract_filters"
    for source_path in filters_root.glob("*.py"):
        if source_path.name in {"__init__.py", "common.py"}:
            continue
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        values = {}
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name) and target.id in {"DEFAULTS", "CONTROLS"}:
                        values[target.id] = ast.literal_eval(node.value)
        if "DEFAULTS" in values and "CONTROLS" in values:
            result[source_path.stem] = {
                "defaults": dict(values["DEFAULTS"]),
                "controls": [
                    {"name": name, "min": minimum, "max": maximum, "step": step}
                    for name, minimum, maximum, step in values["CONTROLS"]
                ],
            }
    return result


lib_abstract_stub = types.ModuleType("lib.abstract_filters")
lib_abstract_stub.manifest = _abstract_filter_manifest
sys.modules["lib.abstract_filters"] = lib_abstract_stub

routes_package = types.ModuleType("routes")
routes_package.__path__ = [str(repo_root / "routes")]


class _RouteStub:
    def route(self, *_args, **_kwargs):
        return lambda function: function


routes_package.routes = _RouteStub()
sys.modules["routes"] = routes_package

from routes.docs import DOC_GROUPS, DOC_ORDER, DOCS, _documentation_search_index  # noqa: E402


output_root = Path(sys.argv[1])
public_url = (sys.argv[2] if len(sys.argv) > 2 else "").rstrip("/")
output_root.mkdir(parents=True, exist_ok=True)
template_source = (repo_root / "templates" / "docs.html").read_text(encoding="utf-8")
template_source = template_source.replace("{% from '_machine_chrome.html' import machine_chrome %}\n", "", 1)
template_source = re.sub(r"\s*\{\{ machine_chrome\([^\n]+\) \}\}\n", "\n", template_source, count=1)
template_source = template_source.replace('<link rel="stylesheet" href="/static/machine_chrome.css?v=3">', "")
template_source = template_source.replace(
    "</head>",
    "  <script>document.documentElement.classList.add('staging-shell-pending');setTimeout(()=>document.documentElement.classList.remove('staging-shell-pending'),3000)</script>\n"
    '  <link rel="stylesheet" href="/machine_chrome.css?v=3">\n'
    '  <link rel="stylesheet" href="/staging-shell.css?v=1">\n'
    '  <script src="/staging-shell.js?v=3" defer></script>\n'
    "</head>",
    1,
)
template_source = template_source.replace(
    "</body>",
    "{% if slug == 'blank-palette-library' %}"
    '<script src="/blank-palette.js?v=2" defer></script>'
    "{% endif %}</body>",
    1,
)

route_rewrites = {
    'href="/color-discovery"': 'href="/color-lab.html"',
    'href="/depthmap-generator"': 'href="/depthmap.html"',
    'href="/fauxlographic-etching"': 'href="/fauxlographic.html"',
    'href="/holographic-etching"': 'href="/fauxlographic.html"',
    'href="/material-libraries"': 'href="/vault.html"',
    'href="/job-history"': 'href="/history.html"',
}
def rewrite_staging_routes(html):
    """Replace production-only application routes after dynamic docs are rendered."""
    for old, new in route_rewrites.items():
        html = html.replace(old, new)
    return html


template_source = rewrite_staging_routes(template_source)

environment = Environment(loader=FileSystemLoader(repo_root / "templates"), autoescape=True)
template = environment.from_string(template_source)


def render(page=None, slug=None):
    page_index = DOC_ORDER.index(slug) if slug else -1
    previous_slug = DOC_ORDER[page_index - 1] if page_index > 0 else None
    next_slug = DOC_ORDER[page_index + 1] if slug and page_index + 1 < len(DOC_ORDER) else None
    return rewrite_staging_routes(template.render(
        page=page,
        slug=slug,
        pages=DOCS,
        groups=DOC_GROUPS,
        canonical=(f"{public_url}/docs/{slug}" if slug else f"{public_url}/docs") if public_url else (f"/docs/{slug}" if slug else "/docs"),
        previous_page=(previous_slug, DOCS[previous_slug]) if previous_slug else None,
        next_page=(next_slug, DOCS[next_slug]) if next_slug else None,
        docs_search_index=_documentation_search_index(),
    ))


(output_root / "index.html").write_text(render(), encoding="utf-8")
for page_slug in DOC_ORDER:
    (output_root / page_slug).write_text(render(DOCS[page_slug], page_slug), encoding="utf-8")
