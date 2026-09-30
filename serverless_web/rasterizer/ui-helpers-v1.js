export function createStatusPresenter(statusElement) {
  return message => { statusElement.textContent = message; };
}

export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, character => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[character]);
}

export function swatchChip(entry, intent = 'color_palette') {
  const color = entry.display_hex || entry.hex || '#303842';
  const rawAngle = Number(entry.angle ?? entry.settings?.angle ?? 0);
  const rawInterval = Number(entry.interval ?? entry.settings?.interval ?? .05);
  const angle = (Number.isFinite(rawAngle) ? rawAngle : 0) + 90;
  const spacing = Math.max(3, Math.min(14, (Number.isFinite(rawInterval) && rawInterval > 0 ? rawInterval : .05) * 120));
  const pattern = intent === 'hatch_palette'
    ? `;background-image:repeating-linear-gradient(${angle}deg,rgba(0,0,0,.88) 0 1px,rgba(255,255,255,.2) 1px 2px,transparent 2px ${spacing}px)`
    : '';
  const name = escapeHtml(entry.description || entry.name);
  return `<span class="swatch-chip" style="background-color:${color}${pattern}"></span><span class="swatch-name" title="${name}">${name}</span>`;
}

export function userFacingStyleError(message) {
  const raw = String(message || '');
  const value = raw.replace(/^ValueError:\s*/, '');
  return /^(?:Image style|Geometry style|Abstract filter) settings are not valid JSON$|^Invalid (?:abstract filter|geometry style) parameters:/.test(value)
    ? "We couldn't read these style settings. Reload Rasterizer, choose the style again, and resubmit. If it keeps happening, report the problem."
    : raw;
}

export async function createJobThumbnail(file, loadPreviewBitmap) {
  if (!file) return null;
  let bitmap;
  try {
    bitmap = await loadPreviewBitmap(file);
    const sourceWidth = bitmap.width || bitmap.naturalWidth;
    const sourceHeight = bitmap.height || bitmap.naturalHeight;
    if (!sourceWidth || !sourceHeight) return null;
    const maximum = 256;
    const scale = Math.min(1, maximum / sourceWidth, maximum / sourceHeight);
    const width = Math.max(1, Math.round(sourceWidth * scale));
    const height = Math.max(1, Math.round(sourceHeight * scale));
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext('2d');
    context.imageSmoothingEnabled = true;
    context.imageSmoothingQuality = 'high';
    context.clearRect(0, 0, width, height);
    context.drawImage(bitmap, 0, 0, width, height);
    let blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/webp', .8));
    if (!blob || blob.type !== 'image/webp') blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
    if (!blob) return null;
    const extension = blob.type === 'image/webp' ? 'webp' : 'png';
    return new File([blob], `input-thumbnail.${extension}`, {type: blob.type, lastModified: Date.now()});
  } catch (error) {
    console.warn('Job History thumbnail could not be generated:', error);
    return null;
  } finally {
    bitmap?.close?.();
  }
}
