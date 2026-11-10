import test from 'node:test';
import assert from 'node:assert/strict';
import {createImportController} from '../dev_setup/lightburn-extension-poc/import-controller.js';
const file = {name: 'tiny.lbrn2', base64: btoa('<LightBurnProject/>')};
test('interrupted staging survives worker recreation for explicit discard, never opens', async () => {
  const f = fixture(), controller = f.make(); await controller.beginUpload('partial.lbrn2', 'tab');
  const restored = f.make(); assert.equal((await restored.status('tab')).state, 'uploading');
  await assert.rejects(restored.review('tab'));
  await restored.discard('tab'); assert.equal((await restored.status('tab')).state, 'idle');
  assert.equal(f.posts(), 0);
});
test('chunked upload reserves one owner and journals only the binary file reference', async () => {
  const f = fixture(), controller = f.make();
  const upload = await controller.beginUpload('large.lbrn2', 'tab-1');
  await assert.rejects(controller.beginUpload('other.lbrn2', 'tab-2'));
  await assert.rejects(controller.finishUpload(upload.uploadId, 262144000, 'tab-2'));
  await assert.rejects(controller.finishUpload(upload.uploadId, 262144001, 'tab-1'));
  await controller.finishUpload(upload.uploadId, 262144000, 'tab-1');
  const saved = await f.storage.get();
  assert.deepEqual(saved.file, {name: 'large.lbrn2', fileId: upload.uploadId});
  assert.ok(JSON.stringify(saved).length < 4096);
});
function fixture() {
  let saved, posts = 0, complete;
  const storage = {get: async () => structuredClone(saved), set: async value => {saved = structuredClone(value);}};
  const opener = {review: async () => ({filename: 'blank', modified: false, shape_count: 0}),
    open: async () => {posts++; return new Promise(resolve => {complete = resolve;});}};
  return {storage, opener, make: () => createImportController({storage, opener}), posts: () => posts,
    complete: () => complete({state: 'loaded', message: 'Loaded.'})};
}
test('stage survives UI and worker recreation, duplicate cannot overwrite it', async () => {
  const f = fixture(); const first = f.make(); await first.stage(file);
  const second = f.make(); assert.equal((await second.status()).state, 'staged');
  await assert.rejects(second.stage(file)); assert.equal(f.posts(), 0);
});
test('confirmation must match review and opening continues without its page dialog', async () => {
  const f = fixture(), controller = f.make(); await controller.stage(file);
  await assert.rejects(controller.open('wrong')); assert.equal(f.posts(), 0);
  const review = await controller.review();
  const pending = controller.open(review.reviewId);
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal((await controller.status()).state, 'opening');
  await assert.rejects(controller.open(review.reviewId));
  f.complete(); await pending;
  assert.equal((await f.make().status()).state, 'loaded'); assert.equal(f.posts(), 1);
});
test('another tab cannot read, review, confirm, or discard a staged import', async () => {
  const f = fixture(), controller = f.make(); await controller.stage(file, 'tab-1');
  const review = await controller.review('tab-1');
  for (const attempt of [() => controller.status('tab-2'), () => controller.review('tab-2'),
    () => controller.open(review.reviewId, 'tab-2'), () => controller.discard('tab-2')]) await assert.rejects(attempt());
  assert.equal(f.posts(), 0);
});
test('closing the owner tab releases its result without cancelling or repeating the import', async () => {
  const f = fixture(), controller = f.make(); await controller.stage(file, 'tab-1');
  const review = await controller.review('tab-1'); const pending = controller.open(review.reviewId, 'tab-1');
  await new Promise(resolve => setTimeout(resolve, 0));
  await controller.releaseOwner('tab-1'); f.complete(); await pending;
  assert.equal((await controller.status('tab-2')).state, 'loaded'); assert.equal(f.posts(), 1);
});
test('worker interruption recovers unknown without retaining a resendable file', async () => {
  const f = fixture(), controller = f.make(); await controller.stage(file);
  const review = await controller.review(); const pending = controller.open(review.reviewId);
  await new Promise(resolve => setTimeout(resolve, 0));
  const restarted = f.make(); assert.equal((await restarted.status()).state, 'unknown');
  await assert.rejects(restarted.review()); await assert.rejects(restarted.open(review.reviewId));
  assert.equal(f.posts(), 1); f.complete(); await pending;
});
test('failed journal write prevents any open and public status never includes bytes', async () => {
  const f = fixture(); let fail = false;
  const controller = createImportController({opener: f.opener, storage: {...f.storage, set: async value => {if (fail) throw new Error('disk'); await f.storage.set(value);}}});
  await controller.stage(file); const review = await controller.review(); fail = true;
  await assert.rejects(controller.open(review.reviewId)); assert.equal(f.posts(), 0);
  assert.doesNotMatch(JSON.stringify(await controller.status()), /base64|LightBurnProject/);
});
