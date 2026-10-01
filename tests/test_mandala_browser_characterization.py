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

  const canvasPaint = [];
  for (const method of ['fill', 'stroke']) {
    const original = CanvasRenderingContext2D.prototype[method];
    CanvasRenderingContext2D.prototype[method] = function(...args) {
      canvasPaint.push({method, canvas: this.canvas.id, color: method === 'fill' ? this.fillStyle : this.strokeStyle, alpha: this.globalAlpha});
      return original.apply(this, args);
    };
  }

  const scenario = new URLSearchParams(location.search).get('scenario');
  const failures = [];
  const runtimeErrors = [];
  const fetchHistory = [];
  const accountAuthorization = [];
  const alerts = [];
  let submittedPayload = null;
  let accountRequests = 0;
  let jobRequests = 0;
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
  const settle = () => new Promise(resolve => setTimeout(resolve, 30));
  const waitFor = async (predicate, message) => {
    const deadline = Date.now() + 7000;
    while (!predicate() && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 20));
    check(predicate(), message);
  };
  const attachFile = (element, file) => {
    const transfer = new DataTransfer();
    transfer.items.add(file);
    element.files = transfer.files;
    element.dispatchEvent(new Event('change', {bubbles: true}));
  };
  const jsonResponse = (value, status = 200) => new Response(JSON.stringify(value), {
    status,
    headers: {'content-type': 'application/json'},
  });
  const finish = () => {
    if (window.__mandalaCharacterizationFinished) return;
    window.__mandalaCharacterizationFinished = true;
    clearInterval(timer);
    runtimeErrors.forEach(error => fail(`runtime error: ${error}`));
    const result = document.createElement('pre');
    result.id = 'characterization-result';
    result.textContent = JSON.stringify({scenario, failures, fetchHistory, submittedPayload, alerts});
    document.body.append(result);
  };

  addEventListener('error', event => runtimeErrors.push(String(event.error?.stack || event.message || 'window error')));
  addEventListener('unhandledrejection', event => runtimeErrors.push(String(event.reason?.stack || event.reason || 'unhandled rejection')));
  window.alert = message => alerts.push(String(message));
  Math.random = () => 0.5;

  const resources = {
    material_libraries: [{
      library_id: 'processing-1',
      name: 'Characterization Processing',
      library_intent: 'processing_palette',
      summary: {
        logical_material_names: ['Maple'],
        entries: [
          {entry_ref: 'cut-1', material: 'Maple', description: 'Cut', type: 'Cut'},
          {entry_ref: 'fill-1', material: 'Maple', description: 'Fill', type: 'Scan'},
        ],
      },
    }, {
      library_id: 'processing-2',
      name: 'Alternate Processing',
      library_intent: 'processing_palette',
      summary: {
        logical_material_names: ['Clear acrylic', 'Engrave only'],
        entries: [
          {entry_ref: 'clear-fast', material: 'Clear acrylic', description: 'Fast Cut', type: 'Cut'},
          {entry_ref: 'clear-fine', material: 'Clear acrylic', description: 'Fine Cut', type: 'Cut'},
          {entry_ref: 'engrave-1', material: 'Engrave only', description: 'Fill', type: 'Scan'},
        ],
      },
    }],
    preferences: {
      processing_palette_role_assignments: {
        'processing-1': {materials: {Maple: {Cut: 'cut-1'}}},
        'processing-2': {materials: {'Clear acrylic': {Cut: 'clear-fine'}}},
      },
    },
  };

  if (scenario === 'guest') {
    localStorage.removeItem('id_token');
    sessionStorage.removeItem('id_token');
  } else {
    localStorage.setItem('id_token', '__JWT__');
  }
  if (scenario === 'auth-retry') localStorage.setItem('refresh_token', 'characterization-refresh');

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
    if (url.pathname === '/oauth2/token') return jsonResponse({id_token: 'characterization-refreshed-token'});
    if (url.pathname === '/api/account/resources') {
      accountRequests += 1;
      accountAuthorization.push(options.headers?.authorization);
      if (scenario === 'auth-retry' && accountRequests === 1) return jsonResponse({message: 'Expired'}, 401);
      return jsonResponse(resources);
    }
    if (url.pathname === '/api/mandala/jobs' && method === 'POST') {
      submittedPayload = JSON.parse(options.body);
      if (scenario === 'submission-error') return jsonResponse({message: 'Mandala characterization failure'}, 500);
      return jsonResponse({task_id: 'mandala-characterization-task'});
    }
    if (url.pathname === '/api/jobs/mandala-characterization-task') {
      jobRequests += 1;
      if (scenario === 'polling-failure') return jsonResponse({status: 'failed', error: 'Worker characterization failure'});
      return jsonResponse({
        status: scenario === 'submit' && jobRequests === 1 ? 'pending' : 'completed',
        outputs: [
          {name: 'nested/combined.lbrn2', download_url: '/download/combined.lbrn2'},
          {name: 'layers/layer-01.svg', download_url: '/download/layer-01.svg'},
          {name: 'assembly-preview.png', download_url: '/download/assembly-preview.png'},
          {name: 'manifest.json', download_url: '/download/manifest.json'},
        ],
      });
    }
    if (url.pathname === '/api/jobs/mandala-resume-task') return jsonResponse({
      status: 'completed',
      outputs: [{name: 'resumed.lbrn2', download_url: '/download/resumed.lbrn2'}],
    });
    throw new Error(`Unexpected characterization fetch: ${method} ${url.pathname}`);
  };

  async function startupChecks() {
    await settle();
    check(visible($('#registeredContent')), 'authenticated content was not shown');
    check(!visible($('#registeredAccess')), 'registered-access prompt remained visible');
    check($$('.layer-card').length === 3, 'three default layers were not rendered');
    check($('#processingPalette').value === 'processing-1', 'Processing Palette was not selected');
    check($('#processingMaterial').value === 'Maple', 'processing material was not selected');
    check($('#cutSetting').value === 'cut-1', 'Cut role did not initialize the cut setting');
    check(!$('#generate').disabled, 'Generate remained disabled with a valid Cut role');
    check($('#layerPreviewPosition').textContent === 'Layer 1 of 3', 'selected-layer position was not initialized');
    check($('#layerPreviewName').textContent === 'Layer 1', 'selected-layer name was not initialized');
    check($('#activePreview').width === 620 && $('#stackPreview').width === 620, 'preview canvas dimensions changed');

    let firstLayer = $$('.layer-card')[0];
    input(firstLayer.querySelector('[data-field="rim_width_mm"]'), 30);
    input(firstLayer.querySelector('[data-field="bridge_width_mm"]'), 20);
    change($('#diameter'), 100);
    firstLayer = $$('.layer-card')[0];
    check(firstLayer.querySelector('[data-field="rim_width_mm"]').value === '15', 'rim width did not follow the diameter limit');
    check(firstLayer.querySelector('[data-field="bridge_width_mm"]').value === '8', 'bridge width did not follow the diameter limit');
    input(firstLayer.querySelector('[data-field="rim_width_mm"]'), 4);
    input(firstLayer.querySelector('[data-field="bridge_width_mm"]'), 1.5);
    change($('#diameter'), 210);
    check($('#workbedWidth').min === '210' && $('#workbedHeight').min === '210', 'workbed minimums did not follow finished diameter');
    check($('#workbedWidth').value === '210' && $('#workbedHeight').value === '210', 'undersized workbed dimensions were not raised');
    change($('#diameter'), 150);
    input($('#workbedWidth'), 175);
    input($('#workbedHeight'), 175);
  }

  async function editorChecks() {
    await startupChecks();
    $('#addLayer').click();
    check($$('.layer-card').length === 4, 'Add layer did not add a fourth layer');
    $$('.layer-card')[0].querySelector('[data-action="duplicate"]').click();
    check($$('.layer-card').length === 5, 'Duplicate did not add a layer');
    check($$('.layer-card')[1].querySelector('[data-field="name"]').value.endsWith(' copy'), 'duplicate name did not preserve copy identity');

    let card = $$('.layer-card')[1];
    input(card.querySelector('[data-field="name"]'), 'Characterized layer');
    input(card.querySelector('[data-field="ornament_style"]'), 'paisley');
    input(card.querySelector('[data-field="motif_composition"]'), 'flow_character');
    input(card.querySelector('[data-field="support_mode"]'), 'fully_connected');
    input(card.querySelector('[data-field="rim_style"]'), 'petal');
    input(card.querySelector('[data-field="repetitions"]'), 18);
    input(card.querySelector('[data-field="rings"]'), 5);
    input(card.querySelector('[data-field="support_sweep_degrees"]'), 32);
    input(card.querySelector('[data-field="bridge_wave_amount"]'), 0.8);
    input(card.querySelector('[data-field="layer_openness"]'), 0.4);
    input(card.querySelector('[data-field="mirror_wedges"]'), false);
    await settle();
    check($('#layerPreviewName').textContent === 'Characterized layer', 'active-layer name did not update');
    check($('#layerPreviewSlider').max === '5', 'preview selector did not track layer count');

    card.querySelector('[data-action="up"]').click();
    check($('#layerPreviewPosition').textContent === 'Layer 1 of 5', 'Earlier did not move the active layer');
    $$('.layer-card')[0].querySelector('[data-action="remove"]').click();
    check($$('.layer-card').length === 4, 'Remove did not remove the active layer');
  }

  async function paletteRoutingChecks() {
    await startupChecks();
    change($('#processingPalette'), 'processing-2');
    check($('#processingMaterial').value === 'Clear acrylic', 'palette change did not select its first material');
    check($('#cutSetting').value === 'clear-fine', 'assigned Cut role did not select the matching setting');
    check(!$('#generate').disabled, 'Generate was disabled for the alternate valid Cut role');
    check($('#paletteStatus').textContent === 'Using Clear acrylic · Fine Cut.', 'alternate Cut status did not reflect the preferred setting');
    change($('#cutSetting'), 'clear-fast');
    check($('#paletteStatus').textContent === 'Using Clear acrylic · Fast Cut.', 'Cut setting change did not update status');
    change($('#processingMaterial'), 'Engrave only');
    check($('#cutSetting').options.length === 0, 'non-Cut material retained a Cut setting');
    check($('#generate').disabled, 'Generate remained enabled without a Cut setting');
    check($('#paletteStatus').textContent.includes('no LightBurn Line setting'), 'missing Cut setting guidance changed');
    change($('#processingPalette'), 'processing-1');
    check($('#processingMaterial').value === 'Maple' && $('#cutSetting').value === 'cut-1', 'returning to the first palette did not restore its Cut route');
    check(!$('#generate').disabled, 'Generate did not recover after returning to a valid palette');
  }

  async function randomizeResetChecks() {
    await startupChecks();
    let card = $$('.layer-card')[0];
    input(card.querySelector('[data-field="name"]'), 'Named layer');
    const before = card.querySelector('[data-field="repetitions"]').value;
    card.querySelector('[data-action="randomize"]').click();
    card = $$('.layer-card')[0];
    check(card.querySelector('[data-field="name"]').value === 'Named layer', 'Randomize changed the layer name');
    check(card.querySelector('[data-field="repetitions"]').value !== before, 'Randomize did not change bounded geometry controls');
    check(Number(card.querySelector('[data-field="bridge_wave_amount"]').value) >= 0 && Number(card.querySelector('[data-field="bridge_wave_amount"]').value) <= 1, 'random bridge wave left its allowed range');
    card.querySelector('[data-action="reset"]').click();
    card = $$('.layer-card')[0];
    check(card.querySelector('[data-field="name"]').value === 'Named layer', 'Reset changed the layer name');
    check(card.querySelector('[data-field="motif"]').value === 'petal', 'Reset did not restore the default motif');
    check(card.querySelector('[data-field="repetitions"]').value === '12', 'Reset did not restore default repetitions');
    check(card.querySelector('[data-field="support_mode"]').value === 'automatic_bridges', 'Reset did not restore automatic bridges');
  }

  async function previewChecks() {
    await startupChecks();
    canvasPaint.length = 0;
    const requestsBefore = requestedFrames;
    const cancellationsBefore = cancelledFrames;
    input($('#layerPreviewSlider'), 2);
    input($('#layerPreviewSlider'), 3);
    await settle();
    check($('#layerPreviewPosition').textContent === 'Layer 3 of 3', 'selected layer did not follow the preview slider');
    check($('#layerPreviewName').textContent === 'Layer 3', 'selected layer name did not follow the preview slider');
    check(requestedFrames - requestsBefore === 2, 'preview changes did not request one frame each');
    check(cancelledFrames - cancellationsBefore === 2, 'preview frame requests were not coalesced');
    const activePaint = canvasPaint.filter(item => item.canvas === 'activePreview');
    const stackPaint = canvasPaint.filter(item => item.canvas === 'stackPreview');
    check(activePaint.some(item => item.color === '#e4d354' && item.alpha === 1), 'selected preview did not use the third layer color');
    for (const color of ['#e44d61', '#f39c49', '#e4d354']) {
      check(stackPaint.some(item => item.color === color && item.alpha === 0.38), `stacked preview did not include ${color}`);
    }
  }

  async function customSvgChecks() {
    await startupChecks();
    let card = $$('.layer-card')[0];
    input(card.querySelector('[data-field="motif"]'), 'custom');
    card = $$('.layer-card')[0];

    attachFile(card.querySelector('[data-field="custom_file"]'), new File(['not svg'], 'motif.txt', {type: 'text/plain'}));
    await waitFor(() => alerts.length === 1, 'non-SVG custom file did not report a validation error');
    check(alerts[0] === 'Choose an SVG file.', `non-SVG error changed (${alerts[0]})`);

    attachFile(card.querySelector('[data-field="custom_file"]'), new File(['x'.repeat(65537)], 'large.svg', {type: 'image/svg+xml'}));
    await waitFor(() => alerts.length === 2, 'oversized custom SVG did not report a validation error');
    check(alerts[1] === 'Custom SVG files must be no larger than 64 KB.', `oversized SVG error changed (${alerts[1]})`);

    attachFile(card.querySelector('[data-field="custom_file"]'), new File(['<not-svg/>'], 'invalid.svg', {type: 'image/svg+xml'}));
    await waitFor(() => alerts.length === 3, 'invalid SVG root did not report a validation error');
    check(alerts[2] === 'The custom SVG could not be read.', `invalid SVG error changed (${alerts[2]})`);

    const embedded = '<svg xmlns="http://www.w3.org/2000/svg"><path fill="url(#paint)" d="M0 0H10V10Z"/></svg>';
    attachFile(card.querySelector('[data-field="custom_file"]'), new File([embedded], 'embedded.svg', {type: 'image/svg+xml'}));
    await waitFor(() => alerts.length === 4, 'embedded SVG content did not report a validation error');
    check(alerts[3] === 'Embedded or external SVG content is not supported.', `embedded SVG error changed (${alerts[3]})`);

    const unsafe = '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script><path d="M0 0H10V10Z"/></svg>';
    attachFile(card.querySelector('[data-field="custom_file"]'), new File([unsafe], 'unsafe.svg', {type: 'image/svg+xml'}));
    await waitFor(() => alerts.length === 5, 'unsafe custom SVG did not report a validation error');
    check(alerts[4]?.includes('SVG element <script> is not supported.'), `unsafe SVG error changed (${alerts[4]})`);

    card = $$('.layer-card')[0];
    const safe = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path d="M50 5L95 95H5Z"/></svg>';
    attachFile(card.querySelector('[data-field="custom_file"]'), new File([safe], 'characterization-motif.svg', {type: 'image/svg+xml'}));
    await waitFor(() => $$('.layer-card')[0].querySelector('.custom-svg-status')?.textContent.includes('Loaded characterization-motif.svg'), 'safe custom SVG was not retained');
    check($$('.layer-card')[0].querySelector('[data-field="motif"]').value === 'custom', 'custom motif selection changed after loading SVG');
  }

  async function submitChecks() {
    await startupChecks();
    input($('#projectName'), 'Characterization Mandala');
    change($('#diameter'), 210);
    input($('#workbedWidth'), 240);
    input($('#workbedHeight'), 230);
    let card = $$('.layer-card')[0];
    input(card.querySelector('[data-field="ornament_style"]'), 'billow');
    input(card.querySelector('[data-field="motif_composition"]'), 'flow_character');
    input(card.querySelector('[data-field="support_sweep_degrees"]'), 24);
    input(card.querySelector('[data-field="bridge_wave_amount"]'), 0.75);
    input(card.querySelector('[data-field="bridge_wave_amplitude_mm"]'), 9);
    input(card.querySelector('[data-field="bridge_wave_position"]'), 0.6);
    input(card.querySelector('[data-field="layer_openness"]'), 0.35);
    input(card.querySelector('[data-field="opening_inner_ratio"]'), 0.42);
    input(card.querySelector('[data-field="opening_rotation_degrees"]'), 15);
    $('#mandalaForm').dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
    await waitFor(() => submittedPayload && $('#status').textContent.startsWith('COMPLETED'), 'Mandala submission did not complete');
    check(submittedPayload?.project_name === 'Characterization Mandala', 'project name changed in payload');
    check(submittedPayload?.diameter_mm === '210', 'diameter changed in payload');
    check(submittedPayload?.workbed_width_mm === '240' && submittedPayload?.workbed_height_mm === '230', 'workbed dimensions changed in payload');
    check(submittedPayload?.processing_palette_id === 'processing-1', 'Processing Palette ID was not submitted');
    check(submittedPayload?.material === 'Maple' && submittedPayload?.cut_entry_ref === 'cut-1', 'Cut role selection changed in payload');
    check(submittedPayload?.layers?.length === 3, 'payload layer count changed');
    check(submittedPayload?.layers?.[0]?.ornament_style === 'billow' && submittedPayload?.layers?.[0]?.motif_composition === 'flow_character', 'ornament settings changed in payload');
    check(submittedPayload?.layers?.[0]?.support_sweep_degrees === 24 && submittedPayload?.layers?.[0]?.bridge_wave_amount === 0.75, 'bridge settings changed in payload');
    check(submittedPayload?.layers?.[0]?.layer_openness === 0.35 && submittedPayload?.layers?.[0]?.opening_inner_ratio === 0.42, 'openwork settings changed in payload');
    check(location.search === '?task=mandala-characterization-task', 'resume URL was not installed after submit');
    check($$('#outputs a').length === 4, 'completed outputs were not rendered');
    check($$('#outputs a')[0].textContent.includes('combined.lbrn2'), 'nested output name was not normalized');
    check($$('#outputs a').map(link => link.getAttribute('href')).join('|') === '/download/combined.lbrn2|/download/layer-01.svg|/download/assembly-preview.png|/download/manifest.json', 'download link order or URLs changed');
    check(jobRequests === 2, `pending job was polled ${jobRequests} times instead of twice`);
    check(!$('#generate').disabled, 'Generate stayed disabled after completion');
  }

  async function submissionErrorChecks() {
    await startupChecks();
    $('#mandalaForm').dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
    await waitFor(() => $('#status').classList.contains('error'), 'submission error was not shown');
    check($('#status').textContent.includes('Mandala characterization failure'), 'submission error message changed');
    check(!$('#generate').disabled, 'Generate stayed disabled after submission error');
    check($$('#outputs a').length === 0, 'failed submission rendered output links');
  }

  async function pollingFailureChecks() {
    await startupChecks();
    $('#mandalaForm').dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
    await waitFor(() => $('#status').classList.contains('error'), 'polling failure was not shown');
    check($('#status').textContent === 'ERROR · Worker characterization failure', 'polling failure text changed');
    check(!$('#generate').disabled, 'Generate stayed disabled after polling failure');
    check($$('#outputs a').length === 0, 'failed job rendered output links');
  }

  async function authRetryChecks() {
    await startupChecks();
    check(accountRequests === 2, `authenticated request was made ${accountRequests} times instead of retrying once`);
    check(fetchHistory.filter(item => item === 'POST /oauth2/token').length === 1, 'session refresh request count changed');
    check(accountAuthorization[0] === `Bearer __JWT__`, 'initial authenticated request did not use the original ID token');
    check(accountAuthorization[1] === 'Bearer characterization-refreshed-token', 'retried request did not use the refreshed ID token');
    check(localStorage.getItem('id_token') === 'characterization-refreshed-token', 'refreshed ID token was not retained');
    check(sessionStorage.getItem('id_token') === null && sessionStorage.getItem('refresh_token') === null, 'session tokens were not cleared after transfer');
  }

  async function resumeChecks() {
    await startupChecks();
    await waitFor(() => $('#status').textContent.startsWith('COMPLETED'), 'resumed Mandala job did not complete');
    check(fetchHistory.includes('GET /api/jobs/mandala-resume-task'), 'resume task was not requested');
    check($$('#outputs a').length === 1, 'resumed output was not rendered');
  }

  async function mobileChecks() {
    await startupChecks();
    check(innerWidth <= 500, `mobile viewport was not applied (${innerWidth})`);
    check(document.documentElement.scrollWidth <= innerWidth + 1, `page overflowed horizontally (${document.documentElement.scrollWidth} > ${innerWidth})`);
    const tooWide = $$('.layer-card, .mandala-panel').filter(element => element.getBoundingClientRect().right > innerWidth + 1);
    check(tooWide.length === 0, `${tooWide.length} cards or panels overflowed the mobile viewport`);
    check($('#layerPreviewSlider').getBoundingClientRect().width > 0, 'layer preview slider disappeared on mobile');
  }

  async function runScenario() {
    if (scenario === 'guest') {
      check(visible($('#registeredAccess')), 'signed-out access prompt was not shown');
      check(!visible($('#registeredContent')), 'signed-out content was exposed');
      check($('#loginLink').href.includes('example.invalid/oauth2/authorize'), 'sign-in link was not configured');
      check(!fetchHistory.includes('GET /api/account/resources'), 'signed-out page requested account resources');
    } else if (scenario === 'startup') await startupChecks();
    else if (scenario === 'palette-routing') await paletteRoutingChecks();
    else if (scenario === 'editor') await editorChecks();
    else if (scenario === 'randomize-reset') await randomizeResetChecks();
    else if (scenario === 'preview') await previewChecks();
    else if (scenario === 'custom-svg') await customSvgChecks();
    else if (scenario === 'submit') await submitChecks();
    else if (scenario === 'submission-error') await submissionErrorChecks();
    else if (scenario === 'polling-failure') await pollingFailureChecks();
    else if (scenario === 'auth-retry') await authRetryChecks();
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
    if (!window.__mandalaCharacterizationFinished) {
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
    request_queue_size = 64


class MandalaBrowserCharacterizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.browser = _browser_path()
        if not cls.browser:
            raise unittest.SkipTest("Chrome, Chromium, or Edge is required for browser characterization")
        cls.temp = tempfile.TemporaryDirectory(prefix="mopa-mandala-browser-")
        cls.site = Path(cls.temp.name) / "site"
        shutil.copytree(WEB, cls.site)
        page_path = cls.site / "mandala.html"
        page = page_path.read_text(encoding="utf-8")
        page = re.sub(r'\s*<script src="/staging-shell\.js\?v=3" defer></script>', '', page)
        page = page.replace(
            '<script src="/mandala.js?v=14" type="module"></script>',
            '<script src="/mandala-characterization-harness.js"></script>\n'
            '<script src="/mandala.js?v=14" type="module"></script>',
        )
        page_path.write_text(page, encoding="utf-8")
        (cls.site / "mandala-characterization-harness.js").write_text(
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
        url = f"http://127.0.0.1:{port}/mandala.html?scenario={scenario}{query}"
        with tempfile.TemporaryDirectory(prefix="mopa-mandala-profile-") as profile:
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
            f"Mandala browser characterization did not finish.\n{completed.stderr}\n{completed.stdout[-3000:]}",
        )
        result = json.loads(html.unescape(match.group(1)))
        self.assertEqual(result["scenario"], scenario)
        self.assertEqual(result["failures"], [])

    def test_signed_out_access_is_gated(self):
        self._run_scenario("guest")

    def test_authenticated_startup_palette_dimensions_and_previews(self):
        self._run_scenario("startup")

    def test_palette_and_cut_setting_events_route_synchronously(self):
        self._run_scenario("palette-routing")

    def test_layer_add_duplicate_edit_reorder_and_remove(self):
        self._run_scenario("editor")

    def test_layer_randomize_is_bounded_and_reset_restores_defaults(self):
        self._run_scenario("randomize-reset")

    def test_selected_and_stacked_previews_preserve_colors_and_frame_coalescing(self):
        self._run_scenario("preview")

    def test_custom_svg_rejects_executable_content_and_retains_safe_vector(self):
        self._run_scenario("custom-svg")

    def test_submission_payload_completion_outputs_and_resume_url(self):
        self._run_scenario("submit")

    def test_submission_error_restores_generate_control(self):
        self._run_scenario("submission-error")

    def test_polling_failure_restores_generate_control(self):
        self._run_scenario("polling-failure")

    def test_authenticated_request_refreshes_and_retries_once(self):
        self._run_scenario("auth-retry")

    def test_existing_task_resumes_and_renders_downloads(self):
        self._run_scenario("resume", "&task=mandala-resume-task")

    def test_mobile_layout_has_no_horizontal_overflow(self):
        self._run_scenario("mobile", mobile=True)


if __name__ == "__main__":
    unittest.main()
