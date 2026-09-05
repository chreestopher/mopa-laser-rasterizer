import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ServerlessRegisteredAccessTests(unittest.TestCase):
    def test_registered_only_pages_have_hidden_content_and_access_prompts(self):
        pages = {
            "vault.html": "/docs/material-vault",
            "history.html": "/docs/job-history",
        }
        for filename, docs_path in pages.items():
            with self.subTest(page=filename):
                source = (ROOT / "serverless_web" / filename).read_text(encoding="utf-8")
                self.assertIn('id="registeredAccess" class="registered-access-message" hidden', source)
                self.assertRegex(
                    source,
                    re.compile(r'id="registeredContent"[^>]*class="[^"]*registered-only-content[^"]*"[^>]*hidden'),
                )
                self.assertIn("data-registered-access-login", source)
                self.assertIn("Sign in or register", source)
                self.assertRegex(
                    source,
                    re.compile(r'<a class="staging-action-button"[^>]*data-registered-access-login'),
                )
                self.assertRegex(
                    source,
                    re.compile(r'<a class="staging-action-button" href="' + re.escape(docs_path) + r'"'),
                )
                self.assertIn(f'href="{docs_path}"', source)

    def test_each_page_reveals_content_only_after_authentication(self):
        for filename in ("vault.js", "history.js"):
            with self.subTest(client=filename):
                source = (ROOT / "serverless_web" / filename).read_text(encoding="utf-8")
                self.assertIn("showRegisteredAccess(authenticated)", source)
                self.assertIn("registeredContent.hidden=!authenticated", source)
                self.assertIn("showRegisteredAccess(false)", source)
                self.assertIn("showRegisteredAccess(true)", source)

    def test_shared_shell_launches_login_and_preserves_return_url(self):
        shell = (ROOT / "serverless_web" / "staging-shell.js").read_text(encoding="utf-8")
        self.assertIn('document.querySelectorAll("[data-registered-access-login]")', shell)
        self.assertIn('sessionStorage.setItem("post_login_path", location.pathname + location.search)', shell)
        self.assertIn("window.stagingShellBeginLogin = beginLogin", shell)

    def test_hidden_access_regions_cannot_be_overridden_by_page_layout(self):
        styles = (ROOT / "serverless_web" / "staging-pages.css").read_text(encoding="utf-8")
        self.assertIn(
            ".registered-only-content[hidden],.registered-access-message[hidden]{display:none!important}",
            styles,
        )
        self.assertIn("body.light-machine .staging-action-button", styles)
        self.assertIn(
            ".registered-access-actions a.staging-action-button{color:#edf4e9!important;font:700 .9rem/1.3 system-ui,sans-serif!important;letter-spacing:0!important;text-transform:none!important}",
            styles,
        )
        self.assertIn(
            ".light-machine .registered-access-actions a.staging-action-button{color:#171815!important}",
            styles,
        )


if __name__ == "__main__":
    unittest.main()
