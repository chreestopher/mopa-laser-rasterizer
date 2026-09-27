function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

function xmlEscape(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatNumber(value) {
  return Number(Number(value).toFixed(6)).toString();
}

function positiveInteger(value, fallback = 1) {
  const number = Number(value);
  const fallbackNumber = Number(fallback);
  return Math.max(1, Math.round(Number.isFinite(number) ? number : (Number.isFinite(fallbackNumber) ? fallbackNumber : 1)));
}

function finiteNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function safeElementName(name) {
  return /^[A-Za-z_][A-Za-z0-9_.-]*$/.test(String(name || ""));
}

function settingValuesXml(settings, indent, excluded = new Set()) {
  return Object.entries(settings || {})
    .filter(([key, value]) => safeElementName(key)
      && !excluded.has(key.toLowerCase())
      && value !== null && value !== undefined
      && typeof value !== "object")
    .map(([key, value]) => `${indent}<${key} Value="${xmlEscape(value)}"/>`);
}

function isCleanupSubLayer(layer) {
  const settings = layer?.settings || {};
  return String(settings.isCleanup || "") === "1"
    || String(settings.subname || "").trim().toLowerCase() === "cleanup";
}

export function hasEmbeddedCleanup(setting) {
  return Boolean((setting?.subLayers || setting?.sub_layers || []).some(isCleanupSubLayer));
}

function embeddedCleanupLayer(setting) {
  return (setting?.subLayers || setting?.sub_layers || []).find(isCleanupSubLayer) || null;
}

function subLayerXml(layer, options = {}) {
  const settings = {...(layer?.settings || {})};
  if (options.forceCleanup) {
    settings.isCleanup = "1";
    settings.subname = "Cleanup";
  }
  if ((options.forceCleanup || isCleanupSubLayer(layer)) && options.cleanupPasses !== undefined) {
    settings.numPasses = String(positiveInteger(options.cleanupPasses, settings.numPasses));
  }
  const excluded = new Set(["index", "name", "priority", "hide", "dooutput", "linkpath", "dithermode", "cleanuppass"]);
  const values = settingValuesXml(settings, "      ", excluded);
  const type = safeElementName(layer?.type) ? layer.type : "Scan";
  return `    <SubLayer type="${xmlEscape(type)}">\n${values.join("\n")}\n    </SubLayer>`;
}

function primarySettingXml(setting, mode, cleanupSetting, options = {}) {
  if (!setting?.settings || String(setting.type || "").toLowerCase() !== "image") {
    throw new Error("The selected 3D-Slice role must use LightBurn Image mode.");
  }
  const primarySettings = {...setting.settings};
  primarySettings.numPasses = String(positiveInteger(options.depthPasses, primarySettings.numPasses));
  primarySettings.angle = formatNumber(finiteNumber(options.angle, finiteNumber(primarySettings.angle, 0)));
  primarySettings.anglePerPass = formatNumber(finiteNumber(options.anglePerPass, finiteNumber(primarySettings.anglePerPass, 0)));
  const sourceDpi = finiteNumber(primarySettings.dpi, 0);
  const sourceInterval = finiteNumber(primarySettings.interval, sourceDpi > 0 ? 25.4 / sourceDpi : .1);
  const interval = clamp(finiteNumber(options.interval, sourceInterval), .0001, 100);
  primarySettings.interval = formatNumber(interval);
  primarySettings.dpi = formatNumber(finiteNumber(options.dpi, 25.4 / interval));
  const excluded = new Set(["index", "name", "priority", "hide", "dooutput", "linkpath", "dithermode", "cleanuppass"]);
  const values = settingValuesXml(primarySettings, "    ", excluded);
  const importedSubLayers = setting.subLayers || setting.sub_layers || [];
  const importedCleanup = importedSubLayers.some(isCleanupSubLayer);
  const subLayers = mode === "3dslice"
    ? (importedCleanup
      ? importedSubLayers
      : cleanupSetting
        ? [{type:String(cleanupSetting.type || "Scan").toLowerCase() === "image" ? "Scan" : cleanupSetting.type, settings:cleanupSetting.settings || {}}]
        : [])
    : importedSubLayers.filter(layer => !isCleanupSubLayer(layer));
  const cleanAfter = positiveInteger(options.cleanAfter, setting.settings.cleanupPass);
  const cleanupPasses = options.cleanupPasses;
  const cleanupXml = mode === "3dslice" && importedCleanup
    ? `    <cleanupPass Value="${cleanAfter}"/>\n`
    : mode === "3dslice" && !importedCleanup && cleanupSetting
      ? `    <cleanupPass Value="${cleanAfter}"/>\n`
      : "";
  const renderedSubLayers = subLayers.map(layer => subLayerXml(layer, {
    forceCleanup:mode === "3dslice" && !importedCleanup && Boolean(cleanupSetting),
    cleanupPasses,
  }));
  return `  <CutSetting_Img type="Image">\n    <index Value="0"/>\n    <name Value="Depthmap"/>\n${values.length ? `${values.join("\n")}\n` : ""}    <ditherMode Value="${mode}"/>\n${cleanupXml}${renderedSubLayers.length ? `${renderedSubLayers.join("\n")}\n` : ""}    <doOutput Value="1"/>\n    <priority Value="0"/>\n    <hide Value="0"/>\n  </CutSetting_Img>`;
}

export function createDepthmapLightBurn(image, options = {}) {
  if (!image?.data || !Number(image.width) || !Number(image.height)) {
    throw new Error("Create or import a depthmap before exporting a LightBurn project.");
  }
  const mode = options.mode === "3dslice" ? "3dslice" : "grayscale";
  const pixelSize = clamp(Number(options.pixelSizeMm) || 0.1, 0.001, 100);
  const artworkWidth = Number(image.width) * pixelSize;
  const artworkHeight = Number(image.height) * pixelSize;
  const workbedWidth = Math.max(artworkWidth, Number(options.workbedWidthMm) || artworkWidth);
  const workbedHeight = Math.max(artworkHeight, Number(options.workbedHeightMm) || artworkHeight);
  const centerX = workbedWidth / 2;
  const centerY = workbedHeight / 2;
  const settingXml = primarySettingXml(
    options.slicingSetting,
    mode,
    options.cleanupSetting,
    options,
  );
  const fileName = image.fileName || "depthmap.png";
  const shape = `  <Shape Type="Bitmap" ShapeID="1" CutIndex="0" W="${formatNumber(image.width)}" H="${formatNumber(image.height)}" Gamma="1" Contrast="0" Brightness="0" EnhanceAmount="0" EnhanceRadius="0" EnhanceDenoise="0" File="${xmlEscape(fileName)}" SourceHash="0" Data="${xmlEscape(image.data)}">\n    <XForm>${formatNumber(pixelSize)} 0 0 ${formatNumber(pixelSize)} ${formatNumber(centerX)} ${formatNumber(centerY)}</XForm>\n  </Shape>`;
  const cleanupDescription = mode === "3dslice"
    ? hasEmbeddedCleanup(options.slicingSetting)
      ? `The imported cleanup sub-layer's laser settings were preserved. Cleanup runs after every ${positiveInteger(options.cleanAfter, options.slicingSetting?.settings?.cleanupPass)} depth pass(es), with ${positiveInteger(options.cleanupPasses, embeddedCleanupLayer(options.slicingSetting)?.settings?.numPasses)} cleanup pass(es) per cycle.`
      : options.cleanupSetting
        ? `Cleanup runs after every ${positiveInteger(options.cleanAfter, 1)} depth pass(es), with ${positiveInteger(options.cleanupPasses, options.cleanupSetting?.settings?.numPasses)} cleanup pass(es) per cycle.`
        : "No automatic cleanup sub-layer is configured."
    : "Automatic cleanup is omitted because this project uses Grayscale image mode.";
  const sourceSettings = options.slicingSetting?.settings || {};
  const depthPasses = positiveInteger(options.depthPasses, sourceSettings.numPasses);
  const sourceDpi = finiteNumber(sourceSettings.dpi, 0);
  const sourceInterval = finiteNumber(sourceSettings.interval, sourceDpi > 0 ? 25.4 / sourceDpi : .1);
  const interval = clamp(finiteNumber(options.interval, sourceInterval), .0001, 100);
  const angle = finiteNumber(options.angle, finiteNumber(sourceSettings.angle, 0));
  const anglePerPass = finiteNumber(options.anglePerPass, finiteNumber(sourceSettings.anglePerPass, 0));
  const notes = xmlEscape([
    "MOPA LASER RASTERIZER - DEPTHMAP IMAGE EXPORT",
    `Image mode: ${mode === "3dslice" ? "3D Sliced" : "Grayscale"}.`,
    `Depth passes: ${depthPasses}; line interval: ${formatNumber(interval)} mm; starting angle: ${formatNumber(angle)} degrees; angle change per pass: ${formatNumber(anglePerPass)} degrees.`,
    `Artwork: ${artworkWidth.toFixed(3)} x ${artworkHeight.toFixed(3)} mm on a ${workbedWidth.toFixed(3)} x ${workbedHeight.toFixed(3)} mm workbed.`,
    cleanupDescription,
    "Inspect all laser and image settings in LightBurn before running the laser.",
  ].join("\n")).replaceAll("\n", "&#10;");
  return `<?xml version="1.0" encoding="UTF-8"?>\n<LightBurnProject AppVersion="2.1.04" FormatVersion="1" MaterialHeight="0" MirrorX="False" MirrorY="True" AskForSendName="True">\n${settingXml}\n${shape}\n  <Notes ShowOnLoad="1" Notes="${notes}"/>\n</LightBurnProject>\n`;
}
