import { createKrasnowParallaxPixels } from "./depthmap_parallax.js";
import { createKrasnowParallaxSvg, parallaxCellIsEngraved } from "./depthmap_parallax_svg.js";
import { createReliefLayers, createReliefLightBurn, reliefVisibleMasks, traceMaskContours } from "./depthmap_layered_relief.js?v=4";

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
const parallaxAppearanceControl = document.querySelector("#depth_parallax_appearance");
const parallaxPhysicalSize = document.querySelector("#depth_parallax_physical_size");
const parallaxSvgButton = document.querySelector("#depth_export_parallax_svg");
const parallaxPreviewCanvas = document.querySelector("#depth_parallax_preview_canvas");
const parallaxMaskCanvas = document.querySelector("#depth_parallax_mask_canvas");
const parallaxPreviewSummary = document.querySelector("#depth_parallax_preview_summary");
const reliefLayerCountControl = document.querySelector("#depth_relief_layers");
const reliefConstructionControl = document.querySelector("#depth_relief_construction");
const reliefSpacingControl = document.querySelector("#depth_relief_spacing");
const reliefSmoothingControl = document.querySelector("#depth_relief_smoothing");
const reliefSmoothingValue = document.querySelector("#depth_relief_smoothing_value");
const reliefNaturalControls = document.querySelector("#depth_relief_natural_controls");
const reliefGroupingStrengthControl = document.querySelector("#depth_relief_grouping_strength");
const reliefGroupingStrengthValue = document.querySelector("#depth_relief_grouping_strength_value");
const reliefMinimumBandControl = document.querySelector("#depth_relief_minimum_band");
const reliefEmphasisControl = document.querySelector("#depth_relief_emphasis");
const reliefEmphasisValue = document.querySelector("#depth_relief_emphasis_value");
const reliefHistogramCanvas = document.querySelector("#depth_relief_histogram");
const reliefThresholdStatus = document.querySelector("#depth_relief_threshold_status");
const reliefThresholdSliders = document.querySelector("#depth_relief_threshold_sliders");
const reliefResetThresholdsButton = document.querySelector("#depth_relief_reset_thresholds");
const reliefPixelSizeControl = document.querySelector("#depth_relief_pixel_size");
const reliefMaterialThicknessControl = document.querySelector("#depth_relief_material_thickness");
const reliefMinimumIslandControl = document.querySelector("#depth_relief_minimum_island");
const reliefWorkbedWidthControl = document.querySelector("#depth_relief_workbed_width");
const reliefWorkbedHeightControl = document.querySelector("#depth_relief_workbed_height");
const reliefPaletteControl = document.querySelector("#depth_relief_palette");
const reliefSettingControl = document.querySelector("#depth_relief_setting");
const reliefSettingStatus = document.querySelector("#depth_relief_setting_status");
const reliefSurfaceEngravingControl = document.querySelector("#depth_relief_surface_engraving");
const reliefPhotoControls = document.querySelector("#depth_relief_photo_controls");
const reliefPhotoSettingControl = document.querySelector("#depth_relief_photo_setting");
const reliefPhotoSettingStatus = document.querySelector("#depth_relief_photo_setting_status");
const reliefExcludeBackgroundControl = document.querySelector("#depth_relief_exclude_background");
const reliefRegistrationControl = document.querySelector("#depth_relief_registration");
const reliefRegistrationControls = document.querySelector("#depth_relief_registration_controls");
const reliefRegistrationDiameterControl = document.querySelector("#depth_relief_registration_diameter");
const reliefRegistrationInsetControl = document.querySelector("#depth_relief_registration_inset");
const reliefExportButton = document.querySelector("#depth_export_layered_relief");
const reliefPreviewLayerControl = document.querySelector("#depth_relief_preview_layer");
const reliefPreviewLayerValue = document.querySelector("#depth_relief_preview_layer_value");
const reliefLayerCanvas = document.querySelector("#depth_relief_layer_canvas");
const reliefCompositeCanvas = document.querySelector("#depth_relief_composite_canvas");
const reliefSummary = document.querySelector("#depth_relief_summary");
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
let reliefMaterialLibraries = [];

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
let sourceLuminance = null;
let sourceRgba = null;
let outputDepth = null;
let outputSourceLuminance = null;
let outputSourceRgba = null;
let outputBackgroundMask = null;
let outputWidth = 0;
let outputHeight = 0;
let paintedDepth = null;
let perimeterDepthOverride = null;
let paintingFarDepth = false;
let lastPaintPoint = null;
let parallaxPreviewTimer = null;
let reliefPreviewTimer = null;
let reliefThresholdOverrides = null;
let displayedReliefThresholds = [];

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
  reliefThresholdOverrides = null;
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
  sourceLuminance = new Uint8Array(depthWidth * depthHeight);
  sourceRgba = new Uint8ClampedArray(pixels);
  colorMatchMap.fill(-1);
  for (let index = 0; index < colorMatchMap.length; index += 1) {
    const offset = index * 4;
    const alpha = pixels[offset + 3] / 255;
    const redValue = pixels[offset] * alpha + 255 * (1 - alpha);
    const greenValue = pixels[offset + 1] * alpha + 255 * (1 - alpha);
    const blueValue = pixels[offset + 2] * alpha + 255 * (1 - alpha);
    sourceLuminance[index] = Math.round(redValue * .2126 + greenValue * .7152 + blueValue * .0722);
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
  outputSourceLuminance = new Uint8Array(outputLength);
  outputSourceLuminance.fill(255);
  outputSourceRgba = new Uint8ClampedArray(outputLength * 4);
  outputSourceRgba.fill(255);
  outputBackgroundMask = sourceBackgroundMask ? new Uint8Array(outputLength) : null;
  if (outputBackgroundMask) outputBackgroundMask.fill(1);
  for (let y = 0; y < contentHeight; y += 1) {
    const sourceY = Math.min(depthHeight - 1, Math.floor(y * depthHeight / contentHeight));
    for (let x = 0; x < contentWidth; x += 1) {
      const sourceX = Math.min(depthWidth - 1, Math.floor(x * depthWidth / contentWidth));
      const outputIndex = (y + offsetY) * outputWidth + x + offsetX;
      const sourceIndex = sourceY * depthWidth + sourceX;
      outputDepth[outputIndex] = guidedDepth[sourceIndex];
      outputSourceLuminance[outputIndex] = sourceLuminance[sourceIndex];
      outputSourceRgba.set(sourceRgba.subarray(sourceIndex * 4, sourceIndex * 4 + 4), outputIndex * 4);
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
  reliefThresholdOverrides = null;
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
  scheduleReliefPreview();
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
    return {depth:outputDepth, detail:outputSourceLuminance, backgroundMask:outputBackgroundMask, width, height, horizontalScale:1};
  }
  const depth = new Float32Array(width * height);
  const detail = new Uint8Array(width * height);
  const backgroundMask = outputBackgroundMask ? new Uint8Array(width * height) : null;
  for (let y = 0; y < height; y += 1) {
    const sourceY = Math.min(outputHeight - 1, Math.floor(y * outputHeight / height));
    for (let x = 0; x < width; x += 1) {
      const sourceX = Math.min(outputWidth - 1, Math.floor(x * outputWidth / width));
      const previewIndex = y * width + x;
      const sourceIndex = sourceY * outputWidth + sourceX;
      depth[previewIndex] = outputDepth[sourceIndex];
      detail[previewIndex] = outputSourceLuminance[sourceIndex];
      if (backgroundMask) backgroundMask[previewIndex] = outputBackgroundMask[sourceIndex];
    }
  }
  return {depth, detail, backgroundMask, width, height, horizontalScale:width / outputWidth};
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
    const isExplicitBackground = preview.backgroundMask && Boolean(preview.backgroundMask[index]);
    const isCutoffBackground = preview.backgroundMask
      ? cutoff > 0 && proximity <= cutoff
      : proximity <= cutoff;
    const isSourceBackground = isExplicitBackground || isCutoffBackground;
    if (isSourceBackground) sourceBackgroundCount += 1;
    const x = index % preview.width;
    const y = Math.floor(index / preview.width);
    const isUnengraved = !parallaxCellIsEngraved(
      pixels[index],
      preview.detail[index],
      x,
      y,
      parallaxAppearanceControl.value,
    );
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
  const sourceLabel = preview.backgroundMask
    ? "explicit or cutoff-derived source background"
    : "cutoff-derived source background";
  const appearanceLabel = parallaxAppearanceControl.value === "source-detail" ? "Source Image Detail" : "Silhouette";
  parallaxPreviewSummary.textContent = `${appearanceLabel}: ${sourceBackgroundPercentage.toFixed(1)}% ${sourceLabel}; ${unengravedPercentage.toFixed(1)}% of cells remain unengraved after source coverage and edge ramps.`;
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
      appearanceMode:parallaxAppearanceControl.value,
      detailPixels:outputSourceLuminance,
      onProgress:(row, total) => {
        if (row === total || row === 1 || row % Math.max(1, Math.ceil(total / 20)) === 0) {
          setProcessingStatus(`Building Parallax SVG grating geometry locally: row ${row} of ${total}.`);
        }
      },
    });
    downloadBlob(blob, "parallax-grating", "svg");
    const appearanceLabel = parallaxAppearanceControl.value === "source-detail" ? "Source Image Detail" : "Silhouette";
    setProcessingStatus(`Parallax SVG grating geometry created locally in ${appearanceLabel} mode and downloaded.`);
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

