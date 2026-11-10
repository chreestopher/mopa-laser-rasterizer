import assert from 'node:assert/strict';
import test from 'node:test';
import {readFile} from 'node:fs/promises';
import {probeConnection} from '../dev_setup/lightburn-extension-poc/lightburn-client.js';

test('proves readable root and authentication rejection from fixed localhost', async () => {
  const calls = [];
  const result = await probeConnection({fetchImpl: async (url, options) => {
    calls.push({url, options});
    return new Response('', {status: calls.length === 1 ? 200 : 401});
  }});
  assert.equal(result.ok, true);
  assert.deepEqual(result.checks.map(check => check.status), [200, 401]);
  assert.deepEqual(calls.map(call => call.url), ['http://localhost:19520/', 'http://localhost:19520/api/status']);
  for (const {options} of calls) {
    assert.equal(options.method, 'GET');
    assert.equal(options.redirect, 'error');
    assert.equal(options.credentials, 'omit');
    assert.equal(options.cache, 'no-store');
    assert.ok(options.signal instanceof AbortSignal);
  }
  assert.equal(calls[1].options.headers.Authorization, 'Bearer connectivity-probe-invalid');
  assert.match(result.message, /does not verify pairing/i);
});

test('unexpected HTTP statuses do not count as a successful connection proof', async () => {
  for (const statuses of [[200, 200], [404, 401], [200, 403], [200, 500]]) {
    const pending = [...statuses];
    const result = await probeConnection({fetchImpl: async () => new Response('', {status: pending.shift()})});
    assert.equal(result.ok, false);
    assert.deepEqual(result.checks.map(check => check.status), statuses);
  }
});

test('unreachable or browser-blocked requests fail without retries or pairing', async () => {
  let calls = 0;
  const result = await probeConnection({fetchImpl: async () => {
    calls++;
    throw new TypeError('Failed to fetch');
  }});
  assert.equal(result.ok, false);
  assert.equal(calls, 2);
  assert.ok(result.checks.every(check => check.error === 'network'));
  assert.match(result.message, /LightBurn|permission/i);
});

test('a hanging request is aborted and reported as a timeout', async () => {
  const result = await probeConnection({timeoutMs: 10, fetchImpl: (_url, {signal}) => new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(signal.reason), {once: true});
  })});
  assert.equal(result.ok, false);
  assert.ok(result.checks.every(check => check.error === 'timeout'));
});

test('preserves a successful first check when authenticated endpoint is unreadable', async () => {
  let calls = 0;
  const result = await probeConnection({fetchImpl: async () => {
    if (++calls === 1) return new Response('', {status: 200});
    throw new TypeError('Failed to fetch');
  }});
  assert.equal(result.ok, false);
  assert.equal(result.checks[0].status, 200);
  assert.equal(result.checks[1].error, 'network');
});

test('manifest grants only localhost access and declares a module worker', async () => {
  const manifest = JSON.parse(await readFile(new URL('../dev_setup/lightburn-extension-poc/manifest.json', import.meta.url)));
  assert.equal(manifest.manifest_version, 3);
  assert.deepEqual(manifest.host_permissions, ['http://localhost/*']);
  assert.deepEqual(manifest.permissions, ['storage']);
  assert.equal(manifest.background.type, 'module');
  assert.ok(manifest.action);
  assert.deepEqual(manifest.content_scripts[0].js, ['discovery.js']);
  assert.deepEqual(manifest.content_scripts[0].matches, ['https://serverless-staging.mopa-laser-rasterizer.com/history.html*', 'https://serverless-staging.mopa-laser-rasterizer.com/lightburn-connection-test.html*', 'https://serverless-staging.mopa-laser-rasterizer.com/vault.html*']);
  assert.deepEqual(manifest.externally_connectable.matches, ['https://serverless-staging.mopa-laser-rasterizer.com/*']);
});

test('a response-body cleanup failure cannot invalidate already readable status', async () => {
  let calls = 0;
  const result = await probeConnection({fetchImpl: async () => ({
    status: ++calls === 1 ? 200 : 401,
    body: {cancel: async () => {throw new Error('Stream already closed');}},
  })});
  assert.equal(result.ok, true);
  assert.equal(result.checks.length, 2);
});
