import test from 'node:test';
import assert from 'node:assert/strict';
import {validateNativeFile, createSseParser, createNativeOpener} from '../dev_setup/lightburn-extension-poc/native-open.js';

const payload = {name: 'tiny.lbrn2', base64: Buffer.from('<?xml version="1.0"?><LightBurnProject><Shape Type="Rect"/></LightBurnProject>').toString('base64')};
const project = {filename: 'C:/test/blank.lbrn2', modified: false, shape_count: 0, device: {name: 'Test MOPA'}};
test('review reports offline and expired pairing with actionable recovery, without a POST', async () => {
  for (const [fetchImpl, expected] of [[async () => {throw new TypeError('Failed to fetch');}, /could not reach LightBurn/i],
    [async () => new Response('', {status: 401}), /pair again/i]]) {
    const opener = createNativeOpener({store: {get: async () => ({secret: 'test'})}, fetchImpl});
    await assert.rejects(opener.review(), expected);
  }
});
test('review timeout aborts the request and provides a recovery message', async () => {
  let signal;
  const opener = createNativeOpener({store: {get: async () => ({secret: 'test'})}, requestMs: 15,
    fetchImpl: async (_url, options) => {assert.equal(options.method, 'GET'); signal = options.signal; return new Promise(() => {});}});
  await assert.rejects(opener.review(), /did not respond in time/);
  assert.equal(signal.aborted, true);
});
function harness({mode = 'success', metadata = project} = {}) {
  const calls = []; const states = []; let eventStream; let projectReads = 0;
  const encode = text => new TextEncoder().encode(text);
  const emit = text => eventStream.enqueue(encode(text));
  const fetchImpl = async (url, options) => {
    calls.push({path: new URL(url).pathname, options});
    if (url.endsWith('/api/project')) {
      projectReads++;
      return Response.json(mode === 'changed' && projectReads >= 2 ? {...metadata, modified: true} : metadata);
    }
    if (url.endsWith('/api/events')) {
      if (mode === 'stream401') return new Response('', {status: 401});
      const stream = new ReadableStream({start(controller) {
        eventStream = controller;
        if (mode !== 'not-ready') emit(':connected\r\n\r\n');
        if (mode === 'interference') emit('event: file_imported\ndata: {"success":true}\n\n');
      }});
      return new Response(stream, {headers: {'Content-Type': 'text/event-stream'}});
    }
    assert.ok(url.endsWith('/api/file/open'));
    if (mode === 'slow-upload') {await new Promise(resolve => setTimeout(resolve, 150)); emit('event: file_imported\ndata: {"success":true}\n\n');}
    if (mode === 'post401') return new Response('', {status: 401});
    if (mode === 'network') throw new TypeError('Connection lost');
    if (mode === 'rejected') return new Response('', {status: 413});
    if (mode === 'early-event' || mode === 'success') emit('event: file_imported\ndata: {"success":true}\n\n');
    if (mode === 'negative') emit('event: file_imported\ndata: {"success":false,"error":"Invalid native file"}\n\n');
    if (mode === 'disconnect') eventStream.close();
    return new Response('', {status: 202});
  };
  const opener = createNativeOpener({store: {get: async () => ({secret: 'test-secret'})}, fetchImpl,
    readinessMs: 20, completionMs: 20, requestMs: 100, onState: state => states.push(state)});
  return {opener, calls, states};
}

test('native file validator enforces extension, canonical base64, size, and native XML root', () => {
  const file = validateNativeFile(payload);
  assert.equal(file.name, 'tiny.lbrn2'); assert.ok(file.bytes.length);
  for (const invalid of [{...payload, name: 'bad.svg'}, {...payload, name: '../bad.lbrn2'},
    {...payload, name: 'bad\r\nX-Header: a.lbrn2'}, {...payload, base64: '!!!!'},
    {...payload, base64: Buffer.from('<svg/>').toString('base64')},
    {...payload, base64: Buffer.from('<!DOCTYPE x><LightBurnProject/>').toString('base64')},
    {...payload, base64: Buffer.alloc(1048577).toString('base64')}]) assert.throws(() => validateNativeFile(invalid));
});

test('SSE parser handles split UTF8/CRLF, multiline data, comments, and ignores unrelated events', () => {
  let ready = 0; const events = [];
  const parser = createSseParser({onReady: () => ready++, onImport: event => events.push(event)});
  const bytes = new TextEncoder().encode(':connected\r\n\r\nevent: position\ndata: {}\n\nevent: file_imported\r\ndata: {"success":false,\r\ndata: "error":"échec"}\r\n\r\n');
  for (const byte of bytes) parser.push(Uint8Array.of(byte));
  assert.equal(ready, 1); assert.deepEqual(events, [{success: false, error: 'échec'}]);
  assert.throws(() => parser.push(new TextEncoder().encode('event: file_imported\ndata: invalid\n\n')));
});

