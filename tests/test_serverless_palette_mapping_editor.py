import ast
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ServerlessPaletteMappingEditorTests(unittest.TestCase):
    def setUp(self):
        self.handler = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
        self.page = (ROOT / "serverless_web" / "vault.html").read_text(encoding="utf-8")
        self.client = (ROOT / "serverless_web" / "vault.js").read_text(encoding="utf-8")

    def test_color_palette_editor_has_visual_assignment_controls(self):
        ast.parse(self.handler)
        self.assertIn('class="mapping-picker-toggle"', self.client)
        self.assertIn('class="mapping-choice-swatch"', self.client)
        self.assertIn('data-map-hex=""', self.client)
        self.assertIn('Reset to default', self.client)
        self.assertIn('Reset mappings', self.client)
        self.assertIn('.mapping-options[hidden]', self.page)
        self.assertIn('grid-template-columns:repeat(4,minmax(0,1fr))', self.page)
        self.assertIn('@media(max-width:850px){.mapping-options{grid-template-columns:repeat(3,minmax(0,1fr))}}', self.page)
        self.assertIn('class="mapping-filter-input" type="search"', self.client)
        self.assertIn('Filter by color name or hex', self.client)
        self.assertIn('choice.textContent.toLowerCase().includes(query)', self.client)
        self.assertIn('label:assigned?"Assigned":"Not assigned"', self.client)
        self.assertIn('occupied?"disabled":""', self.client)
        self.assertIn('button.mapping-choice:disabled', self.page)
        self.assertIn('paletteName!==String(library.name||"").trim()||materialName!==savedMaterialName', self.client)
        self.assertIn('description!==String(entry.description||"")||type!==String(entry.type||"")||settingsChanged', self.client)
        self.assertIn('claimed=new Set()', self.client)

    def test_description_and_assignment_are_saved_independently(self):
        self.assertIn('description=editor.querySelector(".editDescription").value.trim()', self.client)
        self.assertIn('material_library_color_assignments:assignments', self.client)
        self.assertIn('mappingState.get(String(entry.entry_id))', self.client)
        self.assertIn('Move it to', self.client)
        self.assertIn('library.library_intent==="hatch_palette"?"":mappingPicker', self.client)

    def test_rename_preserves_explicit_assignment(self):
        function = next(
            node for node in ast.parse(self.handler).body
            if isinstance(node, ast.FunctionDef) and node.name == "preserve_material_assignment_names"
        )

        class FakeTable:
            def __init__(self):
                self.preferences = {
                    "material_library_color_assignments": {
                        "library-1": {"#A0A000": "holographic-etching"},
                        "library-2": {"#0000FF": "Blue"},
                    }
                }

            def get_item(self, **_kwargs):
                return {"Item": {"preferences": self.preferences}}

            def put_item(self, Item):
                self.preferences = Item["preferences"]

        table = FakeTable()
        namespace = {
            "table": table,
            "time": time,
            "clean_account_preferences": lambda value: value,
            "dynamo_value": lambda value: value,
        }
        exec(compile(ast.Module(body=[function], type_ignores=[]), "handler.py", "exec"), namespace)
        namespace["preserve_material_assignment_names"](
            "owner", "library-1", "holographic-etching", "Iridescent Gold"
        )
        assignments = table.preferences["material_library_color_assignments"]
        self.assertEqual(assignments["library-1"]["#A0A000"], "Iridescent Gold")
        self.assertEqual(assignments["library-2"]["#0000FF"], "Blue")


if __name__ == "__main__":
    unittest.main()
