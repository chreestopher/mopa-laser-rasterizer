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
  if (scenario === 'preview' || scenario === 'panel-tiling' || scenario === 'shape-assets') window.createImageBitmap = async () => {
    const canvas = document.createElement('canvas');
    canvas.width = scenario === 'panel-tiling' || scenario === 'shape-assets' ? 4 : 1;
    canvas.height = scenario === 'panel-tiling' || scenario === 'shape-assets' ? 2 : 1;
    const context = canvas.getContext('2d');
    context.fillStyle = '#000000';
    context.fillRect(0, 0, 1, 1);
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

  if (['resume', 'polling', 'failed', 'authenticated-submit', 'holographic-submit', 'submission-error', 'preview', 'panel-tiling', 'palette-resources', 'shape-assets', 'geometry-routing'].includes(scenario)) localStorage.setItem('id_token', '__JWT__');
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
      material_libraries: [{library_id: 'library-1', name: 'Characterization Library', material_name: 'Walnut', library_intent: 'color_palette', summary: {material_names: ['Walnut', 'Maple']}}],
      holographic_recipes: [{recipe_id: 'recipe-1', name: 'Characterization Fauxlographic Palette', metadata: {schema_version: 2, self_contained: true, swatch_preview: [{name: 'Copper', hex: '#B87333', angle_degrees: 30, interval_mm: 0.06}]}}],
      preferences: scenario === 'palette-resources' ? {
        selected_color_hexes: ['#FFFFFF'],
        material_library_color_assignments: {'library-1': {'#000000': 'Char', '#FFFFFF': 'Bright'}},
        last_rasterizer_form: {values: {material_choice: 'library:library-1', material_name: 'Maple'}}
      } : {}
    });
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
      assert(document.querySelector('#selectedMaterialName').textContent === 'Walnut', 'selected library material summary changed');
      assert(cards.length === palette.length, `material library rendered ${cards.length} swatches instead of ${palette.length}`);
      assert(black?.querySelector('.color-name')?.textContent === 'Char', 'explicit Black assignment was not rendered');
      assert(white?.querySelector('.color-name')?.textContent === 'Bright', 'explicit White assignment was not rendered');
      assert(gray?.querySelector('button')?.disabled === true, 'unassigned library swatch became available');
      assert(preferencePayload?.selected_color_hexes?.join('|') === '#FFFFFF|#000000', `changed swatch selection was not saved (${JSON.stringify(preferencePayload)})`);
      assert(preferencePayload?.material_library_color_assignments?.['library-1']?.['#000000'] === 'Char', 'explicit library assignments changed while saving');
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
      assert(window.__geometryCompatibilityApplied === true, 'Invert Fill did not disable and clear Black Only');
      assert(submittedPayload?.geometry_style === 'by_swatch', `routed geometry style changed (${submittedPayload?.geometry_style})`);
      assert(JSON.stringify(parameters.assignments) === JSON.stringify({'#000000': 'vectors', '#808080': 'glyphs', '#FFFFFF': 'halftone_newsprint'}), `routed swatch assignments changed (${JSON.stringify(parameters.assignments)})`);
      assert(parameters.glyphs?.glyph_shape === 'diamond' && parameters.glyphs?.cell_size_mm === 0.75, `routed Glyph controls changed (${JSON.stringify(parameters.glyphs)})`);
      assert(parameters.glyphs?.invert_fill === 1 && parameters.glyphs?.black_only === 0, `routed Glyph compatibility values changed (${JSON.stringify(parameters.glyphs)})`);
      assert(parameters.halftone_newsprint?.dot_size_source === 'source_brightness' && parameters.halftone_newsprint?.square_dots === 1, `routed Halftone controls changed (${JSON.stringify(parameters.halftone_newsprint)})`);
      assert(parameters.halftone_newsprint?.cell_size_mm === 0.55 && parameters.krasnow_grating === undefined, `routed geometry payload included unexpected settings (${JSON.stringify(parameters)})`);
      assert(document.querySelector('#routedGlyphSettings').hidden === false && document.querySelector('#routedHalftoneSettings').hidden === false && document.querySelector('#routedKrasnowSettings').hidden === true, 'routed settings visibility changed');
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
  const startShapeAssetsCharacterization = () => {
    const form = document.querySelector('#job');
    if (window.__submissionStarted || typeof form?.onsubmit !== 'function' || document.querySelectorAll('#rasterPalette .color-card').length !== palette.length) return;
    if (!window.__shapeConfigured) {
      window.__shapeConfigured = true;
      const choice = document.querySelector('#materialChoice');
      choice.value = 'svg';
      choice.dispatchEvent(new Event('change', {bubbles: true}));
      attachArtwork('#artwork');
      return;
    }
    if (document.querySelector('#materialChoice').value !== 'svg') return;
    if (!window.__shapeGeometrySelected) {
      window.__shapeGeometrySelected = true;
      document.querySelector('#geometryStyle').value = 'glyphs';
      document.querySelector('#geometryStyle').dispatchEvent(new Event('change', {bubbles: true}));
      return;
    }
    const glyphSelect = document.querySelector('#routedGlyphControls [data-geometry-parameter="glyph_shape"]');
    const fileInput = document.querySelector('#routedGlyphControls [data-custom-glyph-file]');
    if (!glyphSelect || !fileInput) return;
    if (!window.__shapeRasterAttached) {
      window.__shapeRasterAttached = true;
      glyphSelect.value = 'custom';
      glyphSelect.dispatchEvent(new Event('change', {bubbles: true}));
      attachFile('#routedGlyphControls [data-custom-glyph-file]', artworkFile());
      return;
    }
    const status = document.querySelector('#routedGlyphControls .custom-shape-status');
    if (!window.__shapeUnsafeAttached) {
      if (!status?.textContent.startsWith('Custom image ready')) return;
      window.__shapeRasterReady = true;
      window.__shapeUnsafeAttached = true;
      attachFile('#routedGlyphControls [data-custom-glyph-file]', new File([
        '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script><path d="M0 0H10V10Z"/></svg>'
      ], 'unsafe-shape.svg', {type: 'image/svg+xml'}));
      return;
    }
    if (!window.__shapeSvgAttached) {
      if (!status?.textContent.startsWith('SVG element <script> is not supported.')) return;
      window.__shapeUnsafeRejected = true;
      window.__shapeSvgAttached = true;
      attachFile('#routedGlyphControls [data-custom-glyph-file]', new File([
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path d="M50 5L95 95H5Z"/></svg>'
      ], 'characterization-shape.svg', {type: 'image/svg+xml'}));
      return;
    }
    if (!status?.textContent.startsWith('Custom SVG ready')) return;
    window.__submissionStarted = true;
    form.requestSubmit();
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
      gray.querySelector('[data-route-selected]').checked = true;
      white.querySelector('[data-route-selected]').checked = true;
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
  const waitForApplication = () => {
    const rasterizerForm = document.querySelector('#job');
    if (typeof rasterizerForm?.onsubmit !== 'function') {
      setTimeout(waitForApplication, 25);
      return;
    }
    if (deadline === 0) deadline = Date.now() + (scenario === 'polling' ? 30000 : 20000);
    if (scenario === 'guest-submit') startGuestSubmission();
    if (scenario === 'authenticated-submit' || scenario === 'submission-error') startAuthenticatedSubmission();
    if (scenario === 'holographic-submit') startHolographicSubmission();
    if (scenario === 'preview') startPreviewCharacterization();
    if (scenario === 'panel-tiling') startPanelTilingCharacterization();
    if (scenario === 'palette-resources') startPaletteResourcesCharacterization();
    if (scenario === 'shape-assets') startShapeAssetsCharacterization();
    if (scenario === 'geometry-routing') startGeometryRoutingCharacterization();
    if (scenario === 'submission-error' && !window.__submissionStarted) return;
    submissionReadinessObserver?.disconnect();
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
        : scenario === 'preview'
          ? document.querySelector('#cropStatus').textContent.startsWith('Original artwork')
        : scenario === 'panel-tiling'
          ? submittedPayload !== null && document.querySelectorAll('#outputs a').length === 1 && document.querySelector('#panelLayoutPreview').width > 0
        : scenario === 'palette-resources'
          ? preferencePayload !== null
        : scenario === 'shape-assets'
          ? submittedPayload !== null && document.querySelectorAll('#outputs a').length === 1
        : scenario === 'geometry-routing'
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
    else setTimeout(waitForApplication, 25);
  };
  addEventListener('DOMContentLoaded', () => {
    if (scenario === 'submission-error') {
      submissionReadinessObserver = new MutationObserver(waitForApplication);
      submissionReadinessObserver.observe(document.querySelector('#rasterPalette'), {childList: true, subtree: true});
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
                    "--virtual-time-budget=60000",
                    "--dump-dom",
                    url,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=75,
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

    def test_authenticated_crop_initialization_quantized_preview_and_stale_state(self):
        self._run_scenario("preview")

    def test_authenticated_panel_tiling_preview_and_submission(self):
        self._run_scenario("panel-tiling")

    def test_authenticated_palette_resources_restore_and_save(self):
        self._run_scenario("palette-resources")

    def test_authenticated_custom_shape_normalization_preview_and_payload(self):
        self._run_scenario("shape-assets")

    def test_authenticated_geometry_routing_controls_and_payload(self):
        self._run_scenario("geometry-routing")

    def test_authenticated_job_polling_sequence_and_completion(self):
        self._run_scenario("polling", "&task=polling-task")

    def test_authenticated_failed_job_restores_submission_controls(self):
        self._run_scenario("failed", "&task=failed-task")


if __name__ == "__main__":
    unittest.main()
