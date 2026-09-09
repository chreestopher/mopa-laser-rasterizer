#!/usr/bin/env python3
"""Render the production client-side Depthmap Lab as a static staging page."""

import re
import sys
from pathlib import Path


source = Path(sys.argv[1]).read_text(encoding="utf-8")
source = source.replace('{% from "_machine_chrome.html" import machine_chrome %}\n', "", 1)
source = source.replace('<link rel="canonical" href="{{ canonical }}">',
                        '<link rel="canonical" href="/depthmap.html">')
source = source.replace('  <link rel="stylesheet" href="/static/machine_chrome.css?v=3">\n', "")
source = source.replace(
    "</head>",
    "  <script>document.documentElement.classList.add('staging-shell-pending');setTimeout(()=>document.documentElement.classList.remove('staging-shell-pending'),3000)</script>\n"
    '  <link rel="stylesheet" href="/machine_chrome.css?v=3">\n'
    '  <link rel="stylesheet" href="/staging-shell.css?v=1">\n'
    '  <script src="/staging-shell.js?v=2" defer></script>\n'
    "</head>",
    1,
)
source = re.sub(
    r"  \{\{ machine_chrome\([^\n]+\) \}\}\n",
    "",
    source,
    count=1,
)
source = re.sub(
    r'\s*<section class="panel hero">.*?</section>\s*',
    "\n",
    source,
    count=1,
    flags=re.DOTALL,
)
source = source.replace('  <main>\n', '  <div class="depthmap-page-content">\n', 1)
source = source.replace('  </main>\n', '  </div>\n', 1)
source = source.replace("/material-libraries", "/")
source = source.replace("/docs/depthmap-generator", "/")
source = source.replace("/login", "/")
source = source.replace("{{ depth_palette|tojson }}", "[]")
source = source.replace(
    '<script type="module" src="/static/depthmap_generator.js?v=9"></script>',
    '<script type="module" src="/depthmap_bootstrap.js?v=3"></script>',
)
Path(sys.argv[2]).write_text(source, encoding="utf-8")
