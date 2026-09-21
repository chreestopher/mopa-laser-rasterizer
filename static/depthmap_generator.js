import { createKrasnowParallaxPixels } from "./depthmap_parallax.js";
import { createKrasnowParallaxSvg } from "./depthmap_parallax_svg.js";
import {
  createScratchHologramArcs,
  createScratchHologramSvg,
} from "./depthmap_scratch_hologram_svg.js";

const MODEL_ID = "onnx-community/depth-anything-v2-small";
const TRANSFORMERS_URL = "https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.7.2";

const input = document.querySelector("#depth_input");
const inputModeControl = document.querySelector("#depth_input_mode");
const inputModeHelp = document.querySelector("#depth_input_mode_help");
const uploadPrompt = document.querySelector("#depth_upload_prompt");
const dropZone = document.querySelector("#depth_drop_zone");
const generateButton = document.querySelector("#depth_generate");
const resetButton = document.querySelector("#depth_reset");
const progress = document.querySelector("#depth_progress");
const uploadStatus = document.querySelector("#depth_status");
const uploadError = document.querySelector("#depth_error");
const processingStatus = document.querySelector("#depth_processing_status");
const processingError = document.querySelector("#depth_processing_error");
const processingPanel = document.querySelector("#depth_processing_panel");
const workspace = document.querySelector("#depth_workspace");
const sourceCanvas = document.querySelector("#depth_source_canvas");
const sourcePreview = document.querySelector("#depth_source_preview");
const mapCanvas = document.querySelector("#depth_map_canvas");
const basePreview = document.querySelector("#depth_base_preview");
const basePreviewCanvas = document.querySelector("#depth_base_preview_canvas");
const guidancePreviewCanvas = document.querySelector("#depth_guidance_preview_canvas");
const parallaxSourceCanvas = document.querySelector("#depth_parallax_source_canvas");
const reliefCanvas = document.querySelector("#depth_relief_canvas");
const legendCanvas = document.querySelector("#depth_legend_canvas");
const nearControl = document.querySelector("#depth_near");
const farControl = document.querySelector("#depth_far");
const gammaControl = document.querySelector("#depth_gamma");
const invertControl = document.querySelector("#depth_invert");
const outputWidthControl = document.querySelector("#depth_output_width");
const outputHeightControl = document.querySelector("#depth_output_height");
const borderPaddingControl = document.querySelector("#depth_border_padding");
const perimeterDepthControl = document.querySelector("#depth_perimeter_depth");
const perimeterDepthValue = document.querySelector("#depth_perimeter_depth_value");
const brushSizeControl = document.querySelector("#depth_brush_size");
const brushSizeValue = document.querySelector("#depth_brush_size_value");
const brushDepthControl = document.querySelector("#depth_brush_depth");
const brushDepthValue = document.querySelector("#depth_brush_depth_value");
const brushDepthPreview = document.querySelector("#depth_brush_preview");
const clearPaintButton = document.querySelector("#depth_clear_paint");
const parallaxScaleControl = document.querySelector("#depth_parallax_scale");
const parallaxScaleValue = document.querySelector("#depth_parallax_scale_value");
const parallaxBackgroundControl = document.querySelector("#depth_parallax_background");
const parallaxBackgroundValue = document.querySelector("#depth_parallax_background_value");
const parallaxPatchSizeControl = document.querySelector("#depth_parallax_patch_size");
const parallaxLineSpacingControl = document.querySelector("#depth_parallax_line_spacing");
const parallaxStrokeWidthControl = document.querySelector("#depth_parallax_stroke_width");
const parallaxPhysicalSize = document.querySelector("#depth_parallax_physical_size");
const parallaxSvgButton = document.querySelector("#depth_export_parallax_svg");
const parallaxPreviewCanvas = document.querySelector("#depth_parallax_preview_canvas");
const parallaxMaskCanvas = document.querySelector("#depth_parallax_mask_canvas");
const parallaxPreviewSummary = document.querySelector("#depth_parallax_preview_summary");
const scratchPixelSizeControl = document.querySelector("#depth_scratch_pixel_size");
const scratchSampleStepControl = document.querySelector("#depth_scratch_sample_step");
const scratchNearDepthControl = document.querySelector("#depth_scratch_near_depth");
const scratchDepthRangeControl = document.querySelector("#depth_scratch_depth_range");
const scratchViewSweepControl = document.querySelector("#depth_scratch_view_sweep");
const scratchBackgroundControl = document.querySelector("#depth_scratch_background");
const scratchStrokeWidthControl = document.querySelector("#depth_scratch_stroke_width");
const scratchPhysicalSize = document.querySelector("#depth_scratch_physical_size");
const scratchSvgButton = document.querySelector("#depth_export_scratch_svg");
const scratchPreviewCanvas = document.querySelector("#depth_scratch_preview_canvas");
const scratchPreviewSummary = document.querySelector("#depth_scratch_preview_summary");
const colorGuidancePanel = document.querySelector("#color_guidance_panel");
const swatchGrid = document.querySelector("#depth_swatch_grid");
const guidanceFeatherControl = document.querySelector("#depth_guidance_feather");
const guidanceFeatherValue = document.querySelector("#depth_guidance_feather_value");
const guidanceStatus = document.querySelector("#depth_guidance_status");
const depthPalettePicker = document.querySelector("#depth_palette_picker");
const savedDepthPaletteSelect = document.querySelector("#saved_depth_palette");
const depthPaletteRequired = document.querySelector("#depth_palette_required");
const depthGuidanceTools = document.querySelector("#depth_guidance_tools");
const depthPalette = JSON.parse(document.querySelector("#depth_palette_data").textContent);
const paletteState = depthPalette.map(swatch => ({...swatch, rgb:hexToRgb(swatch.hex), enabled:true, depth:50, influence:0}));
let savedDepthPalettes = [];

let sourceFile = null;
let sourceUrl = null;
let estimator = null;
let rawDepth = null;
let sourceBackgroundMask = null;
let depthWidth = 0;
let depthHeight = 0;
let adjustedDepth = null;
let guidedDepth = null;
let colorMatchMap = null;
let outputDepth = null;
let outputBackgroundMask = null;
let outputWidth = 0;
let outputHeight = 0;
let paintedDepth = null;
let perimeterDepthOverride = null;
let paintingFarDepth = false;
let lastPaintPoint = null;
let parallaxPreviewTimer = null;
let scratchPreviewTimer = null;

function revealDepthWorkflow() {
  workspace.hidden = false;
  workspace.scrollIntoView({behavior:"smooth", block:"start"});
}

function setUploadStatus(message, isError = false) {
  uploadStatus.textContent = message;
  uploadError.hidden = !isError;
  uploadError.textContent = isError ? message : "";
}

function setProcessingStatus(message, isError = false) {
  processingStatus.textContent = message;
  processingError.hidden = !isError;
  processingError.textContent = isError ? message : "";
}

function setBusy(busy) {
  generateButton.disabled = busy || !sourceFile;
  input.disabled = busy;
  inputModeControl.disabled = busy;
  progress.hidden = !busy;
  if (!busy) progress.value = 0;
}

