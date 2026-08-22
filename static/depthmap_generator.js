const MODEL_ID = "onnx-community/depth-anything-v2-small";
const TRANSFORMERS_URL = "https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.7.2";

const input = document.querySelector("#depth_input");
const dropZone = document.querySelector("#depth_drop_zone");
const generateButton = document.querySelector("#depth_generate");
const resetButton = document.querySelector("#depth_reset");
const progress = document.querySelector("#depth_progress");
const status = document.querySelector("#depth_status");
const error = document.querySelector("#depth_error");
const workspace = document.querySelector("#depth_workspace");
const sourceCanvas = document.querySelector("#depth_source_canvas");
const mapCanvas = document.querySelector("#depth_map_canvas");
const reliefCanvas = document.querySelector("#depth_relief_canvas");
const legendCanvas = document.querySelector("#depth_legend_canvas");
const nearControl = document.querySelector("#depth_near");
const farControl = document.querySelector("#depth_far");
const gammaControl = document.querySelector("#depth_gamma");
const invertControl = document.querySelector("#depth_invert");
const outputWidthControl = document.querySelector("#depth_output_width");
const outputHeightControl = document.querySelector("#depth_output_height");
const brushSizeControl = document.querySelector("#depth_brush_size");
const brushSizeValue = document.querySelector("#depth_brush_size_value");
const brushDepthControl = document.querySelector("#depth_brush_depth");
const brushDepthValue = document.querySelector("#depth_brush_depth_value");
const brushDepthPreview = document.querySelector("#depth_brush_preview");
const clearPaintButton = document.querySelector("#depth_clear_paint");
const colorGuidancePanel = document.querySelector("#color_guidance_panel");
const swatchGrid = document.querySelector("#depth_swatch_grid");
const guidanceFeatherControl = document.querySelector("#depth_guidance_feather");
const guidanceFeatherValue = document.querySelector("#depth_guidance_feather_value");
const guidanceStatus = document.querySelector("#depth_guidance_status");
const resetGuidanceButton = document.querySelector("#depth_reset_guidance");
const depthPalettePicker = document.querySelector("#depth_palette_picker");
const savedDepthPaletteSelect = document.querySelector("#saved_depth_palette");
const depthPalette = JSON.parse(document.querySelector("#depth_palette_data").textContent);
const paletteState = depthPalette.map(swatch => ({...swatch, rgb:hexToRgb(swatch.hex), enabled:true, depth:50, influence:0}));
let savedDepthPalettes = [];

let sourceFile = null;
let sourceUrl = null;
let estimator = null;
let rawDepth = null;
let depthWidth = 0;
let depthHeight = 0;
let adjustedDepth = null;
let guidedDepth = null;
let colorMatchMap = null;
let outputDepth = null;
let outputWidth = 0;
let outputHeight = 0;
let paintedDepth = null;
let paintingFarDepth = false;
let lastPaintPoint = null;

function setStatus(message, isError = false) {
  status.textContent = message;
  error.hidden = !isError;
  error.textContent = isError ? message : "";
}

function setBusy(busy) {
  generateButton.disabled = busy || !sourceFile;
  input.disabled = busy;
  progress.hidden = !busy;
  if (!busy) progress.value = 0;
}

async function acceptFile(file) {
  if (!file || !file.type.startsWith("image/")) {
    setStatus("Choose a supported image file.", true);
    return;
  }
  sourceFile = file;
  if (sourceUrl) URL.revokeObjectURL(sourceUrl);
  sourceUrl = URL.createObjectURL(file);
  const image = await loadImage(sourceUrl);
  drawContainedImage(sourceCanvas, image);
  generateButton.disabled = false;
  resetButton.disabled = false;
  workspace.hidden = false;
  colorGuidancePanel.hidden = false;
  setStatus(`${file.name} is ready. Depth processing has not started.`);
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
  setStatus("Loading the client-side depth model. The first download may take several minutes.");
  const { pipeline, env } = await import(TRANSFORMERS_URL);
  env.allowLocalModels = false;
  const progress_callback = event => {
    if (typeof event.progress === "number") progress.value = Math.round(event.progress);
    if (event.status === "progress" && event.file) status.textContent = `Downloading model: ${event.file}`;
  };
  const options = { progress_callback };
  if ("gpu" in navigator) options.device = "webgpu";
  try {
    estimator = await pipeline("depth-estimation", MODEL_ID, options);
  } catch (webGpuError) {
    if (options.device !== "webgpu") throw webGpuError;
    setStatus("WebGPU was unavailable. Loading the compatible browser CPU version.");
    delete options.device;
    estimator = await pipeline("depth-estimation", MODEL_ID, options);
  }
  return estimator;
}

