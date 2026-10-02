#!/usr/bin/env python3
"""Render the production Community Set page for authenticated staging."""

import re
import sys
from pathlib import Path
from urllib.parse import urljoin

from jinja2 import Environment


repo_root = Path(__file__).resolve().parents[1]
output_path = Path(sys.argv[1])
source = (repo_root / "templates" / "community_set.html").read_text(encoding="utf-8")
source = source.replace('<html lang="en">', '<html lang="en" class="staging-shell-pending">', 1)
source = source.replace("{% from '_machine_chrome.html' import machine_chrome %}\n", "", 1)
source = re.sub(r"\s*\{\{ machine_chrome\([^\n]+\) \}\}\n", "\n", source, count=1)
source = source.replace('<link rel="stylesheet" href="/static/machine_chrome.css?v=3">', "")
source = source.replace('<main class="machine">', '<main id="main-content">', 1)
source = source.replace(
    "</head>",
    '  <link rel="stylesheet" href="/machine_chrome.css?v=3">\n'
    '  <link rel="stylesheet" href="/staging-shell.css?v=1">\n'
    '  <link rel="stylesheet" href="/staging-shell-v2.css">\n'
    '  <link rel="stylesheet" href="/staging-pages.css?v=1">\n'
    '  <script src="/staging-shell.js?v=4" defer></script>\n'
    "</head>",
    1,
)
official_colors = {
    "#000000": "Black", "#0000FF": "Blue", "#FF0000": "Red", "#00E000": "Green",
    "#D0D000": "Yellow", "#FF8000": "Orange", "#00E0E0": "Cyan", "#FF00FF": "Magenta",
    "#B4B4B4": "Light-Gray", "#0000A0": "Dark-Blue", "#A00000": "Dark-Red",
    "#00A000": "Dark-Green", "#A0A000": "Dark-Yellow", "#C08000": "Dark-Orange",
    "#00A0FF": "Light-Blue", "#A000A0": "Dark-Magenta", "#808080": "Medium-Gray",
    "#7D87B9": "Slate-Blue", "#BB7784": "Rose", "#4A6FE3": "Periwinkle-Blue",
    "#D33F6A": "Raspberry", "#8CD78C": "Sage-Green", "#F0B98D": "Peach",
    "#F6C4E1": "Light-Pink", "#FA9ED4": "Orchid-Pink", "#500A78": "Deep-Purple",
    "#B45A00": "Rust-Brown", "#004754": "Teal", "#86FA88": "Bright-Mint-Green",
    "#FFDB66": "Light-Gold",
}

html = Environment(autoescape=True).from_string(source).render(
    member_access=True,
    auth_state="signed_in",
    official_colors=official_colors,
    community_api_mode="serverless",
)
if len(sys.argv) > 2:
    canonical = urljoin(sys.argv[2].rstrip("/") + "/", "community-set")
    html = html.replace("</title>", f'</title>\n  <link rel="canonical" href="{canonical}">', 1)
output_path.write_text(html, encoding="utf-8")