async function acceptFile(file) {
  if (!file || !file.type.startsWith("image/")) {
    setUploadStatus("Choose a supported image file.", true);
    return;
  }
  sourceFile = file;
  perimeterDepthOverride = null;
  perimeterDepthValue.value = "Lowest point";
  if (sourceUrl) URL.revokeObjectURL(sourceUrl);
  sourceUrl = URL.createObjectURL(file);
  const image = await loadImage(sourceUrl);
  drawContainedImage(sourceCanvas, image);
  sourcePreview.hidden = false;
  generateButton.disabled = false;
  resetButton.disabled = false;
  processingPanel.hidden = false;
  workspace.hidden = true;
  setUploadStatus(`${file.name} loaded successfully.`);
  updateInputMode();
  drawLegend();
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("The browser could not decode this image."));
    image.src = url;
  });
}

function drawContainedImage(canvas, image) {
  canvas.width = image.naturalWidth || image.width;
  canvas.height = image.naturalHeight || image.height;
  canvas.getContext("2d").drawImage(image, 0, 0);
}

async function loadEstimator() {
  if (estimator) return estimator;
  setProcessingStatus("Loading the client-side depth model. The first download may take several minutes.");
  const { pipeline, env } = await import(TRANSFORMERS_URL);
  env.allowLocalModels = false;
  const progress_callback = event => {
    if (typeof event.progress === "number") progress.value = Math.round(event.progress);
    if (event.status === "progress" && event.file) processingStatus.textContent = `Downloading model: ${event.file}`;
  };
  const options = { progress_callback };
  if ("gpu" in navigator) options.device = "webgpu";
  try {
    estimator = await pipeline("depth-estimation", MODEL_ID, options);
  } catch (webGpuError) {
    if (options.device !== "webgpu") throw webGpuError;
    setProcessingStatus("WebGPU was unavailable. Loading the compatible browser CPU version.");
    delete options.device;
    estimator = await pipeline("depth-estimation", MODEL_ID, options);
  }
  return estimator;
}

async function generateDepth() {
  if (!sourceUrl) return;
  setBusy(true);
  try {
    if (inputModeControl.value === "depthmap") {
      importExistingDepthmap();
      return;
    }
    const model = await loadEstimator();
    setProcessingStatus("Analyzing perspective and estimating relative depth...");
    progress.removeAttribute("value");
    const result = await model(sourceUrl);
    const tensor = result.predicted_depth;
    const dims = tensor.dims;
    depthHeight = dims[dims.length - 2];
    depthWidth = dims[dims.length - 1];
    rawDepth = Float32Array.from(tensor.data);
    sourceBackgroundMask = null;
    createColorMatchMap();
    outputWidthControl.value = depthWidth;
    outputHeightControl.value = depthHeight;
    renderAdjustedDepth();
    revealDepthWorkflow();
    setProcessingStatus(`Depth map generated at ${depthWidth} × ${depthHeight}. Adjust and export the result.`);
  } catch (cause) {
    console.error(cause);
    setProcessingStatus(`Depth generation failed: ${cause.message || cause}`, true);
  } finally {
    setBusy(false);
  }
}

function importExistingDepthmap() {
  const width = sourceCanvas.width;
  const height = sourceCanvas.height;
  if (!width || !height) throw new Error("The browser could not read the grayscale depthmap.");
  const pixels = sourceCanvas.getContext("2d", {willReadFrequently:true}).getImageData(0, 0, width, height).data;
  depthWidth = width;
  depthHeight = height;
  rawDepth = new Float32Array(width * height);
  sourceBackgroundMask = new Uint8Array(width * height);
  let backgroundCount = 0;
  for (let index = 0; index < rawDepth.length; index += 1) {
    const offset = index * 4;
    const red = pixels[offset];
    const green = pixels[offset + 1];
    const blue = pixels[offset + 2];
    const alpha = pixels[offset + 3];
    const isBackground = alpha === 0 || (red === 255 && green === 255 && blue === 255);
    sourceBackgroundMask[index] = isBackground ? 1 : 0;
    if (isBackground) backgroundCount += 1;
    const gray = Math.min(254, Math.round(red * .2126 + green * .7152 + blue * .0722));
    rawDepth[index] = isBackground ? 1 : gray / 254;
  }
  createColorMatchMap();
  outputWidthControl.value = width;
  outputHeightControl.value = height;
  renderAdjustedDepth();
  revealDepthWorkflow();
  setProcessingStatus(`Existing ${width} × ${height} depthmap loaded directly. Pure-white and transparent pixels mark ${(backgroundCount / rawDepth.length * 100).toFixed(1)}% as explicit background.`);
}

function renderAdjustedDepth() {
  if (!rawDepth) return;
  let minimum = sourceBackgroundMask ? 0 : Infinity;
  let maximum = sourceBackgroundMask ? 1 : -Infinity;
  if (!sourceBackgroundMask) {
    for (const value of rawDepth) {
      if (value < minimum) minimum = value;
      if (value > maximum) maximum = value;
    }
  }
  const span = Math.max(maximum - minimum, Number.EPSILON);
  const near = Number(nearControl.value) / 100;
  const far = Number(farControl.value) / 100;
  const clipSpan = Math.max(far - near, .01);
  const gamma = Number(gammaControl.value) / 100;
  adjustedDepth = new Float32Array(rawDepth.length);
  for (let index = 0; index < rawDepth.length; index += 1) {
    let value = ((rawDepth[index] - minimum) / span - near) / clipSpan;
    value = Math.min(1, Math.max(0, value));
    value = Math.pow(value, 1 / gamma);
    adjustedDepth[index] = invertControl.checked ? 1 - value : value;
  }
  applyColorGuidance();
  buildOutputCanvas();
  drawGrayscale();
  drawRelief();
  drawLegend();
}

function hexToRgb(hex) {
  const value = hex.replace("#", "");
  const expanded = value.length === 3 ? value.split("").map(character => character + character).join("") : value;
  const number = Number.parseInt(expanded, 16);
  return [(number >> 16) & 255, (number >> 8) & 255, number & 255];
}

function createColorMatchMap() {
  const matchingCanvas = document.createElement("canvas");
  matchingCanvas.width = depthWidth;
  matchingCanvas.height = depthHeight;
  const context = matchingCanvas.getContext("2d", {willReadFrequently:true});
  context.drawImage(sourceCanvas, 0, 0, depthWidth, depthHeight);
  const pixels = context.getImageData(0, 0, depthWidth, depthHeight).data;
  colorMatchMap = new Int16Array(depthWidth * depthHeight);
  colorMatchMap.fill(-1);
  for (let index = 0; index < colorMatchMap.length; index += 1) {
    const offset = index * 4;
    if (pixels[offset + 3] < 16) continue;
    let closestIndex = 0;
    let closestDistance = Infinity;
    for (let paletteIndex = 0; paletteIndex < paletteState.length; paletteIndex += 1) {
      const [red, green, blue] = paletteState[paletteIndex].rgb;
      const redDelta = pixels[offset] - red;
      const greenDelta = pixels[offset + 1] - green;
      const blueDelta = pixels[offset + 2] - blue;
      const distance = redDelta * redDelta + greenDelta * greenDelta + blueDelta * blueDelta;
      if (distance < closestDistance) {
        closestDistance = distance;
        closestIndex = paletteIndex;
      }
    }
    colorMatchMap[index] = closestIndex;
  }
}

