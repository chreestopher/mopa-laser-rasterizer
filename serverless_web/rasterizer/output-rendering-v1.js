function escapeHtml(value) {
  return String(value ?? '').replace(
    /[&<>"']/g,
    character => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    })[character],
  );
}

export function outputBasename(output) {
  return String(output?.name || 'download').replaceAll('\\', '/').split('/').pop() || 'download';
}

export function rasterOutputRank(output) {
  const name = outputBasename(output).toLowerCase();
  return name.endsWith('.svg') ? 0 : name.endsWith('.lbrn2') ? 1 : 2;
}

export function renderRasterOutputs(outputs) {
  const ordered = [...(outputs || [])].sort(
    (left, right) =>
      rasterOutputRank(left) - rasterOutputRank(right)
      || outputBasename(left).localeCompare(outputBasename(right)),
  );
  return `<div class="output-downloads">${ordered.map(output => {
    const label = `Download ${outputBasename(output)}`;
    return `<p class="output-download-item"><a class="staging-action-button output-download-button" href="${escapeHtml(output.download_url)}" title="${escapeHtml(label)}">${escapeHtml(label)}</a><span class="output-download-size">${(Number(output.bytes || 0) / 1048576).toFixed(1)} MB</span></p>`;
  }).join('')}</div>`;
}