test('SSE parser bounds unterminated frames', () => {
  const parser = createSseParser({onReady() {}, onImport() {}});
  assert.throws(() => parser.push(new TextEncoder().encode('x'.repeat(70000))));
});

test('confirmation and explicit unmodified project are required before any POST', async () => {
  for (const metadata of [{...project, modified: true}, {...project, modified: undefined}]) {
    const {opener, calls} = harness({metadata});
    const result = await opener.open(payload, {confirmed: true, reviewedProject: project});
    assert.equal(result.state, 'blocked'); assert.ok(calls.every(call => call.options.method === 'GET'));
  }
  const {opener, calls} = harness();
  assert.equal((await opener.open(payload, {confirmed: false, reviewedProject: project})).state, 'blocked');
  assert.equal(calls.length, 0);
});

test('project changed since review or while stream becomes ready cannot be replaced', async () => {
  for (const options of [{metadata: {...project, filename: 'other.lbrn2'}}, {mode: 'changed'}]) {
    const {opener, calls} = harness(options);
    assert.equal((await opener.open(payload, {confirmed: true, reviewedProject: project})).state, 'blocked');
    assert.ok(calls.every(call => call.options.method === 'GET'));
  }
});

test('stream readiness required; unrelated import before send blocks rather than falsely confirming', async () => {
  for (const mode of ['not-ready', 'interference']) {
    const {opener, calls} = harness({mode});
    assert.equal((await opener.open(payload, {confirmed: true, reviewedProject: project})).state, 'blocked');
    assert.ok(calls.every(call => call.options.method === 'GET'));
  }
});

test('raw native open succeeds only after event and metadata read, including event-before-202', async () => {
  const {opener, calls, states} = harness({mode: 'early-event'});
  const result = await opener.open(payload, {confirmed: true, reviewedProject: project});
  assert.equal(result.state, 'loaded');
  const post = calls.find(call => call.options.method === 'POST');
  assert.equal(post.path, '/api/file/open');
  assert.equal(post.options.headers['Content-Type'], 'application/octet-stream');
  assert.equal(post.options.headers['X-Filename'], 'tiny.lbrn2');
  assert.deepEqual(post.options.body, validateNativeFile(payload).bytes);
  assert.equal(post.options.redirect, 'error');
  assert.ok(calls.findIndex(call => call.path === '/api/events') < calls.indexOf(post));
  assert.equal(calls.at(-1).path, '/api/project');
  assert.ok(states.includes('accepted')); assert.equal(states.at(-1), 'loaded');
});

test('accepted without event, lost stream, and failed POST observation are unknown and never resent', async () => {
  for (const mode of ['timeout', 'disconnect', 'network']) {
    const {opener, calls} = harness({mode});
    const result = await opener.open(payload, {confirmed: true, reviewedProject: project});
    assert.equal(result.state, 'unknown');
    assert.equal(calls.filter(call => call.options.method === 'POST').length, 1);
  }
});

test('negative import event and explicit request rejection are failures, not successes', async () => {
  for (const mode of ['negative', 'rejected']) {
    const {opener, calls} = harness({mode});
    assert.equal((await opener.open(payload, {confirmed: true, reviewedProject: project})).state, 'failed');
    assert.equal(calls.filter(call => call.options.method === 'POST').length, 1);
  }
});
test('pairing rejected at stream or upload gives recovery instructions without retrying', async () => {
  for (const mode of ['stream401', 'post401']) {
    const {opener, calls} = harness({mode});
    const result = await opener.open(payload, {confirmed: true, reviewedProject: project});
    assert.equal(result.state, mode === 'stream401' ? 'blocked' : 'failed');
    assert.match(result.message, /pair again/i);
    assert.equal(calls.filter(call => call.options.method === 'POST').length, mode === 'stream401' ? 0 : 1);
  }
});


test('unknown results identify upload versus completion failure without retrying', async () => {
  for (const [mode, expected] of [['network', /Upload response could not be received/], ['no-event', /accepted the file.*completion event/i]]) {
    const {opener, calls} = harness({mode});
    const result = await opener.open(payload, {confirmed: true, reviewedProject: project});
    assert.equal(result.state, 'unknown');
    assert.match(result.message, expected);
    assert.match(result.message, /Check LightBurn/);
    assert.equal(calls.filter(call => call.path === '/api/file/open').length, 1);
  }
});

test('upload has a separate longer deadline than ordinary project requests', async () => {
  const {opener, calls} = harness({mode: 'slow-upload'});
  const result = await opener.open(payload, {confirmed: true, reviewedProject: project});
  assert.equal(result.state, 'loaded');
  assert.equal(calls.filter(call => call.path === '/api/file/open').length, 1);
});
