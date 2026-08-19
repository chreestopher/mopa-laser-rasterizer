import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ColorDiscoveryCoverageTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / "routes" / "color_discovery.py").read_text(encoding="utf-8")
        self.template = (ROOT / "templates" / "color_discovery.html").read_text(encoding="utf-8")

    def test_every_mutating_endpoint_validates_auth_intent(self):
        tree = ast.parse(self.source)
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        for name in (
            "create_color_discovery_session",
            "build_color_discovery_grid",
            "analyze_color_discovery_grid",
            "save_color_discovery_recipes",
        ):
            calls = [
                node for node in ast.walk(functions[name])
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_validated_submission_identity"
            ]
            self.assertTrue(calls, f"{name} must validate submission identity")

    def test_forms_carry_signed_context(self):
        self.assertEqual(3, self.template.count('name="submission_auth_token"'))
        self.assertEqual(3, self.template.count('name="continue_as_guest"'))
        self.assertIn("body.set('submission_auth_token',authToken)", self.template)

    def test_workflow_includes_all_baseline_sources_and_next_steps(self):
        for expected in (
            'value="manual"', 'value="library"', 'name="saved_material_library_id"',
            'name="guest_material_library_id"', 'name="material_settings"',
            'id="refine"', 'id="new_pair"', 'id="save_recipes"',
        ):
            self.assertIn(expected, self.template)

    def test_grid_rejects_duplicate_axes_and_caps_layer_count(self):
        self.assertIn("x_parameter == y_parameter", self.source)
        self.assertIn("rows * columns > 29", self.source)


if __name__ == "__main__":
    unittest.main()
