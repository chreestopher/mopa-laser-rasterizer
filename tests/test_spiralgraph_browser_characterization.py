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
  // Headless --dump-dom does not consistently deliver animation frames when
  // the page is otherwise idle. Keep the application's coalescing semantics,
  // but drive them with the timer queue so characterization is deterministic.
  let requestedFrames = 0;
  let cancelledFrames = 0;
  window.requestAnimationFrame = callback => {
    requestedFrames += 1;
    return setTimeout(() => callback(performance.now()), 0);
  };
  window.cancelAnimationFrame = handle => {
    cancelledFrames += 1;
    clearTimeout(handle);
  };
  const canvasStrokes = [];
  const originalCanvasStroke = CanvasRenderingContext2D.prototype.stroke;
  CanvasRenderingContext2D.prototype.stroke = function(...args) {
    canvasStrokes.push({canvas: this.canvas.id, color: this.strokeStyle, alpha: this.globalAlpha});
    return originalCanvasStroke.apply(this, args);
  };
  const scenario = new URLSearchParams(location.search).get('scenario');
  const failures = [];
  const runtimeErrors = [];
  const fetchHistory = [];
  let submittedPayload = null;
  let started = false;

  const fail = message => failures.push(message);
  const check = (condition, message) => { if (!condition) fail(message); };
  const $ = selector => document.querySelector(selector);
  const $$ = selector => [...document.querySelectorAll(selector)];
  const visible = element => Boolean(element && !element.hidden && getComputedStyle(element).display !== 'none');
  const input = (element, value) => {
    if (element.type === 'checkbox') element.checked = Boolean(value);
    else element.value = String(value);
    element.dispatchEvent(new Event('input', {bubbles: true}));
  };
  const change = (element, value) => {
    element.value = String(value);
    element.dispatchEvent(new Event('change', {bubbles: true}));
  };
  const settlePreviews = () => new Promise(resolve => setTimeout(resolve, 30));
  const jsonResponse = (value, status = 200) => new Response(JSON.stringify(value), {
    status,
    headers: {'content-type': 'application/json'},
  });
  const finish = () => {
    if (window.__spiralgraphCharacterizationFinished) return;
    window.__spiralgraphCharacterizationFinished = true;
    clearInterval(timer);
    runtimeErrors.forEach(error => fail(`runtime error: ${error}`));
    const result = document.createElement('pre');
    result.id = 'characterization-result';
    result.textContent = JSON.stringify({scenario, failures, fetchHistory, submittedPayload});
    document.body.append(result);
  };

  addEventListener('error', event => runtimeErrors.push(String(event.error?.stack || event.message || 'window error')));
  addEventListener('unhandledrejection', event => runtimeErrors.push(String(event.reason?.stack || event.reason || 'unhandled rejection')));
  window.alert = message => fail(`unexpected alert: ${message}`);

  const resources = {
    material_libraries: [
      {
        library_id: 'processing-1',
        name: 'Characterization Processing',
        library_intent: 'processing_palette',
        summary: {
          logical_material_names: ['Maple'],
          entries: [
            {entry_ref: 'line-1', material: 'Maple', description: 'Score', type: 'Cut'},
            {entry_ref: 'fill-1', material: 'Maple', description: 'Fill', type: 'Scan'},
          ],
        },
      },
      {
        library_id: 'color-1',
        name: 'Characterization Colors',
        library_intent: 'color_palette',
        summary: {
          entries: [
            {entry_ref: 'red-line', description: 'Red Line', type: 'Cut', hex: '#FF0000'},
            {entry_ref: 'blue-fill', description: 'Blue Fill', type: 'Scan', hex: '#0000FF'},
          ],
        },
      },
    ],
    preferences: {
      processing_palette_role_assignments: {
        'processing-1': {materials: {Maple: {Score: 'line-1', Fill: 'fill-1'}}},
      },
      material_library_color_assignments: {
        'color-1': {'#FF0000': 'Red Line', '#0000FF': 'Blue Fill'},
      },
    },
  };

  if (scenario === 'guest') {
    localStorage.removeItem('id_token');
    sessionStorage.removeItem('id_token');
  } else {
    localStorage.setItem('id_token', '__JWT__');
  }

  window.fetch = async (inputValue, options = {}) => {
    const url = new URL(typeof inputValue === 'string' ? inputValue : inputValue.url, location.href);
    const method = options.method || 'GET';
    fetchHistory.push(`${method} ${url.pathname}`);
    if (url.pathname === '/config.json') return jsonResponse({
      api_url: '/api',
      client_id: 'characterization-client',
      cognito_domain: 'example.invalid',
      callback_url: `${location.origin}/callback`,
    });
    if (url.pathname === '/api/account/resources') return jsonResponse(resources);
    if (url.pathname === '/api/spiralgraph/jobs' && method === 'POST') {
      submittedPayload = JSON.parse(options.body);
      return jsonResponse({task_id: 'spiralgraph-characterization-task'});
    }
    if (url.pathname === '/api/jobs/spiralgraph-characterization-task') return jsonResponse({
      status: 'completed',
      outputs: [
        {name: 'nested/spiralgraph.svg', download_url: '/download/spiralgraph.svg'},
        {name: 'spiralgraph.lbrn2', download_url: '/download/spiralgraph.lbrn2'},
        {name: 'manifest.json', download_url: '/download/manifest.json'},
      ],
    });
    if (url.pathname === '/api/jobs/spiralgraph-resume-task') return jsonResponse({
      status: 'completed',
      outputs: [{name: 'resumed.svg', download_url: '/download/resumed.svg'}],
    });
    throw new Error(`Unexpected characterization fetch: ${method} ${url.pathname}`);
  };

  async function startupChecks() {
    await settlePreviews();
    check(visible($('#registeredContent')), 'authenticated content was not shown');
    check(!visible($('#registeredAccess')), 'registered-access prompt remained visible');
    check($$('.layer-card').length === 3, 'three default drawings were not rendered');
    check($('#processingPalette').value === 'processing-1', 'processing palette was not selected');
    check($('#processingMaterial').value === 'Maple', 'processing material was not selected');
    check($('#scoreSetting').value === 'line-1', 'Score role did not initialize the line setting');
    check($('#fillSetting').value === 'fill-1', 'Fill role did not initialize the fill setting');
    check(!$('#generate').disabled, 'Generate remained disabled with valid fallback settings');
    input($('#diameter'), 210);
    check($('#workbedWidth').min === '210' && $('#workbedHeight').min === '210', 'workbed minimums did not follow the finished size');
    check($('#workbedWidth').value === '210' && $('#workbedHeight').value === '210', 'undersized workbed dimensions were not raised to the finished size');
    input($('#diameter'), 150);
    input($('#workbedWidth'), 175);
    input($('#workbedHeight'), 175);
    check($$('#gearHardware [data-hole]').length === 6, 'hardware preview did not render six pen holes');
    check($('#trackHardware path'), 'track hardware path was not rendered');
    check($('#assembledHardware path'), 'assembled hardware path was not rendered');
    check($('#activePreview').width === 720 && $('#stackPreview').width === 720, 'preview canvases changed dimensions');
    check($('#hardwareSummary').textContent.includes('tooth'), 'hardware summary was not populated');
  }

  async function editorChecks() {
    await startupChecks();
    $('#addLayer').click();
    check($$('.layer-card').length === 4, 'Add drawing did not add a fourth drawing');
    $$('.layer-card')[0].querySelector('[data-action="duplicate"]').click();
    check($$('.layer-card').length === 5, 'Duplicate did not add a drawing');
    check($$('.layer-card')[1].querySelector('[data-field="name"]').value.endsWith(' copy'), 'duplicate name did not preserve copy identity');

    let card = $$('.layer-card')[1];
    input(card.querySelector('[data-field="name"]'), 'Characterized drawing');
    input(card.querySelector('[data-field="track"]'), 'rounded_square');
    card = $$('.layer-card')[1];
    input(card.querySelector('[data-field="gear_teeth"]'), 60);
    input(card.querySelector('[data-field="side"]'), 'outside');
    input(card.querySelector('[data-field="direction"]'), 'counterclockwise');
    input(card.querySelector('[data-field="rotation_quarter_turns"]'), 3);
    input(card.querySelector('[data-field="output_mode"]'), 'fill');
    const refreshed = $$('.layer-card')[1];
    input(refreshed.querySelector('[data-field="fill_thickness_mm"]'), 2.4);
    input(refreshed.querySelector('[data-field="include_track"]'), true);
    await settlePreviews();
    check($('#layerPreviewName').textContent === 'Characterized drawing', 'active drawing name did not update');
    check($('#layerPreviewSlider').max === '5', 'preview selector did not track drawing count');
    check(visible(refreshed.querySelector('.fill-thickness')), 'fill thickness did not become visible');
    check($('#hardwareSummary').textContent.includes('rounded square'), 'hardware did not reflect the track edit');
    check($('#hardwareSummary').textContent.includes('60-tooth gear'), 'hardware did not reflect the gear edit');
    check($('#hardwareSummary').textContent.includes('outside'), 'hardware did not reflect outside rolling');

    refreshed.querySelector('[data-action="up"]').click();
    check($('#layerPreviewPosition').textContent === 'Drawing 1 of 5', 'Earlier did not move the active drawing');
    $$('.layer-card')[0].querySelector('[data-action="remove"]').click();
    check($$('.layer-card').length === 4, 'Remove did not remove the active drawing');
  }

  async function paletteChecks() {
    await startupChecks();
    const builtInTarget = $$('.layer-card')[0].querySelector('input[value="#43C7BB"]');
    builtInTarget.click();
    check($$('.layer-card')[0].querySelector('input[value="#43C7BB"]').checked, 'built-in swatch selection did not survive the drawing rerender');
    change($('#colorPalette'), 'color-1');
    check($$('.processing-fallback').every(element => element.hidden), 'processing fallback controls stayed visible with a Color Palette');
    check($$('.layer-card').every(card => card.querySelector('[data-field="output_mode"]').disabled), 'Color Palette did not lock automatic output modes');
    check($$('.preview-swatches input').length === 6, 'two palette swatches were not rendered per drawing');
    const cards = $$('.layer-card');
    check(cards[0].querySelector('[data-field="output_mode"]').value === 'line', 'Cut swatch did not select line mode');
    check(cards[1].querySelector('[data-field="output_mode"]').value === 'fill', 'Scan swatch did not select fill mode');
    cards[0].querySelector('input[value="#0000FF"]').click();
    check($$('.layer-card')[0].querySelector('[data-field="output_mode"]').value === 'fill', 'swatch reassignment did not update output mode');
    check(!$('#generate').disabled, 'Generate became disabled with valid Color Palette swatches');
  }

  async function builtInSwatchSubmitChecks() {
    await startupChecks();
    $$('.layer-card')[0].querySelector('input[value="#43C7BB"]').click();
    $('#spiralgrapForm').dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
    const deadline = Date.now() + 7000;
    while (!submittedPayload && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 20));
    check(Boolean(submittedPayload), 'built-in swatch submission payload was not captured');
    if (submittedPayload) {
      check(submittedPayload.color_palette_id === '', 'built-in swatch submission unexpectedly selected a Color Palette');
      check(submittedPayload.layers[0].swatch_hex === '#43C7BB', 'built-in drawing swatch was not submitted for SVG output');
      check(submittedPayload.processing_palette_id === 'processing-1', 'fallback Processing Palette was not retained');
    }
  }

  async function hardwareChecks() {
    await startupChecks();
    const holeTwo = $('#gearHardware [data-hole="2"]');
    holeTwo.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    await settlePreviews();
    check($$('.layer-card')[0].querySelector('[data-field="pen_hole"]').value === '2', 'clicking hardware hole did not synchronize the select');
    check($('#gearHardware [data-hole="2"]').getAttribute('aria-checked') === 'true', 'clicked hardware hole was not selected');
    check($('#holeSelectionStatus').textContent.includes('pen hole 2'), 'pen-hole click was not announced');
    const selected = $('#gearHardware [data-hole="2"]');
    selected.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowRight', bubbles: true}));
    await settlePreviews();
    check($$('.layer-card')[0].querySelector('[data-field="pen_hole"]').value === '3', 'keyboard pen-hole selection did not advance');
    check($('#gearHardware [data-hole="3"]').getAttribute('aria-checked') === 'true', 'keyboard-selected hardware hole was not selected');
  }

  async function canvasPreviewChecks() {
    await startupChecks();
    canvasStrokes.length = 0;
    const requestsBefore = requestedFrames;
    const cancellationsBefore = cancelledFrames;
    input($('#layerPreviewSlider'), 2);
    input($('#layerPreviewSlider'), 3);
    await settlePreviews();
    check($('#layerPreviewPosition').textContent === 'Drawing 3 of 3', 'selected drawing position did not follow the preview slider');
    check($('#layerPreviewName').textContent === 'Drawing 3', 'selected drawing name did not follow the preview slider');
    check(requestedFrames - requestsBefore === 2, 'preview changes did not request one frame each');
    check(cancelledFrames - cancellationsBefore === 2, 'preview frame requests were not coalesced by cancellation');
    const activeStrokes = canvasStrokes.filter(item => item.canvas === 'activePreview');
    const stackStrokes = canvasStrokes.filter(item => item.canvas === 'stackPreview');
    check(activeStrokes.some(item => item.color === '#8bd450' && item.alpha === 1), 'selected preview did not use the active drawing swatch');
    for (const color of ['#f45b69', '#ffb34d', '#8bd450']) {
      check(stackStrokes.some(item => item.color === color && item.alpha === 0.68), `stacked preview did not include ${color}`);
    }
    change($('#colorPalette'), 'color-1');
    $$('.layer-card')[2].querySelector('input[value="#0000FF"]').click();
    await settlePreviews();
    const latestActive = canvasStrokes.filter(item => item.canvas === 'activePreview').at(-1);
    check(latestActive?.color === '#0000ff', 'selected preview did not redraw with the chosen Color Palette swatch');
  }

  async function customTrackChecks() {
    await startupChecks();
    let card = $$('.layer-card')[0];
    input(card.querySelector('[data-field="track"]'), 'custom');
    card = $$('.layer-card')[0];
    const fileInput = card.querySelector('[data-field="custom_file"]');
    const svg = '<svg xmlns="http://www.w3.org/2000/svg"><circle cx="50" cy="50" r="40"/></svg>';
    const file = new File([svg], 'closed-track.svg', {type: 'image/svg+xml'});
    Object.defineProperty(fileInput, 'files', {configurable: true, value: [file]});
    fileInput.dispatchEvent(new Event('change', {bubbles: true}));
    const deadline = Date.now() + 5000;
    while (!$$('.layer-card')[0].querySelector('.custom-status').textContent.includes('Loaded') && Date.now() < deadline) {
      await new Promise(resolve => setTimeout(resolve, 20));
    }
    card = $$('.layer-card')[0];
    check(card.querySelector('.custom-status').textContent.includes('Loaded closed-track.svg'), 'valid custom closed SVG was not retained');
    check($('#hardwareSummary').textContent.includes('custom'), 'hardware summary did not switch to custom track');
    check(!$('#hardwareSummary').textContent.includes('unavailable'), 'custom track made hardware preview unavailable');
  }

  async function submitChecks() {
    await paletteChecks();
    input($('#projectName'), 'Characterization SpiralGraph');
    input($('#diameter'), 210);
    input($('#workbedWidth'), 240);
    input($('#workbedHeight'), 230);
    $('#spiralgrapForm').dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
    const deadline = Date.now() + 7000;
    while ((!submittedPayload || !$('#status').textContent.startsWith('COMPLETED')) && Date.now() < deadline) {
      await new Promise(resolve => setTimeout(resolve, 20));
    }
    check(Boolean(submittedPayload), 'submission payload was not captured');
    if (submittedPayload) {
      check(submittedPayload.project_name === 'Characterization SpiralGraph', 'project name changed in payload');
      check(submittedPayload.diameter_mm === '210', 'diameter changed in payload');
      check(submittedPayload.color_palette_id === 'color-1', 'Color Palette ID was not submitted');
      check(submittedPayload.processing_palette_id === 'processing-1', 'Processing Palette ID was not submitted');
      check(submittedPayload.material === 'Maple', 'material changed in payload');
      check(submittedPayload.layers.length === 3, 'payload drawing count changed');
      check(submittedPayload.layers[0].swatch_hex === '#0000FF', 'selected drawing swatch was not submitted');
      check(submittedPayload.layers[0].output_mode === 'fill', 'palette-driven fill mode was not submitted');
    }
    check(location.search === '?task=spiralgraph-characterization-task', 'resume URL was not installed after submit');
    check($('#status').textContent.startsWith('COMPLETED'), 'completed job status was not shown');
    check($$('#outputs a').length === 3, 'completed outputs were not rendered');
    check($$('#outputs a')[0].textContent.includes('spiralgraph.svg'), 'nested output name was not normalized');
    check(!$('#generate').disabled, 'Generate stayed disabled after completion');
  }

  async function resumeChecks() {
    await startupChecks();
    const deadline = Date.now() + 5000;
    while (!$('#status').textContent.startsWith('COMPLETED') && Date.now() < deadline) {
      await new Promise(resolve => setTimeout(resolve, 20));
    }
    check(fetchHistory.includes('GET /api/jobs/spiralgraph-resume-task'), 'resume task was not requested');
    check($('#status').textContent.startsWith('COMPLETED'), 'resumed completion was not shown');
    check($$('#outputs a').length === 1, 'resumed output was not rendered');
  }

  async function mobileChecks() {
    await startupChecks();
    check(innerWidth <= 500, `mobile viewport was not applied (${innerWidth})`);
    check(document.documentElement.scrollWidth <= innerWidth + 1, `page overflowed horizontally (${document.documentElement.scrollWidth} > ${innerWidth})`);
    const tooWide = $$('.layer-card, .spiralgrap-panel').filter(element => element.getBoundingClientRect().right > innerWidth + 1);
    check(tooWide.length === 0, `${tooWide.length} cards or panels overflowed the mobile viewport`);
    check($('#gearHardware [data-hole="1"]').getBoundingClientRect().width > 0, 'pen-hole target disappeared on mobile');
  }

  async function runScenario() {
    if (scenario === 'guest') {
      check(visible($('#registeredAccess')), 'signed-out access prompt was not shown');
      check(!visible($('#registeredContent')), 'signed-out content was exposed');
      check($('#loginLink').href.includes('example.invalid/oauth2/authorize'), 'sign-in link was not configured');
      check(!fetchHistory.includes('GET /api/account/resources'), 'signed-out page requested account resources');
    } else if (scenario === 'startup') await startupChecks();
    else if (scenario === 'editor') await editorChecks();
    else if (scenario === 'palette') await paletteChecks();
    else if (scenario === 'built-in-swatch-submit') await builtInSwatchSubmitChecks();
    else if (scenario === 'hardware') await hardwareChecks();
    else if (scenario === 'canvas-preview') await canvasPreviewChecks();
    else if (scenario === 'custom-track') await customTrackChecks();
    else if (scenario === 'submit') await submitChecks();
    else if (scenario === 'resume') await resumeChecks();
    else if (scenario === 'mobile') await mobileChecks();
    else fail(`unknown scenario: ${scenario}`);
  }

  const timer = setInterval(async () => {
    if (started) return;
    const ready = scenario === 'guest' ? visible($('#registeredAccess')) : visible($('#registeredContent')) && $$('.layer-card').length === 3;
    if (!ready) return;
    started = true;
    try { await runScenario(); }
    catch (error) { fail(`scenario exception: ${error.stack || error}`); }
    finish();
  }, 20);

  setTimeout(() => {
    if (!window.__spiralgraphCharacterizationFinished) {
      fail('scenario timed out before reaching a stable result');
      finish();
    }
  }, 20000);
})();
"""


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


class _CharacterizationServer(http.server.ThreadingHTTPServer):
    # Chromium requests the growing ES-module graph in parallel. The default
    # socket backlog can drop one of those requests under load and leave the
    # page only partly initialized.
    request_queue_size = 64


class SpiralGraphBrowserCharacterizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.browser = _browser_path()
        if not cls.browser:
            raise unittest.SkipTest("Chrome, Chromium, or Edge is required for browser characterization")
        cls.temp = tempfile.TemporaryDirectory(prefix="mopa-spiralgraph-browser-")
        cls.site = Path(cls.temp.name) / "site"
        shutil.copytree(WEB, cls.site)
        page_path = cls.site / "spiralgraph.html"
        page = page_path.read_text(encoding="utf-8")
        page = re.sub(r'\s*<script src="/staging-shell\.js\?v=3" defer></script>', '', page)
        page = page.replace(
            '<script src="/spiralgraph.js?v=10" type="module"></script>',
            '<script src="/spiralgraph-characterization-harness.js"></script>\n'
            '<script src="/spiralgraph.js?v=10" type="module"></script>',
        )
        page_path.write_text(page, encoding="utf-8")
        (cls.site / "spiralgraph-characterization-harness.js").write_text(
            HARNESS.replace("__JWT__", _jwt()), encoding="utf-8"
        )

        handler = lambda *args, **kwargs: _QuietHandler(*args, directory=str(cls.site), **kwargs)
        cls.server = _CharacterizationServer(("127.0.0.1", 0), handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.temp.cleanup()

    def _run_scenario(self, scenario, query="", mobile=False):
        port = self.server.server_address[1]
        url = f"http://127.0.0.1:{port}/spiralgraph.html?scenario={scenario}{query}"
        with tempfile.TemporaryDirectory(prefix="mopa-spiralgraph-profile-") as profile:
            command = [
                self.browser,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                f"--user-data-dir={profile}",
                "--virtual-time-budget=30000",
                "--dump-dom",
            ]
            if mobile:
                command.extend(["--window-size=390,844", "--force-device-scale-factor=1"])
            command.append(url)
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=45,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        match = re.search(r'<pre id="characterization-result">(.*?)</pre>', completed.stdout, re.DOTALL)
        self.assertIsNotNone(
            match,
            f"SpiralGraph browser characterization did not finish.\n{completed.stderr}\n{completed.stdout[-3000:]}",
        )
        result = json.loads(html.unescape(match.group(1)))
        self.assertEqual(result["scenario"], scenario)
        self.assertEqual(result["failures"], [])

    def test_signed_out_access_is_gated(self):
        self._run_scenario("guest")

    def test_authenticated_startup_processing_palette_and_previews(self):
        self._run_scenario("startup")

    def test_drawing_add_duplicate_edit_reorder_and_remove(self):
        self._run_scenario("editor")

    def test_color_palette_drives_swatches_and_line_fill_modes(self):
        self._run_scenario("palette")

    def test_builtin_swatch_is_submitted_with_processing_palette_fallback(self):
        self._run_scenario("built-in-swatch-submit")

    def test_hardware_pen_holes_support_pointer_and_keyboard_selection(self):
        self._run_scenario("hardware")

    def test_selected_and_stacked_canvas_previews_preserve_colors_and_frame_coalescing(self):
        self._run_scenario("canvas-preview")

    def test_custom_closed_svg_track_updates_hardware(self):
        self._run_scenario("custom-track")

    def test_submission_payload_completion_outputs_and_resume_url(self):
        self._run_scenario("submit")

    def test_existing_task_resumes_and_renders_downloads(self):
        self._run_scenario("resume", "&task=spiralgraph-resume-task")

    def test_mobile_layout_has_no_horizontal_overflow(self):
        self._run_scenario("mobile", mobile=True)


if __name__ == "__main__":
    unittest.main()
