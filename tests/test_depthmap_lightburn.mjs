import assert from "node:assert/strict";
import test from "node:test";

import {createDepthmapLightBurn, hasEmbeddedCleanup} from "../static/depthmap_lightburn.js";

const image = {width:100, height:50, data:"aGVsbG8=", fileName:"test-depthmap.png"};
const slicing = {
  type:"Image",
  description:"3D-Slice",
  settings:{
    LinkPath:"CO2/Wood/3D-Slice",
    maxPower:"75",
    speed:"3000",
    numPasses:"3",
    interval:"0.02",
    ditherMode:"stucki",
    cleanupPass:"4",
  },
  subLayers:[{
    type:"Scan",
    settings:{maxPower:"35", speed:"2000", numPasses:"8", isCleanup:"1", subname:"Cleanup"},
  }],
};

test("grayscale exports one embedded bitmap and strips cleanup and LinkPath", () => {
  const project = createDepthmapLightBurn(image, {
    mode:"grayscale",
    slicingSetting:slicing,
    pixelSizeMm:.2,
    workbedWidthMm:40,
    workbedHeightMm:30,
  });
  assert.match(project, /<ditherMode Value="grayscale"\/>/);
  assert.equal((project.match(/<Shape Type="Bitmap"/g) || []).length, 1);
  assert.match(project, /Data="aGVsbG8="/);
  assert.match(project, /<XForm>0\.2 0 0 0\.2 20 15<\/XForm>/);
  assert.doesNotMatch(project, /LinkPath/);
  assert.doesNotMatch(project, /cleanupPass/);
  assert.doesNotMatch(project, /<SubLayer/);
});

test("3D Sliced preserves an imported cleanup sub-layer", () => {
  assert.equal(hasEmbeddedCleanup(slicing), true);
  const project = createDepthmapLightBurn(image, {mode:"3dslice", slicingSetting:slicing});
  assert.match(project, /<ditherMode Value="3dslice"\/>/);
  assert.match(project, /<cleanupPass Value="4"\/>/);
  assert.match(project, /<SubLayer type="Scan">/);
  assert.match(project, /<numPasses Value="8"\/>/);
  assert.match(project, /<isCleanup Value="1"\/>/);
  assert.match(project, /<subname Value="Cleanup"\/>/);
});

test("3D Sliced can construct cleanup from another selected setting", () => {
  const noCleanup = {...slicing, settings:{...slicing.settings}, subLayers:[]};
  delete noCleanup.settings.cleanupPass;
  const cleanupSetting = {
    type:"Scan",
    description:"Cleaning",
    settings:{LinkPath:"CO2/Wood/Cleaning", maxPower:"22", speed:"2400", numPasses:"99"},
  };
  const project = createDepthmapLightBurn(image, {
    mode:"3dslice",
    slicingSetting:noCleanup,
    cleanupSetting,
    cleanAfter:3,
    cleanupPasses:6,
  });
  assert.match(project, /<cleanupPass Value="3"\/>/);
  assert.match(project, /<maxPower Value="22"\/>/);
  assert.match(project, /<numPasses Value="6"\/>/);
  assert.match(project, /<isCleanup Value="1"\/>/);
  assert.doesNotMatch(project, /LinkPath/);
});

test("3D Sliced can omit automatic cleanup", () => {
  const noCleanup = {...slicing, settings:{...slicing.settings}, subLayers:[]};
  delete noCleanup.settings.cleanupPass;
  const project = createDepthmapLightBurn(image, {mode:"3dslice", slicingSetting:noCleanup});
  assert.doesNotMatch(project, /cleanupPass/);
  assert.doesNotMatch(project, /<SubLayer/);
});
