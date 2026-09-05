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

            depth = (output / "depthmap-relief-engraving-tool").read_text(encoding="utf-8")
            self.assertIn('href="/depthmap.html"', depth)

            sitemap = (output / "sitemap.xml").read_text(encoding="utf-8")
            self.assertIn("https://staging.example.com/docs/example-guide", sitemap)
            self.assertNotIn("history.html</loc>", sitemap)

            robots = (output / "robots.txt").read_text(encoding="utf-8")
            self.assertIn("Disallow: /history.html", robots)
            self.assertIn("Sitemap: https://staging.example.com/sitemap.xml", robots)

    def test_deployment_uploads_all_seo_assets(self):
        deploy = (ROOT / "dev_setup" / "deploy_serverless_staging_web.sh").read_text(encoding="utf-8")
        self.assertIn("build_serverless_seo.py", deploy)
        self.assertIn('PUBLIC_BASE_URL="${SERVERLESS_STAGING_PUBLIC_URL:-$WEB_URL}"', deploy)
        self.assertIn('$BUILD_DIR/seo/index.html', deploy)
        self.assertIn("laser-engraving-tool color-laser-engraving-tool depthmap-relief-engraving-tool", deploy)
        self.assertIn('web/sitemap.xml', deploy)
        self.assertIn('web/robots.txt', deploy)


if __name__ == "__main__":
    unittest.main()
