import assert from "node:assert/strict";
import test from "node:test";
import {
  createReliefLayers,
  createReliefLightBurn,
  prepareReliefDepth,
  reliefLayerPlan,
  reliefVisibleMasks,
  reliefThresholds,
  traceMaskContours,
} from "../static/depthmap_layered_relief.js";

const labelsSetting = {
  description:"Labels",
  material:"Stainless steel",
  type:"Scan",
  settings:{minPower:"12", maxPower:"18", speed:"900", frequency:"300000", QPulseWidth:"51", interval:"0.01", LinkPath:"Stainless steel/Colors/Labels", hide:"1", doOutput:"0"},
};

const photoSetting = {
  description:"Photo",
  material:"Stainless steel",
  type:"Image",
  settings:{minPower:"8", maxPower:"20", speed:"1200", interval:"0.025", ditherMode:"stucki", LinkPath:"Stainless steel/Photo"},
};

test("total relief depth and stock thickness derive physical and LightBurn layer counts", () => {
  const plan = reliefLayerPlan(10, 3, false);
  assert.equal(plan.layerCount, 3);
  assert.equal(plan.actualDepthMm, 9);
  assert.equal(plan.lightBurnLayerCount, 3);
  assert.equal(plan.valid, true);

  const engraved = reliefLayerPlan(21, 3, true);
  assert.equal(engraved.layerCount, 7);
  assert.equal(engraved.lightBurnLayerCount, 14);
  assert.equal(engraved.valid, true);
});

test("derived layer plans fail instead of silently exceeding LightBurn's layer budget", () => {
  const contourOnly = reliefLayerPlan(93, 3, false);
  assert.equal(contourOnly.layerCount, 31);
  assert.equal(contourOnly.lightBurnLayerCount, 31);
  assert.equal(contourOnly.valid, false);
  assert.match(contourOnly.message, /LightBurn supports 30/);

  const engraved = reliefLayerPlan(48, 3, true);
  assert.equal(engraved.layerCount, 16);
  assert.equal(engraved.lightBurnLayerCount, 32);
  assert.equal(engraved.valid, false);
  assert.match(engraved.message, /disable surface engraving/);

  const tooShallow = reliefLayerPlan(3, 3, false);
  assert.equal(tooShallow.valid, false);
  assert.match(tooShallow.message, /at least 2/);
});

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

test("visible surface masks assign every stacked pixel to only its frontmost sheet", () => {
  const relief = createReliefLayers(Float32Array.of(0, .25, .5, .75, 1), 5, 1, {layers:3});
  const visible = reliefVisibleMasks(relief);
  assert.deepEqual(visible.map(mask => [...mask].reduce((sum, value) => sum + value, 0)), [2, 1, 2]);
  for (let index = 0; index < 5; index += 1) {
    assert.equal(visible.reduce((sum, mask) => sum + mask[index], 0), 1);
  }
});

test("LightBurn layers share workbed coordinates and copy the selected palette setting", () => {
  const relief = createReliefLayers(Float32Array.of(1, 1, 1, 1), 2, 2, {layers:2});
  const project = createReliefLightBurn(relief, {pixelSizeMm:1, workbedWidthMm:10, workbedHeightMm:8, cutSetting:labelsSetting});
  assert.match(project, /<LightBurnProject AppVersion="2\.1\.04" FormatVersion="1"/);
  assert.equal((project.match(/<CutSetting type="Scan">/g) || []).length, 2);
  assert.equal((project.match(/<maxPower Value="18"\/>/g) || []).length, 2);
  assert.equal((project.match(/<frequency Value="300000"\/>/g) || []).length, 2);
  assert.equal((project.match(/<doOutput Value="1"\/>/g) || []).length, 2);
  assert.equal((project.match(/<hide Value="0"\/>/g) || []).length, 2);
  assert.doesNotMatch(project, /<maxPower Value="0"\/>/);
  assert.doesNotMatch(project, /<LinkPath\b/);
  assert.ok((project.match(/<Shape Type="Path" ShapeID="\d+" CutIndex="\d+">/g) || []).length >= 2);
  assert.doesNotMatch(project, /VertID=|PrimID=|c0x1c1x1/);
  assert.match(project, /\n\s+V4 3\n/);
  assert.match(project, /\n\s+V6 5\n/);
  assert.ok(project.indexOf("<CutSetting") < project.indexOf("<Shape"));
  assert.ok(project.indexOf("<Shape") < project.indexOf("<Notes"));
});

test("LightBurn geometry uses unique ShapeID values and proven path encoding", () => {
  const relief = createReliefLayers(Float32Array.of(0, 1, 0, 1), 2, 2, {layers:2});
  const project = createReliefLightBurn(relief, {pixelSizeMm:1, registrationHoles:true, registrationDiameterMm:.5, registrationInsetMm:.5, cutSetting:labelsSetting});
  const identifiers = [...project.matchAll(/<Shape Type="(?:Path|Ellipse)" ShapeID="(\d+)"/g)].map(match => match[1]);
  assert.ok(identifiers.length >= 10);
  assert.equal(new Set(identifiers).size, identifiers.length);
  assert.match(project, /<VertList>\n\s+V\S+ \S+(?:\n\s+V\S+ \S+)+\n\s+<\/VertList>/);
  assert.doesNotMatch(project, /VertID=|PrimID=|c0x1c1x1/);
});

