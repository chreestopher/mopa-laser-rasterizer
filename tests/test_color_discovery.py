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

    def test_manual_frequency_default_is_valid_and_inactive_sources_are_disabled(self):
        self.assertIn('name="manual_frequency" type="number" value="100000" min="1" step="1"', self.template)
        self.assertIn("control.disabled=!library", self.template)
        self.assertIn("control.disabled=library", self.template)

    def test_grid_accepts_overall_physical_dimensions(self):
        self.assertIn('class="grid-dimensions full"', self.template)
        self.assertIn('name="grid_width_mm"', self.template)
        self.assertIn('name="grid_length_mm"', self.template)
        self.assertIn('total_width_mm = _number(request.form.get("grid_width_mm")', self.source)
        self.assertIn('total_length_mm = _number(request.form.get("grid_length_mm")', self.source)
        self.assertIn('"cell_width_mm": cell_width_mm', self.source)
        self.assertIn('"cell_height_mm": cell_height_mm', self.source)
        self.assertIn("matrix_width, matrix_height = total_width_mm, total_length_mm", self.source)
        self.assertIn("Row labels extend beyond it.", self.template)

    def test_saved_setting_picker_renders_palette_swatches(self):
        self.assertIn("lightburn_palette=", self.source)
        self.assertIn('id="saved_entry_menu"', self.template)
        self.assertIn('class="mini-swatch"', self.template)
        self.assertIn("paletteHex(entry.description)", self.template)
        self.assertIn("data-entry-index", self.template)

    def test_grid_has_no_full_project_outline(self):
        self.assertNotIn("lightburn.Square(total_width_mm, total_length_mm", self.source)

    def test_page_uses_shared_machine_facade_geometry(self):
        self.assertIn("body{max-width:1040px", self.template)
        self.assertIn("border-radius:30px", self.template)
        self.assertIn("width:125vw;max-width:none;margin:0;zoom:.8", self.template)
        self.assertIn("border-radius:16px", self.template)

    def test_baseline_readout_shows_fixed_minimum_and_maximum_power(self):
        self.assertIn("Minimum power<strong>${esc(setting.minPower)}%</strong>", self.template)
        self.assertIn("Maximum power<strong>${esc(setting.maxPower)}%</strong>", self.template)
        self.assertNotIn("${esc(setting.minPower)}–${esc(setting.maxPower)}%", self.template)

    def test_completed_grid_shows_only_the_download_action(self):
        self.assertNotIn("Grid ready:", self.template)
        self.assertIn("Download LightBurn Project</a>", self.template)

    def test_community_baseline_advances_user_to_grid_step(self):
        self.assertIn('id="community_status"', self.template)
        self.assertIn("You do not need to create another session.", self.template)
        self.assertIn("$('grid_form').classList.add('next-step')", self.template)
        self.assertIn("$('grid_form').scrollIntoView", self.template)


if __name__ == "__main__":
    unittest.main()