function reliefOptions(backgroundMask = outputBackgroundMask) {
  const maximumLayers = reliefSurfaceEngravingControl.checked ? 15 : 30;
  return {
    layers:Math.min(maximumLayers, Math.max(2, Math.round(Number(reliefLayerCountControl.value) || 7))),
    inverted:invertControl.checked,
    spacing:reliefSpacingControl.value,
    smoothing:Math.min(4, Math.max(0, Math.round(Number(reliefSmoothingControl.value) || 0))),
    groupingStrength:Math.min(1, Math.max(0, Number(reliefGroupingStrengthControl.value) / 100 || 0)),
    minimumBandShare:Math.min(40, Math.max(0, Number(reliefMinimumBandControl.value) || 0)),
    emphasis:Math.min(1, Math.max(-1, Number(reliefEmphasisControl.value) / 100 || 0)),
    thresholds:reliefThresholdOverrides,
    construction:reliefConstructionControl.value,
    minimumIslandArea:Math.max(0, Math.round(Number(reliefMinimumIslandControl.value) || 0)),
    backgroundMask:reliefExcludeBackgroundControl.checked ? backgroundMask : null,
  };
}

function reliefExportOptions() {
  return {
    pixelSizeMm:Math.max(.001, Number(reliefPixelSizeControl.value) || .1),
    materialThicknessMm:Math.max(.01, Number(reliefMaterialThicknessControl.value) || 3),
    workbedWidthMm:Math.max(0, Number(reliefWorkbedWidthControl.value) || 0),
    workbedHeightMm:Math.max(0, Number(reliefWorkbedHeightControl.value) || 0),
    registrationHoles:reliefRegistrationControl.checked,
    registrationDiameterMm:Math.max(.1, Number(reliefRegistrationDiameterControl.value) || 3),
    registrationInsetMm:Math.max(.1, Number(reliefRegistrationInsetControl.value) || 5),
    cutSetting:selectedReliefCutSetting(),
    surfaceEngraving:reliefSurfaceEngravingControl.checked,
    photoSetting:selectedReliefPhotoSetting(),
  };
}

