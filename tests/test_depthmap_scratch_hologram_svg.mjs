import assert from "node:assert/strict";
import test from "node:test";

import {
  createScratchHologramArcs,
  createScratchHologramSvg,
} from "../static/depthmap_scratch_hologram_svg.js";

test("relative depth controls scratch radius while preserving highlight position", () => {
  const geometry = createScratchHologramArcs(Float32Array.from([1, 0]), 2, 1, {
    backgroundMask:Uint8Array.from([0, 0]),
    pixelSize:1,
    sampleStep:1,
    nearDepth:2,
    depthRange:8,
    viewSweep:60,
    backgroundCutoff:0,
  });
  assert.equal(geometry.arcs.length, 2);
  assert.equal(geometry.arcs[0].radius, 1);
  assert.equal(geometry.arcs[1].radius, 5);
  assert.equal(geometry.physicalWidth, 2);
  assert.equal(geometry.physicalHeight, 1);
  for (const arc of geometry.arcs) {
    assert.ok(arc.startX >= 0 && arc.startX <= geometry.physicalWidth);
    assert.ok(arc.endX >= 0 && arc.endX <= geometry.physicalWidth);
    assert.ok(arc.startY >= 0 && arc.startY <= geometry.physicalHeight);
    assert.ok(arc.endY >= 0 && arc.endY <= geometry.physicalHeight);
  }
});

test("explicit background and generated-depth cutoff omit background samples", () => {
  const explicit = createScratchHologramArcs(Float32Array.from([0.8, 0.8]), 2, 1, {
    backgroundMask:Uint8Array.from([1, 0]),
    sampleStep:1,
  });
  assert.equal(explicit.arcs.length, 1);

  const inferred = createScratchHologramArcs(Float32Array.from([0, 0.5]), 2, 1, {
    sampleStep:1,
    backgroundCutoff:0.01,
  });
  assert.equal(inferred.arcs.length, 1);
});

test("geometry automatically coarsens sampling to enforce the arc limit", () => {
  const depth = new Float32Array(100).fill(0.5);
  const geometry = createScratchHologramArcs(depth, 10, 10, {
    sampleStep:1,
    backgroundCutoff:0,
    maxArcs:9,
  });
  assert.ok(geometry.effectiveSampleStep > 1);
  assert.ok(geometry.arcs.length <= 9);
});

test("SVG contains open circular arcs, millimeter sizing, and a clipping boundary", async () => {
  const result = await createScratchHologramSvg(Float32Array.from([0.25, 0.75]), 2, 1, {
    pixelSize:0.5,
    sampleStep:1,
    nearDepth:1,
    depthRange:3,
    viewSweep:60,
    backgroundCutoff:0,
    strokeWidth:0.01,
    yieldEveryArcs:0,
  });
  const svg = await result.blob.text();
  assert.match(svg, /width="1mm" height="0\.5mm"/);
  assert.match(svg, /clipPath/);
  assert.match(svg, /stroke-width="0\.01"/);
  assert.equal((svg.match(/ A/g) || []).length, 2);
  assert.doesNotMatch(svg, /\bZ\b/);
  assert.doesNotMatch(svg, /fetch\(|XMLHttpRequest/);
});

test("invalid scratch geometry values are rejected", async () => {
  assert.throws(() => createScratchHologramArcs(Float32Array.of(0.5), 2, 1));
  assert.throws(() => createScratchHologramArcs(Float32Array.of(0.5), 1, 1, {viewSweep:180}));
  await assert.rejects(() => createScratchHologramSvg(Float32Array.of(0), 1, 1));
});
