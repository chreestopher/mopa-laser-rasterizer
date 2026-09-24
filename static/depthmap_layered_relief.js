function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

function quantile(sortedValues, fraction) {
  if (!sortedValues.length) return 0;
  const position = clamp(fraction, 0, 1) * (sortedValues.length - 1);
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  const blend = position - lower;
  return sortedValues[lower] * (1 - blend) + sortedValues[upper] * blend;
}

function median(values) {
  values.sort((left, right) => left - right);
  return values[Math.floor(values.length / 2)];
}

export function prepareReliefDepth(depth, width, height, backgroundMask, inverted = false, smoothing = 0) {
  const proximity = new Float32Array(depth.length);
  for (let index = 0; index < depth.length; index += 1) {
    const encoded = clamp(Number(depth[index]) || 0, 0, 1);
    proximity[index] = inverted ? 1 - encoded : encoded;
  }
  const passes = clamp(Math.round(Number(smoothing) || 0), 0, 4);
  let current = proximity;
  for (let pass = 0; pass < passes; pass += 1) {
    const next = Float32Array.from(current);
    for (let y = 0; y < height; y += 1) for (let x = 0; x < width; x += 1) {
      const index = y * width + x;
      if (backgroundMask?.[index]) continue;
      const center = current[index];
      const neighbors = [];
      for (let offsetY = -1; offsetY <= 1; offsetY += 1) for (let offsetX = -1; offsetX <= 1; offsetX += 1) {
        const neighborX = x + offsetX;
        const neighborY = y + offsetY;
        if (neighborX < 0 || neighborY < 0 || neighborX >= width || neighborY >= height) continue;
        const neighborIndex = neighborY * width + neighborX;
        if (backgroundMask?.[neighborIndex]) continue;
        const value = current[neighborIndex];
        if (Math.abs(value - center) <= 0.08) neighbors.push(value);
      }
      if (neighbors.length) next[index] = median(neighbors);
    }
    current = next;
  }
  return current;
}

function histogramFor(values, backgroundMask, emphasis = 0) {
  const counts = new Float64Array(256);
  const weightedCounts = new Float64Array(256);
  const bias = clamp(Number(emphasis) || 0, -1, 1);
  for (let index = 0; index < values.length; index += 1) {
    if (backgroundMask?.[index]) continue;
    const value = clamp(Number(values[index]) || 0, 0, 1);
    const bin = Math.round(value * 255);
    counts[bin] += 1;
    weightedCounts[bin] += Math.exp(bias * (value * 2 - 1) * 2);
  }
  return {counts, weightedCounts};
}

function prefix(values, transform = value => value) {
  const result = new Float64Array(values.length + 1);
  for (let index = 0; index < values.length; index += 1) result[index + 1] = result[index] + transform(values[index], index);
  return result;
}

