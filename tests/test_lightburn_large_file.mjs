import test from 'node:test';
import assert from 'node:assert/strict';
import {validateNativeBytes, MAX_NATIVE_BYTES} from '../dev_setup/lightburn-extension-poc/native-open.js';
import {uploadNativeFile} from '../serverless_web/lightburn-integration.js';
test('native byte path accepts exactly 100 MiB and rejects one byte over', () => {
  assert.equal(MAX_NATIVE_BYTES, 100 * 1024 * 1024);
  const bytes = new Uint8Array(MAX_NATIVE_BYTES).fill(32);
  bytes.set(new TextEncoder().encode('<LightBurnProject/>'));
  assert.equal(validateNativeBytes({name: 'large.lbrn2', bytes}).bytes.length, MAX_NATIVE_BYTES);
  assert.throws(() => validateNativeBytes({name: 'large.lbrn2', bytes: new Uint8Array(MAX_NATIVE_BYTES + 1)}));
});
test('web download streams bounded messages, preserving bytes, and cleans up oversize upload', async () => {
  const input = new Uint8Array(2 * 1024 * 1024 + 7).fill(32); input.set(new TextEncoder().encode('<LightBurnProject/>'));
  const chunks = []; let ended = false;
  const send = async (command, fields) => {
    if (command === 'beginNativeUpload') return {uploadId: 'test'};
    if (command === 'appendNativeUpload') {assert.ok(fields.base64.length <= 349528); assert.equal(fields.offset, chunks.reduce((n, s) => n + s.length, 0)); chunks.push(atob(fields.base64));}
    if (command === 'finishNativeUpload') {ended = true; return {state: 'staged'};}
  };
  assert.equal((await uploadNativeFile('https://example.test/file', 'large.lbrn2', send, () => {}, async () => new Response(input))).state, 'staged');
  assert.equal(ended, true); assert.deepEqual(Uint8Array.from(chunks.join(''), x => x.charCodeAt(0)), input);
  let began = false;
  await assert.rejects(uploadNativeFile('https://example.test/file', 'large.lbrn2', async () => {began = true;}, () => {}, async () => new Response('', {headers: {'Content-Length': String(MAX_NATIVE_BYTES + 1)}})), /100 MiB/);
  assert.equal(began, false);
  const calls = [];
  await assert.rejects(uploadNativeFile('https://example.test/file', 'large.lbrn2', async command => {calls.push(command); return {uploadId: 'test'};}, () => {}, async () => new Response(new Uint8Array(MAX_NATIVE_BYTES + 1))), /100 MiB/);
  assert.deepEqual(calls, ['beginNativeUpload', 'discardNativeImport']);
});
