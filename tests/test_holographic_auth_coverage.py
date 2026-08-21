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

    def test_guest_material_libraries_are_select_only_in_job_forms(self):
        holographic_template = (
            ROOT / "templates" / "holographic_etching.html"
        ).read_text(encoding="utf-8")
        rasterizer_template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        vault_template = (
            ROOT / "templates" / "material_libraries.html"
        ).read_text(encoding="utf-8")

        self.assertEqual(2, holographic_template.count('name="guest_material_library_id"'))
        self.assertEqual(1, rasterizer_template.count('name="guest_material_library_id"'))
        self.assertIn("/browser-material-libraries", holographic_template)
        self.assertIn("/browser-material-libraries", rasterizer_template)
        self.assertNotIn("guest_material_library_id", vault_template)

    def test_saved_rasterizer_library_populates_its_material_name_selector(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="saved_material_name"', template)
        self.assertIn("library?.summary?.material_names", template)
        self.assertIn("/account/material-libraries/${encodeURIComponent(libraryId)}", template)
        self.assertIn("cache:'no-store'", template)
        self.assertIn("showSavedLibraryMaterialNames(savedMaterialLibraryInput.value)", template)
        self.assertIn("materialInput.value = savedMaterialNameInput.value", template)
        self.assertIn("showManualMaterialName();", template)

    def test_holographic_forms_offer_upload_or_existing_library_to_every_user(self):
        template = (
            ROOT / "templates" / "holographic_etching.html"
        ).read_text(encoding="utf-8")

        self.assertIn('id="calibration_material_upload_row" class="full-width"', template)
        self.assertIn('id="artwork_material_upload_row" class="full-width"', template)
        self.assertNotIn('id="calibration_material_upload_row" class="full-width" hidden', template)
        self.assertNotIn('id="artwork_material_upload_row" class="full-width" hidden', template)
        self.assertIn("calibrationMaterialSettings.disabled = false;", template)
        self.assertIn("artworkMaterialSettings.disabled = false;", template)
        self.assertIn("!savedCalibrationLibrary.value && !calibrationMaterialSettings.files.length", template)
        self.assertIn("!savedArtworkLibrary.value && !artworkMaterialSettings.files.length", template)
        self.assertNotIn("guest_calibration_library_upload", template)
        self.assertNotIn("guest_artwork_library_upload", template)
        self.assertIn(".calibration-form [hidden] { display:none !important; }", template)
        self.assertIn(
            "guestCalibrationLibraryRow.hidden = operatorSignedIn || !guestMaterialLibraries.length;",
            template,
        )
        self.assertIn(
            "guestArtworkLibraryRow.hidden = operatorSignedIn || !guestMaterialLibraries.length;",
            template,
        )
        self.assertIn("guestCalibrationLibrarySource.disabled = operatorSignedIn", template)
        self.assertIn("guestArtworkLibrarySource.disabled = operatorSignedIn", template)


if __name__ == "__main__":
    unittest.main()
