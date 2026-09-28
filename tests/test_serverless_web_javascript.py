import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "serverless_web"
DEPLOY = ROOT / "dev_setup" / "deploy_serverless_staging_web.sh"
EXECUTABLE_SCRIPT_TYPES = {"", "module", "text/javascript", "application/javascript"}


class _ServerlessHtmlParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._capturing_mode: str | None = None
        self._parts: list[str] = []
        self.inline_scripts: list[tuple[str, str]] = []
        self.script_sources: list[tuple[str, str]] = []
        self.inline_event_attributes: list[tuple[str, str]] = []
        self.javascript_urls: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        for name, value in attrs:
            if name.lower().startswith("on"):
                self.inline_event_attributes.append((tag, name))
            if value and re.match(r"^[\x00-\x20]*javascript\s*:", value, re.IGNORECASE):
                self.javascript_urls.append((tag, name))

        if tag != "script":
            return
        script_type = attributes.get("type", "").lower()
        if script_type not in EXECUTABLE_SCRIPT_TYPES:
            return
        mode = "module" if script_type == "module" else "classic"
        if "src" in attributes:
            self.script_sources.append((mode, attributes["src"]))
        else:
            self._capturing_mode = mode
            self._parts = []

    def handle_data(self, data):
        if self._capturing_mode:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._capturing_mode:
            self.inline_scripts.append((self._capturing_mode, "".join(self._parts)))
            self._capturing_mode = None


def _parse_html(source: str) -> _ServerlessHtmlParser:
    parser = _ServerlessHtmlParser()
    parser.feed(source)
    return parser


def _digest(script: str) -> str:
    return hashlib.sha256(script.strip().encode("utf-8")).hexdigest()


