import test from 'node:test';
import assert from 'node:assert/strict';
import {createBridge, validateRequest} from '../dev_setup/lightburn-extension-poc/bridge-protocol.js';

const sender = {url: 'https://serverless-staging.mopa-laser-rasterizer.com/lightburn-connection-test.html', frameId: 0};
const request = {version: 1, id: 'test-1', command: 'getConnectionSummary'};
test('chunk protocol bounds messages and requires exact upload schemas', () => {
  const begin = {...request, command: 'beginNativeUpload', name: 'large.lbrn2'};
  assert.equal(validateRequest(begin, sender), true);
  const append = {...request, command: 'appendNativeUpload', uploadId: 'test', offset: 0, base64: btoa('hello')};
  assert.equal(validateRequest(append, sender), true);
  for (const invalid of [{...append, offset: -1}, {...append, offset: 262144000}, {...append, base64: 'x'.repeat(349529)}, {...append, url: 'http://elsewhere'}, {...begin, name: '../file.lbrn2'}]) assert.equal(validateRequest(invalid, sender), false);
});
test('website can stage a bounded native file but cannot confirm or open it', () => {
  const staged = {...request, command: 'prepareNativeImport', file: {name: 'tiny.lbrn2', base64: btoa('<LightBurnProject/>')}};
  assert.equal(validateRequest(staged, sender), true);
  assert.equal(validateRequest({...request, command: 'getNativeImportStatus'}, sender), true);
  for (const bad of [{...staged, confirmed: true}, {...staged, file: {...staged.file, url: 'http://evil'}},
    {...staged, file: {...staged.file, base64: 'x'.repeat(1400000)}}, {...request, command: 'openNativeFile'}]) assert.equal(validateRequest(bad, sender), false);
});
test('page confirmation requires an explicit reviewed-operation identifier', () => {
  assert.equal(validateRequest({...request, command: 'reviewNativeImport'}, sender), true);
  assert.equal(validateRequest({...request, command: 'confirmNativeImport', reviewId: 'review-123'}, sender), true);
  assert.equal(validateRequest({...request, command: 'confirmNativeImport'}, sender), false);
  assert.equal(validateRequest({...request, command: 'confirmNativeImport', reviewId: 'x'.repeat(81)}, sender), false);
  assert.equal(validateRequest({...request, command: 'discardNativeImport'}, sender), true);
  assert.equal(validateRequest({...request, command: 'getExtensionInfo'}, sender), true);
});

test('staged file forwarded once and status strips private fields', async () => {
  const bridge = createBridge(); const tab = port(); bridge.attach(tab);
  const file = {name: 'tiny.lbrn2', base64: btoa('<LightBurnProject/>')};
  const pending = bridge.handle({...request, command: 'prepareNativeImport', file}, sender);
  assert.deepEqual(tab.messages[0].file, file);
  tab.reply({id: tab.messages[0].id, result: {state: 'staged', name: file.name, size: 19, secret: 'private', project: {filename: 'C:/private'}}});
  const response = await pending;
  assert.equal(response.result.state, 'staged'); assert.doesNotMatch(JSON.stringify(response), /private|base64/);
});
function port() {
  const listeners = {};
  return {messages: [], onMessage: {addListener(fn) {listeners.message = fn;}},
    onDisconnect: {addListener(fn) {listeners.disconnect = fn;}},
    postMessage(message) {this.messages.push(message);},
    reply(message) {listeners.message(message);}, disconnect() {listeners.disconnect();}};
}

test('only exact staging origin, top frame, version and bounded read-only command allowed', () => {
  assert.equal(validateRequest(request, sender), true);
  for (const url of ['http://serverless-staging.mopa-laser-rasterizer.com/',
    'https://serverless-staging.mopa-laser-rasterizer.com.evil.test/', 'https://evil.test/', 'file:///test']) {
    assert.equal(validateRequest(request, {...sender, url}), false);
  }
  for (const message of [null, {}, {...request, version: 2}, {...request, command: 'pair'},
    {...request, url: 'http://elsewhere'}, {...request, id: 'x'.repeat(81)}]) {
    assert.equal(validateRequest(message, sender), false);
  }
  assert.equal(validateRequest(request, {...sender, frameId: 1}), false);
});

