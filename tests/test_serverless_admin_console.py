import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ServerlessAdminConsoleTests(unittest.TestCase):
    def setUp(self):
        self.handler = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
        self.worker = (ROOT / "worker.py").read_text(encoding="utf-8")
        self.page = (ROOT / "serverless_web" / "admin.html").read_text(encoding="utf-8")
        self.client = (ROOT / "serverless_web" / "admin.js").read_text(encoding="utf-8")
        self.styles = (ROOT / "serverless_web" / "admin.css").read_text(encoding="utf-8")
        self.infrastructure = (ROOT / "ecs" / "serverless-staging-web.yaml").read_text(encoding="utf-8")
        self.deploy = (ROOT / "dev_setup" / "deploy_serverless_staging_web.sh").read_text(encoding="utf-8")

    def test_sources_parse_and_routes_are_authenticated(self):
        ast.parse(self.handler)
        for route in (
            "GET /admin/jobs", "GET /admin/jobs/{task_id}",
            "DELETE /admin/jobs/{task_id}", "POST /admin/jobs/{task_id}/cancel",
            "GET /admin/users",
        ):
            self.assertIn(f'RouteKey: "{route}"', self.infrastructure)
        self.assertGreaterEqual(self.infrastructure.count("AuthorizationType: JWT"), 5)

    def test_admin_access_is_verified_email_and_default_deny(self):
        self.assertIn('ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "").strip().casefold()', self.handler)
        self.assertIn('claims.get("email_verified") in (True, "true", "True")', self.handler)
        self.assertIn('secrets.compare_digest(email, ADMIN_EMAIL)', self.handler)
        self.assertIn('return response(404, {"message": "Not found"})', self.handler)
        self.assertIn("NoEcho: true", self.infrastructure)
        self.assertIn('"AdminEmail=$ADMIN_EMAIL"', self.deploy)

    def test_jobs_use_durable_global_index_without_table_scan(self):
        function = self.handler[
            self.handler.index("def admin_jobs(event):"):
            self.handler.index("def admin_job(event, task_id):")
        ]
        self.assertIn('Key("pk").eq("ADMIN#JOBS")', function)
        self.assertNotIn("table.scan", function)
        self.assertIn('batch.put_item(Item=admin_job_index_item(event, history))', self.handler)
        self.assertIn('"expires_at": created_at + TTL_SECONDS', self.handler)

    def test_waiting_job_cancel_is_conditional_and_worker_skips_it(self):
        self.assertIn('ConditionExpression="#status=:pending AND attribute_exists(payload)"', self.handler)
        self.assertIn('"Cancelled while waiting in the queue by an administrator."', self.handler)
        self.assertIn('durable_status in {"completed", "failed", "cancelled"}', self.worker)

    def test_admin_delete_removes_only_task_assets_and_all_job_indexes(self):
        function = self.handler[
            self.handler.index("def delete_job_assets_and_records"):
            self.handler.index("def account_jobs(event):")
        ]
        self.assertIn('f"users/{owner}/jobs/{task_id}/"', function)
        self.assertIn('f"jobs/{task_id}/"', function)
        self.assertIn('{"pk": "ADMIN#JOBS", "sk": history_sk}', function)
        self.assertIn('Wait for this processing job to finish before deleting it', function)
        self.assertIn('REMOVE payload', function)
        self.assertIn('return delete_admin_job(event, parts[2])', self.handler)
        for event_name in (
            "admin_job_delete_not_found", "admin_job_delete_requested",
            "admin_job_delete_blocked", "admin_job_delete_succeeded",
        ):
            self.assertIn(f'"event": "{event_name}"', function)
        self.assertIn('"deleted_assets": deleted_assets', function)
        self.assertIn('"deleted_records": deleted_records', function)

    def test_admin_job_details_offer_confirmed_permanent_deletion(self):
        self.assertIn('data-delete="${esc(job.task_id)}"', self.client)
        self.assertIn("Delete Job and Assets", self.client)
        self.assertIn('api(`/admin/jobs/${taskId}`,{method:"DELETE"})', self.client)
        self.assertIn("jobs=jobs.filter(job=>job.task_id!==taskId)", self.client)
        self.assertIn("This cannot be undone", self.client)

    def test_page_uses_job_history_style_accordion_and_blinking_active_rows(self):
        self.assertIn('id="adminJobs" class="admin-jobs"', self.page)
        self.assertIn('aria-expanded="${open}"', self.client)
        self.assertIn('if(activeTask===taskId)', self.client)
        self.assertIn("admin-active-pulse", self.styles)
        self.assertIn("status-pending>.admin-job-title", self.styles)
        self.assertIn("status-active>.admin-job-title", self.styles)
        self.assertIn("prefers-reduced-motion:reduce", self.styles)
        self.assertIn("Match the Job History console", self.styles)
        self.assertIn("body.staging-admin .admin-panel:first-of-type", self.styles)
        self.assertIn('admin-panel admin-protected admin-jobs-panel', self.page)
        self.assertIn("body.staging-admin .admin-jobs-panel", self.styles)
        self.assertIn("body.staging-admin .admin-log-list", self.styles)
        self.assertIn("body.light-machine.staging-admin .admin-job-detail", self.styles)

    def test_admin_titles_use_staging_title_colors(self):
        self.assertIn("body.staging-admin .staging-page-hero h1", self.styles)
        self.assertIn("color:#e4e3cf!important", self.styles)
        self.assertIn("body.light-machine.staging-admin .staging-page-hero h1", self.styles)
        self.assertIn("color:#20221e!important", self.styles)

    def test_operational_panels_stay_hidden_until_admin_authorization_succeeds(self):
        self.assertEqual(self.page.count('class="admin-panel admin-protected'), 3)
        self.assertEqual(self.page.count('aria-labelledby="admin-'), 3)
        self.assertEqual(self.page.count('hidden>'), 3)
        self.assertIn('document.querySelectorAll(".admin-protected")', self.client)
        self.assertIn("protectedPanels.forEach(panel=>panel.hidden=false)", self.client)
        self.assertIn('if(!token||(tokenExpiresSoon()&&!await refreshSession()))return', self.client)
        self.assertIn('document.body.classList.add("admin-authorized")', self.client)
        self.assertIn(
            "body.staging-admin:not(.admin-authorized) .staging-page-hero p:not(.eyebrow)",
            self.styles,
        )

    def test_admin_assets_are_staging_only_and_unlinked(self):
        for asset in ("admin.html", "admin.js", "admin.css"):
            self.assertIn(f'serverless_web/{asset}', self.deploy)
        shell = (ROOT / "serverless_web" / "staging-shell.js").read_text(encoding="utf-8")
        self.assertIn('"/admin.html": ["Private operational visibility"', shell)
        routes = shell[shell.index("const routes = ["):shell.index("const pageHeroes =")]
        self.assertNotIn("/admin.html", routes)


if __name__ == "__main__":
    unittest.main()
