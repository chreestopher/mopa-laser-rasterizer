import assert from "node:assert/strict";
import test from "node:test";
import {
  createReliefLayers,
  createReliefLightBurn,
  prepareReliefDepth,
  reliefThresholds,
  traceMaskContours,
} from "../static/depthmap_layered_relief.js";

test("linear thresholds and cumulative layers progress from rear to front", () => {
  const depth = Float32Array.of(0, .25, .5, .75, 1);
  const relief = createReliefLayers(depth, 5, 1, {layers:4});
  assert.deepEqual(relief.thresholds.map(value => Number(value.toFixed(2))), [0, .25, .5, .75]);
  assert.deepEqual(relief.layers.map(layer => [...layer.mask].reduce((a, b) => a + b, 0)), [5, 4, 3, 2]);
});

test("inversion and explicit background are honored", () => {
  const relief = createReliefLayers(Float32Array.of(0, .5, 1), 3, 1, {
    layers:2,
    inverted:true,
    backgroundMask:Uint8Array.of(0, 1, 0),
  });
  assert.deepEqual([...relief.layers[0].mask], [1, 0, 1]);
  assert.deepEqual([...relief.layers[1].mask], [1, 0, 0]);
});

test("equal-area thresholds use the depth distribution", () => {
  const values = Float32Array.of(0, 0, 0, .1, .9, 1, 1, 1);
  const thresholds = reliefThresholds(values, null, 4, false, "equal-area");
  assert.equal(thresholds.length, 4);
  assert.ok(thresholds[1] < .1);
  assert.ok(thresholds[3] >= .9);
});

test("natural grouping finds meaningful depth clusters", () => {
  const values = Float32Array.of(0, .01, .02, .45, .46, .47, .90, .91, .92);
  const relief = createReliefLayers(values, 9, 1, {
    layers:3,
    spacing:"natural",
    groupingStrength:1,
    construction:"separated",
  });
  assert.equal(relief.layers.length, 3);
  assert.ok(relief.thresholds[1] > .02 && relief.thresholds[1] <= .45);
  assert.ok(relief.thresholds[2] > .47 && relief.thresholds[2] <= .90);
  assert.deepEqual(relief.layers.map(layer => [...layer.mask].reduce((a, b) => a + b, 0)), [3, 3, 3]);
});

test("natural grouping avoids empty bands when distinct depth data is limited", () => {
  const relief = createReliefLayers(Float32Array.of(0, 0, .5, .5, 1, 1), 6, 1, {
    layers:7,
    spacing:"natural",
    groupingStrength:1,
    construction:"separated",
  });
  assert.equal(relief.requestedLayerCount, 7);
  assert.equal(relief.layers.length, 3);
  assert.deepEqual(relief.layers.map(layer => [...layer.mask].reduce((a, b) => a + b, 0)), [2, 2, 2]);
});

test("surface smoothing removes shallow noise without crossing a strong edge", () => {
  const depth = Float32Array.of(.2, .2, .9, .2, .25, .9, .2, .2, .9);
  const prepared = prepareReliefDepth(depth, 3, 3, null, false, 1);
  assert.ok(Math.abs(prepared[4] - .2) < .001);
  assert.ok(Math.abs(prepared[2] - .9) < .001);
  assert.ok(Math.abs(prepared[5] - .9) < .001);
});

test("manual boundaries directly control exported relief masks", () => {
  const relief = createReliefLayers(Float32Array.of(.1, .3, .5, .7, .9), 5, 1, {
    layers:5,
    thresholds:[.1, .4, .8],
    construction:"separated",
  });
  assert.deepEqual(relief.thresholds.map(value => Number(value.toFixed(3))), [.1, .4, .8]);
  assert.deepEqual(relief.layers.map(layer => [...layer.mask].reduce((a, b) => a + b, 0)), [2, 2, 1]);
});

test("contour tracing produces closed outer and hole boundaries", () => {
  const mask = Uint8Array.of(1,1,1, 1,0,1, 1,1,1);
  const contours = traceMaskContours(mask, 3, 3);
  assert.equal(contours.length, 2);
  for (const contour of contours) assert.deepEqual(contour[0], contour.at(-1));
});

test("LightBurn layers share workbed coordinates and use safe placeholder settings", () => {
  const relief = createReliefLayers(Float32Array.of(1, 1, 1, 1), 2, 2, {layers:2});
  const project = createReliefLightBurn(relief, {pixelSizeMm:1, workbedWidthMm:10, workbedHeightMm:8});
  assert.match(project, /<LightBurnProject AppVersion="2\.1\.04" FormatVersion="1"/);
  assert.equal((project.match(/<maxPower Value="0"\/>/g) || []).length, 2);
  assert.ok((project.match(/<Shape Type="Path" CutIndex="\d+" VertID="\d+" PrimID="\d+">/g) || []).length >= 2);
  assert.doesNotMatch(project, /ShapeID=/);
  assert.match(project, /V4 3c0x1c1x1/);
  assert.match(project, /V6 5c0x1c1x1/);
});

test("LightBurn path geometry uses unique modern vertex and primitive identifiers", () => {
  const relief = createReliefLayers(Float32Array.of(0, 1, 0, 1), 2, 2, {layers:2});
  const project = createReliefLightBurn(relief, {pixelSizeMm:1});
  const identifiers = [...project.matchAll(/<Shape Type="Path" CutIndex="\d+" VertID="(\d+)" PrimID="(\d+)">/g)];
  assert.ok(identifiers.length >= 2);
  assert.equal(new Set(identifiers.map(match => match[1])).size, identifiers.length);
  assert.equal(new Set(identifiers.map(match => match[2])).size, identifiers.length);
  assert.ok(identifiers.every(match => match[1] === match[2]));
});

test("multi-layer LightBurn project keeps every relief slice aligned and ordered", () => {
  const relief = createReliefLayers(Float32Array.of(0, .25, .5, .75, 1), 5, 1, {layers:3});
  const project = createReliefLightBurn(relief, {pixelSizeMm:1, workbedWidthMm:9, workbedHeightMm:5, materialThicknessMm:3});
  assert.equal((project.match(/<CutSetting type="Cut">/g) || []).length, 3);
  assert.match(project, /Layer 01 of 03 - BACK/);
  assert.match(project, /Layer 03 of 03 - FRONT/);
  assert.match(project, /<hide Value="0"\/>/);
  assert.equal((project.match(/<hide Value="1"\/>/g) || []).length, 2);
  assert.match(project, /CutIndex="0"/);
  assert.match(project, /CutIndex="1"/);
  assert.match(project, /CutIndex="2"/);
  assert.match(project, /enable Output for exactly one layer/);
});