function selectedReliefLibrary() {
  return reliefMaterialLibraries.find(library => String(library.library_id) === reliefPaletteControl.value);
}

function selectedReliefSetting(control) {
  const library = selectedReliefLibrary();
  const entry = (library?.summary?.entries || []).find(item => String(item.entry_id) === control.value);
  if (!entry) return null;
  return {
    description:entry.description || "Selected setting",
    material:entry.material || library.material_name || "",
    type:entry.type || "Cut",
    settings:entry.settings || {},
  };
}

function selectedReliefCutSetting() {
  return selectedReliefSetting(reliefSettingControl);
}

function selectedReliefPhotoSetting() {
  return selectedReliefSetting(reliefPhotoSettingControl);
}

function populateReliefSettings() {
  const library = selectedReliefLibrary();
  const entries = library?.summary?.entries || [];
  reliefSettingControl.replaceChildren(new Option("Choose a setting…", ""));
  reliefPhotoSettingControl.replaceChildren(new Option("Choose a Photo setting…", ""));
  for (const entry of entries) {
    const label = entry.description || `Setting ${Number(entry.entry_id) + 1}`;
    reliefSettingControl.add(new Option(label, String(entry.entry_id)));
    reliefPhotoSettingControl.add(new Option(label, String(entry.entry_id)));
  }
  reliefSettingControl.disabled = !entries.length;
  reliefPhotoSettingControl.disabled = !entries.length;
  const roles = (window.serverlessDepthResources?.preferences?.processing_palette_role_assignments || {})[library?.library_id] || {};
  const roleEntry = role => {
    const explicitlyAssigned = Object.prototype.hasOwnProperty.call(roles, role);
    const assigned = String(roles[role] || "").trim().toLowerCase();
    return entries.find(entry => assigned && String(entry.description || "").trim().toLowerCase() === assigned)
      || (!explicitlyAssigned ? entries.find(entry => String(entry.description || "").trim().toLowerCase() === role.toLowerCase()) : null);
  };
  const cut = roleEntry("Cut");
  const photo = roleEntry("Photo");
  const preferred = cut || entries[0];
  reliefSettingControl.value = preferred ? String(preferred.entry_id) : "";
  reliefPhotoSettingControl.value = photo ? String(photo.entry_id) : "";
  updateReliefSettingStatus();
}

