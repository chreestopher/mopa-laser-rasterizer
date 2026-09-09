#!/usr/bin/env python3
"""Build the public SEO landing pages and crawler files for serverless staging."""

import re
import sys
from pathlib import Path
from urllib.parse import urljoin

from jinja2 import Environment, FileSystemLoader


repo_root = Path(__file__).resolve().parents[1]
output_root = Path(sys.argv[1])
public_url = sys.argv[2].rstrip("/") + "/"
output_root.mkdir(parents=True, exist_ok=True)

pages = {
    "laser-engraving-tool": "laser_engraving_tool.html",
    "color-laser-engraving-tool": "color_laser_engraving_tool.html",
    "depthmap-relief-engraving-tool": "depthmap_relief_engraving_tool.html",
}

route_rewrites = {
    'href="/color-discovery"': 'href="/color-lab.html"',
    'href="/depthmap-generator"': 'href="/depthmap.html"',
    'href="/holographic-etching"': 'href="/holographic.html"',
    'href="/material-libraries"': 'href="/vault.html"',
    'href="/job-history"': 'href="/history.html"',
}


def static_template(source):
    source = source.replace("{% from \"_machine_chrome.html\" import machine_chrome %}\n", "", 1)
    source = source.replace("{% from '_machine_chrome.html' import machine_chrome %}\n", "", 1)
    source = re.sub(r"\s*\{\{ machine_chrome\([^\n]+\) \}\}\n", "\n", source, count=1)
    source = source.replace('<link rel="stylesheet" href="/static/machine_chrome.css?v=3">', "")
    source = source.replace(
        "</head>",
        "  <meta name=\"robots\" content=\"index,follow,max-image-preview:large\">\n"
        "  <script>document.documentElement.classList.add('staging-shell-pending');setTimeout(()=>document.documentElement.classList.remove('staging-shell-pending'),3000)</script>\n"
        '  <link rel="stylesheet" href="/machine_chrome.css?v=3">\n'
        '  <link rel="stylesheet" href="/staging-shell.css?v=1">\n'
        '  <script src="/staging-shell.js?v=2" defer></script>\n'
        "</head>",
        1,
    )
    for old, new in route_rewrites.items():
        source = source.replace(old, new)
    return source


environment = Environment(loader=FileSystemLoader(repo_root / "templates"), autoescape=True)
for route, filename in pages.items():
    source = (repo_root / "templates" / filename).read_text(encoding="utf-8")
    template = environment.from_string(static_template(source))
    canonical = urljoin(public_url, route)
    (output_root / route).write_text(template.render(canonical=canonical), encoding="utf-8")

home = (repo_root / "serverless_web" / "index.html").read_text(encoding="utf-8")
home = re.sub(r"<title>.*?</title>", "<title>MOPA Laser Rasterizer | Layered SVG and LightBurn Artwork</title>", home, count=1)
home = home.replace(
    "</title>",
    "</title>\n"
    '  <meta name="description" content="Convert raster artwork into layered SVG geometry and LightBurn projects using color, hatch, holographic, and SVG-only workflows.">\n'
    f'  <link rel="canonical" href="{public_url}">\n'
    '  <meta property="og:type" content="website">\n'
    '  <meta property="og:title" content="MOPA Laser Rasterizer">\n'
    '  <meta property="og:description" content="Prepare layered SVG artwork and LightBurn projects from raster images in your browser.">\n'
    f'  <meta property="og:url" content="{public_url}">\n'
    '  <meta name="robots" content="index,follow,max-image-preview:large">',
    1,
)
(output_root / "index.html").write_text(home, encoding="utf-8")

public_paths = [
    "",
    *pages,
    "experimental-laboratories",
    "holographic.html",
    "depthmap.html",
    "color-lab.html",
    "community-set",
    "docs",
]
docs_root = output_root.parent / "docs"
if docs_root.exists():
    public_paths.extend(f"docs/{path.name}" for path in docs_root.iterdir() if path.name != "index.html")

urls = "\n".join(
    f"  <url><loc>{urljoin(public_url, path)}</loc></url>"
    for path in public_paths
)
(output_root / "sitemap.xml").write_text(
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    f"{urls}\n"
    "</urlset>\n",
    encoding="utf-8",
)
(output_root / "robots.txt").write_text(
    "User-agent: *\n"
    "Allow: /\n"
    "Disallow: /admin.html\n"
    "Disallow: /history.html\n"
    "Disallow: /vault.html\n"
    f"Sitemap: {urljoin(public_url, 'sitemap.xml')}\n",
    encoding="utf-8",
)
