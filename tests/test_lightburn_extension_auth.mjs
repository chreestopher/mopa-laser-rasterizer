import test from 'node:test';
import assert from 'node:assert/strict';
import {createHmac} from 'node:crypto';
import {deriveToken, createAuthenticatedClient, createCredentialStore} from '../dev_setup/lightburn-extension-poc/auth-client.js';
import {sanitizeSnapshot} from '../dev_setup/lightburn-extension-poc/library-snapshot.js';

const fixture = {
  status: {connected: false, device_name: 'Test MOPA'},
  project: {filename: 'C:/private/artwork.lbrn2', modified: false, shape_count: 5,
    device: {name: 'Test MOPA', laser: {galvo: true, mopa_source: 1}}},
  units: {units: 'mm/min', distance_units: 'in'},
  library: {product: 'lightburn', name: 'Stainless', filename: 'C:/private/settings.clb', entries: [
    {guid: 12, material: 'Steel', description: 'Blue', thickness: -1, locked: false,
      cut: {index: -1, kind: 'normal', profile: 'galvo', mode: 'scan', name: 'Blue', enabled: true,
        params: {speed: 3000, max_power: 30, frequency: 200000, override_frequency: true,
          q_pulse_width: 100, interval: 0.001, flood_fill: true, galvo: {laser_on_tc: 100}},
        sub_layers: [{index: 1, name: 'Cleanup', enabled: true, mode: 'scan', params: {speed: 5000}}]}}]},
};
function memoryStore(initial = null) {
  let saved = initial;
  return {get: async () => saved, set: async value => {saved = value;}, remove: async () => {saved = null;}};
}
const json = value => new Response(JSON.stringify(value), {headers: {'Content-Type': 'application/json'}});
const readResponse = url => json(fixture[{'/api/status': 'status', '/api/project': 'project', '/api/units': 'units', '/api/material-library': 'library'}[new URL(url).pathname]]);

test('HMAC uses UTF-8 secret and decimal Unix minute, changing precisely at boundary', async () => {
  for (const time of [0, 59999, 60000, 1790000000000]) {
    const expected = createHmac('sha256', 'test-secret-π').update(String(Math.floor(time / 60000))).digest('hex');
    assert.equal(await deriveToken('test-secret-π', time), expected);
  }
  assert.notEqual(await deriveToken('key', 59999), await deriveToken('key', 60000));
});

test('pair persists only after success, requests exactly approved capabilities, never returns secret', async () => {
  const store = memoryStore(); let captured;
  const client = createAuthenticatedClient({store, fetchImpl: async (url, options) => {
    captured = {url, options}; return json({status: 'ok', secret: 'pairing-secret'});
  }});
  assert.deepEqual(await client.pair(), {paired: true});
  assert.equal(captured.url, 'http://localhost:19520/api/connect');
  assert.equal(captured.options.method, 'POST');
  assert.equal(captured.options.redirect, 'error');
  assert.deepEqual(JSON.parse(captured.options.body).capabilities, ['state', 'project', 'upload']);
  assert.equal((await store.get()).secret, 'pairing-secret');
  assert.equal(await client.hasPairing(), true);
});

test('declined, invalid, network, and timed-out pairing do not replace a saved secret', async () => {
  for (const mode of ['declined', 'invalid', 'network', 'timeout']) {
    const store = memoryStore({secret: 'previous'});
    const client = createAuthenticatedClient({store, pairTimeoutMs: 5, fetchImpl: async (_url, {signal}) => {
      if (mode === 'network') throw new TypeError('sensitive details');
      if (mode === 'timeout') return new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(signal.reason)));
      if (mode === 'declined') return new Response('sensitive details', {status: 403});
      return json({status: 'ok'});
    }});
    await assert.rejects(client.pair(), error => ['declined', 'invalid_response', 'network', 'timeout'].includes(error.code) && !error.message.includes('sensitive'));
    assert.equal((await store.get()).secret, 'previous');
  }
});

