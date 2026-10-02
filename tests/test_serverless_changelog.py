import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "dev_setup" / "build_serverless_changelog.py"


def load_builder():
    spec = importlib.util.spec_from_file_location("build_serverless_changelog", BUILDER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILDER = load_builder()


def release(identifier, version, released_on, title=None):
    return {
        "id": identifier,
        "version": version,
        "date": released_on,
        "title": title or f"Release {version}",
        "summary": f"Summary for {version}",
        "groups": [{"title": "Highlights", "items": [f"Change from {version}"]}],
        "links": [{"label": "Documentation", "href": "/docs"}],
    }


class ChangelogParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.release_ids = []
        self.links = []
        self.main_ids = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "article" and "release" in attributes.get("class", "").split():
            self.release_ids.append(attributes.get("id"))
        if tag == "a":
            self.links.append(attributes)
        if tag == "main":
            self.main_ids.append(attributes.get("id"))


class ServerlessChangelogTests(unittest.TestCase):
    def write_source(self, root, releases):
        path = root / "changelog.json"
        path.write_text(
            json.dumps({"schema_version": 1, "releases": releases}), encoding="utf-8"
        )
        return path

    def render(self, source):
        return BUILDER.render_changelog(
            source, ROOT / "templates" / "changelog.html", "https://staging.example.com"
        )

    def test_generator_is_deterministic_and_renders_newest_first(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = self.write_source(
                Path(temporary),
                [
                    release("v1-2-0", "v1.2.0", "2026-03-03"),
                    release("v1-1-0", "v1.1.0", "2026-02-02"),
                    release("v1-0-0", "v1.0.0", "2026-01-01"),
                ],
            )
            first = self.render(source)
            second = self.render(source)
            self.assertEqual(first, second)
            parser = ChangelogParser()
            parser.feed(first)
            self.assertEqual(parser.release_ids, ["v1-2-0", "v1-1-0", "v1-0-0"])
            self.assertEqual(parser.main_ids, ["main-content"])
            self.assertIn('<link rel="canonical" href="https://staging.example.com/changelog">', first)

    def test_prepending_release_preserves_every_existing_entry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            previous = [
                release("v1-1-0", "v1.1.0", "2026-02-02"),
                release("v1-0-0", "v1.0.0", "2026-01-01"),
            ]
            old_html = self.render(self.write_source(root, previous))
            new_html = self.render(
                self.write_source(
                    root, [release("v1-2-0", "v1.2.0", "2026-03-03"), *previous]
                )
            )
            for identifier in ("v1-1-0", "v1-0-0"):
                self.assertIn(f'id="{identifier}"', old_html)
                self.assertIn(f'id="{identifier}"', new_html)
            self.assertLess(new_html.index('id="v1-2-0"'), new_html.index('id="v1-1-0"'))

    def test_validation_rejects_reordering_duplicates_and_unsafe_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "newest-first"):
                BUILDER.load_releases(
                    self.write_source(
                        root,
                        [
                            release("v1-0-0", "v1.0.0", "2026-01-01"),
                            release("v1-1-0", "v1.1.0", "2026-02-02"),
                        ],
                    )
                )
            with self.assertRaisesRegex(ValueError, "duplicates"):
                BUILDER.load_releases(
                    self.write_source(
                        root,
                        [
                            release("same", "v1.1.0", "2026-02-02"),
                            release("same", "v1.0.0", "2026-01-01"),
                        ],
                    )
                )
            unsafe = release("unsafe", "v2.0.0", "2026-04-04")
            unsafe["links"] = [{"label": "Unsafe", "href": "javascript:alert(1)"}]
            with self.assertRaisesRegex(ValueError, "root-relative or HTTPS"):
                BUILDER.load_releases(self.write_source(root, [unsafe]))

    def test_rendering_escapes_content_and_hardens_external_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            item = release("safe", "v2.0.0", "2026-04-04", "<script>bad()</script>")
            item["links"].append({"label": "Source", "href": "https://example.com/release"})
            html = self.render(self.write_source(Path(temporary), [item]))
            self.assertNotIn("<script>bad()</script>", html)
            self.assertIn("&lt;script&gt;bad()&lt;/script&gt;", html)
            parser = ChangelogParser()
            parser.feed(html)
            external = next(link for link in parser.links if link.get("href") == "https://example.com/release")
            self.assertEqual(external.get("target"), "_blank")
            self.assertEqual(external.get("rel"), "noopener noreferrer")

    def test_repository_source_builds_and_links_to_known_routes(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "changelog"
            subprocess.run(
                [sys.executable, str(BUILDER_PATH), str(output), "https://preview.example.com"],
                check=True,
            )
            html = output.read_text(encoding="utf-8")
            parser = ChangelogParser()
            parser.feed(html)
            self.assertEqual(parser.release_ids, ["v1-1-0", "v1-0-0"])
            self.assertIn("Build Bigger, Shape Deeper, and Control More of the Engraving", html)
            self.assertIn("Panel Tiling", html)
            self.assertIn("Processing Palettes", html)
            self.assertIn("Layered Mandala Lab", html)
            self.assertIn("SpiralGraph Lab", html)
            internal = {link["href"] for link in parser.links if link.get("href", "").startswith("/")}
            self.assertEqual(internal, {"/docs", "/release-story"})
            self.assertIn('src="/staging-shell.js?v=4"', html)
            self.assertIn('href="/staging-shell-v2.css"', html)
            self.assertIn('href="/changelog-v1.css"', html)
            self.assertNotIn("<style", html)

    def test_deployment_navigation_and_sitemap_include_changelog(self):
        deploy = (ROOT / "dev_setup" / "deploy_serverless_staging_web.sh").read_text(encoding="utf-8")
        production = (ROOT / "dev_setup" / "deploy_serverless_production_web.sh").read_text(encoding="utf-8")
        seo = (ROOT / "dev_setup" / "build_serverless_seo.py").read_text(encoding="utf-8")
        shell = (ROOT / "serverless_web" / "staging-shell.js").read_text(encoding="utf-8")
        docs = (ROOT / "templates" / "docs.html").read_text(encoding="utf-8")
        self.assertIn('build_serverless_changelog.py" "$BUILD_DIR/changelog"', deploy)
        self.assertIn('serverless_web/changelog-v1.css', deploy)
        self.assertIn('"s3://$STATIC_BUCKET/web/changelog"', deploy)
        self.assertIn('exec bash "$SCRIPT_DIR/deploy_serverless_staging_web.sh"', production)
        self.assertIn('"changelog",', seo)
        self.assertIn('path === "/changelog"', shell)
        self.assertIn('href="/changelog">Changelog</a>', docs)


if __name__ == "__main__":
    unittest.main()
