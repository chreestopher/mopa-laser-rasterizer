import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest


class _InlineScriptParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._capturing = False
        self._parts: list[str] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and "src" not in dict(attrs):
            self._capturing = True
            self._parts = []

    def handle_data(self, data):
        if self._capturing:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._capturing:
            self.scripts.append("".join(self._parts))
            self._capturing = False


def test_all_serverless_web_inline_javascript_parses():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to syntax-check the browser JavaScript")

    parser = _InlineScriptParser()
    parser.feed(Path("serverless_web/index.html").read_text(encoding="utf-8"))

    assert parser.scripts
    for index, script in enumerate(parser.scripts):
        result = subprocess.run(
            [node, "--check", "-"],
            input=script,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"Inline script {index} contains invalid JavaScript:\n{result.stderr}"
        )
