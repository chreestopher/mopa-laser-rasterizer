import http.server
import json
import os
from pathlib import Path
import re
import signal
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


def _stop_browser_process_tree(browser):
    """Stop Chromium and its profile-owning children before temp cleanup."""
    if os.name == "posix":
        try:
            os.killpg(browser.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            browser.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        # The browser parent can exit before a renderer or profile helper. Kill
        # anything still in the dedicated process group before removing its
        # user-data directory.
        try:
            os.killpg(browser.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        browser.wait(timeout=5)
        return

    browser.terminate()
    try:
        browser.wait(timeout=5)
    except subprocess.TimeoutExpired:
        browser.kill()
        browser.wait(timeout=5)


class _CspHandler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)
        with self.server.result_lock:
            if self.path == "/inline-executed":
                self.server.inline_executed = True
            elif self.path == "/csp-report":
                try:
                    self.server.csp_reports.append(json.loads(body))
                except json.JSONDecodeError as exc:
                    self.server.report_errors.append(str(exc))
            else:
                self.send_error(404)
                return

            complete = self.server.inline_executed and bool(self.server.csp_reports)

        self.send_response(204)
        self.end_headers()
        if complete:
            self.server.csp_result_ready.set()

    def do_GET(self):
        if self.path == "/probe-loaded":
            try:
                self.send_response(204)
            finally:
                self.end_headers()
            self.server.probe_loaded.set()
            return
        if self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        super().do_GET()

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
<img src="/probe-loaded" alt="">
<script>fetch('/inline-executed', {method: 'POST'});</script>
</body></html>""",
            encoding="utf-8",
        )
        handler = lambda *args, **kwargs: _CspHandler(
            *args, directory=str(cls.site), **kwargs
        )
        cls.server = _CspServer(("127.0.0.1", 0), handler)
        cls.server.csp_policy = f"{_report_only_policy()}; report-uri /csp-report"
        cls.server.result_lock = threading.Lock()
        cls.server.inline_executed = False
        cls.server.csp_reports = []
        cls.server.report_errors = []
        cls.server.probe_loaded = threading.Event()
        cls.server.csp_result_ready = threading.Event()
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
        self.server.inline_executed = False
        self.server.csp_reports = []
        self.server.report_errors = []
        self.server.probe_loaded.clear()
        self.server.csp_result_ready.clear()
        with tempfile.TemporaryDirectory(prefix="mopa-csp-profile-") as profile:
            with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as browser_log:
                browser = subprocess.Popen(
                    [
                        self.browser,
                        "--headless=new",
                        "--disable-gpu",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        f"--user-data-dir={profile}",
                        f"http://127.0.0.1:{port}/",
                    ],
                    stdout=browser_log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    start_new_session=os.name == "posix",
                )
                try:
                    # Cold Chromium startup on hosted Linux runners can spend more than
                    # 20 seconds initializing system services. This is only a failure
                    # deadline: a successful probe returns immediately when both
                    # browser-native network signals arrive.
                    ready = self.server.csp_result_ready.wait(timeout=60)
                finally:
                    _stop_browser_process_tree(browser)
                browser_log.seek(0)
                log_output = browser_log.read()

        diagnostics = (
            f"probe_loaded={self.server.probe_loaded.is_set()}, "
            f"inline_executed={self.server.inline_executed}, "
            f"report_errors={self.server.report_errors}, "
            f"reports={self.server.csp_reports}\n{log_output[-2000:]}"
        )
        self.assertTrue(ready, f"Chromium did not complete the CSP probe: {diagnostics}")
        self.assertTrue(self.server.inline_executed, diagnostics)
        self.assertEqual(self.server.report_errors, [], diagnostics)
        reports = [item.get("csp-report", {}) for item in self.server.csp_reports]
        inline_violations = [
            item
            for item in reports
            if item.get("effective-directive") in {"script-src", "script-src-elem"}
            and item.get("blocked-uri") == "inline"
        ]
        self.assertTrue(inline_violations, diagnostics)
        self.assertTrue(
            all(item.get("disposition") == "report" for item in inline_violations),
            diagnostics,
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