function applyColorGuidance() {
  guidedDepth = Float32Array.from(adjustedDepth);
  if (!colorMatchMap) return;
  const targetWeight = new Float32Array(adjustedDepth.length);
  const influence = new Float32Array(adjustedDepth.length);
  let activeSwatches = 0;
  for (const swatch of paletteState) if (swatch.enabled && swatch.influence > 0) activeSwatches += 1;
  guidanceStatus.textContent = activeSwatches
    ? `${activeSwatches} swatch${activeSwatches === 1 ? "" : "es"} currently influence depth.`
    : "All swatches currently follow perspective depth.";
  if (!activeSwatches) return;
  for (let index = 0; index < colorMatchMap.length; index += 1) {
    const paletteIndex = colorMatchMap[index];
    if (paletteIndex < 0) continue;
    const swatch = paletteState[paletteIndex];
    if (!swatch.enabled || swatch.influence <= 0) continue;
    const weight = swatch.influence / 100;
    influence[index] = weight;
    const target = invertControl.checked ? 1 - swatch.depth / 100 : swatch.depth / 100;
    targetWeight[index] = target * weight;
  }
  const radius = Number(guidanceFeatherControl.value);
  const blendedInfluence = radius ? boxBlur(influence, depthWidth, depthHeight, radius) : influence;
  const blendedTarget = radius ? boxBlur(targetWeight, depthWidth, depthHeight, radius) : targetWeight;
  for (let index = 0; index < guidedDepth.length; index += 1) {
    const weight = Math.min(1, blendedInfluence[index]);
    if (weight <= 0) continue;
    const target = blendedTarget[index] / weight;
    guidedDepth[index] = adjustedDepth[index] * (1 - weight) + target * weight;
  }
}

function boxBlur(source, width, height, radius) {
  const horizontal = new Float32Array(source.length);
  const output = new Float32Array(source.length);
  for (let y = 0; y < height; y += 1) {
    let sum = 0;
    for (let x = -radius; x <= radius; x += 1) sum += source[y * width + Math.min(width - 1, Math.max(0, x))];
    for (let x = 0; x < width; x += 1) {
      horizontal[y * width + x] = sum / (radius * 2 + 1);
      const removeX = Math.max(0, x - radius);
      const addX = Math.min(width - 1, x + radius + 1);
      sum += source[y * width + addX] - source[y * width + removeX];
    }
  }
  for (let x = 0; x < width; x += 1) {
    let sum = 0;
    for (let y = -radius; y <= radius; y += 1) sum += horizontal[Math.min(height - 1, Math.max(0, y)) * width + x];
    for (let y = 0; y < height; y += 1) {
      output[y * width + x] = sum / (radius * 2 + 1);
      const removeY = Math.max(0, y - radius);
      const addY = Math.min(height - 1, y + radius + 1);
      sum += horizontal[addY * width + x] - horizontal[removeY * width + x];
    }
  }
  return output;
}

function requestedDimension(control, fallback) {
  const value = Math.round(Number(control.value));
  return Number.isFinite(value) ? Math.min(8192, Math.max(32, value)) : fallback;
}

function syncOutputAspect(changedDimension) {
  if (!depthWidth || !depthHeight) return;
  const aspectRatio = depthWidth / depthHeight;
  if (changedDimension === "height") {
    let height = requestedDimension(outputHeightControl, depthHeight);
    let width = Math.round(height * aspectRatio);
    if (width > 8192) {
      width = 8192;
      height = Math.max(32, Math.round(width / aspectRatio));
    } else if (width < 32) {
      width = 32;
      height = Math.min(8192, Math.round(width / aspectRatio));
    }
    outputWidthControl.value = width;
    outputHeightControl.value = height;
    return;
  }
  let width = requestedDimension(outputWidthControl, depthWidth);
  let height = Math.round(width / aspectRatio);
  if (height > 8192) {
    height = 8192;
    width = Math.max(32, Math.round(height * aspectRatio));
  } else if (height < 32) {
    height = 32;
    width = Math.min(8192, Math.round(height * aspectRatio));
  }
  outputWidthControl.value = width;
  outputHeightControl.value = height;
}

function lowestImageHeight(depthValues, backgroundMask = null) {
  let lowestHeight = invertControl.checked ? -Infinity : Infinity;
  for (let index = 0; index < depthValues.length; index += 1) {
    if (backgroundMask?.[index]) continue;
    const value = depthValues[index];
    if (!Number.isFinite(value)) continue;
    if (invertControl.checked) {
      if (value > lowestHeight) lowestHeight = value;
    } else if (value < lowestHeight) {
      lowestHeight = value;
    }
  }
  return Number.isFinite(lowestHeight) ? lowestHeight : (invertControl.checked ? 1 : 0);
}

function encodedDepthToProximity(encodedDepth) {
  return invertControl.checked ? 1 - encodedDepth : encodedDepth;
}

function proximityDepthLabel(proximity) {
  const percentage = Math.max(0, Math.min(100, proximity * 100));
  if (percentage === 0) return "Farther";
  if (percentage === 50) return "Neutral";
  if (percentage === 100) return "Closer";
  const distanceFromNeutral = Math.abs(percentage - 50) * 2;
  const formatted = Number.isInteger(distanceFromNeutral) ? distanceFromNeutral.toFixed(0) : distanceFromNeutral.toFixed(1);
  return `${formatted}% ${percentage < 50 ? "farther" : "closer"}`;
}

