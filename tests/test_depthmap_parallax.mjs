import assert from "node:assert/strict";
import test from "node:test";

import {createKrasnowParallaxPixels} from "../static/depthmap_parallax.js";

test("flat foreground becomes a neutral angle bounded by blank background", () => {
  const depth = Float32Array.from([0, 0, 0.5, 0.5, 0, 0]);
  const result = createKrasnowParallaxPixels(depth, 6, 1, {
    scaleFactor:0.06,
    backgroundCutoff:0.01,
  });
  assert.deepEqual([...result], [255, 255, 127, 127, 127, 255]);
});

test("an explicit mask keeps zero as a valid imported depth", () => {
  const result = createKrasnowParallaxPixels(Float32Array.of(1, 0, 0, 1), 4, 1, {
    scaleFactor:0,
    backgroundCutoff:0.5,
    backgroundMask:Uint8Array.of(1, 0, 0, 1),
  });
  assert.deepEqual([...result], [255, 127, 127, 127]);
});

test("near depth creates opposite horizontal ramps at the two boundaries", () => {
  const depth = Float32Array.from([0, 0, 1, 1, 0, 0]);
  const result = createKrasnowParallaxPixels(depth, 6, 1, {
    scaleFactor:1,
    backgroundCutoff:0,
  });
  assert.deepEqual([...result], [0, 63, 127, 127, 127, 255]);
});

test("horizontal conversion never spills across scanlines", () => {
  const depth = Float32Array.from([
    0, 1, 1,
    0, 0, 0,
  ]);
  const result = createKrasnowParallaxPixels(depth, 3, 2, {
    scaleFactor:1,
    backgroundCutoff:0,
  });
  assert.deepEqual([...result].slice(3), [255, 255, 255]);
});

test("inverted Lab depth still derives background from physical far depth", () => {
  const depth = Float32Array.from([1, 1, 0.5, 1]);
  const result = createKrasnowParallaxPixels(depth, 4, 1, {
    scaleFactor:0.06,
    backgroundCutoff:0,
    inverted:true,
  });
  assert.deepEqual([...result], [255, 255, 127, 127]);
});

test("an explicit white background mask preserves imported Krasnow depth values", () => {
  const depth = Float32Array.from([1, 1, 40 / 254, 40 / 254, 1, 1]);
  const backgroundMask = Uint8Array.from([1, 1, 0, 0, 1, 1]);
  const result = createKrasnowParallaxPixels(depth, 6, 1, {
    scaleFactor:0.06,
    backgroundCutoff:0,
    backgroundMask,
  });
  assert.deepEqual([...result], [255, 191, 127, 127, 127, 0]);
});

test("an incomplete explicit background mask is rejected", () => {
  assert.throws(() => createKrasnowParallaxPixels(Float32Array.of(0, 1), 2, 1, {
    backgroundMask:Uint8Array.of(1),
  }), /complete background mask/);
});