def _run_builder(*arguments: Path | str) -> None:
    subprocess.run(
        [sys.executable, *(str(argument) for argument in arguments)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.fixture(scope="module")
def rendered_serverless_pages():
    with tempfile.TemporaryDirectory(prefix=".serverless-build-", dir=ROOT) as directory:
        build = Path(directory)
        docs = build / "docs"
        seo = build / "seo"
        _run_builder(
            ROOT / "dev_setup" / "build_serverless_depthmap.py",
            ROOT / "templates" / "depthmap_generator.html",
            build / "depthmap.html",
            "https://staging.example.com/",
        )
        _run_builder(
            ROOT / "dev_setup" / "build_serverless_community.py",
            build / "community-set",
            "https://staging.example.com/",
        )
        _run_builder(
            ROOT / "dev_setup" / "build_serverless_experimental.py",
            ROOT / "templates" / "experimental_laboratories.html",
            build / "experimental-laboratories",
            "https://staging.example.com/",
        )
        _run_builder(
            ROOT / "dev_setup" / "build_serverless_docs.py",
            docs,
            "https://staging.example.com/",
        )
        _run_builder(
            ROOT / "dev_setup" / "build_serverless_seo.py",
            seo,
            "https://staging.example.com/",
        )

        pages = {
            "generated/depthmap.html": (build / "depthmap.html").read_text(encoding="utf-8"),
            "generated/community-set": (build / "community-set").read_text(encoding="utf-8"),
            "generated/experimental-laboratories": (
                build / "experimental-laboratories"
            ).read_text(encoding="utf-8"),
        }
        pages.update(
            {
                f"generated/docs/{path.relative_to(docs).as_posix()}": path.read_text(
                    encoding="utf-8"
                )
                for path in docs.rglob("*")
                if path.is_file()
            }
        )
        pages.update(
            {
                f"generated/seo/{path.relative_to(seo).as_posix()}": path.read_text(
                    encoding="utf-8"
                )
                for path in seo.rglob("*")
                if path.is_file() and path.name not in {"robots.txt", "sitemap.xml"}
            }
        )
        yield pages


def _checked_in_pages() -> dict[str, str]:
    return {
        f"source/{path.relative_to(WEB).as_posix()}": path.read_text(encoding="utf-8")
        for path in WEB.rglob("*.html")
    }


# Transitional debt inventory. Never add or replace hashes to land behavior;
# extraction work removes entries. The Rasterizer hash tracks current staging.
SHELL_GUARD_HASH = "6afe671e06228bf00df1e5b2e9542d2c9bf31bffdb040eed534930592487f3cf"
LEGACY_REDIRECT_HASH = "784998b36758a08dfefab6f0fea37fbe5846fb551eae8eb74352f1cecce9bac6"
RASTERIZER_APPLICATION_HASH = "619e744be7fa9f7fa8c009d0ad30f19fc46109405cc7a064cd99e199f7da3d87"
RELEASE_STORY_HASH = "261e9c866cbd5628036f898e027a1051cac5dc3b1552fa7d825f525fb14ded5d"
COMMUNITY_SET_HASH = "5626d1eaf3a88fe21799fd0c066f210417bfe99b66cef513f026da2550481839"
DOCS_SEARCH_HASH = "ecc28e0ed71b4db2503083131f94f84e6ea0e24605d528ab39e6ee484cefcc56"

SHELL_GUARD = ("classic", SHELL_GUARD_HASH)
LEGACY_REDIRECT = ("classic", LEGACY_REDIRECT_HASH)
RASTERIZER_APPLICATION = ("classic", RASTERIZER_APPLICATION_HASH)
RELEASE_STORY = ("classic", RELEASE_STORY_HASH)
COMMUNITY_SET = ("classic", COMMUNITY_SET_HASH)
DOCS_SEARCH = ("classic", DOCS_SEARCH_HASH)

ALLOWED_SOURCE_INLINE_SCRIPTS = {
    "source/admin.html": [SHELL_GUARD],
    "source/color-lab.html": [SHELL_GUARD],
    "source/history.html": [SHELL_GUARD],
    "source/holographic.html": [SHELL_GUARD],
    "source/holographic-redirect.html": [LEGACY_REDIRECT],
    "source/index.html": [SHELL_GUARD, RASTERIZER_APPLICATION],
    "source/mandala.html": [],
    "source/release-story.html": [SHELL_GUARD, RELEASE_STORY],
    "source/spiralgrap.html": [],
    "source/spiralgraph.html": [],
    "source/vault.html": [SHELL_GUARD],
}


def test_checked_in_serverless_html_does_not_gain_inline_javascript():
    observed = {
        name: [(mode, _digest(script)) for mode, script in parser.inline_scripts]
        for name, source in _checked_in_pages().items()
        if (parser := _parse_html(source))
    }

    assert observed == ALLOWED_SOURCE_INLINE_SCRIPTS


def test_rendered_serverless_html_does_not_gain_inline_javascript(
    rendered_serverless_pages,
):
    observed = {
        name: [(mode, _digest(script)) for mode, script in parser.inline_scripts]
        for name, source in rendered_serverless_pages.items()
        if (parser := _parse_html(source))
    }
    expected = {name: [SHELL_GUARD] for name in rendered_serverless_pages}
    expected["generated/community-set"] = [SHELL_GUARD, COMMUNITY_SET]
    expected["generated/docs/index.html"] = [SHELL_GUARD, DOCS_SEARCH]
    expected["generated/seo/index.html"] = [SHELL_GUARD, RASTERIZER_APPLICATION]
    for zero_inline_page in (
        "generated/seo/mandala.html",
        "generated/seo/spiralgrap.html",
        "generated/seo/spiralgraph.html",
    ):
        expected[zero_inline_page] = []

    assert observed == expected


def test_serverless_sources_and_rendered_routes_have_no_inline_handlers_or_urls(
    rendered_serverless_pages,
):
    violations = {}
    for name, source in {**_checked_in_pages(), **rendered_serverless_pages}.items():
        parser = _parse_html(source)
        if parser.inline_event_attributes or parser.javascript_urls:
            violations[name] = {
                "event_attributes": parser.inline_event_attributes,
                "javascript_urls": parser.javascript_urls,
            }

    assert violations == {}


def test_html_parser_recognizes_obfuscated_executable_attributes():
    parser = _parse_html(
        '<a href="&#x6a;avascript:alert(1)" onClick="alert(2)">unsafe</a>'
    )

    assert parser.javascript_urls == [("a", "href")]
    assert parser.inline_event_attributes == [("a", "onclick")]


def test_all_serverless_web_javascript_parses_in_its_execution_mode(
    rendered_serverless_pages,
):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to syntax-check the browser JavaScript")

    pages = {**_checked_in_pages(), **rendered_serverless_pages}
    referenced_modes: dict[Path, set[str]] = {}
    inline_sources: dict[tuple[str, str], str] = {}
    for source in pages.values():
        parser = _parse_html(source)
        for mode, script in parser.inline_scripts:
            inline_sources[(mode, _digest(script))] = script
        for mode, source_url in parser.script_sources:
            relative = source_url.split("?", 1)[0].lstrip("/")
            candidate = WEB / relative
            if candidate.is_file():
                referenced_modes.setdefault(candidate, set()).add(mode)

    javascript_files = set(WEB.rglob("*.js"))
    assert set(referenced_modes) == javascript_files
    assert all(len(modes) == 1 for modes in referenced_modes.values())
    assert referenced_modes[WEB / "staging-shell.js"] == {"classic"}
    assert referenced_modes[WEB / "blank-palette.js"] == {"classic"}
    for filename in (
        "admin.js",
        "color-lab.js",
        "depthmap_bootstrap.js",
        "history.js",
        "holographic.js",
        "vault.js",
    ):
        assert referenced_modes[WEB / filename] == {"module"}

    sources = [
        (path.relative_to(WEB).as_posix(), next(iter(modes)), path.read_text(encoding="utf-8"))
        for path, modes in sorted(referenced_modes.items())
    ]
    sources.extend(
        (f"inline {digest}", mode, script)
        for (mode, digest), script in inline_sources.items()
    )

    with tempfile.TemporaryDirectory(prefix=".js-check-", dir=ROOT) as directory:
        for index, (name, mode, script) in enumerate(sources):
            suffix = ".mjs" if mode == "module" else ".js"
            check_path = Path(directory) / f"source-{index}{suffix}"
            check_path.write_text(script, encoding="utf-8")
            result = subprocess.run(
                [node, "--check", str(check_path)],
                text=True,
                capture_output=True,
                check=False,
                timeout=15,
            )
            assert result.returncode == 0, (
                f"{name} ({mode}) contains invalid JavaScript:\n{result.stderr}"
            )


def test_new_script_dependencies_must_upload_before_dependent_html(
    rendered_serverless_pages,
):
    deploy = DEPLOY.read_text(encoding="utf-8")
    page_uploads = {
        "source/history.html": '$REPO_ROOT/serverless_web/history.html',
        "source/admin.html": '$REPO_ROOT/serverless_web/admin.html',
        "source/vault.html": '$REPO_ROOT/serverless_web/vault.html',
        "source/release-story.html": '$REPO_ROOT/serverless_web/release-story.html',
        "generated/depthmap.html": '$BUILD_DIR/depthmap.html',
        "generated/community-set": '$BUILD_DIR/community-set',
        "generated/experimental-laboratories": '$BUILD_DIR/experimental-laboratories',
        "generated/docs/index.html": '$BUILD_DIR/docs/index.html',
        "generated/docs/blank-palette-library": '$BUILD_DIR/docs/',
        "generated/seo/index.html": '$BUILD_DIR/seo/index.html',
        "generated/seo/fauxlographic.html": '$BUILD_DIR/seo/fauxlographic.html',
        "generated/seo/color-lab.html": '$BUILD_DIR/seo/color-lab.html',
        "generated/seo/laser-engraving-tool": '$BUILD_DIR/seo/$route',
        "generated/seo/color-laser-engraving-tool": '$BUILD_DIR/seo/$route',
        "generated/seo/depthmap-relief-engraving-tool": '$BUILD_DIR/seo/$route',
    }
    legacy_html_first_debt = {
        ("generated/seo/index.html", "staging-shell.js"),
        ("generated/seo/fauxlographic.html", "holographic.js"),
        ("generated/seo/fauxlographic.html", "staging-shell.js"),
        ("generated/seo/color-lab.html", "color-lab.js"),
        ("generated/seo/color-lab.html", "staging-shell.js"),
        ("generated/depthmap.html", "depthmap_bootstrap.js"),
        ("source/history.html", "history.js"),
        ("source/admin.html", "admin.js"),
        ("source/vault.html", "vault.js"),
    }
    observed_html_first_debt = set()

    pages = {**_checked_in_pages(), **rendered_serverless_pages}
    for page_name, page_source in page_uploads.items():
        page_position = deploy.index(f'aws s3 cp "{page_source}"')
        for _mode, source_url in _parse_html(pages[page_name]).script_sources:
            filename = source_url.split("?", 1)[0].lstrip("/")
            if not (WEB / filename).is_file():
                continue
            asset_source = f"$REPO_ROOT/serverless_web/{filename}"
            marker = f'aws s3 cp "{asset_source}"'
            assert marker in deploy, f"{filename} is referenced but not uploaded"
            if deploy.index(marker) > page_position:
                observed_html_first_debt.add((page_name, filename))

    assert observed_html_first_debt == legacy_html_first_debt
