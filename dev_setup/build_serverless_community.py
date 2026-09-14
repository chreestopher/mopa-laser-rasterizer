#!/usr/bin/env python3
"""Render the production Community Set page for authenticated staging."""

import re
import sys
from pathlib import Path

from jinja2 import Environment


repo_root = Path(__file__).resolve().parents[1]
output_path = Path(sys.argv[1])
source = (repo_root / "templates" / "community_set.html").read_text(encoding="utf-8")
source = source.replace("{% from '_machine_chrome.html' import machine_chrome %}\n", "", 1)
source = re.sub(r"\s*\{\{ machine_chrome\([^\n]+\) \}\}\n", "\n", source, count=1)
source = source.replace('<link rel="stylesheet" href="/static/machine_chrome.css?v=3">', "")
source = source.replace('<main class="machine">', '<main id="main-content">', 1)
source = source.replace(
    "</head>",
    "  <style>html.staging-shell-pending body{visibility:hidden}</style>\n"
    "  <script>document.documentElement.classList.add('staging-shell-pending');setTimeout(()=>document.documentElement.classList.remove('staging-shell-pending'),3000)</script>\n"
    '  <link rel="stylesheet" href="/machine_chrome.css?v=3">\n'
    '  <link rel="stylesheet" href="/staging-shell.css?v=1">\n'
    '  <link rel="stylesheet" href="/staging-pages.css?v=1">\n'
    '  <script src="/staging-shell.js?v=2" defer></script>\n'
    "</head>",
    1,
)
source = source.replace(
    "const response=await fetch(`/community-set/settings?${query}`,{credentials:'same-origin'});",
    "const config=await fetch('/config.json',{cache:'no-store'}).then(result=>result.json());"
    "let token=localStorage.getItem('id_token')||sessionStorage.getItem('id_token');"
    "const refreshToken=localStorage.getItem('refresh_token')||sessionStorage.getItem('refresh_token');"
    "if(!token) throw new Error('Sign in to search Community Set settings.');"
    "const request=()=>fetch(`${config.api_url}/community-set/settings?${query}`,"
    "{headers:{authorization:`Bearer ${token}`}});"
    "let response=await request();"
    "if(response.status===401&&refreshToken){"
    "const body=new URLSearchParams({grant_type:'refresh_token',client_id:config.client_id,refresh_token:refreshToken});"
    "const refreshed=await fetch(`https://${config.cognito_domain}/oauth2/token`,"
    "{method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},body}).then(result=>result.json());"
    "if(refreshed.id_token){token=refreshed.id_token;localStorage.setItem('id_token',token);response=await request();}"
    "}"
    "if(response.status===401)throw new Error('Session expired. Sign in again.');",
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
    member_access=True, auth_state="signed_in", official_colors=official_colors
)
output_path.write_text(html, encoding="utf-8")