test("multi-layer LightBurn project keeps every relief slice aligned and ordered", () => {
  const relief = createReliefLayers(Float32Array.of(0, .25, .5, .75, 1), 5, 1, {layers:3});
  const project = createReliefLightBurn(relief, {pixelSizeMm:1, workbedWidthMm:9, workbedHeightMm:5, materialThicknessMm:3, cutSetting:labelsSetting});
  assert.equal((project.match(/<CutSetting type="Scan">/g) || []).length, 3);
  assert.match(project, /Layer 01 of 03 - BACK/);
  assert.match(project, /Layer 03 of 03 - FRONT/);
  assert.match(project, /<hide Value="0"\/>/);
  assert.equal((project.match(/<hide Value="0"\/>/g) || []).length, 3);
  assert.match(project, /CutIndex="0"/);
  assert.match(project, /CutIndex="1"/);
  assert.match(project, /CutIndex="2"/);
  assert.match(project, /enable Output for exactly one layer/);
});

test("LightBurn export requires a saved palette setting", () => {
  const relief = createReliefLayers(Float32Array.of(1, 1, 1, 1), 2, 2, {layers:2});
  assert.throws(() => createReliefLightBurn(relief, {pixelSizeMm:1}), /Choose a saved Swatch Palette and setting/);
});

test("optional surface engraving embeds aligned bitmap layers and preserves Photo image settings", () => {
  const relief = createReliefLayers(Float32Array.of(0, .25, .5, .75, 1), 5, 1, {layers:3});
  const photoImages = relief.layers.map((_, index) => ({width:5, height:1, data:`cG5nLWRhdGEt${index}`, fileName:`surface-${index + 1}.png`}));
  const project = createReliefLightBurn(relief, {
    pixelSizeMm:1,
    workbedWidthMm:9,
    workbedHeightMm:5,
    cutSetting:labelsSetting,
    surfaceEngraving:true,
    photoSetting,
    photoImages,
  });
  assert.equal((project.match(/<CutSetting type="Scan">/g) || []).length, 3);
  assert.equal((project.match(/<CutSetting_Img type="Image">/g) || []).length, 3);
  assert.equal((project.match(/<Shape Type="Bitmap"/g) || []).length, 3);
  assert.equal((project.match(/<ditherMode Value="stucki"\/>/g) || []).length, 3);
  assert.match(project, /Layer 01 of 03 - BACK - Photo/);
  assert.match(project, /Layer 01 of 03 - BACK - Cut/);
  assert.match(project, /<Shape Type="Bitmap" ShapeID="1" CutIndex="0" W="5" H="1"/);
  assert.match(project, /<XForm>1 0 0 1 4\.5 2\.5<\/XForm>/);
  assert.match(project, /<Shape Type="Path" ShapeID="2" CutIndex="1">/);
  assert.match(project, /CutIndex="5"/);
  assert.doesNotMatch(project, /<LinkPath\b/);
  assert.match(project, /Engrave Photo first, then run Cut/);
});

test("surface engraving requires a selected Photo setting", () => {
  const relief = createReliefLayers(Float32Array.of(0, 1), 2, 1, {layers:2});
  assert.throws(() => createReliefLightBurn(relief, {pixelSizeMm:1, cutSetting:labelsSetting, surfaceEngraving:true}), /Choose a Photo setting/);
});

test("surface engraving requires an Image setting and one bitmap per sheet", () => {
  const relief = createReliefLayers(Float32Array.of(0, 1), 2, 1, {layers:2});
  assert.throws(() => createReliefLightBurn(relief, {
    pixelSizeMm:1,
    cutSetting:labelsSetting,
    surfaceEngraving:true,
    photoSetting:labelsSetting,
    photoImages:[],
  }), /must use LightBurn Image mode/);
  assert.throws(() => createReliefLightBurn(relief, {
    pixelSizeMm:1,
    cutSetting:labelsSetting,
    surfaceEngraving:true,
    photoSetting,
    photoImages:[{width:2, height:1, data:"cG5n"}],
  }), /Every Layered Relief sheet needs a matching visible-surface bitmap/);
});

test("LightBurn export independently rejects projects over the 30-layer limit", () => {
  const depth = Float32Array.from({length:31}, (_, index) => index / 30);
  const relief = createReliefLayers(depth, 31, 1, {layers:30});
  const photoImages = relief.layers.map((_, index) => ({width:31, height:1, data:`cG5nLWRhdGEt${index}`}));
  assert.throws(() => createReliefLightBurn(relief, {
    pixelSizeMm:1,
    cutSetting:labelsSetting,
    surfaceEngraving:true,
    photoSetting,
    photoImages,
  }), /requires 60 LightBurn layers/);
});