function naturalBreakThresholds(values, backgroundMask, count, options = {}) {
  const {counts, weightedCounts} = histogramFor(values, backgroundMask, options.emphasis);
  const occupied = [];
  for (let bin = 0; bin < counts.length; bin += 1) if (counts[bin]) occupied.push(bin);
  if (!occupied.length) return Array.from({length:count}, (_, index) => index / count);
  const wanted = Math.min(count, occupied.length);
  const first = occupied[0];
  const last = occupied.at(-1);
  const rawPrefix = prefix(counts);
  const weightPrefix = prefix(weightedCounts);
  const weightedXPrefix = prefix(weightedCounts, (weight, bin) => weight * bin);
  const weightedX2Prefix = prefix(weightedCounts, (weight, bin) => weight * bin * bin);
  const totalPixels = rawPrefix[last + 1] - rawPrefix[first];
  const requestedMinimum = clamp(Number(options.minimumBandShare) || 0, 0, 40) / 100;

  const rangeSum = (valuesPrefix, start, end) => valuesPrefix[end + 1] - valuesPrefix[start];
  const cost = (start, end) => {
    const weight = rangeSum(weightPrefix, start, end);
    if (!weight) return Infinity;
    const weightedX = rangeSum(weightedXPrefix, start, end);
    return Math.max(0, rangeSum(weightedX2Prefix, start, end) - weightedX * weightedX / weight);
  };

  const solve = (groups, minimumPixels) => {
    const dp = Array.from({length:groups + 1}, () => new Float64Array(256).fill(Infinity));
    const split = Array.from({length:groups + 1}, () => new Int16Array(256).fill(-1));
    for (let end = first; end <= last; end += 1) {
      if (rangeSum(rawPrefix, first, end) >= minimumPixels) dp[1][end] = cost(first, end);
    }
    for (let group = 2; group <= groups; group += 1) {
      for (let end = first; end <= last; end += 1) {
        for (let start = first + 1; start <= end; start += 1) {
          if (!Number.isFinite(dp[group - 1][start - 1])) continue;
          if (rangeSum(rawPrefix, start, end) < minimumPixels) continue;
          const candidate = dp[group - 1][start - 1] + cost(start, end);
          if (candidate < dp[group][end]) {
            dp[group][end] = candidate;
            split[group][end] = start;
          }
        }
      }
    }
    if (!Number.isFinite(dp[groups][last])) return null;
    const starts = new Array(groups);
    starts[0] = first;
    let end = last;
    for (let group = groups; group >= 2; group -= 1) {
      starts[group - 1] = split[group][end];
      end = starts[group - 1] - 1;
    }
    return starts.map(bin => bin / 255);
  };

  for (let groups = wanted; groups >= 2; groups -= 1) {
    const minimumPixels = Math.max(1, Math.ceil(totalPixels * Math.min(requestedMinimum, 0.9 / groups)));
    const natural = solve(groups, minimumPixels);
    if (!natural) continue;
    const minimum = first / 255;
    const maximum = last / 255;
    const requestedStrength = Number(options.groupingStrength);
    const strength = clamp(Number.isFinite(requestedStrength) ? requestedStrength : 1, 0, 1);
    const blended = natural.map((value, index) => {
      if (!index) return minimum;
      const linear = minimum + (maximum - minimum) * index / groups;
      return linear * (1 - strength) + value * strength;
    });
    for (let index = 1; index < blended.length; index += 1) {
      blended[index] = Math.max(blended[index], blended[index - 1] + 1 / 65535);
    }
    return blended;
  }
  return [first / 255, (last + first) / 510];
}

export function reliefThresholds(depth, backgroundMask, layerCount, inverted = false, spacing = "linear", options = {}) {
  const count = clamp(Math.round(Number(layerCount) || 7), 2, 30);
  const values = [];
  for (let index = 0; index < depth.length; index += 1) {
    if (backgroundMask?.[index]) continue;
    const encoded = clamp(Number(depth[index]) || 0, 0, 1);
    values.push(inverted ? 1 - encoded : encoded);
  }
  if (!values.length) return Array.from({length:count}, (_, index) => index / count);
  values.sort((left, right) => left - right);
  if (spacing === "natural") {
    const proximity = Float32Array.from(depth, value => {
      const encoded = clamp(Number(value) || 0, 0, 1);
      return inverted ? 1 - encoded : encoded;
    });
    return naturalBreakThresholds(proximity, backgroundMask, count, options);
  }
  if (spacing === "equal-area") {
    return Array.from({length:count}, (_, index) => quantile(values, index / count));
  }
  const minimum = values[0];
  const maximum = values.at(-1);
  const span = Math.max(Number.EPSILON, maximum - minimum);
  return Array.from({length:count}, (_, index) => minimum + span * index / count);
}

function removeSmallComponents(mask, width, height, minimumArea) {
  const minimum = Math.max(0, Math.round(Number(minimumArea) || 0));
  if (minimum <= 1) return mask;
  const visited = new Uint8Array(mask.length);
  const queue = new Int32Array(mask.length);
  for (let start = 0; start < mask.length; start += 1) {
    if (!mask[start] || visited[start]) continue;
    let head = 0;
    let tail = 1;
    queue[0] = start;
    visited[start] = 1;
    while (head < tail) {
      const index = queue[head++];
      const x = index % width;
      const y = Math.floor(index / width);
      const neighbors = [];
      if (x > 0) neighbors.push(index - 1);
      if (x + 1 < width) neighbors.push(index + 1);
      if (y > 0) neighbors.push(index - width);
      if (y + 1 < height) neighbors.push(index + width);
      for (const neighbor of neighbors) {
        if (!mask[neighbor] || visited[neighbor]) continue;
        visited[neighbor] = 1;
        queue[tail++] = neighbor;
      }
    }
    if (tail < minimum) for (let position = 0; position < tail; position += 1) mask[queue[position]] = 0;
  }
  return mask;
}

