import assert from 'node:assert/strict';
import {readFile, mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';

export async function inlineScenario({context, page, extensionId}) {
  const origin = 'https://serverless-staging.mopa-laser-rasterizer.com';
  const large = process.argv.includes('--large');
  const expectedBytes = large ? 100 * 1024 * 1024 : 2 * 1024 * 1024;
  const job = {task_id: 'native-test', status: 'completed', source_name: 'Sample artwork', created_at: '2026-11-05T12:00:00Z',
    outputs: [{name: 'tiny.lbrn2', bytes: 19, download_url: origin + '/fixture.lbrn2'}, {name: 'tiny.svg', bytes: 10, download_url: origin + '/fixture.svg'}], run_parameters: {}};
  await context.route(`${origin}/**`, async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/config.json') return route.fulfill({json: {api_url: origin + '/api'}});
    if (path === '/api/account/jobs') return route.fulfill({json: {jobs: [job]}});
    if (path === '/api/account/jobs/native-test') return route.fulfill({json: job});
    if (path === '/fixture.lbrn2') {
      throw new Error('Fixture must stream inside the browser, not through a large DevTools message.');
    }
    if (path === '/staging-shell.js') return route.fulfill({body: '', contentType: 'text/javascript'});
    try {return route.fulfill({body: await readFile(new URL('../serverless_web' + path, import.meta.url)), contentType: path.endsWith('.js') ? 'text/javascript' : path.endsWith('.css') ? 'text/css' : 'text/html'});}
    catch {return route.fulfill({status: 404, body: ''});}
  });
  await context.addInitScript(() => {if (location.protocol === 'https:') localStorage.setItem('id_token', 'x.' + btoa(JSON.stringify({exp: Date.now() / 1000 + 3600})) + '.x');});
  await context.addInitScript(expectedBytes => {
    const originalFetch = window.fetch.bind(window); window.testOversized = true;
    window.fetch = (url, options) => {
      if (!String(url).endsWith('/fixture.lbrn2')) return originalFetch(url, options);
      if (window.testOversized) return Promise.resolve(new Response('', {headers: {'Content-Length': '104857601'}}));
      let offset = 0;
      return Promise.resolve(new Response(new ReadableStream({pull(controller) {
        if (window.testDownloadInterrupted && offset > 0) return controller.error(new TypeError('Connection lost'));
        if (offset === expectedBytes) return controller.close();
        const chunk = new Uint8Array(Math.min(262144, expectedBytes - offset)).fill(32);
        if (!offset) chunk.set(new TextEncoder().encode('<LightBurnProject/>'));
        offset += chunk.length; controller.enqueue(chunk);
      }}), {headers: {'Content-Length': String(expectedBytes)}}));
    };
  }, expectedBytes);
  await page.evaluate(() => chrome.storage.local.set({lightburnPairing: {secret: 'test-only'}}));
  const worker = context.serviceWorkers().find(item => item.url().includes(extensionId));
  await worker.evaluate(expectedBytes => {
    self.testPosts = 0; self.testModified = true;
    let stream;
    self.fetch = async (url, options) => {
      if (self.testFailure === 'offline') throw new TypeError('Failed to fetch');
      if (self.testFailure === 'unauthorized') return new Response('', {status: 401});
      if (url.endsWith('/api/project')) return Response.json({filename: 'C:/private/blank.lbrn2', modified: self.testModified, shape_count: 0, device: {name: 'Mock MOPA'}});
      if (url.endsWith('/api/events')) return new Response(new ReadableStream({start(controller) {stream = controller; controller.enqueue(new TextEncoder().encode(':connected\n\n'));}}), {headers: {'Content-Type': 'text/event-stream'}});
      if (url.endsWith('/api/file/open')) {
        self.testPosts++; if (options.method !== 'POST') throw new Error('Wrong method');
        if (options.body.byteLength !== expectedBytes) throw new Error('Wrong native file byte count');
        if (self.testFailure === 'disconnect') {stream.close(); return new Response('', {status: 202});}
        self.completeImport = () => stream.enqueue(new TextEncoder().encode('event: file_imported\ndata: {"success":true}\n\n'));
        return new Response('', {status: 202});
      }
      throw new Error('Unexpected API request');
    };
  }, expectedBytes);
  await page.close(); // No diagnostics tab is available to perform the operation.
  const web = await context.newPage(); const errors = []; web.on('pageerror', error => errors.push(error.message));
  await web.goto(origin + '/history.html?task=native-test');
  await web.locator('[data-load-lightburn]').waitFor();
  assert.equal(await web.locator('[data-load-lightburn]').count(), 1, 'Only native projects get the button');
  await web.locator('[data-load-lightburn]').click();
  await web.waitForFunction(() => document.querySelector('[data-lb-status]')?.textContent.includes('100 MiB'));
  await web.waitForTimeout(3200);
  assert.match(await web.locator('[data-lb-status]').textContent(), /100 MiB/, 'Idle polling must not erase the staging failure');
  assert.equal(await web.locator('[data-lb-stage]').isEnabled(), true, 'Staging failure offers recovery');
  assert.equal(await worker.evaluate(() => self.testPosts), 0);
  await web.evaluate(() => {window.testOversized = false;});
  if (process.argv.includes('--failures')) {
    await web.evaluate(() => {window.testDownloadInterrupted = true;});
    await web.locator('[data-lb-stage]').click();
    await web.waitForFunction(() => document.querySelector('[data-lb-status]').textContent.includes('download was interrupted'));
    await web.waitForTimeout(2000);
    assert.equal(await web.locator('[data-lb-stage]').isEnabled(), true);
    assert.equal(await worker.evaluate(async () => (await chrome.storage.session.get('nativeImport')).nativeImport.state), 'idle');
    assert.equal(await worker.evaluate(() => self.testPosts), 0);
    await web.evaluate(() => {window.testDownloadInterrupted = false;});
  }
  await web.locator('[data-lb-stage]').click();
  await web.waitForFunction(() => document.querySelector('[data-lb-status]')?.dataset.state === 'staged', null, {timeout: 180000});
  const journalBytes = await worker.evaluate(async () => JSON.stringify(await chrome.storage.session.get('nativeImport')).length);
  assert.ok(journalBytes < 4096, 'File bytes must not enter session storage');
  await web.reload();
  await web.locator('[data-load-lightburn]').click();
  await web.waitForFunction(() => document.querySelector('[data-lb-status]')?.dataset.state === 'staged');
  assert.equal(await worker.evaluate(() => self.testPosts), 0);
  await web.locator('[data-lb-review]').click();
  await web.waitForFunction(() => document.querySelector('[data-lb-status]').textContent.includes('Save your current'));
  assert.equal(await web.locator('[data-lb-confirm]').isDisabled(), true);
  await worker.evaluate(() => {self.testModified = false;});
  await web.locator('[data-lb-review]').click();
  await web.waitForFunction(() => document.querySelector('[data-lb-status]').dataset.state === 'reviewed');
  assert.doesNotMatch(await web.locator('[data-lb-project]').textContent(), /private/);
  assert.equal(await web.locator('[data-lb-confirm]').isDisabled(), true);
  if (process.argv.includes('--failures')) {
    await worker.evaluate(() => chrome.storage.local.remove('lightburnPairing'));
    await web.locator('[data-lb-review]').click();
    await web.waitForFunction(() => document.querySelector('[data-lb-status]').textContent.includes('Pair with LightBurn'));
    assert.equal(await web.locator('[data-lb-confirm]').isDisabled(), true);
    assert.equal(await worker.evaluate(() => self.testPosts), 0);
    await worker.evaluate(() => chrome.storage.local.set({lightburnPairing: {secret: 'test-only'}}));
    await web.locator('[data-lb-review]').click();
    await web.waitForFunction(() => document.querySelector('[data-lb-status]').dataset.state === 'reviewed');
    for (const failure of ['offline', 'unauthorized']) {
      await worker.evaluate(value => {self.testFailure = value;}, failure);
      await web.locator('[data-lb-review]').click();
      await web.waitForFunction(() => document.querySelector('[data-lb-review]').disabled === false);
      assert.equal(await web.locator('[data-lb-status]').getAttribute('data-state'), 'staged', 'Failed review must revoke stale confirmation');
      await web.locator('[data-lb-consent]').isDisabled().then(value => assert.equal(value, true));
      assert.match(await web.locator('[data-lb-status]').textContent(), failure === 'offline' ? /could not reach LightBurn/i : /pair again/i);
    }
    await worker.evaluate(() => {self.testFailure = '';});
    await web.locator('[data-lb-review]').click();
    await web.waitForFunction(() => document.querySelector('[data-lb-status]').dataset.state === 'reviewed');
  }
  await web.locator('[data-lb-consent]').check();
  await web.locator('[data-lb-confirm]').click();
  await web.waitForFunction(() => document.querySelector('[data-lb-status]').dataset.state === 'opening');
  await web.locator('[data-lb-close]').click();
  await web.locator('[data-load-lightburn]').click();
  assert.equal(await web.locator('[data-lb-confirm]').isDisabled(), true);
  await worker.evaluate(async () => {
    const deadline = Date.now() + 20000;
    while (typeof self.completeImport !== 'function') {
      if (Date.now() > deadline) throw new Error('Native POST was not observed.');
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    self.completeImport();
  });
  await web.waitForFunction(() => document.querySelector('[data-lb-status]').dataset.state === 'loaded');
  await web.reload();
  await web.locator('[data-load-lightburn]').click();
  await web.waitForFunction(() => document.querySelector('[data-lb-status]').dataset.state === 'loaded');
  assert.equal(await worker.evaluate(() => self.testPosts), 1);
  if (process.argv.includes('--failures')) {
    await web.locator('[data-lb-discard]').click();
    await web.waitForFunction(() => document.querySelector('[data-lb-status]').dataset.state === 'idle');
    await web.evaluate(() => {window.testOversized = false;});
    await web.locator('[data-lb-stage]').click();
    await web.waitForFunction(() => document.querySelector('[data-lb-status]').dataset.state === 'staged');
    await web.locator('[data-lb-review]').click();
    await web.waitForFunction(() => document.querySelector('[data-lb-status]').dataset.state === 'reviewed');
    await worker.evaluate(() => {self.testFailure = 'disconnect';});
    await web.locator('[data-lb-consent]').check();
    await web.locator('[data-lb-confirm]').click();
    await web.waitForFunction(() => document.querySelector('[data-lb-status]').dataset.state === 'unknown');
    await web.reload(); await web.locator('[data-load-lightburn]').click();
    await web.waitForFunction(() => document.querySelector('[data-lb-status]').dataset.state === 'unknown');
    await web.waitForTimeout(3200);
    assert.equal(await worker.evaluate(() => self.testPosts), 2, 'Unknown outcome must never trigger replay');
    assert.equal(await web.locator('[data-lb-confirm]').isDisabled(), true);
  }
  const directory = new URL('../scratch/lightburn-extension/', import.meta.url); await mkdir(directory, {recursive: true});
  await web.screenshot({path: fileURLToPath(new URL(`inline-${process.env.MOPA_BROWSER_CHANNEL}.png`, directory)), fullPage: true});
  const session = await context.browser().newBrowserCDPSession();
  await session.send('Extensions.uninstall', {id: extensionId});
  await web.waitForFunction(() => !document.querySelector('[data-load-lightburn]') && !document.querySelector('.lightburn-dialog'));
  await web.reload();
  await web.locator('a[data-lightburn-name]').waitFor();
  await web.waitForTimeout(3500);
  assert.equal(await web.locator('[data-load-lightburn], .lightburn-dialog').count(), 0, 'No integration UI without extension');
  assert.equal(await web.locator('a[data-lightburn-name]').count(), 1, 'Download remains available');
  assert.deepEqual(errors, []);
  console.log('PASS: real History rendering, automatic detection, native-only button, in-page review and confirmation, close/reopen during import, reload status, no diagnostic tab, no duplicate sends, and no UI after extension removal or on a fresh page without extension. Synthetic LightBurn only.');
  if (process.argv.includes('--failures')) console.log('PASS: interrupted download cleanup/retry, missing pairing, offline and unauthorized re-review revoke confirmation, lost completion stream remains unknown across reload without resending.');
}
