import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SvgOnlyRasterizerCoverageTests(unittest.TestCase):
    def test_submission_requires_explicit_svg_only_confirmation(self):
        route = (ROOT / "routes" / "jobs.py").read_text(encoding="utf-8")
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

        self.assertIn('name="svg_only_confirmed"', template)
        self.assertIn('id="svg_only_modal"', template)
        self.assertIn("Continue with SVG only", template)
        self.assertIn('svg_only_requested = str(user_data.get("svg_only_confirmed"', route)
        self.assertIn('"code": "material_library_confirmation_required"', route)

    def test_svg_only_mode_preserves_default_selections_and_skips_library_usage(self):
        route = (ROOT / "routes" / "jobs.py").read_text(encoding="utf-8")
        pipeline = (ROOT / "lib" / "Material_Library.py").read_text(encoding="utf-8")

        self.assertIn("selected_default_names = [", route)
        self.assertIn('user_data["colors"] = ", ".join(selected_default_names)', route)
        self.assertIn('user_data["color_name_overrides"] = json.dumps(LIGHTBURN_PALETTE_NAMES', route)
        self.assertIn("if len(limit_list) <= 1 and not svg_only", pipeline)
        self.assertIn('if not svg_only:\n            resolved_settings = resolve_material_setting_usage', route)
        self.assertIn('export_lightburn=not svg_only', pipeline)

    def test_svg_only_jobs_do_not_offer_lightburn_downloads(self):
        services = (ROOT / "services.py").read_text(encoding="utf-8")
        loading = (ROOT / "templates" / "loading.html").read_text(encoding="utf-8")

        self.assertIn('None if parameters.get("svg_only")', services)
        self.assertIn("{% if file.lightburn_url %}", loading)
        self.assertIn("{% if not current_svg_only %}", loading)


if __name__ == "__main__":
    unittest.main()
