import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProcessingPaletteTests(unittest.TestCase):
    def test_processing_palette_is_a_supported_saved_intent(self):
        handler = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
        services = (ROOT / "services.py").read_text(encoding="utf-8")
        self.assertIn('"processing_palette"', handler)
        self.assertIn('"processing_palette"', services)
        self.assertIn('processing_palette_role_assignments', handler)

    def test_vault_exposes_all_initial_processing_roles(self):
        page = (ROOT / "serverless_web" / "vault.html").read_text(encoding="utf-8")
        client = (ROOT / "serverless_web" / "vault.js").read_text(encoding="utf-8")
        self.assertIn('<option value="processing_palette">Processing palette</option>', page)
        self.assertIn('["Cut","Score","Photo","Fill","Shovel","Cleaning"]', client)
        self.assertIn('processingRolePicker', client)
        self.assertIn('processing_palette_role_assignments:assignments', client)

    def test_processing_palettes_are_scoped_to_depthmap_tools(self):
        rasterizer = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")
        color_lab = (ROOT / "serverless_web" / "color-lab.js").read_text(encoding="utf-8")
        depthmap = (ROOT / "static" / "depthmap_generator.js").read_text(encoding="utf-8")
        handler = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
        self.assertIn("item.library_intent!=='processing_palette'", rasterizer)
        self.assertIn('item.library_intent!=="processing_palette"', color_lab)
        self.assertIn('library.library_intent === "processing_palette"', depthmap)
        self.assertIn('roleEntry("Cut")', depthmap)
        self.assertIn('roleEntry("Photo")', depthmap)
        self.assertIn('selected Cut setting must use LightBurn Line mode', depthmap)
        self.assertIn('Processing Palettes are for Depthmap tools', handler)
        self.assertIn('Processing Palettes cannot be used for Color Discovery grids', handler)
        self.assertIn('Processing Palettes cannot be used for Fauxlographic calibration grids', handler)

    def test_color_template_no_longer_contains_processing_roles(self):
        template = (ROOT / "lib" / "material_library_template.py").read_text(encoding="utf-8")
        self.assertIn('BLANK_PALETTE_UTILITY_ENTRIES = ("Labels", "Fauxlographic")', template)


if __name__ == "__main__":
    unittest.main()
