import html
import http.server
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "serverless_web"
TEMPLATE = ROOT / "ecs" / "serverless-staging-web.yaml"


def _browser_path():
    candidates = [
        shutil.which("chrome"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("msedge"),
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return None


def _report_only_policy():
    template = TEMPLATE.read_text(encoding="utf-8")
    match = re.search(
        r'Header: Content-Security-Policy-Report-Only\s+Value: "([^"]+)"',
        template,
    )
    if match is None:
        raise AssertionError("The staging template has no report-only CSP header")
    return match.group(1)


class _CspHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Content-Security-Policy-Report-Only", self.server.csp_policy)
        super().end_headers()

    def log_message(self, *_args):
        pass


class _CspServer(http.server.ThreadingHTTPServer):
    request_queue_size = 16


class ServerlessCspBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.browser = _browser_path()
        if not cls.browser:
            raise unittest.SkipTest("Chrome, Chromium, or Edge is required for CSP characterization")
        cls.temp = tempfile.TemporaryDirectory(prefix="mopa-csp-browser-")
        cls.site = Path(cls.temp.name) / "site"
        cls.site.mkdir()
        (cls.site / "index.html").write_text(
            """<!doctype html><html><body>
<pre id="csp-result">pending</pre>
<script src="/listener.js"></script>
<script>window.__inlineProbeExecuted = true;</script>
<script src="/finish.js"></script>
</body></html>""",
            encoding="utf-8",
        )
        (cls.site / "listener.js").write_text(
            """window.__cspViolations = [];
addEventListener('securitypolicyviolation', event => {
  window.__cspViolations.push({
    blockedURI: event.blockedURI,
    disposition: event.disposition,
    effectiveDirective: event.effectiveDirective
  });
  window.__writeCspResult?.();
});""",
            encoding="utf-8",
        )
        (cls.site / "finish.js").write_text(
            """window.__writeCspResult = () => {
  document.querySelector('#csp-result').textContent = JSON.stringify({
    inlineExecuted: window.__inlineProbeExecuted === true,
    violations: window.__cspViolations
  });
};
window.__writeCspResult();""",
            encoding="utf-8",
        )
        handler = lambda *args, **kwargs: _CspHandler(
            *args, directory=str(cls.site), **kwargs
        )
        cls.server = _CspServer(("127.0.0.1", 0), handler)
        cls.server.csp_policy = _report_only_policy()
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.temp.cleanup()

    def test_inline_script_is_reported_but_not_blocked(self):
        port = self.server.server_address[1]
        with tempfile.TemporaryDirectory(prefix="mopa-csp-profile-") as profile:
            completed = subprocess.run(
                [
                    self.browser,
                    "--headless=new",
                    "--disable-gpu",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    f"--user-data-dir={profile}",
                    "--virtual-time-budget=5000",
                    "--dump-dom",
                    f"http://127.0.0.1:{port}/",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        match = re.search(r'<pre id="csp-result">(.*?)</pre>', completed.stdout, re.DOTALL)
        self.assertIsNotNone(match, completed.stdout[-2000:])
        result = json.loads(html.unescape(match.group(1)))
        self.assertTrue(result["inlineExecuted"])
        inline_violations = [
            item
            for item in result["violations"]
            if item["effectiveDirective"] in {"script-src", "script-src-elem"}
            and item["blockedURI"] == "inline"
        ]
        self.assertTrue(inline_violations, result)
        self.assertTrue(
            all(item["disposition"] == "report" for item in inline_violations),
            result,
        )


def test_serverless_html_has_no_inline_javascript_surfaces():
    inline_scripts = []
    inline_handlers = []
    javascript_urls = []
    script_pattern = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.I | re.S)
    handler_pattern = re.compile(r"\son[a-z0-9_-]+\s*=", re.I)
    javascript_url_pattern = re.compile(r"(?:href|src)\s*=\s*['\"]\s*javascript:", re.I)

    for page_path in sorted(WEB.glob("*.html")):
        page = page_path.read_text(encoding="utf-8")
        for match in script_pattern.finditer(page):
            if not re.search(r"\bsrc\s*=", match.group(1), re.I):
                inline_scripts.append(page_path.name)
        if handler_pattern.search(page):
            inline_handlers.append(page_path.name)
        if javascript_url_pattern.search(page):
            javascript_urls.append(page_path.name)

    assert inline_scripts == []
    assert inline_handlers == []
    assert javascript_urls == []