test('unpaired read fails locally; authenticated reads are fixed GETs with freshly derived tokens', async () => {
  let time = 59999; const calls = []; const store = memoryStore();
  const client = createAuthenticatedClient({store, now: () => time, fetchImpl: async (url, options) => {
    calls.push({url, options}); return readResponse(url);
  }});
  await assert.rejects(client.readSnapshot(), {code: 'not_paired'});
  assert.equal(calls.length, 0);
  await store.set({secret: 'saved'});
  const first = await client.readSnapshot();
  assert.equal(first.library.entries[0].cut.params.q_pulse_width, 100);
  assert.equal(first.units.distance_units, 'in');
  assert.equal(first.units.units, 'mm/min');
  time = 60000; await client.readSnapshot();
  assert.equal(calls.length, 8);
  assert.ok(calls.every(({options}) => options.method === 'GET' && options.redirect === 'error' && options.credentials === 'omit'));
  assert.notEqual(calls[0].options.headers.Authorization, calls[4].options.headers.Authorization);
  assert.equal(JSON.stringify(first).includes('saved'), false);
  await client.forget();
  assert.equal(await client.hasPairing(), false);
  await assert.rejects(client.readSnapshot(), {code: 'not_paired'});
  assert.equal(calls.length, 8);
});

test('unauthorized reads never re-pair or delete credentials automatically', async () => {
  let count = 0; const store = memoryStore({secret: 'saved'});
  const client = createAuthenticatedClient({store, fetchImpl: async (_url, options) => {
    count++; assert.equal(options.method, 'GET'); return new Response('', {status: 401});
  }});
  await assert.rejects(client.readSnapshot(), {code: 'unauthorized'});
  assert.equal(count, 4); assert.equal((await store.get()).secret, 'saved');
});

test('snapshot preserves actual settings and independent units but strips filenames and unknown fields', () => {
  const source = structuredClone(fixture);
  source.secret = 'never-export'; source.library.entries[0].cut.params.secret = 'never-export';
  const snapshot = sanitizeSnapshot(source);
  assert.equal(snapshot.library.entries[0].cut.sub_layers[0].params.speed, 5000);
  assert.equal(snapshot.library.entries[0].cut.params.frequency, 200000);
  assert.equal(snapshot.library.entries[0].cut.params.galvo.laser_on_tc, 100);
  assert.equal(snapshot.project.name, 'artwork.lbrn2');
  assert.equal(snapshot.status.connected, false);
  assert.doesNotMatch(JSON.stringify(snapshot), /never-export|C:\/private/);
  assert.equal(sanitizeSnapshot({...fixture, library: {...fixture.library, entries: []}}).library.entries.length, 0);
  assert.throws(() => sanitizeSnapshot({...fixture, library: {product: 'millmage', entries: []}}));
  assert.throws(() => sanitizeSnapshot({...fixture, units: {units: 'mm/min'}}));
});

test('secret storage restricts access to trusted contexts and supports reload without sync storage', async () => {
  const records = {}; const calls = [];
  const local = {setAccessLevel: async value => calls.push(value), get: async () => records,
    set: async value => Object.assign(records, value), remove: async key => {delete records[key];}};
  const store = createCredentialStore(local);
  await store.set({secret: 'local-secret'});
  assert.equal((await createCredentialStore(local).get()).secret, 'local-secret');
  assert.ok(calls.every(call => call.accessLevel === 'TRUSTED_CONTEXTS'));
  await store.remove(); assert.equal(await store.get(), null);
});

test('forget during a read prevents the stale snapshot from being released', async () => {
  const store = memoryStore({secret: 'saved'});
  const client = createAuthenticatedClient({store, fetchImpl: async url => {
    await store.remove(); return readResponse(url);
  }});
  await assert.rejects(client.readSnapshot(), {code: 'not_paired'});
});

test('gantry and image parameters remain intact without unit conversion', () => {
  const source = structuredClone(fixture);
  const cut = source.library.entries[0].cut;
  cut.profile = 'gantry';
  cut.params.gantry = {force_constant_power: true, through_power: 50, lead_length: 2, auto_blower: true, dot_spacing: 0.1};
  const result = sanitizeSnapshot(source);
  assert.deepEqual(result.library.entries[0].cut.params.gantry, cut.params.gantry);
  cut.kind = 'image'; cut.params = {speed: 1000, dpi: 254, dither_mode: 'Stucki', q_pulse_width: 200};
  assert.deepEqual(sanitizeSnapshot(source).library.entries[0].cut.params, cut.params);
});
