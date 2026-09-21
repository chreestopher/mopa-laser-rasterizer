// Original browser implementation of circular specular-scratch geometry. The
// optical approach is described in Matthew Brand's "Specular holography"
// research and was explored for STL models by Aaron Se's HoloZens project.
// No HoloZens source code is included here.
const DEFAULT_MAX_ARCS = 30000;

function positiveNumber(value, label) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) throw new Error(`${label} must be greater than zero.`);
  return number;
}

function nonNegativeNumber(value, label) {
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) throw new Error(`${label} cannot be negative.`);
  return number;
}

function coordinate(value) {
  const rounded = Math.abs(value) < 5e-7 ? 0 : value;
  return rounded.toFixed(6).replace(/\.?0+$/, "");
}

function semanticProximity(encodedDepth, inverted) {
  const depth = Math.min(1, Math.max(0, Number(encodedDepth) || 0));
  return inverted ? 1 - depth : depth;
}

function candidateAnglesForBoundary(candidates, baseAngle, startAngle, endAngle) {
  for (let turn = -2; turn <= 2; turn += 1) {
    const angle = baseAngle + turn * Math.PI * 2;
    if (angle > startAngle + 1e-10 && angle < endAngle - 1e-10) candidates.push(angle);
  }
}

function clipCircularArc(arc, minX, minY, maxX, maxY) {
  const candidates = [arc.startAngle, arc.endAngle];
  for (const boundaryX of [minX, maxX]) {
    const ratio = (boundaryX - arc.centerX) / arc.radius;
    if (ratio >= -1 && ratio <= 1) {
      const angle = Math.acos(Math.min(1, Math.max(-1, ratio)));
      candidateAnglesForBoundary(candidates, angle, arc.startAngle, arc.endAngle);
      candidateAnglesForBoundary(candidates, -angle, arc.startAngle, arc.endAngle);
    }
  }
  for (const boundaryY of [minY, maxY]) {
    const ratio = (boundaryY - arc.centerY) / arc.radius;
    if (ratio >= -1 && ratio <= 1) {
      const angle = Math.asin(Math.min(1, Math.max(-1, ratio)));
      candidateAnglesForBoundary(candidates, angle, arc.startAngle, arc.endAngle);
      candidateAnglesForBoundary(candidates, Math.PI - angle, arc.startAngle, arc.endAngle);
    }
  }
  candidates.sort((left, right) => left - right);

  const segments = [];
  for (let index = 0; index < candidates.length - 1; index += 1) {
    const startAngle = candidates[index];
    const endAngle = candidates[index + 1];
    if (endAngle - startAngle < 1e-10) continue;
    const middle = (startAngle + endAngle) / 2;
    const middleX = arc.centerX + arc.radius * Math.cos(middle);
    const middleY = arc.centerY + arc.radius * Math.sin(middle);
    if (middleX < minX - 1e-8 || middleX > maxX + 1e-8 || middleY < minY - 1e-8 || middleY > maxY + 1e-8) continue;
    const startX = arc.centerX + arc.radius * Math.cos(startAngle);
    const startY = arc.centerY + arc.radius * Math.sin(startAngle);
    const endX = arc.centerX + arc.radius * Math.cos(endAngle);
    const endY = arc.centerY + arc.radius * Math.sin(endAngle);
    segments.push({
      ...arc,
      startAngle,
      endAngle,
      startX:Math.min(maxX, Math.max(minX, startX)),
      startY:Math.min(maxY, Math.max(minY, startY)),
      endX:Math.min(maxX, Math.max(minX, endX)),
      endY:Math.min(maxY, Math.max(minY, endY)),
    });
  }
  return segments;
}

/**
 * Convert a relative depthmap into circular specular-scratch arcs.
 *
 * The virtual object is placed behind the material surface. Nearer samples use
 * smaller-radius arcs; farther samples use larger-radius arcs. The center of
 * every circle is displaced below its zero-angle highlight point by its radius.
 */
