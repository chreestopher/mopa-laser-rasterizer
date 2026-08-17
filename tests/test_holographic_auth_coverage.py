import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class HolographicAuthenticationCoverageTests(unittest.TestCase):
    def test_every_state_changing_holographic_endpoint_validates_auth_intent(self):
        tree = ast.parse((ROOT / "routes" / "holographic.py").read_text(encoding="utf-8"))
        functions = {
            node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
        }
        protected = {
            "calibration_grid",
            "save_calibration_profile",
            "analyze_calibration_profile",
            "save_holographic_recipes",
            "build_holographic_artwork",
        }
        for function_name in protected:
            calls = [
                node for node in ast.walk(functions[function_name])
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_validated_submission_identity"
            ]
            self.assertTrue(calls, f"{function_name} must validate submission identity")

    def test_every_holographic_form_carries_the_signed_context(self):
        template = (ROOT / "templates" / "holographic_etching.html").read_text(encoding="utf-8")
        self.assertEqual(4, template.count('name="submission_auth_token"'))
        self.assertEqual(4, template.count('name="continue_as_guest"'))
        self.assertIn("body.set('submission_auth_token', holographicAuthToken)", template)

    def test_calibration_profile_downloads_are_guest_only(self):
        tree = ast.parse((ROOT / "routes" / "holographic.py").read_text(encoding="utf-8"))
        functions = {
            node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
        }
        for function_name in (
            "save_calibration_profile",
            "analyze_calibration_profile",
            "save_holographic_recipes",
        ):
            guest_urls = [
                node for node in ast.walk(functions[function_name])
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_guest_profile_url"
            ]
            self.assertTrue(guest_urls, f"{function_name} must suppress member downloads")

        template = (ROOT / "templates" / "holographic_etching.html").read_text(encoding="utf-8")
        self.assertGreaterEqual(template.count("data.profile_url\n          ? downloadButtonList"), 3)
        self.assertIn("await loadSavedHolographicRecipes(data.saved_recipe_id || '')", template)


if __name__ == "__main__":
    unittest.main()
