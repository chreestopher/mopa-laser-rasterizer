import base64
import contextlib
import html
import http.server
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "serverless_web"


def _browser_path():
    configured = os.environ.get("MOPA_BROWSER_BIN")
    candidates = [
        configured,
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("msedge"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    return next((str(path) for path in candidates if path and Path(path).exists()), None)


def _jwt():
    encode = lambda value: base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    return f"{encode({'alg': 'none'})}.{encode({'exp': 4102444800})}.characterization"


HARNESS = r"""
(() => {
  const params = new URLSearchParams(location.search);
  const scenario = params.get('scenario');
  const failures = [];
  const runtimeErrors = [];
  const jsonResponse = (value, status = 200) => new Response(JSON.stringify(value), {
    status,
    headers: {'content-type': 'application/json'}
  });

  addEventListener('error', event => runtimeErrors.push(String(event.error?.stack || event.message || 'window error')));
  addEventListener('unhandledrejection', event => runtimeErrors.push(String(event.reason?.stack || event.reason || 'unhandled rejection')));
  window.stagingShellSetAuthenticated = authenticated => { window.__shellAuthenticated = authenticated; };
  window.stagingShellBeginLogin = () => {};

  if (scenario === 'resume') localStorage.setItem('id_token', '__JWT__');
  else {
    localStorage.removeItem('id_token');
    sessionStorage.removeItem('id_token');
    localStorage.removeItem('refresh_token');
    sessionStorage.removeItem('refresh_token');
  }

  const palette = [
    {name: 'Black', hex: '#000000'},
    {name: 'Gray', hex: '#808080'},
    {name: 'White', hex: '#FFFFFF'}
  ];
  window.fetch = async input => {
    const url = new URL(typeof input === 'string' ? input : input.url, location.href);
    if (url.pathname.endsWith('/config.json')) return jsonResponse({api_url: '/api', client_id: 'test', cognito_domain: 'example.invalid'});
    if (url.pathname === '/api/guest/config') return jsonResponse({palette});
    if (url.pathname === '/api/account/resources') return jsonResponse({
      palette,
      material_libraries: [],
      holographic_recipes: [],
      preferences: {}
    });
    if (url.pathname === '/api/jobs/characterization-task') return jsonResponse({
      status: 'completed',
      logs: ['characterization complete'],
      outputs: [
        {name: 'nested\\preview.png', download_url: '/download/preview.png', bytes: 1048576},
        {name: 'result.lbrn2', download_url: '/download/result.lbrn2', bytes: 2097152},
        {name: 'result.svg', download_url: '/download/result.svg', bytes: 524288}
      ]
    });
    throw new Error(`Unexpected characterization fetch: ${url.pathname}`);
  };

  const assert = (condition, message) => { if (!condition) failures.push(message); };
  const finish = () => {
    if (scenario === 'guest') {
      assert(document.querySelector('#job') && !document.querySelector('#job').classList.contains('hidden'), 'guest form did not become visible');
      assert(!document.querySelector('#guestNotice').classList.contains('hidden'), 'guest notice did not become visible');
      assert(document.querySelector('#status').textContent.startsWith('Guest access.'), 'guest status was not initialized');
      assert(document.querySelectorAll('#materialChoice option').length === 3, 'guest output choices were not populated');
      assert(document.querySelectorAll('#rasterPalette .color-card').length === palette.length, 'guest palette was not rendered');
      assert(window.__shellAuthenticated === false, 'shell did not receive guest authentication state');
    } else {
      const links = [...document.querySelectorAll('#outputs a')];
      assert(document.querySelector('#status').textContent.startsWith('COMPLETED · characterization-task'), 'resumed job did not reach completed state');
      assert(links.length === 3, 'completed output links were not rendered');
      assert(links.map(link => link.textContent.trim()).join('|') === 'Download result.svg|Download result.lbrn2|Download preview.png', 'completed outputs were not ordered SVG, LightBurn, then other');
      assert(links.every(link => link.title === link.textContent.trim()), 'download link labels and titles diverged');
      assert(window.__shellAuthenticated === true, 'shell did not receive authenticated state');
    }
    failures.push(...runtimeErrors.map(error => `runtime error: ${error}`));
    const result = document.createElement('pre');
    result.id = 'characterization-result';
    result.textContent = JSON.stringify({scenario, failures});
    document.body.append(result);
  };

  const deadline = Date.now() + 4000;
  const waitForApplication = () => {
    const ready = scenario === 'guest'
      ? document.querySelectorAll('#rasterPalette .color-card').length === palette.length
      : document.querySelectorAll('#outputs a').length === 3;
    if (ready || Date.now() >= deadline) finish();
    else setTimeout(waitForApplication, 25);
  };
  addEventListener('DOMContentLoaded', waitForApplication, {once: true});
})();
"""


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


class RasterizerBrowserCharacterizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.browser = _browser_path()
        if not cls.browser:
            raise unittest.SkipTest("Chrome, Chromium, or Edge is required for browser characterization")
        cls.temp = tempfile.TemporaryDirectory(prefix="mopa-rasterizer-browser-")
        cls.site = Path(cls.temp.name) / "site"
        shutil.copytree(WEB, cls.site)
        index_path = cls.site / "index.html"
        index = index_path.read_text(encoding="utf-8")
        index = re.sub(r'\s*<script src="/staging-shell\.js\?v=3" defer></script>', '', index)
        index = index.replace(
            '<script src="/rasterizer-v1.js"></script>',
            '<script src="/characterization-harness.js"></script>\n<script src="/rasterizer-v1.js"></script>',
        )
        index_path.write_text(index, encoding="utf-8")
        (cls.site / "characterization-harness.js").write_text(HARNESS.replace("__JWT__", _jwt()), encoding="utf-8")

        handler = lambda *args, **kwargs: _QuietHandler(*args, directory=str(cls.site), **kwargs)
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.temp.cleanup()

    def _run_scenario(self, scenario, query=""):
        port = self.server.server_address[1]
        url = f"http://127.0.0.1:{port}/?scenario={scenario}{query}"
        with tempfile.TemporaryDirectory(prefix="mopa-browser-profile-") as profile:
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
                    url,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        match = re.search(r'<pre id="characterization-result">(.*?)</pre>', completed.stdout, re.DOTALL)
        self.assertIsNotNone(match, f"Browser characterization did not finish.\n{completed.stderr}\n{completed.stdout[-2000:]}")
        result = json.loads(html.unescape(match.group(1)))
        self.assertEqual(result["scenario"], scenario)
        self.assertEqual(result["failures"], [])

    def test_guest_startup_and_palette_controls(self):
        self._run_scenario("guest")

    def test_authenticated_job_resume_and_completed_outputs(self):
        self._run_scenario("resume", "&task=characterization-task")


if __name__ == "__main__":
    unittest.main()