function buildOutputCanvas() {
  syncOutputAspect("width");
  const artworkWidth = requestedDimension(outputWidthControl, depthWidth);
  const artworkHeight = requestedDimension(outputHeightControl, depthHeight);
  const requestedPadding = Math.max(0, Math.min(2048, Math.round(Number(borderPaddingControl.value)) || 0));
  const maximumPadding = Math.max(0, Math.floor((8192 - Math.max(artworkWidth, artworkHeight)) / 2));
  const borderPadding = Math.min(requestedPadding, maximumPadding);
  borderPaddingControl.value = borderPadding;
  outputWidth = artworkWidth + borderPadding * 2;
  outputHeight = artworkHeight + borderPadding * 2;
  const scale = Math.min(artworkWidth / depthWidth, artworkHeight / depthHeight);
  const contentWidth = Math.max(1, Math.round(depthWidth * scale));
  const contentHeight = Math.max(1, Math.round(depthHeight * scale));
  const offsetX = borderPadding + Math.floor((artworkWidth - contentWidth) / 2);
  const offsetY = borderPadding + Math.floor((artworkHeight - contentHeight) / 2);
  const lowestDepth = lowestImageHeight(guidedDepth, sourceBackgroundMask);
  const automaticProximity = encodedDepthToProximity(lowestDepth);
  const perimeterProximity = perimeterDepthOverride === null ? automaticProximity : perimeterDepthOverride;
  const perimeterDepth = invertControl.checked ? 1 - perimeterProximity : perimeterProximity;
  if (perimeterDepthOverride === null) perimeterDepthControl.value = (automaticProximity * 100).toFixed(1);
  perimeterDepthValue.value = perimeterDepthOverride === null
    ? `Lowest point (${proximityDepthLabel(automaticProximity)})`
    : proximityDepthLabel(perimeterProximity);
  const outputLength = outputWidth * outputHeight;
  if (!paintedDepth || paintedDepth.length !== outputLength) {
    paintedDepth = new Float32Array(outputLength);
    paintedDepth.fill(Number.NaN);
  }
  outputDepth = new Float32Array(outputLength);
  outputDepth.fill(perimeterDepth);
  outputBackgroundMask = sourceBackgroundMask ? new Uint8Array(outputLength) : null;
  if (outputBackgroundMask) outputBackgroundMask.fill(1);
  for (let y = 0; y < contentHeight; y += 1) {
    const sourceY = Math.min(depthHeight - 1, Math.floor(y * depthHeight / contentHeight));
    for (let x = 0; x < contentWidth; x += 1) {
      const sourceX = Math.min(depthWidth - 1, Math.floor(x * depthWidth / contentWidth));
      const outputIndex = (y + offsetY) * outputWidth + x + offsetX;
      const sourceIndex = sourceY * depthWidth + sourceX;
      outputDepth[outputIndex] = guidedDepth[sourceIndex];
      if (outputBackgroundMask) outputBackgroundMask[outputIndex] = sourceBackgroundMask[sourceIndex];
    }
  }
  for (let index = 0; index < outputLength; index += 1) {
    if (!Number.isNaN(paintedDepth[index])) {
      outputDepth[index] = invertControl.checked ? 1 - paintedDepth[index] : paintedDepth[index];
      if (outputBackgroundMask) outputBackgroundMask[index] = 0;
    }
  }
  updateParallaxControls();
  updateScratchControls();
}

function paintFarDepth(event) {
  if (!outputDepth || !paintingFarDepth) return;
  const bounds = mapCanvas.getBoundingClientRect();
  const centerX = (event.clientX - bounds.left) * outputWidth / bounds.width;
  const centerY = (event.clientY - bounds.top) * outputHeight / bounds.height;
  const radius = Number(brushSizeControl.value) / 2;
  const distance = lastPaintPoint ? Math.hypot(centerX - lastPaintPoint.x, centerY - lastPaintPoint.y) : 0;
  const steps = Math.max(1, Math.ceil(distance / Math.max(1, radius / 2)));
  for (let step = 1; step <= steps; step += 1) {
    const amount = step / steps;
    const brushX = lastPaintPoint ? lastPaintPoint.x + (centerX - lastPaintPoint.x) * amount : centerX;
    const brushY = lastPaintPoint ? lastPaintPoint.y + (centerY - lastPaintPoint.y) * amount : centerY;
    paintFarDepthCircle(brushX, brushY, radius);
  }
  lastPaintPoint = {x:centerX, y:centerY};
  drawGrayscale();
  drawRelief();
}

function paintFarDepthCircle(centerX, centerY, radius) {
  const minimumX = Math.max(0, Math.floor(centerX - radius));
  const maximumX = Math.min(outputWidth - 1, Math.ceil(centerX + radius));
  const minimumY = Math.max(0, Math.floor(centerY - radius));
  const maximumY = Math.min(outputHeight - 1, Math.ceil(centerY + radius));
  const radiusSquared = radius * radius;
  const proximity = Number(brushDepthControl.value) / 100;
  const encodedDepth = invertControl.checked ? 1 - proximity : proximity;
  for (let y = minimumY; y <= maximumY; y += 1) {
    for (let x = minimumX; x <= maximumX; x += 1) {
      const deltaX = x + .5 - centerX;
      const deltaY = y + .5 - centerY;
      if (deltaX * deltaX + deltaY * deltaY > radiusSquared) continue;
      const index = y * outputWidth + x;
      paintedDepth[index] = proximity;
      outputDepth[index] = encodedDepth;
      if (outputBackgroundMask) outputBackgroundMask[index] = 0;
    }
  }
}

function clearPaintedDepth() {
  if (!paintedDepth) return;
  paintedDepth.fill(Number.NaN);
  renderAdjustedDepth();
  setProcessingStatus("Painted depth edits cleared.");
}

function updateBrushDepthPreview() {
  const depth = Number(brushDepthControl.value);
  const proximity = depth / 100;
  const encodedDepth = invertControl.checked ? 1 - proximity : proximity;
  const gray = Math.round(encodedDepth * 255);
  const formattedDepth = Number.isInteger(depth) ? depth.toFixed(0) : depth.toFixed(1);
  brushDepthValue.value = depth === 0 ? "Farther" : depth === 100 ? "Closer" : `${formattedDepth}% closer`;
  brushDepthPreview.style.backgroundColor = `rgb(${gray}, ${gray}, ${gray})`;
  brushDepthPreview.setAttribute("aria-label", `Brush preview: ${brushSizeControl.value} pixel diameter, grayscale ${gray} out of 255, ${brushDepthValue.value}`);
}

function updateBrushSizePreview() {
  const brushSize = Number(brushSizeControl.value);
  const displaySize = 14 + (brushSize - 1) / 199 * 62;
  brushSizeValue.value = `${brushSize} px`;
  brushDepthPreview.style.width = `${displaySize}px`;
  brushDepthPreview.style.height = `${displaySize}px`;
  updateBrushDepthPreview();
}

function drawGrayscale() {
  mapCanvas.width = outputWidth;
  mapCanvas.height = outputHeight;
  const context = mapCanvas.getContext("2d");
  const imageData = context.createImageData(outputWidth, outputHeight);
  for (let index = 0; index < outputDepth.length; index += 1) {
    const gray = Math.round(outputDepth[index] * 255);
    const offset = index * 4;
    imageData.data[offset] = gray;
    imageData.data[offset + 1] = gray;
    imageData.data[offset + 2] = gray;
    imageData.data[offset + 3] = 255;
  }
  context.putImageData(imageData, 0, 0);
  drawBasePreview();
  drawWorkflowPreview(guidancePreviewCanvas);
  drawWorkflowPreview(parallaxSourceCanvas);
  scheduleParallaxPreview();
  scheduleScratchPreview();
}

function drawWorkflowPreview(canvas) {
  if (!outputWidth || !outputHeight) return;
  const maximumSide = 1024;
  const scale = Math.min(1, maximumSide / Math.max(outputWidth, outputHeight));
  canvas.width = Math.max(1, Math.round(outputWidth * scale));
  canvas.height = Math.max(1, Math.round(outputHeight * scale));
  const context = canvas.getContext("2d");
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = "high";
  context.drawImage(mapCanvas, 0, 0, canvas.width, canvas.height);
}

