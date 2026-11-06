import assert from 'node:assert/strict';
import {readFile, mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
export async function paletteScenario({context, page, extensionId}) {
  const origin = 'https://serverless-staging.mopa-laser-rasterizer.com';
  let saves = 0, uploaded = '', mode = 'ok', resourceReads = 0;
  const writes = [];
  let appending = false, processing = false;
  const target = {library_id: 'existing', name: 'My new palette', library_intent: 'color_palette', summary: {entries: [{entry_id: 0, description: 'Keep me', type: 'Scan', hex: '#FF0000', settings: {speed: '50'}}]}};
  await context.route(`${origin}/**`, async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/config.json') return route.fulfill({json: {api_url: origin + '/api'}});
    if (path === '/api/account/resources') {resourceReads++; return route.fulfill({json: {material_libraries: [target], holographic_recipes: [], depth_palettes: [], palette: [{name: 'Blue', hex: '#0000FF'}, {name: 'Red', hex: '#FF0000'}], preferences: {processing_palette_role_assignments: {old: {materials: {Old: {Cut:'setting:legacy'}}}}, material_library_color_assignments: {existing: {'#FF0000': 'Keep me'}}}}});}
    if (path === '/api/account/preferences') {
      writes.push(path);
      if (mode === 'mapping-failure') return route.abort();
      if (processing) {
        assert.deepEqual(route.request().postDataJSON(), {processing_palette_role_assignments: {old: {materials: {Old: {Cut:'setting:legacy'}}}, saved: {materials: {'My processing palette': {Cut:'setting:one',Score:'setting:one',Photo:'',Fill:'',Shovel:'',Cleaning:'','3D-Slice':''}}}}});
        return route.fulfill({json:{preferences:route.request().postDataJSON()}});
      }
      assert.deepEqual(route.request().postDataJSON(), {material_library_color_assignments: appending ? {existing: {'#FF0000': 'Keep me', '#0000FF': '<Blue>'}} : {existing: {'#FF0000': 'Keep me'}, saved: {'#0000FF': '<Blue>'}}});
      return route.fulfill({json: {preferences: route.request().postDataJSON()}});
    }
    if (path === '/api/account/imports') {
      writes.push(path); const body = route.request().postDataJSON();
      assert.equal(body.target_library_id, appending ? 'existing' : undefined); assert.equal(body.library_intent, processing ? 'processing_palette' : 'color_palette'); assert.equal(body.name, processing ? 'My processing palette' : 'My new palette'); assert.equal(body.material_name, body.name);
      return route.fulfill({json: {import_id: 'test', upload_token: 'test-token', upload: {url: origin + '/upload', fields: {}, max_file_bytes: 4194304}}});
    }
    if (path === '/upload') {writes.push(path); uploaded = route.request().postDataBuffer().toString('utf8'); return route.fulfill({status: 204});}
    if (path === '/api/account/imports/test/finalize') {
      writes.push(path); saves++; if (mode === 'uncertain') return route.abort();
      return route.fulfill({json: {material_library: {library_id: appending ? 'existing' : 'saved', entries: processing ? [{description:'<Blue>',entry_ref:'setting:one',material:'My processing palette'}] : []}, import_adjustments: []}});
    }
    if (path === '/staging-shell.js') return route.fulfill({body: '', contentType: 'text/javascript'});
    try {return route.fulfill({body: await readFile(new URL('../serverless_web' + path, import.meta.url)), contentType: path.endsWith('.js') ? 'text/javascript' : path.endsWith('.css') ? 'text/css' : 'text/html'});}
    catch {return route.fulfill({status: 404, body: ''});}
  });
  await context.addInitScript(() => {if (location.protocol === 'https:') localStorage.setItem('id_token', 'x.' + btoa(JSON.stringify({exp: Date.now() / 1000 + 3600})) + '.x');});
  await page.evaluate(() => chrome.storage.local.set({lightburnPairing: {secret: 'test-only'}}));
  const worker = context.serviceWorkers().find(item => item.url().includes(extensionId));
  await worker.evaluate(() => {
    self.libraryMode = 'ok'; self.libraryCalls = [];
    self.fetch = async (url, options) => {
      self.libraryCalls.push(options.method); if (options.method !== 'GET') throw new Error('Library import must not write to LightBurn');
      if (self.libraryMode === 'unauthorized') return new Response('', {status: 401});
      const entry = {guid: 'one', material: 'Steel', description: '<Blue>', cut: {kind: 'normal', mode: 'scan', profile: 'galvo', params: {speed: 600, frequency: 200000, q_pulse_width: 100, max_power: 30, interval: .05, fiber_pulse_width: 5}}};
      const values = {'/api/project': {filename: 'C:/private/project.lbrn2'}, '/api/status': {connected: false}, '/api/units': {units: 'mm/min', distance_units: 'mm'},
        '/api/material-library': {product: 'lightburn', name: 'Live library', entries: self.libraryMode === 'empty' ? [] : [entry, {...entry, guid: 'two', material: 'Brass', description: 'Red'}]}};
      return Response.json(values[new URL(url).pathname]);
    };
  });
  await page.close();
  const web = await context.newPage(); const errors = []; web.on('pageerror', error => errors.push(error.message));
  await web.goto(origin + '/vault.html');
  await web.locator('[data-lightburn-palette-import]').click();
  await web.locator('[data-lbp-read]').click();
  await web.locator('[data-lbp-entry="0"]').waitFor();
  assert.equal(await web.locator('blue').count(), 0);
  await web.locator('[data-lbp-entry="0"]').check(); await web.locator('[data-lbp-name]').fill('My new palette');
  await web.locator('[data-lbp-preview]').click();
  assert.equal(await web.locator('[data-lbp-save]').isDisabled(), true);
  assert.match(await web.locator('[data-lbp-preview-details]').textContent(), /fiber_pulse_width/);
  assert.equal(writes.length, 0);
  assert.equal(await web.locator('[data-lbp-swatch="0"]').inputValue(), '');
  await web.locator('[data-lbp-swatch="0"]').selectOption('#0000FF');
  await web.locator('[data-lbp-preview-details] details').evaluateAll(nodes => nodes.forEach(node => {node.open = true;}));
  await web.locator('[data-lbp-ack]').check();
  await web.locator('[data-lbp-save]').click();
  await web.waitForFunction(() => document.querySelector('[data-lbp-status]').textContent.includes('saved with your swatch assignments'));
  assert.equal(saves, 1); assert.equal(resourceReads, 3);
  assert.equal(await web.locator('[data-lbp-status]').evaluate(node => {
    const rect = node.getBoundingClientRect(), panel = node.closest('dialog').getBoundingClientRect();
    return rect.top >= Math.max(0, panel.top) && rect.bottom <= Math.min(innerHeight, panel.bottom);
  }), true, 'Save confirmation must be visible without scrolling');
  assert.equal(await web.locator('[data-lbp-close]').textContent(), 'Done');
  assert.equal(writes.filter(path => path === '/api/account/preferences').length, 1);
  assert.match(uploaded, /Desc="&lt;Blue&gt;"/); assert.doesNotMatch(uploaded, /guid&quot;:&quot;two/);
  assert.match(uploaded, /speed Value="10"/); assert.match(uploaded, /RasterizerLightBurnSource/);
  assert.equal(await web.locator('[data-lbp-save]').isDisabled(), true);
  const directory = new URL('../scratch/lightburn-extension/', import.meta.url); await mkdir(directory, {recursive: true});
  await web.screenshot({path: fileURLToPath(new URL(`palette-${process.env.MOPA_BROWSER_CHANNEL}.png`, directory)), fullPage: true});
  await web.locator('[data-lbp-close]').click();
  appending = true;
  await web.locator('[data-lightburn-append="existing"]').click();
  assert.match(await web.locator('#lb-palette-heading').textContent(), /into My new palette/);
  await web.locator('[data-lbp-read]').click();
  await web.locator('[data-lbp-entry="0"]').check();
  await web.locator('[data-lbp-preview]').click();
  assert.equal(await web.locator('[data-lbp-swatch="0"] option[value="#FF0000"]').evaluate(option => option.disabled), true);
  await web.locator('[data-lbp-swatch="0"]').selectOption('#0000FF');
  await web.locator('[data-lbp-ack]').check();
  await web.locator('[data-lbp-save]').click();
  await web.waitForFunction(() => document.querySelector('[data-lbp-status]').textContent.includes('Swatches imported into'));
  assert.equal(saves, 2);
  assert.equal(await web.locator('[data-lbp-save]').textContent(), 'Swatches imported');
  await web.locator('[data-lbp-close]').click();
  appending = false;
  await web.locator('[data-lightburn-palette-import]').click();
  for (const value of ['unauthorized', 'empty']) {
    await worker.evaluate(value => {self.libraryMode = value;}, value); await web.locator('[data-lbp-read]').click();
    await web.waitForFunction(() => !document.querySelector('[data-lbp-read]').disabled);
    assert.equal(await web.locator('[data-lbp-entry]').count(), 0); assert.equal(await web.locator('[data-lbp-save]').isDisabled(), true);
  }
  await worker.evaluate(() => {self.libraryMode = 'ok';}); await web.locator('[data-lbp-read]').click();
  await web.locator('[data-lbp-entry="0"]').check(); await web.locator('[data-lbp-name]').fill('My new palette');
  await web.locator('[data-lbp-preview]').click(); await web.locator('[data-lbp-ack]').check(); mode = 'uncertain';
  await web.locator('[data-lbp-save]').click();
  await web.waitForFunction(() => document.querySelector('[data-lbp-status]').textContent.includes('could not be confirmed'));
  await web.waitForTimeout(1500); assert.equal(saves, 3); assert.equal(await web.locator('[data-lbp-save]').isDisabled(), true);
  await web.locator('[data-lbp-close]').click();
  await web.locator('[data-lightburn-palette-import]').click();
  await web.locator('[data-lbp-read]').click();
  await web.locator('[data-lbp-entry="0"]').check(); await web.locator('[data-lbp-name]').fill('My new palette');
  await web.locator('[data-lbp-preview]').click(); await web.locator('[data-lbp-ack]').check();
  mode = 'mapping-failure';
  await web.locator('[data-lbp-save]').click();
  await web.waitForFunction(() => document.querySelector('[data-lbp-status]').textContent.includes('Do not import again'));
  assert.equal(saves, 4);
  assert.equal(await web.locator('[data-lbp-save]').isDisabled(), true);
  assert.equal(await web.locator('[data-lbp-close]').isDisabled(), false);
  assert.ok((await worker.evaluate(() => self.libraryCalls)).every(method => method === 'GET'));
  await web.locator('[data-lbp-close]').click();
  processing = true; mode = 'ok';
  await web.locator('[data-lightburn-processing-import]').click();
  await web.locator('[data-proc-read]').click();
  await web.locator('[data-proc-role="Cut"]').waitFor();
  assert.equal(await web.locator('[data-proc-role]').count(), 7);
  assert.equal(await web.locator('[data-proc-role="Cut"]').inputValue(), '');
  assert.equal(await web.locator('[data-proc-preview]').isDisabled(), true);
  await web.locator('[data-proc-name]').fill('My processing palette');
  await web.getByRole('searchbox', {name:'Find a setting for Cut',exact:true}).fill('steel');
  assert.equal(await web.locator('[data-proc-role="Cut"] option').count(), 2);
  await web.locator('[data-proc-role="Cut"]').selectOption('0');
  await web.locator('[data-proc-role="Score"]').selectOption('0');
  await web.locator('[data-proc-preview]').click();
  assert.equal(await web.locator('[data-proc-save]').isDisabled(), true);
  await web.locator('[data-proc-ack]').check();
  // Changing a role revokes the previous preview and acknowledgment.
  await web.locator('[data-proc-role="Photo"]').selectOption('1');
  assert.equal(await web.locator('[data-proc-save]').isDisabled(), true);
  await web.locator('[data-proc-role="Photo"]').selectOption('');
  await web.locator('[data-proc-preview]').click(); await web.locator('[data-proc-ack]').check();
  await web.locator('[data-proc-save]').click();
  await web.waitForFunction(() => document.querySelector('[data-proc-status]').textContent.includes('created with your role assignments'));
  assert.equal((uploaded.match(/<Entry /g) || []).length, 1);
  assert.doesNotMatch(uploaded, /guid&quot;:&quot;two/);
  assert.equal(await web.locator('[data-proc-save]').isDisabled(), true);
  await web.locator('[data-proc-close]').click();
  await web.locator('[data-lightburn-processing-import]').click();
  await web.locator('[data-proc-read]').click(); await web.locator('[data-proc-role="Cut"]').selectOption('0');
  await web.locator('[data-proc-name]').fill('My processing palette');
  await web.locator('[data-proc-preview]').click(); await web.locator('[data-proc-ack]').check();
  mode = 'mapping-failure'; const beforePartial = saves;
  await web.locator('[data-proc-save]').click();
  await web.waitForFunction(() => document.querySelector('[data-proc-status]').textContent.includes('Do not import again'));
  assert.equal(saves, beforePartial + 1);
  assert.equal(await web.locator('[data-proc-save]').isDisabled(), true);
  await web.locator('[data-proc-close]').click();
  await web.locator('[data-lightburn-processing-import]').click();
  for (const state of ['unauthorized', 'empty']) {
    await worker.evaluate(value => {self.libraryMode=value;}, state);
    await web.locator('[data-proc-read]').click();
    await web.waitForFunction(() => !document.querySelector('[data-proc-read]').disabled);
    assert.equal(await web.locator('[data-proc-preview]').isDisabled(), true);
    assert.equal(await web.locator('[data-proc-save]').isDisabled(), true);
  }
  const session = await context.browser().newBrowserCDPSession(); await session.send('Extensions.uninstall', {id: extensionId});
  await web.waitForFunction(() => !document.querySelector('[data-lightburn-palette-import]') && !document.querySelector('.lightburn-palette-dialog'));
  await web.reload(); await web.waitForTimeout(3200); assert.equal(await web.locator('[data-lightburn-palette-import]').count(), 0); assert.equal(await web.locator('[data-lightburn-append]').count(), 0); assert.equal(await web.locator('[data-lightburn-processing-import]').count(), 0);
  assert.deepEqual(errors, []);
  console.log('PASS: Processing role-first import, shared settings, mapping preservation, partial-save recovery; Vault discovery, selected-entry preview, unsupported-field acknowledgment, single save, no LightBurn writes, empty/unauthorized reads, uncertain-save no retry, and extension-free UI. Synthetic API only.');
}
