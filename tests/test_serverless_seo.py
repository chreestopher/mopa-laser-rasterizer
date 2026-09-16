import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ServerlessSeoTests(unittest.TestCase):
    def test_builder_renders_public_pages_and_crawler_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            docs = root / "docs"
            docs.mkdir()
            (docs / "example-guide").write_text("guide", encoding="utf-8")
            output = root / "seo"
            subprocess.run(
                [sys.executable, str(ROOT / "dev_setup" / "build_serverless_seo.py"), str(output), "https://staging.example.com"],
                check=True,
            )

            color = (output / "color-laser-engraving-tool").read_text(encoding="utf-8")
            self.assertIn('<link rel="canonical" href="https://staging.example.com/color-laser-engraving-tool">', color)
            self.assertIn('href="/laser-engraving-tool"', color)
            self.assertIn("select <strong>SVG-Only</strong>", color)
            self.assertNotIn("machine_chrome(", color)

            home = (output / "index.html").read_text(encoding="utf-8")
            self.assertIn("MOPA Laser Rasterizer | Layered SVG and LightBurn Artwork", home)
            self.assertIn('<link rel="canonical" href="https://staging.example.com/">', home)

            fauxlographic = (output / "fauxlographic.html").read_text(encoding="utf-8")
            self.assertIn('<link rel="canonical" href="https://staging.example.com/fauxlographic.html">', fauxlographic)
            color_lab = (output / "color-lab.html").read_text(encoding="utf-8")
            self.assertIn('<link rel="canonical" href="https://staging.example.com/color-lab.html">', color_lab)
            self.assertIn('<meta name="description"', color_lab)

            depth = (output / "depthmap-relief-engraving-tool").read_text(encoding="utf-8")
            self.assertIn('href="/depthmap.html"', depth)

            sitemap = (output / "sitemap.xml").read_text(encoding="utf-8")
            self.assertIn("https://staging.example.com/docs/example-guide", sitemap)
            self.assertNotIn("history.html</loc>", sitemap)

            robots = (output / "robots.txt").read_text(encoding="utf-8")
            self.assertIn("Disallow: /history.html", robots)
            self.assertIn("Sitemap: https://staging.example.com/sitemap.xml", robots)

    def test_other_public_pages_use_the_deployment_hostname(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            url = "https://staging.example.com"
            for script, source, target, route in (
                ("build_serverless_depthmap.py", "templates/depthmap_generator.html", "depthmap.html", "depthmap.html"),
                ("build_serverless_experimental.py", "templates/experimental_laboratories.html", "experimental-laboratories", "experimental-laboratories"),
            ):
                subprocess.run(
                    [sys.executable, str(ROOT / "dev_setup" / script), str(ROOT / source), str(output / target), url],
                    check=True,
                )
                html = (output / target).read_text(encoding="utf-8")
                self.assertIn(f'<link rel="canonical" href="{url}/{route}">', html)
            subprocess.run(
                [sys.executable, str(ROOT / "dev_setup" / "build_serverless_community.py"), str(output / "community-set"), url],
                check=True,
            )
            community = (output / "community-set").read_text(encoding="utf-8")
            self.assertIn('<link rel="canonical" href="https://staging.example.com/community-set">', community)
            story = (ROOT / "serverless_web" / "release-story.html").read_text(encoding="utf-8")
            self.assertIn('<link rel="canonical" href="https://mopa-laser-rasterizer.com/release-story">', story)

    def test_deployment_uploads_all_seo_assets(self):
        deploy = (ROOT / "dev_setup" / "deploy_serverless_staging_web.sh").read_text(encoding="utf-8")
        self.assertIn("build_serverless_seo.py", deploy)
        self.assertIn('PUBLIC_BASE_URL="${SERVERLESS_PUBLIC_URL:-${SERVERLESS_STAGING_PUBLIC_URL:-$WEB_URL}}"', deploy)
        self.assertIn('$BUILD_DIR/seo/index.html', deploy)
        self.assertIn("laser-engraving-tool color-laser-engraving-tool depthmap-relief-engraving-tool", deploy)
        self.assertIn('web/sitemap.xml', deploy)
        self.assertIn('web/robots.txt', deploy)
        self.assertIn('$BUILD_DIR/seo/fauxlographic.html', deploy)
        self.assertIn('$BUILD_DIR/seo/color-lab.html', deploy)


if __name__ == "__main__":
    unittest.main()