function drawBasePreview() {
  if (!outputWidth || !outputHeight) return;
  const maximumSide = 1024;
  const scale = Math.min(1, maximumSide / Math.max(outputWidth, outputHeight));
  basePreviewCanvas.width = Math.max(1, Math.round(outputWidth * scale));
  basePreviewCanvas.height = Math.max(1, Math.round(outputHeight * scale));
  const context = basePreviewCanvas.getContext("2d");
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = "high";
  context.drawImage(mapCanvas, 0, 0, basePreviewCanvas.width, basePreviewCanvas.height);
  basePreview.hidden = false;
}

function drawRelief() {
  reliefCanvas.width = outputWidth;
  reliefCanvas.height = outputHeight;
  const context = reliefCanvas.getContext("2d");
  const imageData = context.createImageData(outputWidth, outputHeight);
  const light = [-.45, -.55, .7];
  for (let y = 0; y < outputHeight; y += 1) {
    for (let x = 0; x < outputWidth; x += 1) {
      const index = y * outputWidth + x;
      const left = outputDepth[y * outputWidth + Math.max(0, x - 1)];
      const right = outputDepth[y * outputWidth + Math.min(outputWidth - 1, x + 1)];
      const up = outputDepth[Math.max(0, y - 1) * outputWidth + x];
      const down = outputDepth[Math.min(outputHeight - 1, y + 1) * outputWidth + x];
      const nx = (left - right) * 4;
      const ny = (up - down) * 4;
      const length = Math.hypot(nx, ny, 1);
      const shade = Math.max(0, (nx * light[0] + ny * light[1] + light[2]) / length);
      const value = Math.round((.18 + shade * .65 + outputDepth[index] * .17) * 255);
      const offset = index * 4;
      imageData.data[offset] = Math.round(value * .78);
      imageData.data[offset + 1] = Math.round(value * .9);
      imageData.data[offset + 2] = Math.round(value * .72);
      imageData.data[offset + 3] = 255;
    }
  }
  context.putImageData(imageData, 0, 0);
}

function drawLegend() {
  const context = legendCanvas.getContext("2d");
  const gradient = context.createLinearGradient(70, 0, 570, 0);
  gradient.addColorStop(0, "#000");
  gradient.addColorStop(1, "#fff");
  context.fillStyle = "#161a14";
  context.fillRect(0, 0, legendCanvas.width, legendCanvas.height);
  context.fillStyle = gradient;
  context.fillRect(70, 130, 500, 70);
  context.fillStyle = "#e4e3cf";
  context.font = "24px system-ui";
  context.textAlign = "center";
  context.fillText(invertControl.checked ? "Near" : "Far", 70, 245);
  context.fillText(invertControl.checked ? "Far" : "Near", 570, 245);
  context.font = "18px system-ui";
  context.fillText("Relative depth - not physical distance", 320, 90);
}

function downloadBlob(blob, suffix, extension = "png") {
  const name = (sourceFile?.name || "depthmap").replace(/\.[^.]+$/, "");
  const anchor = document.createElement("a");
  anchor.href = URL.createObjectURL(blob);
  anchor.download = `${name}-${suffix}.${extension}`;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(anchor.href), 1000);
}

function export8Bit() {
  mapCanvas.toBlob(blob => downloadBlob(blob, "depth-8bit"), "image/png");
}

async function export16Bit() {
  if (!adjustedDepth) return;
  const scanlines = new Uint8Array((outputWidth * 2 + 1) * outputHeight);
  for (let y = 0; y < outputHeight; y += 1) {
    const row = y * (outputWidth * 2 + 1);
    scanlines[row] = 0;
    for (let x = 0; x < outputWidth; x += 1) {
      const value = Math.round(outputDepth[y * outputWidth + x] * 65535);
      scanlines[row + 1 + x * 2] = value >>> 8;
      scanlines[row + 2 + x * 2] = value & 255;
    }
  }
  const compressed = await compressDeflate(scanlines);
  const signature = Uint8Array.from([137,80,78,71,13,10,26,10]);
  const ihdr = new Uint8Array(13);
  const view = new DataView(ihdr.buffer);
  view.setUint32(0, outputWidth);
  view.setUint32(4, outputHeight);
  ihdr.set([16,0,0,0,0], 8);
  downloadBlob(new Blob([signature, pngChunk("IHDR", ihdr), pngChunk("IDAT", compressed), pngChunk("IEND", new Uint8Array())], {type:"image/png"}), "depth-16bit");
}

function exportParallax() {
  if (!outputDepth) return;
  const pixels = currentParallaxPixels();
  const canvas = document.createElement("canvas");
  canvas.width = outputWidth;
  canvas.height = outputHeight;
  const context = canvas.getContext("2d");
  const imageData = context.createImageData(outputWidth, outputHeight);
  for (let index = 0; index < pixels.length; index += 1) {
    const offset = index * 4;
    imageData.data[offset] = pixels[index];
    imageData.data[offset + 1] = pixels[index];
    imageData.data[offset + 2] = pixels[index];
    imageData.data[offset + 3] = 255;
  }
  context.putImageData(imageData, 0, 0);
  canvas.toBlob(blob => {
    if (!blob) {
      setProcessingStatus("The browser could not create the Parallax PNG.", true);
      return;
    }
    downloadBlob(blob, "parallax");
    setProcessingStatus("Parallax angle map created locally and downloaded.");
  }, "image/png");
}

function currentParallaxPixels() {
  return createKrasnowParallaxPixels(outputDepth, outputWidth, outputHeight, {
    scaleFactor:Number(parallaxScaleControl.value),
    backgroundCutoff:Number(parallaxBackgroundControl.value) / 100,
    inverted:invertControl.checked,
    backgroundMask:outputBackgroundMask,
  });
}

function previewDepthMap(maximumSide = 1024) {
  const previewScale = Math.min(1, maximumSide / Math.max(outputWidth, outputHeight));
  const width = Math.max(1, Math.round(outputWidth * previewScale));
  const height = Math.max(1, Math.round(outputHeight * previewScale));
  if (width === outputWidth && height === outputHeight) {
    return {depth:outputDepth, backgroundMask:outputBackgroundMask, width, height, horizontalScale:1};
  }
  const depth = new Float32Array(width * height);
  const backgroundMask = outputBackgroundMask ? new Uint8Array(width * height) : null;
  for (let y = 0; y < height; y += 1) {
    const sourceY = Math.min(outputHeight - 1, Math.floor(y * outputHeight / height));
    for (let x = 0; x < width; x += 1) {
      const sourceX = Math.min(outputWidth - 1, Math.floor(x * outputWidth / width));
      const previewIndex = y * width + x;
      const sourceIndex = sourceY * outputWidth + sourceX;
      depth[previewIndex] = outputDepth[sourceIndex];
      if (backgroundMask) backgroundMask[previewIndex] = outputBackgroundMask[sourceIndex];
    }
  }
  return {depth, backgroundMask, width, height, horizontalScale:width / outputWidth};
}

