import ast
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
        self.assertIn('processingMaterialNames', client)
        self.assertIn('[library.library_id]:{materials}', client)
        self.assertIn('processingMaterialFilterMarkup', client)
        self.assertIn('applyProcessingMaterialFilter', client)
        self.assertIn('data-processing-material', client)
        self.assertIn('class="processingMaterialFilter"', client)

    def test_vault_processing_material_filter_hides_other_material_rows(self):
        page = (ROOT / "serverless_web" / "vault.html").read_text(encoding="utf-8")
        client = (ROOT / "serverless_web" / "vault.js").read_text(encoding="utf-8")
        self.assertIn('.library-entry[hidden]{display:none!important}', page)
        self.assertIn('row.dataset.processingMaterial===material', client)
        self.assertIn('processingMaterialSelections.set(item.library_id,material)', client)
        self.assertIn('event.target.matches(".processingMaterialFilter")', client)

    def test_processing_role_preferences_accept_material_scopes_and_legacy_values(self):
        handler_path = ROOT / "serverless_api" / "handler.py"
        tree = ast.parse(handler_path.read_text(encoding="utf-8"))
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "clean_account_preferences"
        )
        namespace = {
            "PROCESSING_PALETTE_ROLES": {"Cut", "Score", "Photo", "Fill", "Shovel", "Cleaning"},
            "PALETTE_NAMES": {},
            "LAST_USED_FORM_FIELDS": (),
            "clean_last_used_form": lambda _name, _value: None,
        }
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(handler_path), "exec"), namespace)

        nested = namespace["clean_account_preferences"]({
            "processing_palette_role_assignments": {
                "co2": {
                    "materials": {
                        "Acrylic": {"Cut": "setting:cut-acrylic", "Photo": "setting:photo-acrylic"},
                        "Hard Wood": {"Cut": "setting:cut-wood", "Unknown": "discard-me"},
                    }
                }
            }
        })
        self.assertEqual(
            nested["processing_palette_role_assignments"]["co2"]["materials"],
            {
                "Acrylic": {"Cut": "setting:cut-acrylic", "Photo": "setting:photo-acrylic"},
                "Hard Wood": {"Cut": "setting:cut-wood"},
            },
        )

        legacy = namespace["clean_account_preferences"]({
            "processing_palette_role_assignments": {"fiber": {"Cut": "Cut", "Photo": "Photo"}}
        })
        self.assertEqual(
            legacy["processing_palette_role_assignments"]["fiber"],
            {"Cut": "Cut", "Photo": "Photo"},
        )

    def test_processing_palettes_are_scoped_to_depthmap_tools(self):
        rasterizer = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")
        color_lab = (ROOT / "serverless_web" / "color-lab.js").read_text(encoding="utf-8")
        depthmap = (ROOT / "static" / "depthmap_generator.js").read_text(encoding="utf-8")
        handler = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
        self.assertIn("item.library_intent!=='processing_palette'", rasterizer)
        self.assertIn('item.library_intent!=="processing_palette"', color_lab)
        self.assertIn('library.library_intent === "processing_palette"', depthmap)
        self.assertIn('id="depth_relief_material"', (ROOT / "templates" / "depthmap_generator.html").read_text(encoding="utf-8"))
        self.assertIn('paletteRoles.materials[selectedReliefMaterial()]', depthmap)
        self.assertIn('reliefMaterialControl.addEventListener("change", populateReliefSettings)', depthmap)
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
