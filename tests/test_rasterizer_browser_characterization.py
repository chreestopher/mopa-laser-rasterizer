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
  const statusHistory = [];
  const fetchHistory = [];
  let submittedPayload = null;
  let uploadGrantPayload = null;
  let holographicGrantPayload = null;
  let holographicPayload = null;
  let preferencePayload = null;
  let submissionCount = 0;
  let pollIndex = 0;
  let accountResourceRequests = 0;
  if (scenario === 'preview' || scenario === 'image-style-matching' || scenario === 'panel-tiling' || scenario === 'shape-assets' || scenario === 'flow-painter') window.createImageBitmap = async () => {
    const canvas = document.createElement('canvas');
    canvas.width = scenario === 'panel-tiling' || scenario === 'shape-assets' || scenario === 'flow-painter' ? 4 : 1;
    canvas.height = scenario === 'panel-tiling' || scenario === 'shape-assets' || scenario === 'flow-painter' ? 2 : 1;
    const context = canvas.getContext('2d');
    if (scenario === 'flow-painter') {
      context.clearRect(0, 0, canvas.width, canvas.height);
      context.fillStyle = '#404040';
      context.fillRect(0, 0, 2, 2);
      context.fillStyle = '#C0C0C0';
      context.fillRect(2, 0, 2, 2);
    } else {
      context.fillStyle = '#000000';
      context.fillRect(0, 0, 1, 1);
    }
    canvas.close = () => {};
    return canvas;
  };
  const jsonResponse = (value, status = 200) => new Response(JSON.stringify(value), {
    status,
    headers: {'content-type': 'application/json'}
  });

  addEventListener('error', event => runtimeErrors.push(String(event.error?.stack || event.message || 'window error')));
  addEventListener('unhandledrejection', event => runtimeErrors.push(String(event.reason?.stack || event.reason || 'unhandled rejection')));
  window.stagingShellSetAuthenticated = authenticated => { window.__shellAuthenticated = authenticated; };
  window.stagingShellBeginLogin = () => {};

  if (scenario === 'auth-refresh') {
    localStorage.setItem('id_token', 'expired-token');
    localStorage.setItem('refresh_token', 'refresh-capability');
  } else if (['auth-retry', 'resume', 'polling', 'failed', 'authenticated-submit', 'holographic-submit', 'submission-error', 'preview', 'image-style-matching', 'panel-tiling', 'palette-resources', 'shape-assets', 'geometry-routing', 'flow-painter'].includes(scenario)) {
    localStorage.setItem('id_token', '__JWT__');
    if (scenario === 'auth-retry') localStorage.setItem('refresh_token', 'refresh-capability');
  } else {
    localStorage.removeItem('id_token');
    sessionStorage.removeItem('id_token');
    localStorage.removeItem('refresh_token');
    sessionStorage.removeItem('refresh_token');
  }
  if (scenario === 'guest-resume' || scenario === 'guest-expired-task') {
    sessionStorage.setItem('guest_access_token', 'guest-resume-capability');
  } else {
    sessionStorage.removeItem('guest_access_token');
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
    if (url.pathname === '/oauth2/token') return jsonResponse({id_token: '__JWT__'});
    if (url.pathname === '/api/guest/config') return jsonResponse({palette});
    if (url.pathname === '/api/account/resources') {
      accountResourceRequests += 1;
      if (scenario === 'auth-retry' && accountResourceRequests === 1) return jsonResponse({message: 'Expired characterization token'}, 401);
      return jsonResponse({
      palette,
      material_libraries: [{library_id: 'library-1', name: 'Characterization Library', material_name: 'Walnut', library_intent: 'color_palette', summary: {material_names: ['Walnut', 'Maple']}}],
      holographic_recipes: [{recipe_id: 'recipe-1', name: 'Characterization Fauxlographic Palette', metadata: {schema_version: 2, self_contained: true, swatch_preview: [{name: 'Copper', hex: '#B87333', angle_degrees: 30, interval_mm: 0.06}]}}],
      preferences: scenario === 'palette-resources' ? {
        selected_color_hexes: ['#FFFFFF'],
        material_library_color_assignments: {'library-1': {'#000000': 'Char', '#FFFFFF': 'Bright'}},
        last_rasterizer_form: {values: {
          material_choice: 'library:library-1', material_name: 'Maple', pixel_square_mm: '0.09',
          new_width: '321', new_height: '123', white_is: 'unengraved', cut_mode: 'line',
          preserve_black_outlines: true
        }}
      } : scenario === 'image-style-matching' ? {
        selected_color_hexes: ['#000000', '#808080', '#FFFFFF'],
        last_rasterizer_form: {values: {
          material_choice: 'svg',
          image_preset: 'abstract_optical_color_mix',
          filter_parameters: {mixing_model: 'hsv', keep_available_colors_as_vectors: 0, square_dots: 1, dot_pitch_mm: 0.7, mix_cell_dots: 6},
          color_matching_mode: 'custom',
          color_matching_hue_weight: 7,
          color_matching_saturation_weight: 2,
          color_matching_lightness_weight: 5
        }}
      } : {}
      });
    }
    if (url.pathname === '/api/account/preferences' && options.method === 'PATCH') {
      preferencePayload = JSON.parse(options.body);
      return jsonResponse({preferences: preferencePayload});
    }
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
        {status: 'completed', logs: ['done'], outputs: [
          {name: 'polling.svg', download_url: '/download/polling.svg', bytes: 512}
        ]},
        {status: 'completed', logs: ['queued', 'worker started', 'done'], outputs: [
          {name: 'polling.svg', download_url: '/download/polling.svg', bytes: 512}
        ]},
        {status: 'completed', logs: ['queued', 'worker started', 'done'], outputs: [
          {name: 'polling.svg', download_url: '/download/polling.svg', bytes: 512}
        ]},
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
    if (url.pathname === '/api/guest/jobs/guest-resume-task') {
      const headers = new Headers(options.headers || {});
      if (headers.get('x-guest-capability') !== 'guest-resume-capability') {
        return jsonResponse({message: 'Guest task not found or access expired'}, 404);
      }
      return jsonResponse({
        status: 'completed', logs: ['guest resume complete'], outputs: [
          {name: 'guest-resume.svg', download_url: '/download/guest-resume.svg', bytes: 1024}
        ]
      });
    }
    if (url.pathname === '/api/guest/jobs/expired-guest-task') {
      return jsonResponse({message: 'Guest task not found or access expired'}, 404);
    }
    throw new Error(`Unexpected characterization fetch: ${url.pathname}`);
  };

  const assert = (condition, message) => { if (!condition) failures.push(message); };
  const finish = () => {
    submissionReadinessObserver?.disconnect();
    if (scenario === 'guest') {
      assert(document.querySelector('#job') && !document.querySelector('#job').classList.contains('hidden'), 'guest form did not become visible');
      assert(!document.querySelector('#guestNotice').classList.contains('hidden'), 'guest notice did not become visible');
      assert(document.querySelector('#status').textContent.startsWith('Guest access.'), 'guest status was not initialized');
      assert(document.querySelectorAll('#materialChoice option').length === 3, 'guest output choices were not populated');
      assert(document.querySelectorAll('#rasterPalette .color-card').length === palette.length, 'guest palette was not rendered');
      assert(window.__shellAuthenticated === false, 'shell did not receive guest authentication state');
    } else if (scenario === 'guest-stale-task-no-capability') {
      assert(!new URL(location.href).searchParams.has('task'), 'stale guest task remained in the URL without a capability');
      assert(new URL(location.href).searchParams.get('keep') === 'yes', 'unrelated query parameters were removed with the stale task');
      assert(!fetchHistory.some(value => value.includes('/api/guest/jobs/')), `guest job was requested without a capability (${fetchHistory.join(', ')})`);
      assert(document.querySelector('#status').textContent.startsWith('Guest access.'), 'guest startup status changed while clearing stale task context');
      assert(document.querySelector('#submit').disabled === false, 'Rasterizer submit was disabled after clearing stale task context');
    } else if (scenario === 'guest-expired-task') {
      assert(fetchHistory.filter(value => value === 'GET /api/guest/jobs/expired-guest-task').length === 1, `expired guest task was requested more than once (${fetchHistory.join(', ')})`);
      assert(!new URL(location.href).searchParams.has('task'), 'expired guest task remained in the URL');
      assert(new URL(location.href).searchParams.get('keep') === 'yes', 'unrelated query parameters were removed with the expired task');
      assert(sessionStorage.getItem('guest_access_token') === 'guest-resume-capability', 'task recovery removed a capability that may belong to another guest job');
      assert(document.querySelector('#status').textContent === 'This guest job is no longer available. Start a new temporary Rasterizer job below.', `expired guest recovery message changed (${document.querySelector('#status').textContent})`);
      assert(document.querySelector('#activity').classList.contains('hidden'), 'activity indicator remained visible after expired guest recovery');
      assert(document.querySelector('#submit').disabled === false && document.querySelector('#holoSubmit').disabled === false, 'submit controls remained disabled after expired guest recovery');
    } else if (scenario === 'guest-resume') {
      assert(fetchHistory.filter(value => value === 'GET /api/guest/jobs/guest-resume-task').length === 4, `valid guest resume did not complete terminal log refreshes (${fetchHistory.join(', ')})`);
      assert(new URL(location.href).searchParams.get('task') === 'guest-resume-task', 'valid guest task was removed from the URL');
      assert(document.querySelector('#status').textContent.startsWith('COMPLETED'), 'valid guest resume did not complete');
      assert(document.querySelectorAll('#outputs a').length === 1, 'valid guest resume outputs were not rendered');
    } else if (scenario === 'auth-refresh') {
      assert(fetchHistory.includes('POST /oauth2/token'), `expiring session did not request a refreshed token (${fetchHistory.join(', ')})`);
      assert(localStorage.getItem('id_token') === '__JWT__', 'refreshed identity token was not persisted');
      assert(localStorage.getItem('refresh_token') === 'refresh-capability', 'refresh capability changed during token refresh');
      assert(window.__shellAuthenticated === true, 'shell did not receive refreshed authenticated state');
      assert(document.querySelector('#status').textContent.startsWith('Authenticated.'), 'refreshed session did not initialize authenticated status');
    } else if (scenario === 'auth-retry') {
      assert(accountResourceRequests === 2, `authenticated API request was not retried exactly once (${accountResourceRequests})`);
      assert(fetchHistory.includes('POST /oauth2/token'), `401 response did not request a refreshed token (${fetchHistory.join(', ')})`);
      assert(localStorage.getItem('id_token') === '__JWT__', '401 retry did not persist the refreshed identity token');
      assert(window.__shellAuthenticated === true, 'successful 401 retry changed authenticated shell state');
      assert(document.querySelectorAll('#rasterPalette .color-card').length === palette.length, 'successful 401 retry did not finish loading account resources');
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
    } else if (scenario === 'preview') {
      const canvas = document.querySelector('#quantPreviewCanvas');
      const usage = [...document.querySelectorAll('#quantPreviewCounts .quant-preview-usage small')]
        .map(item => Number(item.textContent.split(' ')[0].replaceAll(',', '')));
      assert(document.querySelector('#artworkCropPanel').hidden === false, `artwork crop panel did not initialize (${document.querySelector('#cropStatus').textContent})`);
      assert(document.querySelector('#cropStatus').textContent.startsWith('Original artwork'), `artwork crop status did not report source dimensions (${document.querySelector('#cropStatus').textContent})`);
      assert(canvas.width === 4 && canvas.height === 4, `quantized preview dimensions changed: ${canvas.width} x ${canvas.height}`);
      assert(usage.length === palette.length, `quantized preview rendered ${usage.length} swatch counts instead of ${palette.length}`);
      assert(usage.reduce((sum, count) => sum + count, 0) === 16, `quantized preview counted ${usage.reduce((sum, count) => sum + count, 0)} pixels instead of 16`);
      assert(document.querySelector('#quantPreviewOutput').hidden === true, 'changed preview settings did not hide the stale preview');
      assert(document.querySelector('#quantPreviewStatus').textContent === 'Preview settings changed. Generate it again to use the currently enabled swatches.', `stale preview status changed (${document.querySelector('#quantPreviewStatus').textContent})`);
      assert(document.querySelector('#generateQuantPreview').disabled === false, 'preview button remained disabled');
    } else if (scenario === 'image-style-matching') {
      const controls = Object.fromEntries([...document.querySelectorAll('#filterControls [data-parameter]')].map(input => [input.dataset.parameter, input]));
      const usage = [...document.querySelectorAll('#quantPreviewCounts .quant-preview-usage small')]
        .map(item => Number(item.textContent.split(' ')[0].replaceAll(',', '')));
      assert(document.querySelector('#imagePreset').value === 'abstract_optical_color_mix', `restored Image Style changed (${document.querySelector('#imagePreset').value})`);
      assert(document.querySelector('#filterDescription').textContent.startsWith('Keeps ordinary continuous vector geometry'), 'Image Style description changed');
      assert(controls.mixing_model?.value === 'hsv', `restored mixing model changed (${controls.mixing_model?.value})`);
      assert(controls.keep_available_colors_as_vectors?.checked === false && controls.square_dots?.checked === true, 'restored Image Style toggles changed');
      assert(controls.dot_pitch_mm?.value === '0.7' && controls.mix_cell_dots?.value === '6', 'restored Image Style numeric controls changed');
      assert(document.querySelector('#colorMatchingMode').value === 'custom' && document.querySelector('#colorMatchingCustom').hidden === false, 'custom color matching was not restored');
      assert(document.querySelector('#matchingHue').value === '7' && document.querySelector('#matchingSaturation').value === '2' && document.querySelector('#matchingLightness').value === '5', 'restored color matching weights changed');
      assert(document.querySelector('#matchingHueNumber').value === '7' && document.querySelector('#matchingSaturationNumber').value === '2' && document.querySelector('#matchingLightnessNumber').value === '5', 'restored color matching number controls changed');
      assert(document.querySelector('#quantPreviewCanvas').width === 4 && document.querySelector('#quantPreviewCanvas').height === 4, 'Image Style quantized preview dimensions changed');
      assert(usage.reduce((sum, count) => sum + count, 0) === 16, `Image Style quantized preview counted ${usage.reduce((sum, count) => sum + count, 0)} pixels instead of 16`);
    } else if (scenario === 'panel-tiling') {
      const panel = submittedPayload?.panel_tiling;
      assert(panel?.enabled === true, 'panel tiling was not enabled in the submission payload');
      assert(panel?.tile_width_mm === 50 && panel?.tile_height_mm === 40, 'panel dimensions changed in the submission payload');
      assert(panel?.columns === 3 && panel?.rows === 2, 'auto-matched panel rows or columns changed in the submission payload');
      assert(panel?.gap_x_mm === 2 && panel?.gap_y_mm === 1, 'panel gaps changed in the submission payload');
      assert(panel?.fit_mode === 'fit' && panel?.padding_mode === 'swatch', 'panel fit or padding mode changed');
      assert(panel?.padding_swatch_hex === '#808080', 'panel padding swatch changed');
      assert(panel?.border_mode === 'panel' && panel?.border_swatch_hex === '#000000' && panel?.border_width_mm === 1.5, `panel border settings changed (${JSON.stringify(panel)})`);
      assert(document.querySelector('#panelTilingDetails').hidden === false, 'enabled panel controls remained hidden');
      assert(document.querySelector('#width').disabled && document.querySelector('#height').disabled, 'derived processing dimensions remained editable');
      assert(document.querySelector('#width').value === '1232' && document.querySelector('#height').value === '648', `derived processing dimensions changed: ${document.querySelector('#width').value} x ${document.querySelector('#height').value}`);
      assert(document.querySelector('#tileAutoAspectStatus').textContent.startsWith('Matched 4 × 2 artwork with 3 columns × 2 rows'), `auto-match status changed (${document.querySelector('#tileAutoAspectStatus').textContent})`);
      assert(document.querySelector('#panelLayoutPreview').width > 0 && document.querySelector('#panelLayoutPreview').height > 0, 'panel layout preview was not drawn');
      assert(document.querySelector('#panelLayoutPreviewStatus').textContent.startsWith('Fit preserves the whole image'), `panel preview status changed (${document.querySelector('#panelLayoutPreviewStatus').textContent})`);
      assert(document.querySelector('#status').textContent.startsWith('COMPLETED'), 'panel submission did not complete');
    } else if (scenario === 'palette-resources') {
      const cards = [...document.querySelectorAll('#rasterPalette .color-card')];
      const black = document.querySelector('#rasterPalette .color-card[data-hex="#000000"]');
      const gray = document.querySelector('#rasterPalette .color-card[data-hex="#808080"]');
      const white = document.querySelector('#rasterPalette .color-card[data-hex="#FFFFFF"]');
      assert(document.querySelector('#materialChoice').value === 'library:library-1', 'saved material library was not restored');
      assert(document.querySelector('#materialName').value === 'Maple', 'saved library material was not restored');
      assert(document.querySelector('#pixel').value === '0.09', `saved pixel size was not restored (${document.querySelector('#pixel').value})`);
      assert(document.querySelector('#width').value === '321' && document.querySelector('#height').value === '123', `saved processing dimensions were not restored (${document.querySelector('#width').value} x ${document.querySelector('#height').value})`);
      assert(document.querySelector('#whiteIs').value === 'unengraved', `saved White treatment was not restored (${document.querySelector('#whiteIs').value})`);
      assert(document.querySelector('#rasterHoloCutMode').value === 'line', `saved cut mode was not restored (${document.querySelector('#rasterHoloCutMode').value})`);
      assert(document.querySelector('#rasterHoloBlack').checked === false, 'saved preserved-Black choice was not cleared while unavailable');
      assert(document.querySelector('#selectedMaterialName').textContent === 'Walnut', 'selected library material summary changed');
      assert(cards.length === palette.length, `material library rendered ${cards.length} swatches instead of ${palette.length}`);
      assert(black?.querySelector('.color-name')?.textContent === 'Char', 'explicit Black assignment was not rendered');
      assert(white?.querySelector('.color-name')?.textContent === 'Bright', 'explicit White assignment was not rendered');
      assert(gray?.querySelector('button')?.disabled === true, 'unassigned library swatch became available');
      assert(preferencePayload?.selected_color_hexes?.join('|') === '#FFFFFF|#000000', `changed swatch selection was not saved (${JSON.stringify(preferencePayload)})`);
      assert(preferencePayload?.material_library_color_assignments?.['library-1']?.['#000000'] === 'Char', 'explicit library assignments changed while saving');
    } else if (scenario === 'material-input') {
      assert(window.__materialLibraryReady === true, 'uploaded CLB material names were not discovered');
      assert(window.__materialProfileReady === true, 'uploaded Fauxlographic palette was not accepted');
      assert(document.querySelector('#materialChoice').value === 'holographic-upload', 'Fauxlographic upload choice changed');
      assert(document.querySelector('#materialFile').accept === '.json,application/json', 'Fauxlographic upload file types changed');
      assert(document.querySelectorAll('#rasterPalette .color-card').length === 1, 'uploaded Fauxlographic swatches were not rendered');
      assert(document.querySelector('#status').textContent.startsWith('Loaded 1 fauxlographic swatches from characterization-palette.json.'), `uploaded Fauxlographic status changed (${document.querySelector('#status').textContent})`);
      assert(document.querySelector('#status').textContent.includes('Preserved Black was left unchecked'), 'unreadable preserved Black was not safely ignored');
    } else if (scenario === 'shape-assets') {
      const rawParameters = submittedPayload?.geometry_style_parameters || {};
      const parameters = typeof rawParameters === 'string' ? JSON.parse(rawParameters) : rawParameters;
      assert(window.__shapeRasterReady === true, 'custom raster glyph did not normalize and render before SVG replacement');
      assert(window.__shapeUnsafeRejected === true, 'custom SVG sanitization did not reject executable content before accepting the safe SVG');
      assert(submittedPayload?.geometry_style === 'glyphs', `custom shape submission geometry changed (${submittedPayload?.geometry_style})`);
      assert(parameters.glyph_shape === 'custom', `custom glyph selection changed (${JSON.stringify(parameters)})`);
      assert(parameters.custom_glyph_svg?.name === 'characterization-shape.svg', `custom SVG name changed (${JSON.stringify(parameters)})`);
      assert(parameters.custom_glyph_svg?.svg?.includes('<path'), `custom SVG path was not preserved (${JSON.stringify(parameters)})`);
      assert(!parameters.custom_glyph_svg?.svg?.includes('<script'), 'custom SVG sanitization retained executable content');
      assert(parameters.custom_glyph_mask === undefined, 'replaced raster glyph remained in the payload');
      assert(document.querySelector('#routedGlyphControls .custom-shape-status')?.textContent === 'Custom SVG ready: characterization-shape.svg.', `custom SVG status changed (${document.querySelector('#routedGlyphControls .custom-shape-status')?.textContent})`);
      assert(document.querySelector('#routedGlyphControls .custom-shape-preview')?.width === 96 && document.querySelector('#routedGlyphControls .custom-shape-preview')?.height === 96, 'custom shape preview dimensions changed');
    } else if (scenario === 'geometry-routing') {
      const rawParameters = submittedPayload?.geometry_style_parameters || {};
      const parameters = typeof rawParameters === 'string' ? JSON.parse(rawParameters) : rawParameters;
      assert(window.__geometryBulkApplied === true, 'bulk geometry routing did not update both selected swatches');
      assert(window.__geometrySelectionControlsApplied === true, 'route-by-swatch selection controls did not select and deselect all editable swatches');
      assert(window.__geometryCompatibilityApplied === true, 'Invert Fill did not disable and clear Black Only');
      assert(submittedPayload?.geometry_style === 'by_swatch', `routed geometry style changed (${submittedPayload?.geometry_style})`);
      assert(JSON.stringify(parameters.assignments) === JSON.stringify({'#000000': 'vectors', '#808080': 'glyphs', '#FFFFFF': 'halftone_newsprint'}), `routed swatch assignments changed (${JSON.stringify(parameters.assignments)})`);
      assert(parameters.glyphs?.glyph_shape === 'diamond' && parameters.glyphs?.cell_size_mm === 0.75, `routed Glyph controls changed (${JSON.stringify(parameters.glyphs)})`);
      assert(parameters.glyphs?.invert_fill === 1 && parameters.glyphs?.black_only === 0, `routed Glyph compatibility values changed (${JSON.stringify(parameters.glyphs)})`);
      assert(parameters.halftone_newsprint?.dot_size_source === 'source_brightness' && parameters.halftone_newsprint?.square_dots === 1, `routed Halftone controls changed (${JSON.stringify(parameters.halftone_newsprint)})`);
      assert(parameters.halftone_newsprint?.cell_size_mm === 0.55 && parameters.krasnow_grating === undefined, `routed geometry payload included unexpected settings (${JSON.stringify(parameters)})`);
      assert(document.querySelector('#routedGlyphSettings').hidden === false && document.querySelector('#routedHalftoneSettings').hidden === false && document.querySelector('#routedKrasnowSettings').hidden === true, 'routed settings visibility changed');
    } else if (scenario === 'flow-painter') {
      const rawParameters = submittedPayload?.geometry_style_parameters || {};
      const parameters = typeof rawParameters === 'string' ? JSON.parse(rawParameters) : rawParameters;
      const flow = parameters.fauxlogram_flow;
      assert(window.__flowPainted === true, 'painted flow stroke was not created');
      assert(window.__flowMaskReady === true, 'flow mask was not normalized before submission');
      assert(window.__flowMaskMoved === true, 'flow mask move tool did not update its offset');
      assert(window.__fauxlogramDefaultsReset === true, 'Fauxlogram controls did not reset to their full-range defaults');
      assert(submittedPayload?.geometry_style === 'krasnow_grating', `flow submission geometry changed (${submittedPayload?.geometry_style})`);
      assert(parameters.gradient_top === 0 && parameters.gradient_bottom === 255, `Fauxlogram gradient defaults changed (${parameters.gradient_top}, ${parameters.gradient_bottom})`);
      assert(parameters.angle_min === -180 && parameters.angle_max === 180, `Fauxlogram angle defaults changed (${parameters.angle_min}, ${parameters.angle_max})`);
      assert(flow?.enabled === true, `fauxlogram flow was not enabled (${JSON.stringify(flow)})`);
      assert(flow?.regions?.length === 2 && flow?.strokes?.length === 1, `flow regions or strokes changed (${JSON.stringify(flow)})`);
      assert(flow?.regions?.[0]?.scope === 'each_shape' && flow?.regions?.[0]?.guide_type === 'radial', `painted region scope or guide changed (${JSON.stringify(flow?.regions?.[0])})`);
      assert(flow?.regions?.[0]?.orientation === 'perpendicular' && flow?.regions?.[0]?.gradient_start === 200 && flow?.regions?.[0]?.gradient_end === 40, `painted region gradient changed (${JSON.stringify(flow?.regions?.[0])})`);
      assert(flow?.regions?.[0]?.curve === 1.5 && flow?.regions?.[0]?.fixed_angle === 15 && flow?.regions?.[0]?.angle_offset === -20 && flow?.regions?.[0]?.reverse === true, `painted region advanced controls changed (${JSON.stringify(flow?.regions?.[0])})`);
      assert(flow?.strokes?.[0]?.erase === false && flow?.strokes?.[0]?.width === 0.2 && flow?.strokes?.[0]?.points?.length === 2, `painted stroke changed (${JSON.stringify(flow?.strokes?.[0])})`);
      assert(flow?.regions?.[1]?.region_type === 'image_mask' && flow?.regions?.[1]?.mask_name === 'characterization.png', `image-mask region changed (${JSON.stringify(flow?.regions?.[1])})`);
      assert(flow?.regions?.[1]?.mask_mode === 'grayscale' && flow?.regions?.[1]?.mask_threshold === 0.25 && flow?.regions?.[1]?.mask_invert === true, `image-mask controls changed (${JSON.stringify(flow?.regions?.[1])})`);
      assert(flow?.regions?.[1]?.mask?.width === 96 && flow?.regions?.[1]?.mask?.height === 96 && typeof flow?.regions?.[1]?.mask?.data === 'string' && typeof flow?.regions?.[1]?.mask?.alpha === 'string', `normalized flow mask changed (${JSON.stringify(flow?.regions?.[1]?.mask)})`);
      assert(flow.regions[1].mask.data !== flow.regions[1].mask.alpha, 'transparent grayscale flow mask collapsed luminance into alpha');
      assert(flow?.regions?.[1]?.mask_offset?.some(value => Math.abs(value) > 0.01), `flow mask offset was not retained (${JSON.stringify(flow?.regions?.[1]?.mask_offset)})`);
      assert(document.querySelector('#flowCanvas').width > 0 && document.querySelector('#flowCanvas').height > 0, 'flow canvas was not initialized');
      assert(document.querySelector('#flowPainter').open === false, 'flow dialog remained open after accepting the flow');
      assert(document.querySelector('#flowPainterSummary').textContent.includes('2 flow regions') && document.querySelector('#flowPainterSummary').textContent.includes('1 painted shape') && document.querySelector('#flowPainterSummary').textContent.includes('1 image mask'), `flow summary changed (${document.querySelector('#flowPainterSummary').textContent})`);
    } else if (scenario === 'submission-error') {
      assert(submissionCount === 1, `failed submission ran ${submissionCount} times`);
      assert(document.querySelector('#status').textContent === 'ERROR: Submission characterization failure', 'submission error was not shown');
      assert(document.querySelector('#uploadProgressStatus').textContent.includes('Submission characterization failure'), 'submission progress did not expose the failure');
      assert(document.querySelector('#activity').classList.contains('hidden'), 'activity indicator remained visible after submission failure');
      assert(document.querySelector('#submit').disabled === false, 'Rasterizer submit remained disabled after submission failure');
    } else if (scenario === 'polling') {
      assert(pollIndex === 6, `polling job used ${pollIndex} requests instead of 6 (${fetchHistory.join(', ')})`);
      assert(statusHistory.some(value => value.startsWith('PENDING')), 'pending polling state was not shown');
      assert(statusHistory.some(value => value.startsWith('PROCESSING')), 'processing polling state was not shown');
      assert(document.querySelector('#status').textContent.startsWith('COMPLETED'), 'polling job did not reach completed state');
      assert(document.querySelector('#status').textContent.includes('queued\nworker started\ndone'), 'late terminal logs were not refreshed after completion');
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

  let deadline = 0;
  let submissionReadinessObserver = null;
  let applicationCheckQueued = false;
  const queueApplicationCheck = () => {
    if (applicationCheckQueued) return;
    applicationCheckQueued = true;
    queueMicrotask(() => {
      applicationCheckQueued = false;
      waitForApplication();
    });
  };
  const status = document.querySelector('#status');
  if (status) new MutationObserver(() => statusHistory.push(status.textContent)).observe(status, {childList: true, characterData: true, subtree: true});
  const artworkFile = () => new File([Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zy3sAAAAASUVORK5CYII='), character => character.charCodeAt(0))], 'characterization.png', {type: 'image/png'});
  const attachArtwork = selector => {
    const transfer = new DataTransfer();
    transfer.items.add(artworkFile());
    const artwork = document.querySelector(selector);
    artwork.files = transfer.files;
    artwork.dispatchEvent(new Event('change', {bubbles: true}));
  };
  const attachFile = (selector, file) => {
    const transfer = new DataTransfer();
    transfer.items.add(file);
    const input = document.querySelector(selector);
    input.files = transfer.files;
    input.dispatchEvent(new Event('change', {bubbles: true}));
  };
  const beginMultistageSubmission = form => {
    // Shape normalization and flow-mask preparation are asynchronous setup
    // phases. Do not mark submission started until requestSubmit actually
    // dispatches the submit event; browser constraint validation can still
    // reject a request after the preceding readiness checks.
    if (!document.querySelector('#artwork').files.length || !form.checkValidity()) return false;
    let dispatched = false;
    const markDispatched = () => {
      dispatched = true;
      window.__submissionStarted = true;
    };
    form.addEventListener('submit', markDispatched, {once: true});
    form.requestSubmit();
    if (!dispatched) form.removeEventListener('submit', markDispatched);
    // Shape assets advance from observable DOM and submission state changes.
    // Keep that scenario event-driven after dispatch too: a virtual-time
    // deadline can outrun async image/SVG normalization under CI load.
    else if (scenario !== 'shape-assets') deadline = Date.now() + 20000;
    return dispatched;
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
    const form = document.querySelector('#job');
    if (window.__submissionStarted || typeof form?.onsubmit !== 'function' || document.querySelectorAll('#rasterPalette .color-card').length !== palette.length) return;
    window.__submissionStarted = true;
    const choice = document.querySelector('#materialChoice');
    choice.value = 'svg';
    choice.dispatchEvent(new Event('change', {bubbles: true}));
    attachArtwork('#artwork');
    form.requestSubmit();
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
  const startPreviewCharacterization = () => {
    if (window.__previewStarted || document.querySelectorAll('#rasterPalette .color-card').length !== palette.length) return;
    window.__previewStarted = true;
    const choice = document.querySelector('#materialChoice');
    choice.value = 'svg';
    choice.dispatchEvent(new Event('change', {bubbles: true}));
    document.querySelector('#width').value = '4';
    document.querySelector('#height').value = '0';
    attachArtwork('#artwork');
  };
  const startImageStyleMatchingCharacterization = () => {
    if (window.__imageStyleStarted || document.querySelector('#imagePreset').value !== 'abstract_optical_color_mix') return;
    window.__imageStyleStarted = true;
    document.querySelector('#width').value = '4';
    document.querySelector('#height').value = '0';
    attachArtwork('#artwork');
  };
  const startPanelTilingCharacterization = () => {
    const form = document.querySelector('#job');
    if (window.__submissionStarted || typeof form?.onsubmit !== 'function' || document.querySelectorAll('#rasterPalette .color-card').length !== palette.length) return;
    if (!window.__panelConfigured) {
      window.__panelConfigured = true;
      const choice = document.querySelector('#materialChoice');
      choice.value = 'svg';
      choice.dispatchEvent(new Event('change', {bubbles: true}));
      document.querySelector('#pixel').value = '0.125';
      attachArtwork('#artwork');
      document.querySelector('#panelTilingEnabled').checked = true;
      for (const [id, value] of Object.entries({tileWidth: '50', tileHeight: '40', tileColumns: '2', tileRows: '3', tileGapX: '2', tileGapY: '1', tileFitMode: 'fit', tilePaddingMode: 'swatch', tileBorderMode: 'panel', tileBorderWidth: '1.5'})) {
        document.querySelector(`#${id}`).value = value;
      }
      document.querySelector('#panelTilingEnabled').dispatchEvent(new Event('change', {bubbles: true}));
      document.querySelector('#tileAutoAspect').click();
      return;
    }
    if (!document.querySelector('#tileAutoAspectStatus').textContent.startsWith('Matched')) return;
    document.querySelector('#tilePaddingSwatch').value = '#808080';
    document.querySelector('#tileBorderSwatch').value = '#000000';
    document.querySelector('#panelTilingControls').dispatchEvent(new Event('change', {bubbles: true}));
    window.__submissionStarted = true;
    form.requestSubmit();
  };
  const startPaletteResourcesCharacterization = () => {
    if (window.__paletteResourcesStarted || document.querySelector('#materialChoice').value !== 'library:library-1') return;
    const black = document.querySelector('#rasterPalette .color-card[data-hex="#000000"] button');
    if (!black) return;
    const blackCard = black.closest('.color-card');
    const whiteCard = document.querySelector('#rasterPalette .color-card[data-hex="#FFFFFF"]');
    assert(blackCard?.classList.contains('off') && !whiteCard?.classList.contains('off'), 'saved enabled swatches were not restored');
    window.__paletteResourcesStarted = true;
    black.click();
  };
  const startMaterialInputCharacterization = () => {
    if (window.__materialProfileReady) return;
    const choice = document.querySelector('#materialChoice');
    if (!window.__materialInputStarted) {
      if (!choice.querySelector('option[value="holographic-upload"]')) return;
      window.__materialInputStarted = true;
      choice.value = '';
      choice.dispatchEvent(new Event('change', {bubbles: true}));
      attachFile('#materialFile', new File([
        '<LightBurnLibrary><Material name="Birch"><Entry name="Cut"/></Material><Material name="Walnut"><Entry name="Fill"/></Material></LightBurnLibrary>'
      ], 'characterization.clb', {type: 'application/xml'}));
      return;
    }
    if (!window.__materialLibraryReady) {
      if (!document.querySelector('#status').textContent.startsWith('Loaded 2 materials from characterization.clb.')) return;
      const names = [...document.querySelector('#materialName').options].map(option => option.value).filter(Boolean);
      window.__materialLibraryReady = names.join('|') === 'Birch|Walnut' && document.querySelector('#materialName').value === 'Birch';
      choice.value = 'holographic-upload';
      choice.dispatchEvent(new Event('change', {bubbles: true}));
      attachFile('#materialFile', new File([JSON.stringify({
        kind: 'holographic_calibration_profile',
        profile_name: 'Characterization Palette',
        black_setting: {laser_settings: {type: '', settings: {}}},
        recipes: [{name: 'Copper', observed_hex: '#A06030', angle_degrees: 25, interval_mm: .05, laser_settings: {type: 'Cut', settings: {speed: 100}}}]
      })], 'characterization-palette.json', {type: 'application/json'}));
      return;
    }
    if (!document.querySelector('#status').textContent.startsWith('Loaded 1 fauxlographic swatches from characterization-palette.json.')) return;
    window.__materialProfileReady = true;
  };
  const startShapeAssetsCharacterization = () => {
    const form = document.querySelector('#job');
    if (window.__submissionStarted || typeof form?.onsubmit !== 'function' || document.querySelectorAll('#rasterPalette .color-card').length !== palette.length) return false;
    if (!window.__shapeConfigured) {
      window.__shapeConfigured = true;
      const choice = document.querySelector('#materialChoice');
      choice.value = 'svg';
      choice.dispatchEvent(new Event('change', {bubbles: true}));
      attachArtwork('#artwork');
      return true;
    }
    if (document.querySelector('#materialChoice').value !== 'svg') return false;
    const geometryStyle = document.querySelector('#geometryStyle');
    if (window.__shapeGeometrySelected && geometryStyle?.value !== 'glyphs') {
      window.__shapeGeometrySelected = false;
      return true;
    }
    if (!window.__shapeGeometrySelected) {
      window.__shapeGeometrySelected = true;
      geometryStyle.value = 'glyphs';
      geometryStyle.dispatchEvent(new Event('change', {bubbles: true}));
      return true;
    }
    const glyphSelect = document.querySelector('#routedGlyphControls [data-geometry-parameter="glyph_shape"]');
    const fileInput = document.querySelector('#routedGlyphControls [data-custom-glyph-file]');
    if (!glyphSelect || !fileInput) return false;
    if (!window.__shapeRasterAttached) {
      window.__shapeRasterAttached = true;
      glyphSelect.value = 'custom';
      glyphSelect.dispatchEvent(new Event('change', {bubbles: true}));
      attachFile('#routedGlyphControls [data-custom-glyph-file]', artworkFile());
      return true;
    }
    const status = document.querySelector('#routedGlyphControls .custom-shape-status');
    if (!window.__shapeUnsafeAttached) {
      if (!status?.textContent.startsWith('Custom image ready')) return false;
      window.__shapeRasterReady = true;
      window.__shapeUnsafeAttached = true;
      attachFile('#routedGlyphControls [data-custom-glyph-file]', new File([
        '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script><path d="M0 0H10V10Z"/></svg>'
      ], 'unsafe-shape.svg', {type: 'image/svg+xml'}));
      return true;
    }
    if (!window.__shapeSvgAttached) {
      if (!status?.textContent.startsWith('SVG element <script> is not supported.')) return false;
      window.__shapeUnsafeRejected = true;
      window.__shapeSvgAttached = true;
      attachFile('#routedGlyphControls [data-custom-glyph-file]', new File([
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path d="M50 5L95 95H5Z"/></svg>'
      ], 'characterization-shape.svg', {type: 'image/svg+xml'}));
      return true;
    }
    if (!status?.textContent.startsWith('Custom SVG ready') || geometryStyle.value !== 'glyphs' || glyphSelect.value !== 'custom') return false;
    return beginMultistageSubmission(form);
  };
  const startGeometryRoutingCharacterization = () => {
    const form = document.querySelector('#job');
    if (window.__submissionStarted || typeof form?.onsubmit !== 'function' || document.querySelectorAll('#rasterPalette .color-card').length !== palette.length) return;
    if (!window.__geometryConfigured) {
      window.__geometryConfigured = true;
      const choice = document.querySelector('#materialChoice');
      choice.value = 'svg';
      choice.dispatchEvent(new Event('change', {bubbles: true}));
      attachArtwork('#artwork');
      return;
    }
    if (!window.__geometryStyleSelected) {
      window.__geometryStyleSelected = true;
      document.querySelector('#geometryStyle').value = 'by_swatch';
      document.querySelector('#geometryStyle').dispatchEvent(new Event('change', {bubbles: true}));
      return;
    }
    const routes = [...document.querySelectorAll('#geometryRoutingGrid .geometry-route-card')];
    if (routes.length !== palette.length) return;
    const gray = routes.find(card => card.querySelector('[data-route-style]')?.dataset.hex === '#808080');
    const white = routes.find(card => card.querySelector('[data-route-style]')?.dataset.hex === '#FFFFFF');
    if (!window.__geometryBulkApplied) {
      const black = routes.find(card => card.querySelector('[data-route-style]')?.dataset.hex === '#000000');
      const selectAll = document.querySelector('[data-route-selection="all"]');
      const deselectAll = document.querySelector('[data-route-selection="none"]');
      selectAll.click();
      const editableSelected = gray.querySelector('[data-route-selected]').checked && white.querySelector('[data-route-selected]').checked;
      const fixedBlackUnaffected = black.querySelector('[data-route-selected]').disabled && !black.querySelector('[data-route-selected]').checked;
      deselectAll.click();
      const editableDeselected = !gray.querySelector('[data-route-selected]').checked && !white.querySelector('[data-route-selected]').checked;
      selectAll.click();
      window.__geometrySelectionControlsApplied = editableSelected && fixedBlackUnaffected && editableDeselected && selectAll.textContent === 'Select all' && deselectAll.textContent === 'Deselect all';
      document.querySelector('[data-route-bulk="glyphs"]').click();
      window.__geometryBulkApplied = gray.querySelector('[data-route-style]').value === 'glyphs' && white.querySelector('[data-route-style]').value === 'glyphs';
      white.querySelector('[data-route-style]').value = 'halftone_newsprint';
      white.querySelector('[data-route-style]').dispatchEvent(new Event('change', {bubbles: true}));
      return;
    }
    const glyphBox = document.querySelector('#routedGlyphControls');
    const halftoneBox = document.querySelector('#routedHalftoneControls');
    if (!glyphBox.childElementCount || !halftoneBox.childElementCount) return;
    const invertFill = glyphBox.querySelector('[data-geometry-parameter="invert_fill"]');
    const blackOnly = glyphBox.querySelector('[data-geometry-parameter="black_only"]');
    blackOnly.checked = true;
    invertFill.checked = true;
    invertFill.dispatchEvent(new Event('change', {bubbles: true}));
    window.__geometryCompatibilityApplied = !blackOnly.checked && blackOnly.disabled && blackOnly.closest('label').classList.contains('disabled');
    const glyphSize = glyphBox.querySelector('[data-geometry-parameter="cell_size_mm"]');
    glyphSize.value = '0.75';
    glyphSize.dispatchEvent(new Event('input', {bubbles: true}));
    const squareDots = halftoneBox.querySelector('[data-geometry-parameter="square_dots"]');
    squareDots.checked = true;
    squareDots.dispatchEvent(new Event('change', {bubbles: true}));
    const dotSize = halftoneBox.querySelector('[data-geometry-parameter="cell_size_mm"]');
    dotSize.value = '0.55';
    dotSize.dispatchEvent(new Event('input', {bubbles: true}));
    window.__submissionStarted = true;
    form.requestSubmit();
  };
  const startFlowPainterCharacterization = () => {
    const form = document.querySelector('#job');
    if (window.__submissionStarted || typeof form?.onsubmit !== 'function' || document.querySelectorAll('#rasterPalette .color-card').length !== palette.length) return;
    const materialChoice = document.querySelector('#materialChoice');
    const geometryStyle = document.querySelector('#geometryStyle');
    if (window.__flowReadyToSubmit) {
      const summary = document.querySelector('#flowPainterSummary').textContent;
      if (materialChoice.value !== 'svg') return;
      if (geometryStyle.value !== 'krasnow_grating') {
        geometryStyle.value = 'krasnow_grating';
        geometryStyle.dispatchEvent(new Event('change', {bubbles: true}));
        return;
      }
      if (document.querySelector('#flowPainter').open || !summary.includes('2 flow regions') || !summary.includes('1 painted shape') || !summary.includes('1 image mask')) return;
      beginMultistageSubmission(form);
      return;
    }
    if (!window.__flowConfigured) {
      window.__flowConfigured = true;
      materialChoice.value = 'svg';
      materialChoice.dispatchEvent(new Event('change', {bubbles: true}));
      attachArtwork('#artwork');
      return;
    }
    if (materialChoice.value !== 'svg') return;
    if (window.__flowGeometrySelected && geometryStyle.value !== 'krasnow_grating') {
      window.__flowGeometrySelected = false;
      return;
    }
    if (!window.__flowGeometrySelected) {
      window.__flowGeometrySelected = true;
      geometryStyle.value = 'krasnow_grating';
      geometryStyle.dispatchEvent(new Event('change', {bubbles: true}));
      return;
    }
    const dialog = document.querySelector('#flowPainter');
    const canvas = document.querySelector('#flowCanvas');
    if (!window.__flowOpened) {
      if (document.querySelector('#routedKrasnowSettings').hidden) return;
      if (!window.__fauxlogramDefaultsReset) {
        const controls = document.querySelector('#routedKrasnowControls');
        const parameters = Object.fromEntries(['gradient_top', 'gradient_bottom', 'angle_min', 'angle_max'].map(name => [name, controls.querySelector(`[data-geometry-parameter="${name}"]`)]));
        const initialDefaults = parameters.gradient_top.value === '0' && parameters.gradient_bottom.value === '255' && parameters.angle_min.value === '-180' && parameters.angle_max.value === '180';
        const angleRangesMatch = parameters.angle_min.min === '-180' && parameters.angle_min.max === '180' && parameters.angle_max.min === '-180' && parameters.angle_max.max === '180';
        for (const input of Object.values(parameters)) input.value = '12';
        document.querySelector('#resetGeometryStyle').click();
        const resetControls = document.querySelector('#routedKrasnowControls');
        window.__fauxlogramDefaultsReset = initialDefaults && angleRangesMatch && resetControls.querySelector('[data-geometry-parameter="gradient_top"]').value === '0' && resetControls.querySelector('[data-geometry-parameter="gradient_bottom"]').value === '255' && resetControls.querySelector('[data-geometry-parameter="angle_min"]').value === '-180' && resetControls.querySelector('[data-geometry-parameter="angle_max"]').value === '180';
        return;
      }
      window.__flowOpened = true;
      document.querySelector('#openFlowPainter').click();
      return;
    }
    if (!dialog.open || canvas.width === 0 || canvas.height === 0) return;
    if (!window.__flowPainted) {
      for (const [id, value] of Object.entries({flowScope: 'each_shape', flowGuideType: 'radial', flowOrientation: 'perpendicular', flowGradientStart: '200', flowGradientEnd: '40', flowCurve: '1.5', flowFixedAngle: '15', flowAngleOffset: '-20'})) document.querySelector(`#${id}`).value = value;
      document.querySelector('#flowReverse').checked = true;
      document.querySelector('#flowBrush').value = '20';
      document.querySelector('#flowAngleOffset').dispatchEvent(new Event('input', {bubbles: true}));
      const rect = canvas.getBoundingClientRect();
      const first = {currentTarget: {setPointerCapture() {}}, pointerId: 1, clientX: rect.left + rect.width * 0.2, clientY: rect.top + rect.height * 0.3};
      const second = {currentTarget: canvas, pointerId: 1, clientX: rect.left + rect.width * 0.7, clientY: rect.top + rect.height * 0.65};
      canvas.onpointerdown(first);
      canvas.onpointermove(second);
      canvas.onpointerup(second);
      window.__flowPainted = true;
      document.querySelector('#flowAddMaskRegion').click();
      attachFile('#flowMaskFile', artworkFile());
      return;
    }
    if (!window.__flowMaskReady) {
      if (!document.querySelector('#flowMaskStatus').textContent.includes('is attached to this region')) return;
      window.__flowMaskReady = true;
      document.querySelector('#flowMaskMode').value = 'grayscale';
      document.querySelector('#flowMaskMode').dispatchEvent(new Event('change', {bubbles: true}));
      document.querySelector('#flowMaskThreshold').value = '0.25';
      document.querySelector('#flowMaskInvert').checked = true;
      document.querySelector('#flowMaskInvert').dispatchEvent(new Event('input', {bubbles: true}));
      document.querySelector('[data-flow-tool="move"]').click();
      const rect = canvas.getBoundingClientRect();
      const first = {currentTarget: {setPointerCapture() {}}, pointerId: 2, clientX: rect.left + rect.width * 0.3, clientY: rect.top + rect.height * 0.35};
      const second = {currentTarget: canvas, pointerId: 2, clientX: rect.left + rect.width * 0.48, clientY: rect.top + rect.height * 0.58};
      canvas.onpointerdown(first);
      canvas.onpointermove(second);
      canvas.onpointerup(second);
      window.__flowMaskMoved = true;
      document.querySelector('#flowDone').click();
      window.__flowReadyToSubmit = true;
      return;
    }
  };
  const waitForApplication = () => {
    const rasterizerForm = document.querySelector('#job');
    if (typeof rasterizerForm?.onsubmit !== 'function' || rasterizerForm.dataset.ready !== 'true') {
      setTimeout(waitForApplication, 25);
      return;
    }
    if (deadline === 0) deadline = scenario === 'shape-assets'
      ? Number.POSITIVE_INFINITY
      : Date.now() + (scenario === 'flow-painter' ? 50000 : scenario === 'polling' ? 30000 : 20000);
    if (scenario === 'guest-submit') startGuestSubmission();
    if (scenario === 'authenticated-submit' || scenario === 'submission-error') startAuthenticatedSubmission();
    if (scenario === 'holographic-submit') startHolographicSubmission();
    if (scenario === 'preview') startPreviewCharacterization();
    if (scenario === 'image-style-matching') startImageStyleMatchingCharacterization();
    if (scenario === 'panel-tiling') startPanelTilingCharacterization();
    if (scenario === 'palette-resources') startPaletteResourcesCharacterization();
    if (scenario === 'material-input') startMaterialInputCharacterization();
    const shapeAssetsAdvanced = scenario === 'shape-assets' && startShapeAssetsCharacterization();
    if (scenario === 'geometry-routing') startGeometryRoutingCharacterization();
    if (scenario === 'flow-painter') startFlowPainterCharacterization();
    if (scenario === 'submission-error' && !window.__submissionStarted) return;
    if (scenario !== 'shape-assets') submissionReadinessObserver?.disconnect();
    const ready = scenario === 'guest' || scenario === 'guest-stale-task-no-capability' || scenario === 'auth-refresh' || scenario === 'auth-retry'
      ? document.querySelectorAll('#rasterPalette .color-card').length === palette.length
      : scenario === 'guest-expired-task'
        ? document.querySelector('#status').textContent.startsWith('This guest job is no longer available.')
      : scenario === 'guest-resume'
        ? fetchHistory.filter(value => value === 'GET /api/guest/jobs/guest-resume-task').length === 4 && document.querySelectorAll('#outputs a').length === 1
      : scenario === 'guest-submit'
        ? submittedPayload !== null && document.querySelectorAll('#outputs a').length === 1
        : scenario === 'authenticated-submit'
          ? submittedPayload !== null && document.querySelectorAll('#outputs a').length === 1
        : scenario === 'holographic-submit'
          ? holographicPayload !== null && document.querySelectorAll('#outputs a').length === 1
        : scenario === 'submission-error'
          ? document.querySelector('#status').textContent.startsWith('ERROR:')
        : scenario === 'preview'
          ? document.querySelector('#cropStatus').textContent.startsWith('Original artwork')
        : scenario === 'image-style-matching'
          ? document.querySelector('#cropStatus').textContent.startsWith('Original artwork')
        : scenario === 'panel-tiling'
          ? submittedPayload !== null && document.querySelectorAll('#outputs a').length === 1 && document.querySelector('#panelLayoutPreview').width > 0
        : scenario === 'palette-resources'
          ? preferencePayload !== null
        : scenario === 'material-input'
          ? window.__materialProfileReady === true
        : scenario === 'shape-assets'
          ? submittedPayload !== null && document.querySelectorAll('#outputs a').length === 1
        : scenario === 'geometry-routing'
          ? submittedPayload !== null && document.querySelectorAll('#outputs a').length === 1
        : scenario === 'flow-painter'
          ? submittedPayload !== null && document.querySelectorAll('#outputs a').length === 1
        : scenario === 'polling'
          ? pollIndex === 6 && document.querySelectorAll('#outputs a').length === 1
          : scenario === 'failed'
            ? document.querySelector('#status').textContent.startsWith('FAILED')
            : document.querySelectorAll('#outputs a').length === 3;
    if (scenario === 'preview' && ready && !window.__previewGenerated) {
      window.__previewGenerated = true;
      document.querySelector('#generateQuantPreview').click();
      setTimeout(waitForApplication, 25);
      return;
    }
    if (scenario === 'image-style-matching' && ready && !window.__imageStylePreviewGenerated) {
      window.__imageStylePreviewGenerated = true;
      document.querySelector('#generateQuantPreview').click();
      setTimeout(waitForApplication, 25);
      return;
    }
    if (scenario === 'image-style-matching' && window.__imageStylePreviewGenerated && !document.querySelector('#quantPreviewStatus').textContent.startsWith('Preview ready')) {
      if (Date.now() >= deadline) finish();
      else setTimeout(waitForApplication, 25);
      return;
    }
    if (scenario === 'preview' && window.__previewGenerated && !window.__previewMadeStale) {
      if (!document.querySelector('#quantPreviewStatus').textContent.startsWith('Preview ready')) {
        if (Date.now() >= deadline) finish();
        else setTimeout(waitForApplication, 25);
        return;
      }
      window.__previewMadeStale = true;
      document.querySelector('#width').value = '8';
      document.querySelector('#width').dispatchEvent(new Event('input', {bubbles: true}));
      setTimeout(waitForApplication, 25);
      return;
    }
    if (ready || Date.now() >= deadline) finish();
    else if (scenario === 'shape-assets') {
      if (shapeAssetsAdvanced) queueApplicationCheck();
    }
    else setTimeout(waitForApplication, 25);
  };
  addEventListener('DOMContentLoaded', () => {
    if (scenario === 'submission-error') {
      submissionReadinessObserver = new MutationObserver(waitForApplication);
      submissionReadinessObserver.observe(document.querySelector('#rasterPalette'), {childList: true, subtree: true});
    }
    if (scenario === 'shape-assets') {
      submissionReadinessObserver = new MutationObserver(queueApplicationCheck);
      submissionReadinessObserver.observe(document.body, {
        attributes: true,
        attributeFilter: ['data-ready', 'hidden', 'open'],
        characterData: true,
        childList: true,
        subtree: true
      });
    }
    waitForApplication();
  }, {once: true});
})();
"""


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/rasterizer/submission-v1.js"):
            time.sleep(0.25)
        super().do_GET()

    def log_message(self, *_args):
        pass


class _CharacterizationServer(http.server.ThreadingHTTPServer):
    # Chromium requests the growing ES-module graph in parallel.  The
    # socketserver default backlog of five can intermittently drop one of
    # those requests under CI load, leaving the page only partly initialized.
    request_queue_size = 64


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
        index = re.sub(r'\s*<script src="/staging-shell\.js\?v=4" defer></script>', '', index)
        index = index.replace(
            '<script type="module" src="/rasterizer-v4.js"></script>',
            '<script src="/characterization-harness.js"></script>\n<script type="module" src="/rasterizer-v4.js"></script>',
        )
        index_path.write_text(index, encoding="utf-8")
        (cls.site / "characterization-harness.js").write_text(HARNESS.replace("__JWT__", _jwt()), encoding="utf-8")

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

    def _run_scenario(self, scenario, query=""):
        port = self.server.server_address[1]
        url = f"http://127.0.0.1:{port}/?scenario={scenario}{query}"
        completed = None
        match = None
        for _attempt in range(2):
            with tempfile.TemporaryDirectory(prefix="mopa-browser-profile-") as profile:
                completed = subprocess.run(
                    [
                        self.browser,
                        "--headless=new",
                        "--disable-gpu",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        f"--user-data-dir={profile}",
                        "--virtual-time-budget=90000",
                        "--dump-dom",
                        url,
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=105,
                    check=False,
                )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            match = re.search(r'<pre id="characterization-result">(.*?)</pre>', completed.stdout, re.DOTALL)
            if match is not None:
                break
        self.assertIsNotNone(match, f"Browser characterization did not finish.\n{completed.stderr}\n{completed.stdout[-2000:]}")
        result = json.loads(html.unescape(match.group(1)))
        self.assertEqual(result["scenario"], scenario)
        self.assertEqual(result["failures"], [])

    def test_guest_startup_and_palette_controls(self):
        self._run_scenario("guest")

    def test_guest_history_task_without_capability_returns_to_rasterizer(self):
        self._run_scenario("guest-stale-task-no-capability", "&task=stale-guest-task&keep=yes")

    def test_expired_guest_capability_returns_to_rasterizer(self):
        self._run_scenario("guest-expired-task", "&task=expired-guest-task&keep=yes")

    def test_valid_guest_capability_resumes_the_task(self):
        self._run_scenario("guest-resume", "&task=guest-resume-task")

    def test_expiring_authenticated_session_refreshes_before_loading_resources(self):
        self._run_scenario("auth-refresh")

    def test_authenticated_api_retries_once_after_refreshing_a_401(self):
        self._run_scenario("auth-retry")

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

    def test_authenticated_crop_initialization_quantized_preview_and_stale_state(self):
        self._run_scenario("preview")

    def test_authenticated_image_style_color_matching_restore_and_preview(self):
        self._run_scenario("image-style-matching")

    def test_authenticated_panel_tiling_preview_and_submission(self):
        self._run_scenario("panel-tiling")

    def test_authenticated_palette_resources_restore_and_save(self):
        self._run_scenario("palette-resources")

    def test_guest_material_library_and_fauxlographic_palette_inputs(self):
        self._run_scenario("material-input")

    def test_authenticated_custom_shape_normalization_preview_and_payload(self):
        self._run_scenario("shape-assets")

    def test_authenticated_geometry_routing_controls_and_payload(self):
        self._run_scenario("geometry-routing")

    def test_authenticated_fauxlogram_flow_painter_and_payload(self):
        self._run_scenario("flow-painter")

    def test_authenticated_job_polling_sequence_and_completion(self):
        self._run_scenario("polling", "&task=polling-task")

    def test_authenticated_failed_job_restores_submission_controls(self):
        self._run_scenario("failed", "&task=failed-task")


if __name__ == "__main__":
    unittest.main()
