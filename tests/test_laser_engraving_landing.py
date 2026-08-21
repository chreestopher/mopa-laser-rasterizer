import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LaserEngravingLandingCoverageTests(unittest.TestCase):
    def test_non_color_landing_page_is_routed_and_indexed(self):
        home = (ROOT / "routes" / "home.py").read_text(encoding="utf-8")
        docs = (ROOT / "routes" / "docs.py").read_text(encoding="utf-8")
        page = (ROOT / "templates" / "laser_engraving_tool.html").read_text(encoding="utf-8")

        self.assertIn('@routes.route("/laser-engraving-tool")', home)
        self.assertIn('"laser_engraving_tool.html"', home)
        self.assertIn('"/laser-engraving-tool"', docs)
        self.assertIn("Hatch Palettes for monochrome contrast", page)
        self.assertIn("Using a MOPA or Q-switched fiber laser?", page)
        self.assertIn('href="/color-laser-engraving-tool"', page)
        self.assertIn('/docs/svg-only-mode', page)
        self.assertIn('/docs/laser-compatibility', page)
        self.assertIn("Hatch Palette settings require LightBurn mode", page)
        self.assertIn("SVG-only mode does not apply Hatch Palette angles", page)
        self.assertIn("Each Entry Description must match its Rasterizer swatch name", page)
        self.assertIn("Members:</strong> create and retain Hatch Palettes", page)


if __name__ == "__main__":
    unittest.main()