function drawParallaxPreview() {
  parallaxPreviewTimer = null;
  if (!outputDepth || !outputWidth || !outputHeight) return;

  const preview = previewDepthMap();
  const cutoff = Number(parallaxBackgroundControl.value) / 100;
  const pixels = createKrasnowParallaxPixels(preview.depth, preview.width, preview.height, {
    scaleFactor:Number(parallaxScaleControl.value) * preview.horizontalScale,
    backgroundCutoff:cutoff,
    inverted:invertControl.checked,
    backgroundMask:preview.backgroundMask,
  });
  parallaxPreviewCanvas.width = preview.width;
  parallaxPreviewCanvas.height = preview.height;
  parallaxMaskCanvas.width = preview.width;
  parallaxMaskCanvas.height = preview.height;
  const angleContext = parallaxPreviewCanvas.getContext("2d");
  const maskContext = parallaxMaskCanvas.getContext("2d");
  const angleImage = angleContext.createImageData(preview.width, preview.height);
  const maskImage = maskContext.createImageData(preview.width, preview.height);
  let sourceBackgroundCount = 0;
  let unengravedCount = 0;
  for (let index = 0; index < pixels.length; index += 1) {
    const angleOffset = index * 4;
    angleImage.data[angleOffset] = pixels[index];
    angleImage.data[angleOffset + 1] = pixels[index];
    angleImage.data[angleOffset + 2] = pixels[index];
    angleImage.data[angleOffset + 3] = 255;

    const encoded = Math.min(1, Math.max(0, Number(preview.depth[index]) || 0));
    const proximity = invertControl.checked ? 1 - encoded : encoded;
    const isSourceBackground = preview.backgroundMask
      ? Boolean(preview.backgroundMask[index])
      : proximity <= cutoff;
    if (isSourceBackground) sourceBackgroundCount += 1;
    const isUnengraved = pixels[index] === 255;
    if (isUnengraved) unengravedCount += 1;
    const maskValue = isUnengraved ? 255 : 0;
    maskImage.data[angleOffset] = maskValue;
    maskImage.data[angleOffset + 1] = maskValue;
    maskImage.data[angleOffset + 2] = maskValue;
    maskImage.data[angleOffset + 3] = 255;
  }
  angleContext.putImageData(angleImage, 0, 0);
  maskContext.putImageData(maskImage, 0, 0);
  const sourceBackgroundPercentage = sourceBackgroundCount / pixels.length * 100;
  const unengravedPercentage = unengravedCount / pixels.length * 100;
  const sourceLabel = preview.backgroundMask ? "explicit source background" : "cutoff-derived source background";
  parallaxPreviewSummary.textContent = `${sourceBackgroundPercentage.toFixed(1)}% ${sourceLabel}; ${unengravedPercentage.toFixed(1)}% remains unengraved after generating edge ramps.`;
}

function scheduleParallaxPreview() {
  if (parallaxPreviewTimer !== null) clearTimeout(parallaxPreviewTimer);
  if (!outputDepth) return;
  parallaxPreviewTimer = setTimeout(drawParallaxPreview, 100);
}

async function exportParallaxSvg() {
  if (!outputDepth) return;
  parallaxSvgButton.disabled = true;
  try {
    const pixels = currentParallaxPixels();
    const patchSize = Number(parallaxPatchSizeControl.value);
    const lineSpacing = Number(parallaxLineSpacingControl.value);
    const strokeWidth = Number(parallaxStrokeWidthControl.value);
    setProcessingStatus("Building Parallax SVG grating geometry locally: row 0 of " + outputHeight + ".");
    const blob = await createKrasnowParallaxSvg(pixels, outputWidth, outputHeight, {
      patchSize,
      lineSpacing,
      strokeWidth,
      onProgress:(row, total) => {
        if (row === total || row === 1 || row % Math.max(1, Math.ceil(total / 20)) === 0) {
          setProcessingStatus(`Building Parallax SVG grating geometry locally: row ${row} of ${total}.`);
        }
      },
    });
    downloadBlob(blob, "parallax-grating", "svg");
    setProcessingStatus("Parallax SVG grating geometry created locally and downloaded.");
  } finally {
    parallaxSvgButton.disabled = false;
  }
}

function updateParallaxControls() {
  parallaxScaleValue.value = Number(parallaxScaleControl.value).toFixed(2);
  parallaxBackgroundValue.value = `${Number(parallaxBackgroundControl.value).toFixed(1)}%`;
  if (outputWidth && outputHeight) {
    const patchSize = Number(parallaxPatchSizeControl.value);
    parallaxPhysicalSize.value = `${(outputWidth * patchSize).toFixed(2)} × ${(outputHeight * patchSize).toFixed(2)} mm`;
  } else {
    parallaxPhysicalSize.value = "Generate a depthmap first";
  }
  scheduleParallaxPreview();
}

function scratchGeometryOptions(maxArcs = 30000) {
  return {
    backgroundMask:outputBackgroundMask,
    inverted:invertControl.checked,
    pixelSize:Number(scratchPixelSizeControl.value),
    sampleStep:Number(scratchSampleStepControl.value),
    nearDepth:Number(scratchNearDepthControl.value),
    depthRange:Number(scratchDepthRangeControl.value),
    viewSweep:Number(scratchViewSweepControl.value),
    backgroundCutoff:Number(scratchBackgroundControl.value) / 100,
    minimumCellInset:Number(scratchStrokeWidthControl.value) / 2 + 1e-6,
    maxArcs,
  };
}

function drawScratchPreview() {
  scratchPreviewTimer = null;
  if (!outputDepth || !outputWidth || !outputHeight) return;
  try {
    const geometry = createScratchHologramArcs(
      outputDepth,
      outputWidth,
      outputHeight,
      scratchGeometryOptions(8000),
    );
    const longestSide = 960;
    const scale = longestSide / Math.max(geometry.physicalWidth, geometry.physicalHeight);
    scratchPreviewCanvas.width = Math.max(1, Math.round(geometry.physicalWidth * scale));
    scratchPreviewCanvas.height = Math.max(1, Math.round(geometry.physicalHeight * scale));
    const context = scratchPreviewCanvas.getContext("2d");
    context.fillStyle = "#f7f7f2";
    context.fillRect(0, 0, scratchPreviewCanvas.width, scratchPreviewCanvas.height);
    context.save();
    context.scale(scale, scale);
    context.strokeStyle = "#111";
    context.lineWidth = Math.max(Number(scratchStrokeWidthControl.value), 1 / scale);
    context.lineCap = "round";
    context.beginPath();
    for (const arc of geometry.arcs) {
      context.moveTo(arc.startX, arc.startY);
      context.arc(arc.centerX, arc.centerY, arc.radius, arc.startAngle, arc.endAngle);
    }
    context.stroke();
    context.restore();
    const adjusted = geometry.effectiveSampleStep !== geometry.requestedSampleStep
      ? ` The preview automatically increased the sample step to ${geometry.effectiveSampleStep} px to remain within its geometry limit.`
      : "";
    scratchPreviewSummary.textContent = `${geometry.arcs.length.toLocaleString()} preview arcs; ${geometry.physicalWidth.toFixed(2)} ? ${geometry.physicalHeight.toFixed(2)} mm.${adjusted}`;
  } catch (cause) {
    scratchPreviewSummary.textContent = cause.message || String(cause);
  }
}