function updateReliefSettingStatus() {
  const setting = selectedReliefCutSetting();
  if (setting) {
    const source = [setting.material, setting.description].filter(Boolean).join(" · ");
    reliefSettingStatus.textContent = String(setting.type).toLowerCase() === "cut"
      ? `${source} will be copied to every Layered Relief cutting layer. Enable only one layer at a time before running the laser.`
      : `${source} is not a LightBurn Line setting. Choose an entry whose Cut Mode is Line so the relief contours remain editable cutting paths.`;
    updateReliefPhotoControls();
    return;
  }
  reliefSettingStatus.textContent = reliefMaterialLibraries.length
    ? "Choose a Processing Palette and Cut setting to use for every Layered Relief cutting layer."
    : "No saved Processing Palettes are available. Import one in the Swatch Palette Vault before exporting a Layered Relief project.";
  updateReliefPhotoControls();
}

function updateReliefPhotoControls() {
  const enabled = reliefSurfaceEngravingControl.checked;
  const maximumLayers = enabled ? 15 : 30;
  reliefLayerCountControl.max = String(maximumLayers);
  if (Number(reliefLayerCountControl.value) > maximumLayers) reliefLayerCountControl.value = String(maximumLayers);
  reliefPhotoControls.hidden = !enabled;
  if (!enabled) {
    reliefPhotoSettingStatus.textContent = "Surface photo engraving is off. The project will contain cutting contours only.";
    return;
  }
  const setting = selectedReliefPhotoSetting();
  if (setting) {
    const source = [setting.material, setting.description].filter(Boolean).join(" · ");
    reliefPhotoSettingStatus.textContent = String(setting.type).toLowerCase() === "image"
      ? `${source} will be copied to each visible-surface bitmap. Its saved LightBurn image mode and processing options are preserved.`
      : `${source} is not a LightBurn Image setting. Choose an entry whose Cut Mode is Image so its grayscale or dither mode can be preserved.`;
  } else {
    reliefPhotoSettingStatus.textContent = "Choose the LightBurn image setting for the visible-surface bitmaps. The Processing Palette's Photo role is selected automatically when available.";
  }
}

function loadReliefCutSettings() {
  reliefMaterialLibraries = (window.serverlessDepthResources?.material_libraries || [])
    .filter(library => library.library_intent === "processing_palette" && (library.summary?.entries || []).length);
  reliefPaletteControl.replaceChildren(new Option("Choose a Processing Palette…", ""));
  for (const library of reliefMaterialLibraries) {
    reliefPaletteControl.add(new Option(library.name || library.material_name || "Processing Palette", String(library.library_id)));
  }
  reliefPaletteControl.disabled = !reliefMaterialLibraries.length;
  reliefPaletteControl.value = reliefMaterialLibraries.length ? String(reliefMaterialLibraries[0].library_id) : "";
  populateReliefSettings();
}

function paintReliefCutPaths(context, mask, width, height, options) {
  const lineWidth = Math.max(1, Math.min(width, height) / 350);
  context.save();
  context.strokeStyle = "#ff3030";
  context.lineWidth = lineWidth;
  context.lineJoin = "round";
  context.lineCap = "round";
  for (const contour of traceMaskContours(mask, width, height)) {
    context.beginPath();
    contour.forEach(([x, y], index) => index ? context.lineTo(x, y) : context.moveTo(x, y));
    context.stroke();
  }
  if (options.registrationHoles) {
    const pixelSize = Math.max(.001, Number(options.pixelSizeMm) || .1);
    const artworkWidth = width * pixelSize;
    const artworkHeight = height * pixelSize;
    const diameter = Math.min(Math.min(artworkWidth, artworkHeight), Math.max(.1, Number(options.registrationDiameterMm) || 3));
    const radius = diameter / 2;
    const maximumInset = Math.max(radius, Math.min(artworkWidth, artworkHeight) / 2);
    const inset = Math.min(maximumInset, Math.max(radius, Number(options.registrationInsetMm) || 5));
    const positions = [[inset, inset], [artworkWidth - inset, inset], [artworkWidth - inset, artworkHeight - inset], [inset, artworkHeight - inset]];
    for (const [x, y] of positions) {
      context.beginPath();
      context.arc(x / pixelSize, y / pixelSize, radius / pixelSize, 0, Math.PI * 2);
      context.stroke();
    }
  }
  context.restore();
}

