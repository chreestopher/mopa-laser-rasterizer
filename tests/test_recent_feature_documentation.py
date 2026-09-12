import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RecentFeatureDocumentationTests(unittest.TestCase):
    def test_recent_workflow_guides_render_and_are_linked(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "docs"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "dev_setup" / "build_serverless_docs.py"),
                    str(output),
                    "https://staging.example.com",
                ],
                check=True,
            )

            index = (output / "index.html").read_text(encoding="utf-8")
            cropping = (output / "artwork-cropping").read_text(encoding="utf-8")
            geometry = (output / "geometry-styles").read_text(encoding="utf-8")
            krasnow = (output / "krasnow-grating-filter").read_text(encoding="utf-8")
            export = (output / "lightburn-export").read_text(encoding="utf-8")

            self.assertIn('href="/docs/artwork-cropping"', index)
            self.assertIn('href="/docs/geometry-styles"', index)
            self.assertIn("Crop transparency", cropping)
            self.assertIn("transparent holes inside it remain transparent", cropping)
            self.assertIn("Choose by swatch", geometry)
            self.assertIn("mutually exclusive", geometry)
            self.assertIn("Invert Fill", geometry)
            self.assertIn("paw print", geometry)
            self.assertIn("Fauxlogram Gradient Scope", geometry)
            self.assertIn("vertically, horizontally, or radially", geometry)
            self.assertFalse((output / "glyph-mosaic-filter").exists())
            self.assertIn("Preserve Black disabled", krasnow)
            self.assertIn("parent Fauxlographic CutSetting", krasnow)
            self.assertIn("Fauxlogram Gradient controls in Geometry Style", krasnow)
            self.assertIn("whole-artwork radial layouts", krasnow)
            self.assertIn("50,000,000 bytes", export)
            self.assertIn("Geometry Style and its parameters", export)


if __name__ == "__main__":
    unittest.main()