test('closed console and denied request have explicit failures without network activity', async () => {
  const bridge = createBridge();
  assert.equal((await bridge.handle(request, sender)).error, 'console_closed');
  assert.equal((await bridge.handle({...request, command: 'pair'}, sender)).error, 'denied');
});

test('routes one read-only probe and returns only sanitized connection fields', async () => {
  const bridge = createBridge(); const tab = port(); bridge.attach(tab);
  const response = bridge.handle(request, sender);
  assert.equal(tab.messages[0].command, 'getConnectionSummary');
  tab.reply({id: tab.messages[0].id, result: {ok: true, secret: 'must-not-leak',
    checks: [{path: '/', status: 200, expected: 200, ok: true},
      {path: '/api/status', status: 401, expected: 401, ok: true}]}});
  const result = await response;
  assert.equal(result.ok, true); assert.equal(result.id, request.id);
  assert.equal(result.result.ok, true);
  assert.equal(JSON.stringify(result).includes('must-not-leak'), false);
});

test('concurrent requests are rejected and disconnect completes pending request without replay', async () => {
  const bridge = createBridge(); const tab = port(); bridge.attach(tab);
  const pending = bridge.handle(request, sender);
  assert.equal((await bridge.handle({...request, id: 'test-2'}, sender)).error, 'busy');
  tab.disconnect();
  assert.equal((await pending).error, 'console_closed');
  assert.equal(tab.messages.length, 1);
  assert.equal((await bridge.handle(request, sender)).error, 'console_closed');
});

test('missing reply times out, unrelated reply ignored, later request can succeed', async () => {
  const bridge = createBridge({timeoutMs: 15}); const tab = port(); bridge.attach(tab);
  const pending = bridge.handle(request, sender);
  tab.reply({id: 'unrelated', result: {ok: true}});
  assert.equal((await pending).error, 'timeout');
  assert.equal(tab.messages.length, 1);
  tab.disconnect();
});

test('malformed result cannot claim successful transport', async () => {
  const bridge = createBridge(); const tab = port(); bridge.attach(tab);
  const pending = bridge.handle(request, sender);
  tab.reply({id: tab.messages[0].id, result: {ok: true, checks: []}});
  assert.equal((await pending).error, 'invalid_response');
  tab.disconnect();
});

test('library read is allowed but pairing and forgetting stay extension-only', async () => {
  const message = {...request, command: 'readMaterialLibrary'};
  assert.equal(validateRequest(message, sender), true);
  assert.equal(validateRequest({...request, command: 'forget'}, sender), false);
  const bridge = createBridge(); const tab = port(); bridge.attach(tab);
  const pending = bridge.handle(message, sender);
  assert.equal(tab.messages[0].command, 'readMaterialLibrary');
  tab.reply({id: tab.messages[0].id, result: {secret: 'no-leak', status: {connected: false},
    project: {filename: 'C:/private/example.lbrn2'}, units: {units: 'mm/s', distance_units: 'mm'},
    library: {product: 'lightburn', name: 'Selected library', filename: 'C:/private/library.clb', entries: []}}});
  const response = await pending;
  assert.equal(response.ok, true);
  assert.equal(response.result.library.name, 'Selected library');
  assert.doesNotMatch(JSON.stringify(response), /no-leak|C:\/private/);
});

test('unpaired/unauthorized library errors are bounded codes, never raw server text', async () => {
  const bridge = createBridge(); const tab = port(); bridge.attach(tab);
  const pending = bridge.handle({...request, command: 'readMaterialLibrary'}, sender);
  tab.reply({id: tab.messages[0].id, error: 'not_paired', secret: 'no-leak'});
  assert.deepEqual(await pending, {version: 1, id: request.id, ok: false, error: 'not_paired'});
});