function paintReliefMask(canvas, mask, width, height, options) {
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  const image = context.createImageData(width, height);
  for (let index = 0; index < mask.length; index += 1) {
    const value = mask[index] ? 24 : 244;
    const offset = index * 4;
    image.data[offset] = value;
    image.data[offset + 1] = value;
    image.data[offset + 2] = value;
    image.data[offset + 3] = 255;
  }
  context.putImageData(image, 0, 0);
  paintReliefCutPaths(context, mask, width, height, options);
}

function paintReliefComposite(canvas, relief) {
  const colors = [[35,52,40],[60,83,54],[79,110,68],[102,137,82],[132,163,102],[168,190,130],[211,209,166]];
  canvas.width = relief.width;
  canvas.height = relief.height;
  const context = canvas.getContext("2d");
  const image = context.createImageData(relief.width, relief.height);
  for (let index = 0; index < relief.width * relief.height; index += 1) {
    let top = -1;
    for (let layerIndex = 0; layerIndex < relief.layers.length; layerIndex += 1) if (relief.layers[layerIndex].mask[index]) top = layerIndex;
    const offset = index * 4;
    if (top < 0) {
      image.data[offset + 3] = 0;
      continue;
    }
    const paletteIndex = relief.layers.length === 1 ? 0 : Math.round(top / (relief.layers.length - 1) * (colors.length - 1));
    const color = colors[paletteIndex];
    image.data[offset] = color[0];
    image.data[offset + 1] = color[1];
    image.data[offset + 2] = color[2];
    image.data[offset + 3] = 255;
  }
  context.putImageData(image, 0, 0);
}

function reliefHistogram(depth, backgroundMask) {
  const bins = new Uint32Array(128);
  for (let index = 0; index < depth.length; index += 1) {
    if (backgroundMask?.[index]) continue;
    const value = Math.min(1, Math.max(0, Number(depth[index]) || 0));
    bins[Math.min(bins.length - 1, Math.floor(value * bins.length))] += 1;
  }
  return bins;
}

function drawReliefHistogram(relief, backgroundMask) {
  const context = reliefHistogramCanvas.getContext("2d");
  const width = reliefHistogramCanvas.width;
  const height = reliefHistogramCanvas.height;
  const light = document.body.classList.contains("light-machine");
  context.clearRect(0, 0, width, height);
  context.fillStyle = light ? "#f2f0e8" : "#151814";
  context.fillRect(0, 0, width, height);
  const bins = reliefHistogram(relief.proximityDepth, backgroundMask);
  const maximum = Math.max(1, ...bins);
  context.fillStyle = light ? "#657064" : "#7c9572";
  const binWidth = width / bins.length;
  for (let index = 0; index < bins.length; index += 1) {
    const barHeight = bins[index] / maximum * (height - 18);
    context.fillRect(index * binWidth, height - barHeight, Math.max(1, binWidth - 1), barHeight);
  }
  context.strokeStyle = "#ff4545";
  context.fillStyle = light ? "#7b1212" : "#ffb0a8";
  context.lineWidth = 2;
  context.font = "bold 11px monospace";
  context.textAlign = "center";
  relief.thresholds.slice(1).forEach((threshold, index) => {
    const x = Math.round(threshold * width) + .5;
    context.beginPath();
    context.moveTo(x, 0);
    context.lineTo(x, height);
    context.stroke();
    context.fillText(String(index + 1), Math.min(width - 7, Math.max(7, x)), 12);
  });
  context.fillStyle = light ? "#343730" : "#c5c7b5";
  context.textAlign = "left";
  context.fillText("far", 6, height - 5);
  context.textAlign = "right";
  context.fillText("near", width - 6, height - 5);
}

function currentManualReliefThresholds(firstThreshold) {
  return [firstThreshold, ...[...reliefThresholdSliders.querySelectorAll("input[type=range]")]
    .map(control => Number(control.value) / 100)];
}