async function generateDepth() {
  if (!sourceUrl) return;
  setBusy(true);
  try {
    const model = await loadEstimator();
    setStatus("Analyzing perspective and estimating relative depth...");
    progress.removeAttribute("value");
    const result = await model(sourceUrl);
    const tensor = result.predicted_depth;
    const dims = tensor.dims;
    depthHeight = dims[dims.length - 2];
    depthWidth = dims[dims.length - 1];
    rawDepth = Float32Array.from(tensor.data);
    createColorMatchMap();
    outputWidthControl.value = depthWidth;
    outputHeightControl.value = depthHeight;
    renderAdjustedDepth();
    setStatus(`Depth map generated at ${depthWidth} × ${depthHeight}. Adjust and export the result.`);
  } catch (cause) {
    console.error(cause);
    setStatus(`Depth generation failed: ${cause.message || cause}`, true);
  } finally {
    setBusy(false);
  }
}

function renderAdjustedDepth() {
  if (!rawDepth) return;
  let minimum = Infinity;
  let maximum = -Infinity;
  for (const value of rawDepth) {
    if (value < minimum) minimum = value;
    if (value > maximum) maximum = value;
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

function buildOutputCanvas() {
  outputWidth = requestedDimension(outputWidthControl, depthWidth);
  outputHeight = requestedDimension(outputHeightControl, depthHeight);
  outputWidthControl.value = outputWidth;
  outputHeightControl.value = outputHeight;
  const scale = Math.min(outputWidth / depthWidth, outputHeight / depthHeight);
  const contentWidth = Math.max(1, Math.round(depthWidth * scale));
  const contentHeight = Math.max(1, Math.round(depthHeight * scale));
  const offsetX = Math.floor((outputWidth - contentWidth) / 2);
  const offsetY = Math.floor((outputHeight - contentHeight) / 2);
  const farthest = invertControl.checked ? 1 : 0;
  const outputLength = outputWidth * outputHeight;
  if (!paintedDepth || paintedDepth.length !== outputLength) {
    paintedDepth = new Float32Array(outputLength);
    paintedDepth.fill(Number.NaN);
  }
  outputDepth = new Float32Array(outputLength);
  outputDepth.fill(farthest);
  for (let y = 0; y < contentHeight; y += 1) {
    const sourceY = Math.min(depthHeight - 1, Math.floor(y * depthHeight / contentHeight));
    for (let x = 0; x < contentWidth; x += 1) {
      const sourceX = Math.min(depthWidth - 1, Math.floor(x * depthWidth / contentWidth));
      outputDepth[(y + offsetY) * outputWidth + x + offsetX] = guidedDepth[sourceY * depthWidth + sourceX];
    }
  }
  for (let index = 0; index < outputLength; index += 1) {
    if (!Number.isNaN(paintedDepth[index])) {
      outputDepth[index] = invertControl.checked ? 1 - paintedDepth[index] : paintedDepth[index];
    }
  }
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
    }
  }
}

