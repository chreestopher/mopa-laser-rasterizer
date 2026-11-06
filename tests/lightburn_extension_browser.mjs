// Optional live acceptance: node tests/lightburn_extension_browser.mjs --live
// Requires Playwright. Overrides: MOPA_PLAYWRIGHT_MODULE, MOPA_BROWSER_BIN.
import assert from 'node:assert/strict';
import {mkdtemp, rm, mkdir, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, isAbsolute} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {createHmac} from 'node:crypto';

const moduleName = process.env.MOPA_PLAYWRIGHT_MODULE || 'playwright';
const {chromium} = await import(isAbsolute(moduleName) ? pathToFileURL(moduleName).href : moduleName);
const extension = fileURLToPath(new URL('../dev_setup/lightburn-extension-poc', import.meta.url));
const profile = await mkdtemp(join(tmpdir(), 'mopa-lightburn-poc-'));
const basicAuth = process.env.MOPA_STAGING_BASIC_AUTH
  ? Buffer.from(process.env.MOPA_STAGING_BASIC_AUTH, 'base64').toString('utf8') : '';
const separator = basicAuth.indexOf(':');
const context = await chromium.launchPersistentContext(profile, {
  headless: true, channel: process.env.MOPA_BROWSER_CHANNEL || 'chromium',
  ignoreDefaultArgs: ['--disable-extensions'],
  ...(separator >= 0 ? {httpCredentials: {
    origin: 'https://serverless-staging.mopa-laser-rasterizer.com',
    username: basicAuth.slice(0, separator), password: basicAuth.slice(separator + 1),
  }} : {}),
  ...(process.env.MOPA_BROWSER_BIN ? {executablePath: process.env.MOPA_BROWSER_BIN} : {}),
  args: ['--enable-unsafe-extension-debugging',
    ...(['chrome', 'msedge'].includes(process.env.MOPA_BROWSER_CHANNEL) ? []
      : [`--disable-extensions-except=${extension}`, `--load-extension=${extension}`])],
});
try {
  // Branded Chrome/Edge no longer consistently accept --load-extension.
  // CDP installs only into this temporary test profile; web security stays enabled.
  let extensionId;
  if (!context.serviceWorkers().length) {
    try {
      const session = await context.browser().newBrowserCDPSession();
      extensionId = (await session.send('Extensions.loadUnpacked', {path: extension})).id;
      await session.detach();
    } catch { /* Older Chromium uses the startup load-extension flag. */ }
  }
  if (!extensionId) {
    const worker = context.serviceWorkers()[0] || await context.waitForEvent('serviceworker', {timeout: 15000});
    extensionId = new URL(worker.url()).host;
  }
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(`chrome-extension://${extensionId}/console.html`);
  assert.equal(await page.title(), 'LightBurn Connection Test');
  assert.equal(await page.locator('#status').textContent(), 'Ready to check.');
  const requests = [];
  const recordRequest = request => {
    if (request.url().startsWith('http://localhost:19520')) requests.push({url: request.url(), method: request.method()});
  };
  page.on('request', recordRequest);
  if (process.argv.includes('--palette')) {
    const {paletteScenario} = await import('./lightburn_palette_scenario.mjs');
    await paletteScenario({context, page, extensionId});
  } else if (process.argv.includes('--cors')) {
    const web = await context.newPage();
    await web.goto('https://serverless-staging.mopa-laser-rasterizer.com/lightburn-connection-test.html');
    const result = await web.evaluate(async url => {const response = await fetch(url, {credentials: 'omit'}); return {status: response.status, type: response.type, matches: (await response.text()).includes('.lightburn-dialog')};}, process.env.MOPA_DOWNLOAD_TEST_URL);
    assert.deepEqual(result, {status: 200, type: 'cors', matches: true});
    console.log('PASS: real staging-origin browser read of a private artifact using its signed URL.');
  } else if (process.argv.includes('--inline') || process.argv.includes('--import')) {
    const {inlineScenario} = await import('./lightburn_inline_scenario.mjs');
    await inlineScenario({context, page, extensionId});
  } else if (process.argv.includes('--pair-live')) {
    console.log(`Live ${process.env.MOPA_BROWSER_CHANNEL || 'Chromium'} pairing: approve the MOPA Rasterizer Connection POC dialog in LightBurn now.`);
    await page.locator('#pair').click();
    await page.waitForFunction(() => ['paired', 'failed'].includes(document.querySelector('#pairing-status').dataset.state), null, {timeout: 45000});
    assert.equal(await page.locator('#pairing-status').getAttribute('data-state'), 'paired', await page.locator('#pairing-status').textContent());
    await page.locator('#read-library').click();
    await page.waitForFunction(() => ['loaded', 'empty', 'failed'].includes(document.querySelector('#library-status').dataset.state));
    console.log('Initial live read:', await page.locator('#library-status').textContent());
    assert.equal(await page.locator('#library-status').getAttribute('data-state'), 'loaded');
    const pairCount = requests.filter(item => item.method === 'POST').length;
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#pairing-status').dataset.state === 'saved');
    await page.locator('#read-library').click();
    await page.waitForFunction(() => document.querySelector('#library-status').dataset.state === 'loaded');
    assert.equal(requests.filter(item => item.method === 'POST').length, pairCount);
    if (process.argv.includes('--minute-rollover')) {
      const remaining = 60000 - (Date.now() % 60000) + 500;
      console.log(`Waiting ${Math.ceil(remaining / 1000)} seconds to verify a fresh token after minute rollover.`);
      await page.waitForTimeout(remaining);
      await page.locator('#read-library').click();
      await page.waitForFunction(() => document.querySelector('#library-status').dataset.state === 'loaded');
    }
    const web = await context.newPage(); web.on('pageerror', error => errors.push(error.message));
    const origin = 'https://serverless-staging.mopa-laser-rasterizer.com';
    if (!process.argv.includes('--deployed')) {
      await context.route(`${origin}/lightburn-connection-test.*`, async route => {
        const name = new URL(route.request().url()).pathname.slice(1);
        await route.fulfill({body: await readFile(new URL(`../serverless_web/${name}`, import.meta.url)),
          contentType: name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html'});
      });
    }
    await web.goto(`${origin}/lightburn-connection-test.html`);
    await web.locator('#extension-id').fill(extensionId);
    await web.locator('#read-library').click();
    await web.waitForFunction(() => ['loaded', 'empty', 'failed'].includes(document.querySelector('#library-status').dataset.state));
    assert.equal(await web.locator('#library-status').getAttribute('data-state'), 'loaded', await web.locator('#library-status').textContent());
    const entry = JSON.parse(await web.locator('#entry-details').textContent());
    console.log(JSON.stringify({browser: context.browser().version(), deployed: process.argv.includes('--deployed'),
      summary: await web.locator('#library-summary').textContent(), sample: {material: entry.material, description: entry.description,
        profile: entry.cut.profile, params: entry.cut.params, sublayers: entry.cut.sub_layers?.length || 0},
      pairingRequests: pairCount, reloadPassed: true, rolloverPassed: process.argv.includes('--minute-rollover')}, null, 2));
    assert.ok(requests.every(item => item.method === 'GET' || item.url === 'http://localhost:19520/api/connect'));
    const screenshots = fileURLToPath(new URL('../scratch/lightburn-extension', import.meta.url));
    await mkdir(screenshots, {recursive: true});
    await web.screenshot({path: join(screenshots, `library-${process.env.MOPA_BROWSER_CHANNEL || 'chromium'}.png`), fullPage: true});
    console.log('PASS: real pairing, reload persistence, authenticated selected-library read, and website handoff. No file or machine operations.');
  } else if (process.argv.includes('--auth')) {
    let pairCalls = 0; let scenario = 'declined';
    const sample = {product: 'lightburn', name: 'Test library', filename: 'C:/private/test.clb', entries: [{
      material: 'Stainless', description: '<Blue>', cut: {kind: 'normal', profile: 'galvo', mode: 'scan',
        params: {speed: 2000, max_power: 30, frequency: 200000, override_frequency: true, q_pulse_width: 100},
        sub_layers: [{index: 1, name: 'Cleanup', mode: 'scan', enabled: true, params: {speed: 3000}}]},
    }]};
    await context.route('http://localhost:19520/**', async route => {
      const path = new URL(route.request().url()).pathname;
      if (path === '/api/connect') {
        pairCalls++;
        return route.fulfill(scenario === 'declined' ? {status: 403, body: ''}
          : {json: {status: 'ok', secret: 'browser-test-secret'}});
      }
      if (scenario === 'unauthorized') return route.fulfill({status: 401, body: ''});
      const minute = Math.floor(Date.now() / 60000);
      const valid = [minute, minute - 1].map(value => `Bearer ${createHmac('sha256', 'browser-test-secret').update(String(value)).digest('hex')}`);
      assert.ok(valid.includes(route.request().headers().authorization));
      const values = {'/api/status': {connected: false, device_name: 'MOPA'},
        '/api/project': {filename: 'C:/private/project.lbrn2', device: {name: 'MOPA', laser: {galvo: true, mopa_source: 1}}},
        '/api/units': {units: 'mm/min', distance_units: 'in'},
        '/api/material-library': scenario === 'empty' ? {...sample, entries: []} : sample};
      await route.fulfill({json: values[path]});
    });
    await page.locator('#read-library').click();
    await page.waitForFunction(() => document.querySelector('#library-status').textContent.includes('Pair with LightBurn'));
    assert.equal(requests.length, 0);
    await page.locator('#pair').click();
    await page.waitForFunction(() => document.querySelector('#pairing-status').dataset.state === 'failed');
    assert.equal(await page.evaluate(async () => Boolean((await chrome.storage.local.get('lightburnPairing')).lightburnPairing)), false);
    scenario = 'success';
    await page.locator('#pair').click();
    await page.waitForFunction(() => document.querySelector('#pairing-status').dataset.state === 'paired');
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#pairing-status').dataset.state === 'saved');
    await page.locator('#read-library').click();
    await page.waitForFunction(() => document.querySelector('#library-status').dataset.state === 'loaded');
    assert.match(await page.locator('#library-summary').textContent(), /Test library/);
    assert.match(await page.locator('#library-summary').textContent(), /mm\/min.*in/);
    assert.match(await page.locator('#entry-details').textContent(), /q_pulse_width/);
    assert.equal(await page.locator('blue').count(), 0, 'Library text must not become HTML');
    const web = await context.newPage();
    const origin = 'https://serverless-staging.mopa-laser-rasterizer.com';
    await context.route(`${origin}/lightburn-connection-test.*`, async route => {
      const name = new URL(route.request().url()).pathname.slice(1);
      await route.fulfill({body: await readFile(new URL(`../serverless_web/${name}`, import.meta.url)),
        contentType: name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html'});
    });
    await web.goto(`${origin}/lightburn-connection-test.html`);
    await web.locator('#extension-id').fill(extensionId);
    await web.locator('#read-library').click();
    await web.waitForFunction(() => document.querySelector('#library-status').dataset.state === 'loaded');
    assert.match(await web.locator('#entry-details').textContent(), /q_pulse_width/);
    assert.doesNotMatch(await web.locator('body').textContent(), /browser-test-secret|C:\/private/);
    scenario = 'unauthorized';
    await page.locator('#read-library').click();
    await page.waitForFunction(() => document.querySelector('#library-status').dataset.state === 'failed');
    assert.equal(await page.locator('#entry-details').textContent(), '');
    assert.equal(pairCalls, 2, '401 must not re-pair');
    scenario = 'empty';
    await page.locator('#read-library').click();
    await page.waitForFunction(() => document.querySelector('#library-status').dataset.state === 'empty');
    await page.locator('#forget').click();
    await page.waitForFunction(() => document.querySelector('#pairing-status').dataset.state === 'unpaired');
    await web.locator('#read-library').click();
    await web.waitForFunction(() => document.querySelector('#library-status').dataset.state === 'failed');
    assert.match(await web.locator('#library-status').textContent(), /Pair with LightBurn/);
    assert.equal(await web.locator('#entry-details').textContent(), '');
    console.log('PASS: pairing decline/success, persistence, authenticated library + units + sublayers, webpage read, empty library, 401 recovery, forget');
  } else if (process.argv.includes('--bridge')) {
    const web = await context.newPage();
    const origin = 'https://serverless-staging.mopa-laser-rasterizer.com';
    // Local response substitution tests extension messaging at the real origin.
    // --deployed separately verifies actual staging delivery without substitution.
    if (!process.argv.includes('--deployed')) {
      await context.route(`${origin}/lightburn-connection-test.*`, async route => {
        const name = new URL(route.request().url()).pathname.slice(1);
        const body = await readFile(new URL(`../serverless_web/${name}`, import.meta.url));
        await route.fulfill({body, contentType: name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html'});
      });
    }
    await web.goto(`${origin}/lightburn-connection-test.html`);
    await web.locator('#extension-id').fill(extensionId);
    await web.locator('#check').click();
    await web.waitForFunction(() => ['passed', 'failed'].includes(document.querySelector('#status').dataset.outcome));
    const outcome = await web.locator('#status').getAttribute('data-outcome');
    console.log(JSON.stringify({browser: context.browser().version(), deployed: process.argv.includes('--deployed'),
      outcome, message: await web.locator('#status').textContent()}, null, 2));
    assert.equal(outcome, 'passed');
    assert.equal(requests.length, 2);
    assert.ok(requests.every(request => request.method === 'GET'));
    await page.close();
    const denied = await web.evaluate(id => new Promise(resolve => {
      chrome.runtime.sendMessage(id, {version: 1, id: 'denied-test', command: 'pair'}, resolve);
    }), extensionId);
    assert.equal(denied.error, 'denied');
    assert.equal(requests.length, 2, 'Denied command must not reach LightBurn');
    const screenshots = fileURLToPath(new URL('../scratch/lightburn-extension', import.meta.url));
    await mkdir(screenshots, {recursive: true});
    await web.screenshot({path: join(screenshots, `bridge-${process.env.MOPA_BROWSER_CHANNEL || 'chromium'}.png`), fullPage: true});
    await web.locator('#check').click();
    await web.waitForFunction(() => document.querySelector('#status').dataset.outcome === 'failed');
    assert.match(await web.locator('#status').textContent(), /Open the extension/);
    assert.equal(await web.locator('#check').isEnabled(), true);
    console.log('PASS: website bridge to live LightBurn and closed-console recovery');
  } else if (process.argv.includes('--live')) {
    await page.locator('#check').click();
    await page.waitForFunction(() => ['passed', 'failed'].includes(document.querySelector('#status').dataset.outcome));
    const outcome = await page.locator('#status').getAttribute('data-outcome');
    console.log(JSON.stringify({browser: context.browser()?.version(), extensionId, outcome,
      status: await page.locator('#status').textContent(), checks: await page.locator('#results li').allTextContents(), requests}, null, 2));
    const screenshots = fileURLToPath(new URL('../scratch/lightburn-extension', import.meta.url));
    await mkdir(screenshots, {recursive: true});
    await page.screenshot({path: join(screenshots, 'connection.png'), fullPage: true});
    assert.equal(outcome, 'passed', 'Live extension transport must pass without CORS/security bypasses');
    assert.equal(requests.length, 2);
    assert.ok(requests.every(request => request.method === 'GET'));
  } else {
    let scenario = 'success';
    await context.route('http://localhost:19520/**', async route => {
      if (scenario === 'offline') return route.abort('connectionrefused');
      await route.fulfill({status: route.request().url().endsWith('/api/status') ? 401 : 200, body: ''});
    });
    await page.locator('#check').click();
    await page.waitForFunction(() => document.querySelector('#status').dataset.outcome === 'passed');
    assert.match(await page.locator('#status').textContent(), /does not verify pairing/);
    assert.equal(await page.locator('#results li').count(), 2);
    scenario = 'offline';
    await page.locator('#check').click();
    await page.waitForFunction(() => document.querySelector('#status').dataset.outcome === 'failed');
    assert.equal(await page.locator('#results li').count(), 2, 'Previous results must be replaced');
    assert.equal(await page.locator('#check').isEnabled(), true);
    console.log('PASS: extension UI success, failed recheck, and button recovery');
  }
  assert.deepEqual(errors, []);
} finally {
  await context.close().catch(error => { if (context.browser()?.isConnected()) throw error; });
  // mkdtemp returns a unique directory under the OS temp directory owned by this run.
  assert.ok(profile.startsWith(join(tmpdir(), 'mopa-lightburn-poc-')));
  await rm(profile, {recursive: true, force: true});
}