function renderReliefThresholdControls(relief, backgroundMask) {
  displayedReliefThresholds = [...relief.thresholds];
  const boundaries = relief.thresholds.slice(1);
  const existing = [...reliefThresholdSliders.querySelectorAll("input[type=range]")];
  if (existing.length !== boundaries.length) {
    reliefThresholdSliders.replaceChildren();
    boundaries.forEach((threshold, index) => {
      const row = document.createElement("label");
      row.className = "depth-threshold-row";
      const caption = document.createElement("span");
      caption.textContent = `Boundary ${index + 1} · layers ${index + 1} / ${index + 2}`;
      const control = document.createElement("input");
      control.type = "range";
      control.min = "0";
      control.max = "100";
      control.step = "0.1";
      control.dataset.boundaryIndex = String(index);
      const output = document.createElement("output");
      const controlWrap = document.createElement("span");
      controlWrap.className = "depth-threshold-control";
      controlWrap.append(control, output);
      row.append(caption, controlWrap);
      reliefThresholdSliders.append(row);
      control.addEventListener("input", () => {
        const controls = [...reliefThresholdSliders.querySelectorAll("input[type=range]")];
        const position = Number(control.dataset.boundaryIndex);
        const lower = position ? Number(controls[position - 1].value) + .1 : displayedReliefThresholds[0] * 100 + .1;
        const upper = position + 1 < controls.length ? Number(controls[position + 1].value) - .1 : 100;
        control.value = String(Math.min(upper, Math.max(lower, Number(control.value))));
        output.value = `${Number(control.value).toFixed(1)}%`;
        reliefThresholdOverrides = currentManualReliefThresholds(displayedReliefThresholds[0]);
        scheduleReliefPreview();
      });
    });
  }
  [...reliefThresholdSliders.querySelectorAll("input[type=range]")].forEach((control, index) => {
    if (document.activeElement !== control) control.value = String(boundaries[index] * 100);
    control.nextElementSibling.value = `${Number(control.value).toFixed(1)}%`;
  });
  let excluded = 0;
  if (backgroundMask) for (const value of backgroundMask) excluded += value;
  const total = Math.max(1, relief.proximityDepth.length - excluded);
  const shares = relief.layers.map(layer => {
    const count = layer.mask.reduce((sum, value) => sum + value, 0);
    return `${(count / total * 100).toFixed(1)}%`;
  }).join(" · ");
  const reduced = relief.layers.length < relief.requestedLayerCount
    ? ` The available depth detail supports ${relief.layers.length} distinct bands rather than the ${relief.requestedLayerCount} requested.`
    : "";
  reliefThresholdStatus.textContent = `${reliefThresholdOverrides ? "Manual" : "Automatic"} boundaries. Layer coverage: ${shares}.${reduced}`;
  reliefResetThresholdsButton.disabled = !reliefThresholdOverrides;
}

function drawReliefPreview() {
  reliefPreviewTimer = null;
  if (!outputDepth || !outputWidth || !outputHeight) return;
  const preview = previewDepthMap();
  const options = reliefOptions(preview.backgroundMask);
  reliefLayerCountControl.value = options.layers;
  const relief = createReliefLayers(preview.depth, preview.width, preview.height, options);
  const actualLayers = relief.layers.length;
  reliefPreviewLayerControl.max = String(actualLayers);
  reliefPreviewLayerControl.value = String(Math.min(actualLayers, Math.max(1, Number(reliefPreviewLayerControl.value) || 1)));
  const selectedIndex = Number(reliefPreviewLayerControl.value) - 1;
  const exportOptions = reliefExportOptions();
  paintReliefMask(reliefLayerCanvas, relief.layers[selectedIndex].mask, relief.width, relief.height, exportOptions);
  paintReliefComposite(reliefCompositeCanvas, relief);
  reliefPreviewLayerValue.value = `${selectedIndex + 1} of ${actualLayers} · ${selectedIndex === 0 ? "rear" : selectedIndex === actualLayers - 1 ? "front" : "middle"}`;
  const physicalWidth = outputWidth * exportOptions.pixelSizeMm;
  const physicalHeight = outputHeight * exportOptions.pixelSizeMm;
  const occupied = relief.layers[selectedIndex].mask.reduce((sum, value) => sum + value, 0);
  const coverage = occupied / relief.layers[selectedIndex].mask.length * 100;
  const requestedNote = actualLayers < options.layers ? ` (${options.layers} requested)` : "";
  reliefSummary.textContent = `${actualLayers} layers${requestedNote} · ${physicalWidth.toFixed(2)} × ${physicalHeight.toFixed(2)} mm each · ${(actualLayers * exportOptions.materialThicknessMm).toFixed(2)} mm nominal assembled depth · selected layer covers ${coverage.toFixed(1)}% of the canvas.`;
  drawReliefHistogram(relief, options.backgroundMask);
  renderReliefThresholdControls(relief, options.backgroundMask);
}

function scheduleReliefPreview() {
  if (reliefPreviewTimer !== null) clearTimeout(reliefPreviewTimer);
  if (!outputDepth) return;
  reliefPreviewTimer = setTimeout(drawReliefPreview, 100);
}

