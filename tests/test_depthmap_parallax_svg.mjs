import assert from "node:assert/strict";
import test from "node:test";

import {
  createKrasnowParallaxSvg,
  grayscaleToGratingAngle,
  gratingCellSegments,
  parallaxCellIsEngraved,
} from "../static/depthmap_parallax_svg.js";

test("grayscale spans Krasnow's negative-to-positive angle range", () => {
  assert.equal(grayscaleToGratingAngle(0), -90);
  assert.equal(grayscaleToGratingAngle(255), 90);
  assert.ok(Math.abs(grayscaleToGratingAngle(127)) < 0.36);
});

test("every grating segment is clipped to its physical square cell", () => {
  for (const gray of [0, 63, 127, 191, 254]) {
    const segments = gratingCellSegments(gray, 0.4, 0.06);
    assert.ok(segments.length > 0);
    for (const segment of segments) {
      for (const coordinate of segment) {
        assert.ok(coordinate >= -1e-7 && coordinate <= 0.4000001);
      }
    }
  }
});

test("SVG uses millimeter dimensions and omits white background cells", async () => {
  const pixels = Uint8Array.from([255, 127]);
  const expectedSegments = gratingCellSegments(127, 0.4, 0.06).length;
  const blob = await createKrasnowParallaxSvg(pixels, 2, 1, {
    patchSize:0.4,
    lineSpacing:0.06,
    strokeWidth:0.01,
    yieldEveryRows:0,
  });
  const svg = await blob.text();

  assert.match(svg, /width="0\.8mm" height="0\.4mm"/);
  assert.match(svg, /viewBox="0 0 0\.8 0\.4"/);
  assert.match(svg, /stroke="#000000" stroke-width="0\.01"/);
  assert.equal((svg.match(/M/g) || []).length, expectedSegments);
  assert.doesNotMatch(svg, /<line/);
  assert.doesNotMatch(svg, /fetch\(|XMLHttpRequest/);
});

test("source detail dithers neutral cells but always preserves parallax edge ramps", async () => {
  assert.equal(parallaxCellIsEngraved(127, 0, 0, 0, "source-detail"), true);
  assert.equal(parallaxCellIsEngraved(127, 255, 1, 0, "source-detail"), false);
  assert.equal(parallaxCellIsEngraved(0, 255, 2, 0, "source-detail"), true);
  assert.equal(parallaxCellIsEngraved(255, 0, 3, 0, "source-detail"), false);

  const pixels = Uint8Array.from([127, 127, 0, 255]);
  const detailPixels = Uint8Array.from([0, 255, 255, 0]);
  const blob = await createKrasnowParallaxSvg(pixels, 4, 1, {
    appearanceMode:"source-detail",
    detailPixels,
    patchSize:0.4,
    lineSpacing:0.06,
    yieldEveryRows:0,
  });
  const svg = await blob.text();
  const expectedSegments = gratingCellSegments(127, 0.4, 0.06).length
    + gratingCellSegments(0, 0.4, 0.06).length;
  assert.equal((svg.match(/M/g) || []).length, expectedSegments);
});

test("SVG conversion rejects incomplete maps and unsafe geometry values", async () => {
  await assert.rejects(() => createKrasnowParallaxSvg(Uint8Array.of(127), 2, 1));
  await assert.rejects(() => createKrasnowParallaxSvg(Uint8Array.of(127), 1, 1, {lineSpacing:0}));
  await assert.rejects(() => createKrasnowParallaxSvg(Uint8Array.of(127), 1, 1, {
    appearanceMode:"source-detail",
  }), /source-luminance/);
});