export function createReliefLayers(depth, width, height, options = {}) {
  if (!(depth?.length === width * height) || width < 1 || height < 1) {
    throw new Error("Layered Relief requires a complete depthmap and valid dimensions.");
  }
  const requestedLayerCount = clamp(Math.round(Number(options.layers) || 7), 2, 30);
  const inverted = Boolean(options.inverted);
  const construction = options.construction === "separated" ? "separated" : "stacked";
  const proximityDepth = prepareReliefDepth(depth, width, height, options.backgroundMask, inverted, options.smoothing);
  let thresholds = Array.isArray(options.thresholds) && options.thresholds.length >= 2
    ? options.thresholds.map(value => clamp(Number(value) || 0, 0, 1)).sort((left, right) => left - right)
    : reliefThresholds(proximityDepth, options.backgroundMask, requestedLayerCount, false, options.spacing, {
      groupingStrength:options.groupingStrength,
      minimumBandShare:options.minimumBandShare,
      emphasis:options.emphasis,
    });
  if (Array.isArray(options.thresholds) && options.thresholds.length >= 2) {
    let minimum = Infinity;
    for (let index = 0; index < proximityDepth.length; index += 1) {
      if (options.backgroundMask?.[index]) continue;
      minimum = Math.min(minimum, proximityDepth[index]);
    }
    if (Number.isFinite(minimum)) thresholds[0] = minimum;
  }
  thresholds = thresholds.filter((value, index) => index === 0 || value > thresholds[index - 1]);
  if (thresholds.length < 2) {
    const minimum = thresholds[0] ?? 0;
    thresholds = [minimum, Math.min(1, minimum + 1 / 65535)];
  }
  const layerCount = thresholds.length;
  const layers = [];
  for (let layerIndex = 0; layerIndex < layerCount; layerIndex += 1) {
    const lower = thresholds[layerIndex];
    const upper = layerIndex + 1 < layerCount ? thresholds[layerIndex + 1] : Infinity;
    const mask = new Uint8Array(depth.length);
    for (let index = 0; index < depth.length; index += 1) {
      if (options.backgroundMask?.[index]) continue;
      const proximity = proximityDepth[index];
      mask[index] = construction === "stacked"
        ? Number(proximity + 1e-7 >= lower)
        : Number(proximity + 1e-7 >= lower && proximity < upper);
    }
    removeSmallComponents(mask, width, height, options.minimumIslandArea);
    layers.push({index:layerIndex, threshold:lower, upperThreshold:upper, mask});
  }
  return {width, height, thresholds, construction, layers, requestedLayerCount, proximityDepth};
}

function pointKey(x, y) {
  return `${x},${y}`;
}

function direction(edge) {
  const dx = edge.x2 - edge.x1;
  const dy = edge.y2 - edge.y1;
  if (dx > 0) return 0;
  if (dy > 0) return 1;
  if (dx < 0) return 2;
  return 3;
}

function chooseNextEdge(edges, candidates, incomingDirection) {
  const preference = [1, 0, 3, 2]; // right, straight, left, back: keeps touching diagonals separate
  for (const turn of preference) {
    const wanted = (incomingDirection + turn) % 4;
    const candidate = candidates.find(index => !edges[index].used && direction(edges[index]) === wanted);
    if (candidate !== undefined) return candidate;
  }
  return candidates.find(index => !edges[index].used);
}