function updateReliefControls() {
  const maximumLayers = reliefSurfaceEngravingControl.checked ? 15 : 30;
  const layers = Math.min(maximumLayers, Math.max(2, Math.round(Number(reliefLayerCountControl.value) || 7)));
  reliefLayerCountControl.value = layers;
  reliefPreviewLayerControl.max = String(layers);
  reliefRegistrationControls.hidden = !reliefRegistrationControl.checked;
  reliefNaturalControls.hidden = reliefSpacingControl.value !== "natural";
  const smoothing = Math.min(4, Math.max(0, Math.round(Number(reliefSmoothingControl.value) || 0)));
  reliefSmoothingControl.value = String(smoothing);
  reliefSmoothingValue.value = smoothing === 1 ? "1 pass" : `${smoothing} passes`;
  reliefGroupingStrengthValue.value = `${Math.round(Number(reliefGroupingStrengthControl.value) || 0)}%`;
  const emphasis = Math.round(Number(reliefEmphasisControl.value) || 0);
  reliefEmphasisValue.value = emphasis === 0 ? "Balanced" : `${Math.abs(emphasis)}% ${emphasis < 0 ? "farther" : "nearer"}`;
  scheduleReliefPreview();
}

function resetReliefThresholds() {
  reliefThresholdOverrides = null;
  reliefResetThresholdsButton.disabled = true;
  scheduleReliefPreview();
}

function updateReliefQuantizationControls() {
  reliefThresholdOverrides = null;
  updateReliefControls();
}

function createReliefSurfaceImages(relief) {
  if (!outputSourceRgba || outputSourceRgba.length !== relief.width * relief.height * 4) {
    throw new Error("The uploaded image is not available for Layered Relief surface engraving. Generate the depthmap again and retry.");
  }
  const visibleMasks = reliefVisibleMasks(relief);
  return visibleMasks.map((mask, layerIndex) => {
    const canvas = document.createElement("canvas");
    canvas.width = relief.width;
    canvas.height = relief.height;
    const context = canvas.getContext("2d");
    const image = context.createImageData(relief.width, relief.height);
    image.data.fill(255);
    for (let index = 0; index < mask.length; index += 1) {
      if (!mask[index]) continue;
      const sourceOffset = index * 4;
      const alpha = outputSourceRgba[sourceOffset + 3] / 255;
      image.data[sourceOffset] = Math.round(outputSourceRgba[sourceOffset] * alpha + 255 * (1 - alpha));
      image.data[sourceOffset + 1] = Math.round(outputSourceRgba[sourceOffset + 1] * alpha + 255 * (1 - alpha));
      image.data[sourceOffset + 2] = Math.round(outputSourceRgba[sourceOffset + 2] * alpha + 255 * (1 - alpha));
      image.data[sourceOffset + 3] = 255;
    }
    context.putImageData(image, 0, 0);
    const dataUrl = canvas.toDataURL("image/png");
    return {
      width:relief.width,
      height:relief.height,
      data:dataUrl.slice(dataUrl.indexOf(",") + 1),
      fileName:`layered-relief-surface-${String(layerIndex + 1).padStart(2, "0")}.png`,
    };
  });
}

async function exportLayeredRelief() {
  if (!outputDepth) return;
  reliefExportButton.disabled = true;
  try {
    if (!selectedReliefCutSetting()) {
      throw new Error("Choose a saved Processing Palette and Cut setting before downloading the Layered Relief project.");
    }
    if (String(selectedReliefCutSetting().type).toLowerCase() !== "cut") {
      throw new Error("The selected Cut setting must use LightBurn Line mode. Configure the cutting setting in LightBurn, import the Processing Palette again, and retry.");
    }
    if (reliefSurfaceEngravingControl.checked && !selectedReliefPhotoSetting()) {
      throw new Error("Choose a Photo setting before downloading the Layered Relief project with surface engraving.");
    }
    if (reliefSurfaceEngravingControl.checked && String(selectedReliefPhotoSetting().type).toLowerCase() !== "image") {
      throw new Error("The selected Photo setting must use LightBurn Image mode. Configure its grayscale or dither mode in LightBurn, import the palette again, and retry.");
    }
    const layerCount = reliefOptions().layers;
    if (outputWidth * outputHeight * layerCount > 40000000) {
      throw new Error(`This ${outputWidth.toLocaleString()} × ${outputHeight.toLocaleString()} depthmap with ${layerCount} layers is too large to vectorize safely in the browser. Reduce Final Canvas Size or the number of physical layers.`);
    }
    setProcessingStatus("Building layered relief masks and closed SVG contours locally.");
    await new Promise(resolve => setTimeout(resolve, 0));
    const relief = createReliefLayers(outputDepth, outputWidth, outputHeight, reliefOptions());
    const exportOptions = reliefExportOptions();
    if (exportOptions.surfaceEngraving) exportOptions.photoImages = createReliefSurfaceImages(relief);
    const project = createReliefLightBurn(relief, exportOptions);
    const blob = new Blob([project], {type:"application/xml"});
    downloadBlob(blob, "layered-relief", "lbrn2");
    setProcessingStatus(`Layered Relief LightBurn project created locally with ${relief.layers.length} aligned cutting layers${exportOptions.surfaceEngraving ? " and matching visible-surface Photo layers" : ""}.`);
  } finally {
    reliefExportButton.disabled = false;
  }
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
  sourceLuminance = outputSourceLuminance = null;
  sourceRgba = outputSourceRgba = null;
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
  reliefLayerCanvas.width = 0;
  reliefLayerCanvas.height = 0;
  reliefCompositeCanvas.width = 0;
  reliefCompositeCanvas.height = 0;
  reliefHistogramCanvas.getContext("2d").clearRect(0, 0, reliefHistogramCanvas.width, reliefHistogramCanvas.height);
  reliefThresholdOverrides = null;
  displayedReliefThresholds = [];
  reliefThresholdSliders.replaceChildren();
  reliefThresholdStatus.textContent = "Generate a depthmap to inspect automatic layer boundaries.";
  reliefResetThresholdsButton.disabled = true;
  reliefSummary.textContent = "Generate a depthmap to inspect layered relief slices.";
  processingPanel.hidden = true;
  workspace.hidden = true;
  resetButton.disabled = true;
  generateButton.disabled = true;
  setUploadStatus("Waiting for an image.");
  setProcessingStatus("Depth processing has not started.");
}