function scheduleScratchPreview() {
  if (scratchPreviewTimer !== null) clearTimeout(scratchPreviewTimer);
  if (!outputDepth) return;
  scratchPreviewTimer = setTimeout(drawScratchPreview, 100);
}

async function exportScratchHologramSvg() {
  if (!outputDepth) return;
  scratchSvgButton.disabled = true;
  try {
    setProcessingStatus("Building experimental specular scratch hologram geometry locally.");
    const result = await createScratchHologramSvg(outputDepth, outputWidth, outputHeight, {
      ...scratchGeometryOptions(),
      strokeWidth:Number(scratchStrokeWidthControl.value),
      onProgress:(completed, total) => {
        if (completed === total || completed % 5000 === 0) {
          setProcessingStatus(`Building specular scratch hologram SVG: ${completed.toLocaleString()} of ${total.toLocaleString()} arcs.`);
        }
      },
    });
    downloadBlob(result.blob, "specular-scratch-hologram", "svg");
    const adjustment = result.effectiveSampleStep !== result.requestedSampleStep
      ? ` The sample step was automatically increased to ${result.effectiveSampleStep} px to remain below 30,000 arcs.`
      : "";
    setProcessingStatus(`Experimental scratch hologram SVG created locally with ${result.arcs.length.toLocaleString()} open arcs.${adjustment}`);
  } finally {
    scratchSvgButton.disabled = false;
  }
}

function updateScratchControls() {
  if (outputWidth && outputHeight) {
    const pixelSize = Number(scratchPixelSizeControl.value);
    scratchPhysicalSize.value = `${(outputWidth * pixelSize).toFixed(2)} ? ${(outputHeight * pixelSize).toFixed(2)} mm`;
  } else {
    scratchPhysicalSize.value = "Generate a depthmap first";
  }
  scheduleScratchPreview();
}

