import hashlib
import shutil
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "serverless_web"


class _ServerlessHtmlParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._capturing = False
        self._parts: list[str] = []
        self.scripts: list[str] = []
        self.inline_event_attributes: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        self.inline_event_attributes.extend(
            (tag, name) for name, _value in attrs if name.lower().startswith("on")
        )
        script_type = attributes.get("type", "").lower()
        if (
            tag == "script"
            and "src" not in attributes
            and script_type in {"", "module", "text/javascript", "application/javascript"}
        ):
            self._capturing = True
            self._parts = []

    def handle_data(self, data):
        if self._capturing:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._capturing:
            self.scripts.append("".join(self._parts))
            self._capturing = False


def _parse_html(path: Path) -> _ServerlessHtmlParser:
    parser = _ServerlessHtmlParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser


def _digest(script: str) -> str:
    return hashlib.sha256(script.strip().encode("utf-8")).hexdigest()


# Transitional debt inventory. Do not add or replace hashes when adding behavior;
# put new JavaScript in an external file. Extraction work should only remove entries.
SHELL_GUARD_HASH = (
    "6afe671e06228bf00df1e5b2e9542d2c9bf31bffdb040eed534930592487f3cf"
)
LEGACY_REDIRECT_HASH = (
    "784998b36758a08dfefab6f0fea37fbe5846fb551eae8eb74352f1cecce9bac6"
)
RASTERIZER_APPLICATION_HASH = (
    "83a03ec91d821d55ee7d0fa89ca0dcbeb166650a3665dd3aa46df1eac8e6766f"
)
RELEASE_STORY_HASH = (
    "261e9c866cbd5628036f898e027a1051cac5dc3b1552fa7d825f525fb14ded5d"
)
ALLOWED_INLINE_SCRIPT_HASHES = {
    # Exact hashes ensure that modifying a grandfathered block also fails.
    "admin.html": {SHELL_GUARD_HASH},
    "color-lab.html": {SHELL_GUARD_HASH},
    "history.html": {SHELL_GUARD_HASH},
    "holographic.html": {SHELL_GUARD_HASH},
    "holographic-redirect.html": {LEGACY_REDIRECT_HASH},
    "index.html": {SHELL_GUARD_HASH, RASTERIZER_APPLICATION_HASH},
    "release-story.html": {SHELL_GUARD_HASH, RELEASE_STORY_HASH},
    "vault.html": {SHELL_GUARD_HASH},
}


def test_serverless_html_does_not_gain_inline_javascript():
    observed = {
        path.relative_to(WEB).as_posix(): {_digest(script) for script in parser.scripts}
        for path in sorted(WEB.rglob("*.html"))
        if (parser := _parse_html(path)).scripts
    }

    assert observed == ALLOWED_INLINE_SCRIPT_HASHES


def test_serverless_html_has_no_inline_event_attributes():
    violations = {
        path.relative_to(WEB).as_posix(): parser.inline_event_attributes
        for path in sorted(WEB.rglob("*.html"))
        if (parser := _parse_html(path)).inline_event_attributes
    }

    assert violations == {}


def test_all_serverless_web_javascript_parses():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to syntax-check the browser JavaScript")

    sources = [
        (path.relative_to(WEB).as_posix(), path.read_text(encoding="utf-8"))
        for path in sorted(WEB.rglob("*.js"))
    ]
    for path in sorted(WEB.rglob("*.html")):
        sources.extend(
            (
                f"{path.relative_to(WEB).as_posix()} inline script {index}",
                script,
            )
            for index, script in enumerate(_parse_html(path).scripts)
        )

    assert sources
    with tempfile.TemporaryDirectory(prefix=".js-check-", dir=ROOT) as directory:
        for index, (name, script) in enumerate(sources):
            check_path = Path(directory) / f"source-{index}.mjs"
            check_path.write_text(script, encoding="utf-8")
            result = subprocess.run(
                [node, "--check", str(check_path)],
                text=True,
                capture_output=True,
                check=False,
                timeout=15,
            )
            assert result.returncode == 0, (
                f"{name} contains invalid JavaScript:\n{result.stderr}"
            )