function updateInputMode() {
  const direct = inputModeControl.value === "depthmap";
  generateButton.textContent = direct ? "Use Existing Depthmap" : "Initialize Depthmap";
  inputModeHelp.textContent = direct
    ? "Uses grayscale values directly without AI inference. Pure-white or transparent pixels are always background; Far-depth background cutoff can include additional far-depth pixels. Set it to 0% to use only the explicit background."
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
  reliefThresholdOverrides = null;
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
  reliefThresholdOverrides = null;
  renderAdjustedDepth();
});
guidanceFeatherControl.addEventListener("input", () => {
  guidanceFeatherValue.value = `${guidanceFeatherControl.value} px`;
  reliefThresholdOverrides = null;
  if (rawDepth) renderAdjustedDepth();
});
savedDepthPaletteSelect.addEventListener("change", selectDepthPalette);
outputWidthControl.addEventListener("change", () => {
  syncOutputAspect("width");
  reliefThresholdOverrides = null;
  renderAdjustedDepth();
});
outputHeightControl.addEventListener("change", () => {
  syncOutputAspect("height");
  reliefThresholdOverrides = null;
  renderAdjustedDepth();
});
borderPaddingControl.addEventListener("change", () => {
  reliefThresholdOverrides = null;
  renderAdjustedDepth();
});
perimeterDepthControl.addEventListener("input", () => {
  perimeterDepthOverride = Number(perimeterDepthControl.value) / 100;
  reliefThresholdOverrides = null;
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
parallaxAppearanceControl.addEventListener("input", updateParallaxControls);
for (const control of [reliefLayerCountControl, reliefSpacingControl, reliefSmoothingControl, reliefGroupingStrengthControl, reliefMinimumBandControl, reliefEmphasisControl, reliefExcludeBackgroundControl]) control.addEventListener("input", updateReliefQuantizationControls);
for (const control of [reliefConstructionControl, reliefPixelSizeControl, reliefMaterialThicknessControl, reliefMinimumIslandControl, reliefWorkbedWidthControl, reliefWorkbedHeightControl, reliefRegistrationControl, reliefRegistrationDiameterControl, reliefRegistrationInsetControl]) control.addEventListener("input", updateReliefControls);
reliefResetThresholdsButton.addEventListener("click", resetReliefThresholds);
reliefPreviewLayerControl.addEventListener("input", scheduleReliefPreview);
reliefPaletteControl.addEventListener("change", populateReliefSettings);
reliefSettingControl.addEventListener("change", updateReliefSettingStatus);
reliefSurfaceEngravingControl.addEventListener("change", () => {
  updateReliefPhotoControls();
  updateReliefQuantizationControls();
});
reliefPhotoSettingControl.addEventListener("change", updateReliefPhotoControls);
reliefExportButton.addEventListener("click", () => exportLayeredRelief().catch(cause => setProcessingStatus(cause.message, true)));
drawLegend();
updateParallaxControls();
updateReliefControls();
updateInputMode();
updateBrushDepthPreview();
updateBrushSizePreview();
createSwatchControls();
loadReliefCutSettings();
loadSavedDepthPalettes().catch(cause => setProcessingStatus(cause.message, true));