export function createScratchHologramArcs(
  depth,
  width,
  height,
  {
    backgroundMask = null,
    inverted = false,
    pixelSize = 0.1,
    sampleStep = 4,
    nearDepth = 1,
    depthRange = 10,
    viewSweep = 60,
    backgroundCutoff = 0.01,
    maxArcs = DEFAULT_MAX_ARCS,
    minimumCellInset = 0,
  } = {},
) {
  if (!depth || depth.length !== width * height) {
    throw new Error("Scratch hologram conversion requires a complete depthmap.");
  }
  if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1) {
    throw new Error("Scratch hologram conversion requires valid image dimensions.");
  }
  if (backgroundMask && backgroundMask.length !== depth.length) {
    throw new Error("Scratch hologram conversion received an incomplete background mask.");
  }

  const pitch = positiveNumber(pixelSize, "Depthmap pixel size");
  let step = Math.max(1, Math.round(positiveNumber(sampleStep, "Sample step")));
  const nearestDepth = positiveNumber(nearDepth, "Near-point virtual depth");
  const range = nonNegativeNumber(depthRange, "Virtual depth range");
  const sweep = positiveNumber(viewSweep, "Viewing sweep");
  if (sweep > 180) throw new Error("Viewing sweep cannot exceed 180 degrees.");
  const cutoff = Number(backgroundCutoff);
  if (!Number.isFinite(cutoff) || cutoff < 0 || cutoff >= 1) {
    throw new Error("Background cutoff must be between 0 and 100 percent.");
  }
  const arcLimit = Math.max(1, Math.floor(positiveNumber(maxArcs, "Maximum arc count")));
  const requestedInset = nonNegativeNumber(minimumCellInset, "Minimum cell inset");

  while (Math.ceil(width / step) * Math.ceil(height / step) > arcLimit) step += 1;

  const arcs = [];
  const halfSweepRadians = sweep * Math.PI / 360;
  const startAngle = -Math.PI / 2 - halfSweepRadians;
  const endAngle = -Math.PI / 2 + halfSweepRadians;
  const physicalWidth = width * pitch;
  const physicalHeight = height * pitch;

  for (let blockY = 0; blockY < height; blockY += step) {
    const endY = Math.min(height, blockY + step);
    for (let blockX = 0; blockX < width; blockX += step) {
      const endX = Math.min(width, blockX + step);
      let proximityTotal = 0;
      let included = 0;
      for (let y = blockY; y < endY; y += 1) {
        for (let x = blockX; x < endX; x += 1) {
          const index = y * width + x;
          const proximity = semanticProximity(depth[index], inverted);
          const background = backgroundMask ? Boolean(backgroundMask[index]) : proximity <= cutoff;
          if (background) continue;
          proximityTotal += proximity;
          included += 1;
        }
      }
      if (!included) continue;

      const proximity = proximityTotal / included;
      const virtualDepth = nearestDepth + (1 - proximity) * range;
      const radius = virtualDepth / 2;
      const highlightX = ((blockX + endX) / 2) * pitch;
      const highlightY = ((blockY + endY) / 2) * pitch;
      const cellMinX = blockX * pitch;
      const cellMinY = blockY * pitch;
      const cellMaxX = endX * pitch;
      const cellMaxY = endY * pitch;
      const cellWidth = cellMaxX - cellMinX;
      const cellHeight = cellMaxY - cellMinY;
      const inset = Math.max(requestedInset, Math.min(cellWidth, cellHeight) * 0.05);
      if (inset * 2 >= Math.min(cellWidth, cellHeight)) {
        throw new Error("Scratch stroke width is too large for the sampled cells. Reduce stroke width, increase Depthmap pixel size, or increase Sample Every.");
      }
      const centerX = highlightX;
      const centerY = highlightY + radius;
      const arc = {
        centerX,
        centerY,
        radius,
        startAngle,
        endAngle,
        startX:centerX + radius * Math.cos(startAngle),
        startY:centerY + radius * Math.sin(startAngle),
        endX:centerX + radius * Math.cos(endAngle),
        endY:centerY + radius * Math.sin(endAngle),
        proximity,
      };
      // Keep every scratch inside its own inset sampling cell. Adjacent cells
      // are disjoint, so their open paths cannot intersect one another.
      arcs.push(...clipCircularArc(
        arc,
        cellMinX + inset,
        cellMinY + inset,
        cellMaxX - inset,
        cellMaxY - inset,
      ));
    }
  }

  return {
    arcs,
    effectiveSampleStep:step,
    physicalWidth,
    physicalHeight,
    requestedSampleStep:Math.max(1, Math.round(Number(sampleStep))),
  };
}

export async function createScratchHologramSvg(
  depth,
  width,
  height,
  {
    strokeWidth = 0.01,
    onProgress = null,
    yieldEveryArcs = 2000,
    ...geometryOptions
  } = {},
) {
  const stroke = positiveNumber(strokeWidth, "Stroke width");
  const configuredInset = Number(geometryOptions.minimumCellInset);
  const geometry = createScratchHologramArcs(depth, width, height, {
    ...geometryOptions,
    minimumCellInset:Math.max(
      Number.isFinite(configuredInset) ? configuredInset : 0,
      stroke / 2 + 1e-6,
    ),
  });
  if (!geometry.arcs.length) {
    throw new Error("No scratch arcs were created. Lower the background cutoff or use a depthmap with visible foreground depth.");
  }

  const clipId = "scratch-hologram-output-boundary";
  const parts = [
    '<?xml version="1.0" encoding="UTF-8"?>\n',
    `<svg xmlns="http://www.w3.org/2000/svg" width="${coordinate(geometry.physicalWidth)}mm" height="${coordinate(geometry.physicalHeight)}mm" viewBox="0 0 ${coordinate(geometry.physicalWidth)} ${coordinate(geometry.physicalHeight)}">\n`,
    "<title>Depthmap Lab specular scratch hologram</title>\n",
    "<desc>Relative grayscale depth sampled into non-intersecting open circular arcs for experimental specular scratch engraving under directional light.</desc>\n",
    `<defs><clipPath id="${clipId}"><rect width="${coordinate(geometry.physicalWidth)}" height="${coordinate(geometry.physicalHeight)}"/></clipPath></defs>\n`,
    `<g fill="none" stroke="#000000" stroke-width="${coordinate(stroke)}" stroke-linecap="round" clip-path="url(#${clipId})">\n`,
  ];

  const chunkSize = 1000;
  for (let offset = 0; offset < geometry.arcs.length; offset += chunkSize) {
    const commands = [];
    const end = Math.min(geometry.arcs.length, offset + chunkSize);
    for (let index = offset; index < end; index += 1) {
      const arc = geometry.arcs[index];
      commands.push(
        `M${coordinate(arc.startX)} ${coordinate(arc.startY)}`,
        `A${coordinate(arc.radius)} ${coordinate(arc.radius)} 0 0 1 ${coordinate(arc.endX)} ${coordinate(arc.endY)}`,
      );
    }
    parts.push(`<path d="${commands.join(" ")}"/>\n`);
    if (onProgress) onProgress(end, geometry.arcs.length, geometry);
    if (yieldEveryArcs > 0 && end % yieldEveryArcs === 0) {
      await new Promise(resolve => setTimeout(resolve, 0));
    }
  }

  parts.push("</g>\n</svg>\n");
  return {
    blob:new Blob(parts, {type:"image/svg+xml;charset=utf-8"}),
    ...geometry,
  };
}