async function compressDeflate(bytes) {
  if (!("CompressionStream" in window)) throw new Error("This browser cannot create a 16-bit PNG. Use the 8-bit export instead.");
  const stream = new Blob([bytes]).stream().pipeThrough(new CompressionStream("deflate"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

function pngChunk(type, data) {
  const typeBytes = new TextEncoder().encode(type);
  const output = new Uint8Array(12 + data.length);
  const view = new DataView(output.buffer);
  view.setUint32(0, data.length);
  output.set(typeBytes, 4);
  output.set(data, 8);
  view.setUint32(8 + data.length, crc32(output.subarray(4, 8 + data.length)));
  return output;
}

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function reset() {
  sourceFile = null;
  perimeterDepthOverride = null;
  rawDepth = adjustedDepth = guidedDepth = outputDepth = paintedDepth = colorMatchMap = null;
  sourceBackgroundMask = outputBackgroundMask = null;
  if (sourceUrl) URL.revokeObjectURL(sourceUrl);
  sourceUrl = null;
  input.value = "";
  sourcePreview.hidden = true;
  basePreview.hidden = true;
  basePreviewCanvas.width = 0;
  basePreviewCanvas.height = 0;
  guidancePreviewCanvas.width = 0;
  guidancePreviewCanvas.height = 0;
  parallaxSourceCanvas.width = 0;
  parallaxSourceCanvas.height = 0;
  parallaxPreviewCanvas.width = 0;
  parallaxPreviewCanvas.height = 0;
  parallaxMaskCanvas.width = 0;
  parallaxMaskCanvas.height = 0;
  parallaxPreviewSummary.textContent = "Generate a depthmap to inspect the parallax conversion.";
  scratchPreviewCanvas.width = 0;
  scratchPreviewCanvas.height = 0;
  scratchPreviewSummary.textContent = "Generate a depthmap to inspect the scratch geometry.";
  processingPanel.hidden = true;
  workspace.hidden = true;
  resetButton.disabled = true;
  generateButton.disabled = true;
  setUploadStatus("Waiting for an image.");
  setProcessingStatus("Depth processing has not started.");
}

function updateInputMode() {
  const direct = inputModeControl.value === "depthmap";
  parallaxBackgroundControl.disabled = direct;
  scratchBackgroundControl.disabled = direct;
  generateButton.textContent = direct ? "Use Existing Depthmap" : "Initialize Depthmap";
  inputModeHelp.textContent = direct
    ? "Uses grayscale values directly without AI inference. Pure-white or transparent pixels become Krasnow's explicit source background; the cutoff control is not applied. Edge ramps may extend into that background."
    : "Uses browser-based AI to estimate relative depth from an ordinary photograph or illustration.";
  uploadPrompt.textContent = direct
    ? "Drop an existing grayscale depthmap here, or select one from your device."
    : "Drop a PNG, JPEG, WebP, BMP, or TIFF here, or select one from your device.";
  if (sourceFile) setProcessingStatus(direct ? "Ready to use the existing grayscale depthmap." : "Ready to generate a depth map.");
}

function createSwatchControls() {
  for (const swatch of paletteState) {
    const card = document.createElement("article");
    card.className = "color-card";
    const name = document.createElement("span");
    name.className = "color-name";
    name.textContent = swatch.name;
    const square = document.createElement("button");
    square.className = "color-square";
    square.type = "button";
    square.style.setProperty("--depth-swatch-color", swatch.hex);
    const hex = document.createElement("span");
    hex.className = "color-hex";
    hex.textContent = swatch.hex;
    card.append(name, square, hex);
    const update = (rerender = true) => {
      const paletteSelected = Boolean(savedDepthPaletteSelect.value);
      square.classList.toggle("selected", paletteSelected && !swatch.enabled);
      square.setAttribute("aria-pressed", String(paletteSelected && !swatch.enabled));
      square.setAttribute("aria-disabled", String(!paletteSelected));
      square.setAttribute("aria-label", paletteSelected ? `${swatch.enabled ? "Exclude" : "Include"} ${swatch.name} from color-guided depth` : `${swatch.name}; choose a Depth Palette to enable this swatch`);
      square.title = paletteSelected ? (swatch.enabled ? `Click to exclude ${swatch.name}` : `Click to include ${swatch.name}`) : `${swatch.name} is available after choosing a Depth Palette`;
      if (rerender && rawDepth) renderAdjustedDepth();
    };
    square.addEventListener("click", () => {
      if (!savedDepthPaletteSelect.value) return;
      swatch.enabled = !swatch.enabled;
      update(true);
    });
    swatch.enabled = false;
    update(false);
    swatch.controls = {card, square};
    swatch.update = update;
    swatchGrid.appendChild(card);
  }
}

async function loadSavedDepthPalettes() {
  if (window.serverlessDepthResources) {
    savedDepthPalettes = window.serverlessDepthResources.depth_palettes || [];
    const chooseOption = new Option("Choose a saved Depth Palette", "");
    savedDepthPaletteSelect.replaceChildren(chooseOption);
    for (const palette of savedDepthPalettes) {
      savedDepthPaletteSelect.add(new Option(palette.name || "Depth Palette", palette.palette_id));
    }
    depthPalettePicker.hidden = false;
    if (window.serverlessDepthGuest) {
      depthPalettePicker.hidden = true;
      depthPaletteRequired.innerHTML = 'Color-guided depth is optional. <a class="vault-depth-link" href="/">Sign in or create an account</a> to use saved Depth Palettes; all other Depthmap Lab tools remain available to guests.';
      return;
    }
    depthPaletteRequired.innerHTML = savedDepthPalettes.length
      ? "Color-guided depth is optional. Choose a saved Depth Palette to enable its swatches."
      : "Color-guided depth is optional. No saved Depth Palettes are available in this staging account.";
    return;
  }
  const auth = await (window.machineChrome?.authStatus || Promise.resolve({signed_in:false}));
  if (!auth.signed_in) {
    depthPaletteRequired.hidden = false;
    return;
  }
  const response = await fetch("/account/depth-palettes", {credentials:"same-origin"});
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || "Could not load saved Depth Palettes.");
  savedDepthPalettes = data.palettes || [];
  const chooseOption = new Option("Choose a saved Depth Palette", "");
  savedDepthPaletteSelect.replaceChildren(chooseOption);
  for (const palette of savedDepthPalettes) {
    savedDepthPaletteSelect.add(new Option(palette.name || "Depth Palette", palette.palette_id));
  }
  depthPalettePicker.hidden = false;
  depthPaletteRequired.innerHTML = savedDepthPalettes.length
    ? 'Color-guided depth is optional. Choose a saved Depth Palette to enable its swatches.'
    : 'Color-guided depth is optional. Create a Depth Palette in <a class="vault-depth-link" href="/material-libraries">Swatch Palette Vault</a> to map colors to artificial depth and perspective influence.';
}

function selectDepthPalette() {
  const palette = savedDepthPalettes.find(item => item.palette_id === savedDepthPaletteSelect.value);
  colorGuidancePanel.classList.toggle("awaiting-depth-palette", !palette);
  depthGuidanceTools.hidden = !palette;
  depthPaletteRequired.hidden = Boolean(palette);
  if (!palette) {
    for (const swatch of paletteState) {
      swatch.controls.card.hidden = false;
      swatch.enabled = false;
      swatch.influence = 0;
      swatch.update(false);
    }
    if (rawDepth) renderAdjustedDepth();
    return;
  }
  const entries = new Map((palette.entries || []).map(entry => [String(entry.hex).toUpperCase(), entry]));
  for (const swatch of paletteState) {
    const entry = entries.get(swatch.hex.toUpperCase());
    swatch.controls.card.hidden = !entry;
    swatch.enabled = entry?.enabled !== false && Boolean(entry);
    swatch.depth = entry?.depth ?? 50;
    swatch.influence = entry?.influence ?? 0;
    swatch.update(false);
  }
  if (rawDepth) renderAdjustedDepth();
}


input.addEventListener("change", () => acceptFile(input.files[0]).catch(cause => setUploadStatus(cause.message, true)));
inputModeControl.addEventListener("change", updateInputMode);
generateButton.addEventListener("click", generateDepth);
resetButton.addEventListener("click", reset);
for (const eventName of ["dragenter", "dragover"]) dropZone.addEventListener(eventName, event => { event.preventDefault(); dropZone.classList.add("is-dragging"); });
for (const eventName of ["dragleave", "drop"]) dropZone.addEventListener(eventName, event => { event.preventDefault(); dropZone.classList.remove("is-dragging"); });
dropZone.addEventListener("drop", event => acceptFile(event.dataTransfer.files[0]).catch(cause => setUploadStatus(cause.message, true)));
for (const control of [nearControl, farControl, gammaControl, invertControl]) control.addEventListener("input", () => {
  if (Number(nearControl.value) >= Number(farControl.value)) nearControl.value = Math.max(0, Number(farControl.value) - 5);
  document.querySelector("#depth_near_value").value = `${nearControl.value}%`;
  document.querySelector("#depth_far_value").value = `${farControl.value}%`;
  document.querySelector("#depth_gamma_value").value = (Number(gammaControl.value) / 100).toFixed(2);
  updateBrushDepthPreview();
  if (control === invertControl) for (const swatch of paletteState) swatch.update(false);
  renderAdjustedDepth();
});
guidanceFeatherControl.addEventListener("input", () => {
  guidanceFeatherValue.value = `${guidanceFeatherControl.value} px`;
  if (rawDepth) renderAdjustedDepth();
});
savedDepthPaletteSelect.addEventListener("change", selectDepthPalette);
outputWidthControl.addEventListener("change", () => {
  syncOutputAspect("width");
  renderAdjustedDepth();
});
outputHeightControl.addEventListener("change", () => {
  syncOutputAspect("height");
  renderAdjustedDepth();
});
borderPaddingControl.addEventListener("change", renderAdjustedDepth);
perimeterDepthControl.addEventListener("input", () => {
  perimeterDepthOverride = Number(perimeterDepthControl.value) / 100;
  renderAdjustedDepth();
});
brushSizeControl.addEventListener("input", updateBrushSizePreview);
brushDepthControl.addEventListener("input", updateBrushDepthPreview);
clearPaintButton.addEventListener("click", clearPaintedDepth);
mapCanvas.addEventListener("pointerdown", event => {
  if (!outputDepth) return;
  paintingFarDepth = true;
  lastPaintPoint = null;
  mapCanvas.setPointerCapture(event.pointerId);
  paintFarDepth(event);
});
mapCanvas.addEventListener("pointermove", paintFarDepth);
for (const eventName of ["pointerup", "pointercancel", "lostpointercapture"]) {
  mapCanvas.addEventListener(eventName, () => { paintingFarDepth = false; lastPaintPoint = null; });
}
document.querySelector("#depth_export_8").addEventListener("click", export8Bit);
document.querySelector("#depth_export_16").addEventListener("click", () => export16Bit().catch(cause => setProcessingStatus(cause.message, true)));
document.querySelector("#depth_export_parallax").addEventListener("click", exportParallax);
parallaxSvgButton.addEventListener("click", () => exportParallaxSvg().catch(cause => setProcessingStatus(cause.message, true)));
parallaxScaleControl.addEventListener("input", updateParallaxControls);
parallaxBackgroundControl.addEventListener("input", updateParallaxControls);
parallaxPatchSizeControl.addEventListener("input", updateParallaxControls);
scratchSvgButton.addEventListener("click", () => exportScratchHologramSvg().catch(cause => setProcessingStatus(cause.message, true)));
for (const control of [
  scratchPixelSizeControl,
  scratchSampleStepControl,
  scratchNearDepthControl,
  scratchDepthRangeControl,
  scratchViewSweepControl,
  scratchBackgroundControl,
  scratchStrokeWidthControl,
]) control.addEventListener("input", updateScratchControls);
drawLegend();
updateParallaxControls();
updateScratchControls();
updateInputMode();
updateBrushDepthPreview();
updateBrushSizePreview();
createSwatchControls();
loadSavedDepthPalettes().catch(cause => setProcessingStatus(cause.message, true));
