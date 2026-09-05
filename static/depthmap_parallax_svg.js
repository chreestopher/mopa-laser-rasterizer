// Browser implementation of the grating-cell geometry published in Ben
// Krasnow's MIT-licensed MOPA_Laser_Diffraction_Gratings repository:
// https://github.com/benkrasnow/MOPA_Laser_Diffraction_Gratings/blob/main/grayscale_to_svg/angle_and_pitch_to_svg.py

const EPSILON = 1e-9;

function positiveNumber(value, label) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) throw new Error(`${label} must be greater than zero.`);
  return number;
}

function coordinate(value) {
  const rounded = Math.abs(value) < 5e-7 ? 0 : value;
  return rounded.toFixed(6).replace(/\.?0+$/, "");
}

function addUniquePoint(points, x, y) {
  if (points.some(point => Math.abs(point[0] - x) < 1e-7 && Math.abs(point[1] - y) < 1e-7)) return;
  points.push([x, y]);
}

export function grayscaleToGratingAngle(pixelValue) {
  const gray = Math.min(255, Math.max(0, Number(pixelValue) || 0));
  return gray / 255 * 180 - 90;
}

/** Return clipped parallel-line segments for one square cell at the origin. */
export function gratingCellSegments(pixelValue, patchSize = 0.4, lineSpacing = 0.06) {
  const size = positiveNumber(patchSize, "Patch size");
  const spacing = positiveNumber(lineSpacing, "Line spacing");
  const angle = grayscaleToGratingAngle(pixelValue) * Math.PI / 180;
  const cosine = Math.cos(angle);
  const sine = Math.sin(angle);
  const half = size / 2;
  const maximumOffset = Math.SQRT2 * half;
  const segments = [];

  for (let offset = -maximumOffset; offset <= maximumOffset + EPSILON; offset += spacing) {
    const points = [];
    if (Math.abs(sine) > 1e-6) {
      const leftY = (offset + half * cosine) / sine;
      if (leftY >= -half - EPSILON && leftY <= half + EPSILON) addUniquePoint(points, -half, leftY);
      const rightY = (offset - half * cosine) / sine;
      if (rightY >= -half - EPSILON && rightY <= half + EPSILON) addUniquePoint(points, half, rightY);
    }
    if (Math.abs(cosine) > 1e-6) {
      const topX = (offset + half * sine) / cosine;
      if (topX >= -half - EPSILON && topX <= half + EPSILON) addUniquePoint(points, topX, -half);
      const bottomX = (offset - half * sine) / cosine;
      if (bottomX >= -half - EPSILON && bottomX <= half + EPSILON) addUniquePoint(points, bottomX, half);
    }
    if (points.length === 2) {
      segments.push([
        points[0][0] + half,
        points[0][1] + half,
        points[1][0] + half,
        points[1][1] + half,
      ]);
    }
  }
  return segments;
}

/**
 * Convert a Krasnow-style parallax angle map into black grating geometry.
 * Pixel value 255 remains unengraved, matching depth_map_to_parallax's
 * documented sentinel instead of creating a background cell.
 */
export async function createKrasnowParallaxSvg(
  pixels,
  width,
  height,
  {
    patchSize = 0.4,
    lineSpacing = 0.06,
    strokeWidth = 0.01,
    onProgress = null,
    yieldEveryRows = 8,
  } = {},
) {
  if (!pixels || pixels.length !== width * height) {
    throw new Error("Parallax SVG conversion requires a complete angle map.");
  }
  if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1) {
    throw new Error("Parallax SVG conversion requires valid image dimensions.");
  }
  const size = positiveNumber(patchSize, "Patch size");
  const spacing = positiveNumber(lineSpacing, "Line spacing");
  const stroke = positiveNumber(strokeWidth, "Stroke width");
  const svgWidth = width * size;
  const svgHeight = height * size;
  const parts = [
    '<?xml version="1.0" encoding="UTF-8"?>\n',
    `<svg xmlns="http://www.w3.org/2000/svg" width="${coordinate(svgWidth)}mm" height="${coordinate(svgHeight)}mm" viewBox="0 0 ${coordinate(svgWidth)} ${coordinate(svgHeight)}">\n`,
    "<title>Depthmap Lab parallax diffraction grating</title>\n",
    "<desc>Horizontal parallax angle map converted to square cells of clipped parallel grating lines.</desc>\n",
    `<g fill="none" stroke="#000000" stroke-width="${coordinate(stroke)}" stroke-linecap="butt">\n`,
  ];
  const segmentCache = new Map();

  for (let y = 0; y < height; y += 1) {
    const commands = [];
    for (let x = 0; x < width; x += 1) {
      const pixel = Math.min(255, Math.max(0, Math.round(Number(pixels[y * width + x]) || 0)));
      if (pixel === 255) continue;
      let segments = segmentCache.get(pixel);
      if (!segments) {
        segments = gratingCellSegments(pixel, size, spacing);
        segmentCache.set(pixel, segments);
      }
      const originX = x * size;
      const originY = y * size;
      for (const [x1, y1, x2, y2] of segments) {
        commands.push(
          `M${coordinate(originX + x1)} ${coordinate(originY + y1)}`,
          `L${coordinate(originX + x2)} ${coordinate(originY + y2)}`,
        );
      }
    }
    if (commands.length) parts.push(`<path d="${commands.join(" ")}"/>\n`);
    if (onProgress) onProgress(y + 1, height);
    if (yieldEveryRows > 0 && (y + 1) % yieldEveryRows === 0) {
      await new Promise(resolve => setTimeout(resolve, 0));
    }
  }

  parts.push("</g>\n</svg>\n");
  return new Blob(parts, {type:"image/svg+xml;charset=utf-8"});
}
