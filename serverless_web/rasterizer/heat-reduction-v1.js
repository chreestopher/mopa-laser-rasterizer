export function heatReductionParameters() {
  const enabled = document.querySelector('#heatReductionEnabled').checked;
  if (!enabled) return {enabled: false};
  const projects = Number(document.querySelector('#heatReductionProjects').value);
  if (!Number.isInteger(projects) || projects < 2 || projects > 10) {
    throw new Error('Heat Reduction requires a whole number of projects from 2 to 10.');
  }
  return {enabled: true, projects};
}

export function syncHeatReduction() {
  const toggle = document.querySelector('#heatReductionEnabled');
  document.querySelector('#heatReductionDetails').hidden = !toggle.checked;
  document.querySelector('#heatReductionProjects').disabled = !toggle.checked;
  toggle.setAttribute('aria-expanded', String(toggle.checked));
}

export function restoreHeatReduction(values) {
  const settings = values?.heat_reduction;
  document.querySelector('#heatReductionEnabled').checked = settings?.enabled === true;
  document.querySelector('#heatReductionProjects').value = settings?.projects ?? 4;
  syncHeatReduction();
}

export function bindHeatReduction() {
  document.querySelector('#heatReductionEnabled').addEventListener('change', syncHeatReduction);
  syncHeatReduction();
}