function clearPaintedDepth() {
  if (!paintedDepth) return;
  paintedDepth.fill(Number.NaN);
  renderAdjustedDepth();
  setStatus("Painted depth edits cleared.");
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

function downloadBlob(blob, suffix) {
  const name = (sourceFile?.name || "depthmap").replace(/\.[^.]+$/, "");
  const anchor = document.createElement("a");
  anchor.href = URL.createObjectURL(blob);
  anchor.download = `${name}-${suffix}.png`;
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
  rawDepth = adjustedDepth = guidedDepth = outputDepth = paintedDepth = colorMatchMap = null;
  if (sourceUrl) URL.revokeObjectURL(sourceUrl);
  sourceUrl = null;
  input.value = "";
  workspace.hidden = true;
  colorGuidancePanel.hidden = true;
  resetButton.disabled = true;
  generateButton.disabled = true;
  setStatus("Waiting for an image.");
}

function createSwatchControls() {
  for (const [index, swatch] of paletteState.entries()) {
    const card = document.createElement("article");
    card.className = "depth-swatch";
    card.innerHTML = `<div class="depth-swatch-title"><input class="swatch-enabled" type="checkbox" checked aria-label="Enable ${swatch.name} color guidance"><span class="depth-swatch-color" style="background:${swatch.hex}" title="Source color"></span><span class="swatch-depth-preview" title="Assigned depth"></span><span class="depth-swatch-name">${swatch.name}</span></div><label class="depth-setting-control">Artificial depth <output class="swatch-depth-output">50% closer</output></label><input class="swatch-depth depth-setting-control" type="range" min="0" max="100" step="0.1" value="50"><div class="guidance-scale depth-setting-control"><span>Farther</span><span>Closer</span></div><label class="depth-setting-control">Influence <output class="swatch-influence-output">0%</output></label><input class="swatch-influence depth-setting-control" type="range" min="0" max="100" step="1" value="0"><div class="guidance-scale depth-setting-control"><span>Perspective</span><span>Assigned depth</span></div>`;
    const enabled = card.querySelector(".swatch-enabled");
    const depth = card.querySelector(".swatch-depth");
    const influence = card.querySelector(".swatch-influence");
    const depthOutput = card.querySelector(".swatch-depth-output");
    const influenceOutput = card.querySelector(".swatch-influence-output");
    const preview = card.querySelector(".swatch-depth-preview");
    const update = (rerender = true) => {
      swatch.enabled = enabled.checked;
      swatch.depth = Number(depth.value);
      swatch.influence = Number(influence.value);
      const encoded = invertControl.checked ? 1 - swatch.depth / 100 : swatch.depth / 100;
      const gray = Math.round(encoded * 255);
      depthOutput.value = swatch.depth === 0 ? "Farther" : swatch.depth === 100 ? "Closer" : `${swatch.depth}% closer`;
      influenceOutput.value = `${swatch.influence}%`;
      preview.style.backgroundColor = `rgb(${gray},${gray},${gray})`;
      card.style.opacity = swatch.enabled ? "1" : ".5";
      if (rerender && rawDepth) renderAdjustedDepth();
    };
    for (const control of [enabled, depth, influence]) control.addEventListener("input", () => update(true));
    update(false);
    swatch.controls = {enabled, depth, influence};
    swatch.update = update;
    swatchGrid.appendChild(card);
  }
}

async function loadSavedDepthPalettes() {
  const auth = await (window.machineChrome?.authStatus || Promise.resolve({signed_in:false}));
  if (!auth.signed_in) return;
  const response = await fetch("/account/depth-palettes", {credentials:"same-origin"});
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || "Could not load saved Depth Palettes.");
  savedDepthPalettes = data.palettes || [];
  const manualOption = new Option("Manual unsaved settings", "");
  savedDepthPaletteSelect.replaceChildren(manualOption);
  for (const palette of savedDepthPalettes) {
    savedDepthPaletteSelect.add(new Option(palette.name || "Depth Palette", palette.palette_id));
  }
  depthPalettePicker.hidden = false;
}

function selectDepthPalette() {
  const palette = savedDepthPalettes.find(item => item.palette_id === savedDepthPaletteSelect.value);
  colorGuidancePanel.classList.toggle("using-saved-depth-palette", Boolean(palette));
  resetGuidanceButton.hidden = Boolean(palette);
  if (!palette) return;
  const entries = new Map((palette.entries || []).map(entry => [String(entry.hex).toUpperCase(), entry]));
  for (const swatch of paletteState) {
    const entry = entries.get(swatch.hex.toUpperCase());
    swatch.controls.enabled.checked = entry?.enabled !== false && Boolean(entry);
    swatch.controls.depth.value = entry?.depth ?? 50;
    swatch.controls.influence.value = entry?.influence ?? 0;
    swatch.update(false);
  }
  if (rawDepth) renderAdjustedDepth();
}

function resetColorGuidance() {
  for (const swatch of paletteState) {
    swatch.controls.enabled.checked = true;
    swatch.controls.depth.value = 50;
    swatch.controls.influence.value = 0;
    swatch.update(false);
  }
  guidanceFeatherControl.value = 2;
  guidanceFeatherValue.value = "2 px";
  if (rawDepth) renderAdjustedDepth();
}

input.addEventListener("change", () => acceptFile(input.files[0]).catch(cause => setStatus(cause.message, true)));
generateButton.addEventListener("click", generateDepth);
resetButton.addEventListener("click", reset);
for (const eventName of ["dragenter", "dragover"]) dropZone.addEventListener(eventName, event => { event.preventDefault(); dropZone.classList.add("is-dragging"); });
for (const eventName of ["dragleave", "drop"]) dropZone.addEventListener(eventName, event => { event.preventDefault(); dropZone.classList.remove("is-dragging"); });
dropZone.addEventListener("drop", event => acceptFile(event.dataTransfer.files[0]).catch(cause => setStatus(cause.message, true)));
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
resetGuidanceButton.addEventListener("click", resetColorGuidance);
savedDepthPaletteSelect.addEventListener("change", selectDepthPalette);
for (const control of [outputWidthControl, outputHeightControl]) control.addEventListener("change", renderAdjustedDepth);
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
document.querySelector("#depth_export_16").addEventListener("click", () => export16Bit().catch(cause => setStatus(cause.message, true)));
drawLegend();
updateBrushDepthPreview();
updateBrushSizePreview();
createSwatchControls();
loadSavedDepthPalettes().catch(cause => setStatus(cause.message, true));
