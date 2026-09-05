import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ServerlessGuestAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.handler = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
        cls.page = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")
        cls.stack = (ROOT / "ecs" / "serverless-staging-web.yaml").read_text(encoding="utf-8")
        cls.foundation = (ROOT / "ecs" / "serverless-staging-foundation.yaml").read_text(encoding="utf-8")
        cls.worker = (ROOT / "worker.py").read_text(encoding="utf-8")
        cls.services = (ROOT / "services.py").read_text(encoding="utf-8")

    def test_sources_parse(self):
        ast.parse(self.handler)

    def test_only_guest_capability_routes_are_public(self):
        for route in (
            "GET /guest/config",
            "POST /guest/uploads",
            "POST /guest/jobs/{task_id}/submit",
            "GET /guest/jobs/{task_id}",
        ):
            start = self.stack.index(f"RouteKey: {route}")
            route_block = self.stack[start:start + 180]
            self.assertIn("AuthorizationType: NONE", route_block)
        self.assertIn("RouteKey: POST /uploads\n      AuthorizationType: JWT", self.stack)
        self.assertIn("RouteKey: GET /jobs/{task_id}\n      AuthorizationType: JWT", self.stack)
        self.assertIn("x-guest-capability", self.stack)

    def test_guest_access_uses_short_lived_unpredictable_capabilities(self):
        self.assertIn('access_token = secrets.token_urlsafe(32)', self.handler)
        self.assertIn('"guest_access_capability": token_hash(access_token)', self.handler)
        self.assertIn('request_header(event, "x-guest-capability")', self.handler)
        self.assertIn("valid_guest_capability", self.handler)
        self.assertNotIn('guest_access_token"', self.handler[self.handler.index("item = {"):self.handler.index("table.put_item(Item=item")])

    def test_guest_jobs_cannot_use_saved_account_assets(self):
        self.assertIn("Guest jobs cannot use saved palettes or Material Libraries", self.handler)
        self.assertIn('"material": None if svg_only or uploaded_holographic_palette else presigned_post(', self.handler)
        self.assertIn("Guest jobs require a freshly uploaded Material Library, a Holographic Swatch Palette, or SVG-Only", self.page)

    def test_guest_can_upload_a_transient_holographic_palette(self):
        self.assertIn("Upload a Holographic Swatch Palette", self.page)
        self.assertIn("new Option('Upload a Holographic Swatch Palette','holographic-upload')", self.page)
        self.assertIn('id="holographicUploadInfo"', self.page)
        self.assertIn("store Holographic Swatch Palettes in your Swatch Palette Vault", self.page)
        self.assertIn("uploadedHolographicProfile", self.page)
        self.assertIn("holographic_palette_key:grant.holographic_palette?.key||''", self.page)
        self.assertIn('item["uploaded_holographic_palette"] = True', self.handler)
        self.assertIn('"holographic_palette": presigned_post(', self.handler)
        self.assertIn("uploaded_holographic_settings_root(profile, all_indexes", self.handler)
        self.assertIn('"generated_recipe_id": "uploaded-holographic-palette"', self.handler)
        self.assertIn('Tagging="mopa-retention=guest"', self.handler)

    def test_holographic_palette_schema_version_is_not_user_facing(self):
        self.assertNotIn("self-contained v2 Holographic Palettes", self.handler)
        self.assertNotIn("v2 Holographic", self.page)

    def test_guest_swatches_are_editable_but_preferences_are_not_saved(self):
        self.assertIn("async function loadGuestResources()", self.page)
        self.assertRegex(self.page, r"contenteditable=(?:\"true\"|true)")
        self.assertIn("if(guestMode)return;", self.page)
        self.assertIn("selectedPaletteHexes", self.page)
        self.assertIn("paletteNameOverrides", self.page)

    def test_direct_uploads_report_depthmap_style_progress(self):
        self.assertIn('id="uploadProgress" class="upload-progress"', self.page)
        self.assertIn("new XMLHttpRequest()", self.page)
        self.assertIn("request.upload.onprogress", self.page)
        self.assertIn("async function uploadBatch(entries)", self.page)
        self.assertIn("Uploads complete · preparing job submission", self.page)

    def test_guest_jobs_do_not_create_user_history(self):
        self.assertIn("if not guest:\n            batch.put_item(Item=history)", self.handler)
        self.assertIn('"user_id": None if guest else owner', self.handler)
        self.assertIn('artifact_prefix = f"jobs/{task_id}/" if guest', self.handler)
        self.assertIn("if(!guestMode)history.replaceState", self.page)
        self.assertIn("Swatch edits and job results are not added to an account or Job History", self.page)

    def test_guest_jobs_are_rate_limited_and_short_lived(self):
        self.assertIn('GUEST_DAILY_JOB_LIMIT = int(os.environ.get("GUEST_DAILY_JOB_LIMIT", "5"))', self.handler)
        self.assertIn("guest_quota_context(event)", self.handler)
        self.assertIn('"guest_daily_job_limit": GUEST_DAILY_JOB_LIMIT', self.handler)
        self.assertIn("job_runtime.claim_guest_quota", self.services)
        self.assertIn("Validating artwork, parameters, Material Library", self.services)
        self.assertLess(
            self.services.index("validation_exit, validation_message"),
            self.services.index("job_runtime.claim_guest_quota"),
        )
        self.assertLess(
            self.services.index("job_runtime.claim_guest_quota"),
            self.services.index("process = subprocess.Popen(command"),
        )
        self.assertIn("Guest limit reached", self.services)
        self.assertIn('GUEST_JOB_SECONDS: "86400"', self.stack)
        self.assertIn("mopa-retention=guest", self.handler)
        self.assertIn("Value: guest", self.foundation)
        self.assertIn("ExpirationInDays: 1", self.foundation)
        self.assertIn('upload_args["ExtraArgs"] = {"Tagging": "mopa-retention=guest"}', self.services)
        self.assertIn('guest_job=payload.get("guest_job") is True', self.worker)

    def test_account_and_holographic_features_remain_authenticated(self):
        self.assertIn("holographicForm.classList.toggle('hidden',!authenticated)", self.page)
        self.assertIn("if(token)await loadAccountResources();else await loadGuestResources()", self.page)
        self.assertIn("if not user_id(event):\n            return response(401", self.handler)


if __name__ == "__main__":
    unittest.main()