function simplifyOrthogonalContour(points) {
  if (points.length < 5) return points;
  const open = points.slice(0, -1);
  const simplified = [];
  for (let index = 0; index < open.length; index += 1) {
    const previous = open[(index - 1 + open.length) % open.length];
    const current = open[index];
    const next = open[(index + 1) % open.length];
    const collinear = (previous[0] === current[0] && current[0] === next[0]) || (previous[1] === current[1] && current[1] === next[1]);
    if (!collinear) simplified.push(current);
  }
  simplified.push([...simplified[0]]);
  return simplified;
}

export function traceMaskContours(mask, width, height) {
  if (!(mask?.length === width * height)) throw new Error("Contour tracing requires a complete layer mask.");
  const edges = [];
  const add = (x1, y1, x2, y2) => edges.push({x1, y1, x2, y2, used:false});
  const filled = (x, y) => x >= 0 && y >= 0 && x < width && y < height && Boolean(mask[y * width + x]);
  for (let y = 0; y < height; y += 1) for (let x = 0; x < width; x += 1) {
    if (!filled(x, y)) continue;
    if (!filled(x, y - 1)) add(x, y, x + 1, y);
    if (!filled(x + 1, y)) add(x + 1, y, x + 1, y + 1);
    if (!filled(x, y + 1)) add(x + 1, y + 1, x, y + 1);
    if (!filled(x - 1, y)) add(x, y + 1, x, y);
  }
  const starts = new Map();
  edges.forEach((edge, index) => {
    const key = pointKey(edge.x1, edge.y1);
    if (!starts.has(key)) starts.set(key, []);
    starts.get(key).push(index);
  });
  const contours = [];
  for (let startIndex = 0; startIndex < edges.length; startIndex += 1) {
    if (edges[startIndex].used) continue;
    const start = edges[startIndex];
    const points = [[start.x1, start.y1]];
    let currentIndex = startIndex;
    let guard = 0;
    while (currentIndex !== undefined && guard++ <= edges.length + 1) {
      const edge = edges[currentIndex];
      edge.used = true;
      points.push([edge.x2, edge.y2]);
      if (edge.x2 === start.x1 && edge.y2 === start.y1) break;
      currentIndex = chooseNextEdge(edges, starts.get(pointKey(edge.x2, edge.y2)) || [], direction(edge));
    }
    if (points.length >= 4 && points.at(-1)[0] === points[0][0] && points.at(-1)[1] === points[0][1]) contours.push(simplifyOrthogonalContour(points));
  }
  return contours;
}

function formatNumber(value) {
  return Number(value.toFixed(4)).toString();
}

function xmlEscape(value) {
  return String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}

function reliefGeometry(layer, width, height, options, cutIndex, firstShapeId) {
  const pixelSize = clamp(Number(options.pixelSizeMm) || 0.1, 0.001, 100);
  const artworkWidth = width * pixelSize;
  const artworkHeight = height * pixelSize;
  const workbedWidth = Math.max(artworkWidth, Number(options.workbedWidthMm) || artworkWidth);
  const workbedHeight = Math.max(artworkHeight, Number(options.workbedHeightMm) || artworkHeight);
  const offsetX = (workbedWidth - artworkWidth) / 2;
  const offsetY = (workbedHeight - artworkHeight) / 2;
  const contours = traceMaskContours(layer.mask, width, height);
  let shapeId = firstShapeId;
  const shapes = contours.map(points => {
    const vertices = points.slice(0, -1).map(([x, y]) => `V${formatNumber(offsetX + x * pixelSize)} ${formatNumber(offsetY + y * pixelSize)}`).join("\n        ");
    return `    <Shape Type="Path" ShapeID="${shapeId++}" CutIndex="${cutIndex}">\n      <XForm>1 0 0 1 0 0</XForm>\n      <VertList>\n        ${vertices}\n      </VertList>\n      <PrimList>LineClosed</PrimList>\n    </Shape>`;
  });
  if (options.registrationHoles) {
    const diameter = clamp(Number(options.registrationDiameterMm) || 3, 0.1, Math.min(artworkWidth, artworkHeight));
    const radius = diameter / 2;
    const inset = clamp(Number(options.registrationInsetMm) || 5, radius, Math.max(radius, Math.min(artworkWidth, artworkHeight) / 2));
    const positions = [[inset, inset], [artworkWidth - inset, inset], [artworkWidth - inset, artworkHeight - inset], [inset, artworkHeight - inset]];
    for (const [x, y] of positions) {
      shapes.push(`    <Shape Type="Ellipse" ShapeID="${shapeId++}" CutIndex="${cutIndex}" Rx="${formatNumber(radius)}" Ry="${formatNumber(radius)}">\n      <XForm>1 0 0 1 ${formatNumber(offsetX + x)} ${formatNumber(offsetY + y)}</XForm>\n    </Shape>`);
    }
  }
  return {shapes, nextShapeId:shapeId};
}

