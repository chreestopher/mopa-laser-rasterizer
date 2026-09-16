#!/usr/bin/env python3
"""Render the production Experimental Laboratories landing page for staging."""

import re
import sys
from pathlib import Path


source = Path(sys.argv[1]).read_text(encoding="utf-8")
source = source.replace('{% from "_machine_chrome.html" import machine_chrome %}\n', "", 1)
source = source.replace('<link rel="canonical" href="{{ canonical }}">',
                        '<link rel="canonical" href="/experimental-laboratories">')
source = source.replace('  <link rel="stylesheet" href="/static/machine_chrome.css?v=3">\n', "")
source = re.sub(r"\s*\{\{ machine_chrome\([^\n]+\) \}\}\n", "\n", source, count=1)
source = re.sub(
    r'\s*<section class="hero">.*?</section>\s*',
    "\n",
    source,
    count=1,
    flags=re.DOTALL,
)
source = source.replace('href="/fauxlographic-etching"', 'href="/fauxlographic.html"')
source = source.replace('href="/holographic-etching"', 'href="/fauxlographic.html"')
source = source.replace('href="/depthmap-generator"', 'href="/depthmap.html"')
source = source.replace('href="/color-discovery"', 'href="/color-lab.html"')
source = source.replace('href="/depthmap-relief-engraving-tool"', 'href="/docs/depthmap-generator"')
source = source.replace(
    "</head>",
    "  <style>html.staging-shell-pending body{visibility:hidden}</style>\n"
    "  <script>document.documentElement.classList.add('staging-shell-pending');setTimeout(()=>document.documentElement.classList.remove('staging-shell-pending'),3000)</script>\n"
    '  <link rel="stylesheet" href="/machine_chrome.css?v=3">\n'
    '  <link rel="stylesheet" href="/staging-shell.css?v=1">\n'
    '  <link rel="stylesheet" href="/staging-pages.css?v=1">\n'
    '  <script src="/staging-shell.js?v=3" defer></script>\n'
    "</head>",
    1,
)
Path(sys.argv[2]).write_text(source, encoding="utf-8")
