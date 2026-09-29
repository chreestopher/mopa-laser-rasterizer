import base64
import html
import http.server
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
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
  const statusHistory = [];
  const fetchHistory = [];
  let submittedPayload = null;
  let uploadGrantPayload = null;
  let holographicGrantPayload = null;
  let holographicPayload = null;
  let submissionCount = 0;
  let pollIndex = 0;
  const jsonResponse = (value, status = 200) => new Response(JSON.stringify(value), {
    status,
    headers: {'content-type': 'application/json'}
  });

  addEventListener('error', event => runtimeErrors.push(String(event.error?.stack || event.message || 'window error')));
  addEventListener('unhandledrejection', event => runtimeErrors.push(String(event.reason?.stack || event.reason || 'unhandled rejection')));
  window.stagingShellSetAuthenticated = authenticated => { window.__shellAuthenticated = authenticated; };
  window.stagingShellBeginLogin = () => {};

  if (['resume', 'polling', 'failed', 'authenticated-submit', 'holographic-submit', 'submission-error'].includes(scenario)) localStorage.setItem('id_token', '__JWT__');
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
  class CharacterizationUpload {
    constructor() { this.upload = {}; this.status = 204; }
    open(method, url) { this.method = method; this.url = url; }
    send() {
      queueMicrotask(() => {
        this.upload.onprogress?.({lengthComputable: true, loaded: 3, total: 3});
        this.onload?.();
      });
    }
  }
  window.XMLHttpRequest = CharacterizationUpload;

  window.fetch = async (input, options = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url, location.href);
    fetchHistory.push(`${options.method || 'GET'} ${url.pathname}`);
    if (url.pathname.endsWith('/config.json')) return jsonResponse({api_url: '/api', client_id: 'test', cognito_domain: 'example.invalid'});
    if (url.pathname === '/api/guest/config') return jsonResponse({palette});
    if (url.pathname === '/api/account/resources') return jsonResponse({
      palette,
      material_libraries: [{library_id: 'library-1', name: 'Characterization Library', library_intent: 'color_palette'}],
      holographic_recipes: [{recipe_id: 'recipe-1', name: 'Characterization Fauxlographic Palette', metadata: {schema_version: 2, self_contained: true, swatch_preview: [{name: 'Copper', hex: '#B87333', angle_degrees: 30, interval_mm: 0.06}]}}],
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
    if (url.pathname === '/api/jobs/polling-task') {
      const states = [
        {status: 'pending', logs: ['queued']},
        {status: 'processing', logs: ['queued', 'worker started']},
        {status: 'completed', logs: ['queued', 'worker started', 'done'], outputs: [
          {name: 'polling.svg', download_url: '/download/polling.svg', bytes: 512}
        ]}
      ];
      return jsonResponse(states[Math.min(pollIndex++, states.length - 1)]);
    }
    if (url.pathname === '/api/jobs/failed-task') return jsonResponse({
      status: 'failed',
      logs: ['worker started', 'Invalid geometry style parameters: bad test value']
    });
    if (url.pathname === '/api/uploads' && options.method === 'POST') {
      uploadGrantPayload = JSON.parse(options.body);
      return jsonResponse({
        task_id: scenario === 'submission-error' ? 'submission-error-task' : 'authenticated-submit-task',
        upload_token: 'authenticated-upload-capability',
        artwork: {url: '/upload/authenticated-artwork', key: 'users/test/artwork.png', fields: {}},
        material: null,
        thumbnail: null
      });
    }
    if (url.pathname === '/api/jobs/authenticated-submit-task/submit' && options.method === 'POST') {
      submissionCount += 1;
      submittedPayload = JSON.parse(options.body);
      return jsonResponse({accepted: true});
    }
    if (url.pathname === '/api/jobs/authenticated-submit-task') return jsonResponse({
      status: 'completed', logs: ['authenticated complete'], outputs: [
        {name: 'authenticated-result.svg', download_url: '/download/authenticated-result.svg', bytes: 2048}
      ]
    });
    if (url.pathname === '/api/jobs/submission-error-task/submit' && options.method === 'POST') {
      submissionCount += 1;
      return jsonResponse({message: 'Submission characterization failure'}, 500);
    }
    if (url.pathname === '/api/holographic/uploads' && options.method === 'POST') {
      holographicGrantPayload = JSON.parse(options.body);
      return jsonResponse({
        task_id: 'holographic-submit-task',
        upload_token: 'holographic-upload-capability',
        artwork: {url: '/upload/holographic-artwork', key: 'users/test/holographic-artwork.png', fields: {}},
        thumbnail: null,
        recipe: {key: 'users/test/recipe.json'},
        material: {key: 'users/test/material.clb'}
      });
    }
    if (url.pathname === '/api/holographic/jobs/holographic-submit-task/submit' && options.method === 'POST') {
      submissionCount += 1;
      holographicPayload = JSON.parse(options.body);
      return jsonResponse({accepted: true});
    }
    if (url.pathname === '/api/jobs/holographic-submit-task') return jsonResponse({
      status: 'completed', logs: ['fauxlographic complete'], outputs: [
        {name: 'fauxlographic-result.lbrn2', download_url: '/download/fauxlographic-result.lbrn2', bytes: 4096}
      ]
    });
    if (url.pathname === '/api/guest/uploads' && options.method === 'POST') return jsonResponse({
      task_id: 'guest-submit-task',
      guest_access_token: 'guest-capability',
      upload_token: 'upload-capability',
      artwork: {url: '/upload/artwork', key: 'guest/artwork.png', fields: {}},
      material: null,
      thumbnail: null
    });
    if (url.pathname === '/api/guest/jobs/guest-submit-task/submit' && options.method === 'POST') {
      submittedPayload = JSON.parse(options.body);
      return jsonResponse({accepted: true});
    }
    if (url.pathname === '/api/guest/jobs/guest-submit-task') return jsonResponse({
      status: 'completed', logs: ['guest complete'], outputs: [
        {name: 'guest-result.svg', download_url: '/download/guest-result.svg', bytes: 1024}
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
    } else if (scenario === 'guest-submit') {
      const expectedKeys = [
        'upload_token', 'artwork_key', 'thumbnail_key', 'material_key', 'holographic_palette_key',
        'pixel_square_mm', 'new_width', 'new_height', 'crop_shape', 'white_is', 'material', 'colors',
        'selected_color_hexes', 'selected_holographic_recipe_indexes', 'image_preset', 'abstract_filter',
        'abstract_filter_parameters', 'color_matching_mode', 'color_matching_hue_weight',
        'color_matching_saturation_weight', 'color_matching_lightness_weight',
        'geometry_style', 'geometry_style_parameters', 'panel_tiling', 'color_name_overrides', 'cut_mode',
        'preserve_black_outlines', 'svg_only'
      ];
      assert(submittedPayload !== null, 'guest submission payload was not sent');
      assert(Object.keys(submittedPayload || {}).join('|') === expectedKeys.join('|'), `guest submission payload keys or ordering changed: ${Object.keys(submittedPayload || {}).join('|')}`);
      assert(submittedPayload?.upload_token === 'upload-capability', 'guest upload capability was not forwarded');
      assert(submittedPayload?.artwork_key === 'guest/artwork.png', 'guest artwork key was not forwarded');
      assert(submittedPayload?.pixel_square_mm === '0.125' && submittedPayload?.new_width === '400' && submittedPayload?.new_height === '0', 'numeric form fields stopped being submitted as strings');
      assert(submittedPayload?.svg_only === true && submittedPayload?.material === '', 'SVG-only submission flags changed');
      assert(Array.isArray(submittedPayload?.selected_color_hexes) && submittedPayload.selected_color_hexes.length === palette.length, 'selected guest swatches changed');
      assert(typeof submittedPayload?.panel_tiling === 'object' && submittedPayload.panel_tiling !== null, 'panel tiling payload stopped being an object');
      assert(fetchHistory.includes('POST /api/guest/uploads'), 'guest upload permission was not requested');
      assert(fetchHistory.includes('POST /api/guest/jobs/guest-submit-task/submit'), 'guest job was not submitted');
      assert(document.querySelector('#status').textContent.startsWith('COMPLETED'), 'submitted guest job did not complete');
      assert(document.querySelectorAll('#outputs a').length === 1, 'submitted guest output was not rendered');
      assert(submissionCount === 0, 'guest submission unexpectedly used an authenticated submission listener');
      assert(!location.search.includes('task='), 'guest submission unexpectedly persisted its task ID in the URL');
    } else if (scenario === 'authenticated-submit') {
      const expectedGrantKeys = ['artwork_name', 'artwork_content_type', 'thumbnail_content_type', 'material_name', 'material_content_type', 'holographic_palette_name', 'holographic_palette_content_type', 'upload_holographic_palette', 'saved_material_library_id', 'saved_holographic_recipe_id', 'svg_only'];
      const expectedPayloadKeys = ['upload_token', 'artwork_key', 'thumbnail_key', 'material_key', 'holographic_palette_key', 'pixel_square_mm', 'new_width', 'new_height', 'crop_shape', 'white_is', 'material', 'colors', 'selected_color_hexes', 'selected_holographic_recipe_indexes', 'image_preset', 'abstract_filter', 'abstract_filter_parameters', 'color_matching_mode', 'color_matching_hue_weight', 'color_matching_saturation_weight', 'color_matching_lightness_weight', 'geometry_style', 'geometry_style_parameters', 'panel_tiling', 'color_name_overrides', 'cut_mode', 'preserve_black_outlines', 'svg_only'];
      assert(Object.keys(uploadGrantPayload || {}).join('|') === expectedGrantKeys.join('|'), `authenticated upload grant keys or ordering changed: ${Object.keys(uploadGrantPayload || {}).join('|')}`);
      assert(Object.keys(submittedPayload || {}).join('|') === expectedPayloadKeys.join('|'), `authenticated submission keys or ordering changed: ${Object.keys(submittedPayload || {}).join('|')}`);
      assert(uploadGrantPayload?.svg_only === true && uploadGrantPayload?.upload_holographic_palette === false, 'authenticated upload grant booleans changed');
      assert(submittedPayload?.upload_token === 'authenticated-upload-capability' && submittedPayload?.artwork_key === 'users/test/artwork.png', 'authenticated grant fields were not forwarded');
      assert(submittedPayload?.pixel_square_mm === '0.125' && submittedPayload?.new_width === '400' && submittedPayload?.new_height === '0', 'authenticated numeric fields stopped being strings');
      assert(submittedPayload?.preserve_black_outlines === null && submittedPayload?.svg_only === true, 'authenticated SVG-only flags changed');
      assert(submissionCount === 1, `authenticated form installed duplicate submission behavior (${submissionCount} requests)`);
      assert(location.search === '?task=authenticated-submit-task', `authenticated task ID was not persisted in the URL: ${location.search}`);
      assert(document.querySelector('#status').textContent.startsWith('COMPLETED'), 'authenticated submitted job did not complete');
    } else if (scenario === 'holographic-submit') {
      const expectedGrantKeys = ['artwork_name', 'artwork_content_type', 'thumbnail_content_type', 'saved_holographic_recipe_id', 'saved_material_library_id'];
      const expectedPayloadKeys = ['upload_token', 'artwork_key', 'thumbnail_key', 'recipe_key', 'material_key', 'max_dimension', 'pixel_mm', 'cut_mode', 'preserve_black_outlines'];
      assert(Object.keys(holographicGrantPayload || {}).join('|') === expectedGrantKeys.join('|'), `fauxlographic upload grant keys or ordering changed: ${Object.keys(holographicGrantPayload || {}).join('|')}`);
      assert(Object.keys(holographicPayload || {}).join('|') === expectedPayloadKeys.join('|'), `fauxlographic submission keys or ordering changed: ${Object.keys(holographicPayload || {}).join('|')}`);
      assert(holographicGrantPayload?.saved_holographic_recipe_id === 'recipe-1' && holographicGrantPayload?.saved_material_library_id === 'library-1', 'fauxlographic saved resource IDs changed');
      assert(holographicPayload?.max_dimension === '1000' && holographicPayload?.pixel_mm === '0.08', 'fauxlographic numeric fields stopped being strings');
      assert(holographicPayload?.cut_mode === 'fill' && holographicPayload?.preserve_black_outlines === true, 'fauxlographic cut flags changed');
      assert(submissionCount === 1, `fauxlographic form installed duplicate submission behavior (${submissionCount} requests)`);
      assert(location.search === '?task=holographic-submit-task', `fauxlographic task ID was not persisted in the URL: ${location.search}`);
      assert(document.querySelector('#status').textContent.startsWith('COMPLETED'), 'fauxlographic submitted job did not complete');
    } else if (scenario === 'submission-error') {
      assert(submissionCount === 1, `failed submission ran ${submissionCount} times`);
      assert(document.querySelector('#status').textContent === 'ERROR: Submission characterization failure', 'submission error was not shown');
      assert(document.querySelector('#uploadProgressStatus').textContent.includes('Submission characterization failure'), 'submission progress did not expose the failure');
      assert(document.querySelector('#activity').classList.contains('hidden'), 'activity indicator remained visible after submission failure');
      assert(document.querySelector('#submit').disabled === false, 'Rasterizer submit remained disabled after submission failure');
    } else if (scenario === 'polling') {
      assert(pollIndex === 3, `polling job used ${pollIndex} requests instead of 3 (${fetchHistory.join(', ')})`);
      assert(statusHistory.some(value => value.startsWith('PENDING')), 'pending polling state was not shown');
      assert(statusHistory.some(value => value.startsWith('PROCESSING')), 'processing polling state was not shown');
      assert(document.querySelector('#status').textContent.startsWith('COMPLETED'), 'polling job did not reach completed state');
      assert(document.querySelector('#activity').classList.contains('hidden'), 'activity indicator remained visible after completion');
      assert(document.querySelector('#submit').disabled === false && document.querySelector('#holoSubmit').disabled === false, 'submit controls remained disabled after completion');
    } else if (scenario === 'failed') {
      assert(document.querySelector('#status').textContent.startsWith('FAILED'), 'failed job did not show failed status');
      assert(document.querySelector('#status').textContent.includes("We couldn't read these style settings."), 'failed job reason was not converted to the reviewed user-facing message');
      assert(document.querySelector('#activity').classList.contains('hidden'), 'activity indicator remained visible after failure');
      assert(document.querySelector('#submit').disabled === false, 'Rasterizer submit remained disabled after failure');
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

  const deadline = Date.now() + 7500;
  const status = document.querySelector('#status');
  if (status) new MutationObserver(() => statusHistory.push(status.textContent)).observe(status, {childList: true, characterData: true, subtree: true});
  const artworkFile = () => new File([Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL8WQAAAABJRU5ErkJggg=='), character => character.charCodeAt(0))], 'characterization.png', {type: 'image/png'});
  const attachArtwork = selector => {
    const transfer = new DataTransfer();
    transfer.items.add(artworkFile());
    const artwork = document.querySelector(selector);
    artwork.files = transfer.files;
    artwork.dispatchEvent(new Event('change', {bubbles: true}));
  };
  const startGuestSubmission = () => {
    if (window.__submissionStarted || document.querySelectorAll('#rasterPalette .color-card').length !== palette.length) return;
    window.__submissionStarted = true;
    const choice = document.querySelector('#materialChoice');
    choice.value = 'svg';
    choice.dispatchEvent(new Event('change', {bubbles: true}));
    attachArtwork('#artwork');
    document.querySelector('#job').requestSubmit();
  };
  const startAuthenticatedSubmission = () => {
    if (window.__submissionStarted || document.querySelectorAll('#rasterPalette .color-card').length !== palette.length) return;
    window.__submissionStarted = true;
    const choice = document.querySelector('#materialChoice');
    choice.value = 'svg';
    choice.dispatchEvent(new Event('change', {bubbles: true}));
    attachArtwork('#artwork');
    document.querySelector('#job').requestSubmit();
  };
  const startHolographicSubmission = () => {
    if (window.__submissionStarted || document.querySelector('#holoRecipe option[value="recipe-1"]') === null) return;
    window.__submissionStarted = true;
    document.querySelector('#holoRecipe').value = 'recipe-1';
    document.querySelector('#holoMaterial').value = 'library-1';
    document.querySelector('#holoDimension').value = '1000';
    document.querySelector('#holoPixel').value = '0.08';
    document.querySelector('#holoCutMode').value = 'fill';
    document.querySelector('#holoBlack').checked = true;
    attachArtwork('#holoArtwork');
    document.querySelector('#holographicJob').requestSubmit();
  };
  const waitForApplication = () => {
    if (scenario === 'guest-submit') startGuestSubmission();
    if (scenario === 'authenticated-submit' || scenario === 'submission-error') startAuthenticatedSubmission();
    if (scenario === 'holographic-submit') startHolographicSubmission();
    const ready = scenario === 'guest'
      ? document.querySelectorAll('#rasterPalette .color-card').length === palette.length
      : scenario === 'guest-submit'
        ? submittedPayload !== null && document.querySelectorAll('#outputs a').length === 1
        : scenario === 'authenticated-submit'
          ? submittedPayload !== null && document.querySelectorAll('#outputs a').length === 1
        : scenario === 'holographic-submit'
          ? holographicPayload !== null && document.querySelectorAll('#outputs a').length === 1
        : scenario === 'submission-error'
          ? document.querySelector('#status').textContent.startsWith('ERROR:')
        : scenario === 'polling'
          ? pollIndex === 3 && document.querySelectorAll('#outputs a').length === 1
          : scenario === 'failed'
            ? document.querySelector('#status').textContent.startsWith('FAILED')
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
            '<script type="module" src="/rasterizer-v4.js"></script>',
            '<script src="/characterization-harness.js"></script>\n<script type="module" src="/rasterizer-v4.js"></script>',
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
                    "--virtual-time-budget=9000",
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

    def test_guest_svg_only_submission_payload_and_completion(self):
        self._run_scenario("guest-submit")

    def test_authenticated_svg_only_submission_payload_completion_and_resume_url(self):
        self._run_scenario("authenticated-submit")

    def test_fauxlographic_submission_payload_completion_and_resume_url(self):
        self._run_scenario("holographic-submit")

    def test_authenticated_submission_error_restores_controls(self):
        self._run_scenario("submission-error")

    def test_authenticated_job_polling_sequence_and_completion(self):
        self._run_scenario("polling", "&task=polling-task")

    def test_authenticated_failed_job_restores_submission_controls(self):
        self._run_scenario("failed", "&task=failed-task")


if __name__ == "__main__":
    unittest.main()
