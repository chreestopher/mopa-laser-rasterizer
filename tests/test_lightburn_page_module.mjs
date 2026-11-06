import test from 'node:test';
import assert from 'node:assert/strict';
import {uploadNativeFile} from '../serverless_web/lightburn-integration.js';
test('native download omits credentials, rejects HTTP, and discards interrupted chunks', async () => {
  const commands = [];
  const send = async command => {commands.push(command); if (command === 'appendNativeUpload') throw new Error('Storage full'); return {uploadId: 'test'};};
  await assert.rejects(uploadNativeFile('https://example.test/file', 'test.lbrn2', send, () => {}, async (_url, options) => {
    assert.equal(options.credentials, 'omit'); return new Response('<LightBurnProject/>');
  }), /Storage full/);
  assert.deepEqual(commands, ['beginNativeUpload', 'appendNativeUpload', 'discardNativeImport']);
  await assert.rejects(uploadNativeFile('http://example.test/file', 'test.lbrn2', send));
});
test('an interrupted transfer with failed cleanup tells the user to discard partial data', async () => {
  const send = async command => {if (command === 'beginNativeUpload') return {uploadId: 'test'}; throw new Error('Extension unavailable');};
  await assert.rejects(uploadNativeFile('https://example.test/file', 'test.lbrn2', send, () => {}, async () => new Response('<LightBurnProject/>')), /Discard \/ clear result/);
});
