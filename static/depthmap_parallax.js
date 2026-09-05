// Browser implementation of the depth-edge conversion published in Ben
// Krasnow's MIT-licensed MOPA_Laser_Diffraction_Gratings repository:
// https://github.com/benkrasnow/MOPA_Laser_Diffraction_Gratings/blob/main/depth_map_to_parallax/convert.py

const clamp = (value, minimum, maximum) => Math.min(maximum, Math.max(minimum, value));

function writeGradient(output, start, end, startValue, endValue) {
  const count = end - start + 1;
  if (count <= 1) {
    output[start] = 127;
    return;
  }
  for (let offset = 0; offset < count; offset += 1) {
    const amount = offset / (count - 1);
    // NumPy's float-to-uint8 conversion truncates positive values.
    output[start + offset] = Math.trunc(startValue + (endValue - startValue) * amount);
  }
}

/**
 * Convert the Lab's normalized depth pixels into Krasnow's parallax-angle map.
 *
 * The source algorithm reserves 255 for areas that should not be processed,
 * uses 127 for the hologram plane, and writes horizontal angle ramps around
 * the boundaries of foreground regions. The Lab uses a configurable far-depth
 * cutoff to derive the otherwise absent 255 background mask.
 */
export function createKrasnowParallaxPixels(
  encodedDepth,
  width,
  height,
  {scaleFactor = 0.06, backgroundCutoff = 0.01, inverted = false, backgroundMask = null} = {},
) {
  if (!encodedDepth || encodedDepth.length !== width * height) {
    throw new Error("Parallax conversion requires a complete depth map.");
  }
  if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1) {
    throw new Error("Parallax conversion requires valid image dimensions.");
  }
  if (backgroundMask && backgroundMask.length !== encodedDepth.length) {
    throw new Error("Parallax conversion requires a complete background mask.");
  }

  const scale = clamp(Number(scaleFactor) || 0, 0, 4);
  const cutoff = clamp(Number(backgroundCutoff) || 0, 0, 1);
  const output = new Uint8ClampedArray(encodedDepth.length);
  output.fill(255);

  const inputValue = index => {
    const encoded = clamp(Number(encodedDepth[index]) || 0, 0, 1);
    const proximity = inverted ? 1 - encoded : encoded;
    const isBackground = backgroundMask ? Boolean(backgroundMask[index]) : proximity <= cutoff;
    return isBackground ? 255 : Math.min(254, Math.round(proximity * 254));
  };

  // Process each row independently. This follows the script's left-to-right
  // scan while preventing the end of one scanline from spilling into the next.
  for (let y = 0; y < height; y += 1) {
    const rowStart = y * width;
    const rowEnd = rowStart + width - 1;
    let previous = 255;
    let x = 0;
    while (x < width) {
      const index = rowStart + x;
      const current = inputValue(index);

      if (current === 255 && previous === 255) {
        output[index] = 255;
      } else if (current !== 255 && previous === 255) {
        const length = Math.trunc(Math.abs(current - 127) * scale);
        const start = Math.max(rowStart, index - length);
        writeGradient(output, start, index, current < 127 ? 255 : 0, 127);
      } else if (current === 255 && previous !== 255) {
        const length = Math.trunc(Math.abs(previous - 127) * scale);
        const end = Math.min(rowEnd, index + length);
        writeGradient(output, index, end, 127, previous < 127 ? 0 : 255);
        x += end - index;
      } else {
        output[index] = 127;
      }

      previous = current;
      x += 1;
    }
  }

  return output;
}