export function createReliefLightBurn(relief, options = {}) {
  const pixelSize = Number(options.pixelSizeMm) || 0.1;
  const artworkWidth = relief.width * pixelSize;
  const artworkHeight = relief.height * pixelSize;
  const workbedWidth = Math.max(artworkWidth, Number(options.workbedWidthMm) || artworkWidth);
  const workbedHeight = Math.max(artworkHeight, Number(options.workbedHeightMm) || artworkHeight);
  const thickness = Math.max(0, Number(options.materialThicknessMm) || 0);
  const count = relief.layers.length;
  const digits = Math.max(2, String(count).length);
  const cutSettings = [];
  const shapes = [];
  let shapeId = 1;
  for (const layer of relief.layers) {
    const number = layer.index + 1;
    const position = number === 1 ? "BACK" : number === count ? "FRONT" : "MIDDLE";
    const name = `Layer ${String(number).padStart(digits, "0")} of ${String(count).padStart(digits, "0")} - ${position}`;
    cutSettings.push(`  <CutSetting type="Cut">\n    <index Value="${layer.index}"/>\n    <name Value="${xmlEscape(name)}"/>\n    <minPower Value="0"/>\n    <maxPower Value="0"/>\n    <speed Value="100"/>\n    <frequency Value="20"/>\n    <numPasses Value="1"/>\n    <priority Value="${layer.index}"/>\n    <hide Value="${layer.index === 0 ? 0 : 1}"/>\n  </CutSetting>`);
    const geometry = reliefGeometry(layer, relief.width, relief.height, options, layer.index, shapeId);
    shapes.push(...geometry.shapes);
    shapeId = geometry.nextShapeId;
  }
  const notes = xmlEscape([
    "MOPA LASER RASTERIZER - LAYERED RELIEF",
    `Assembly order: Layer 01 is the rear; Layer ${String(count).padStart(digits, "0")} is closest to the viewer.`,
    `Construction: ${relief.construction === "stacked" ? "cumulative stacked relief" : "separated depth bands / shadow box"}.`,
    `Material: ${count} sheets at ${thickness.toFixed(3)} mm; nominal assembled depth ${(thickness * count).toFixed(3)} mm.`,
    `Artwork: ${artworkWidth.toFixed(3)} x ${artworkHeight.toFixed(3)} mm on a ${workbedWidth.toFixed(3)} x ${workbedHeight.toFixed(3)} mm workbed.`,
    "All layers intentionally overlap at identical workspace coordinates.",
    "CUT ONE SHEET AT A TIME: enable Output for exactly one layer and disable every other layer before starting.",
    "WARNING: Every layer uses a zero-power placeholder. Assign tested cutting settings before running the laser.",
    "Inspect every contour. Small or disconnected islands may require manual placement or a supporting frame.",
  ].join("\n")).replaceAll("\n", "&#10;");
  // These paths use Rasterizer's established ShapeID-based LightBurn schema.
  // Declaring a newer LightBurn writer version makes current LightBurn expect
  // VertID/PrimID path records and silently discard otherwise valid geometry.
  return `<?xml version="1.0" encoding="UTF-8"?>\n<LightBurnProject AppVersion="1.2.01" FormatVersion="1" MaterialHeight="0" MirrorX="False" MirrorY="True">\n  <Notes ShowOnLoad="1" Notes="${notes}"/>\n${cutSettings.join("\n")}\n${shapes.join("\n")}\n</LightBurnProject>\n`;
}
