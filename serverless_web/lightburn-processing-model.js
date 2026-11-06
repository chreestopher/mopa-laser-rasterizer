import {buildPaletteImport} from './lightburn-palette-model.js';

export function buildProcessingImport(snapshot, choices, name, roles) {
  if (Object.keys(choices).some(role => !roles.includes(role))) throw new Error('Unknown processing role.');
  const selected = [...new Set(roles.map(role => choices[role]).filter(value => value !== '' && value !== undefined).map(value => {
    if (!/^\d+$/.test(String(value))) throw new Error('Select a valid LightBurn setting.');
    return Number(value);
  }))];
  const preview = buildPaletteImport(snapshot, selected, name);
  preview.roleDescriptions = Object.fromEntries(roles.map(role => {
    const value = choices[role];
    return [role, value === '' || value === undefined ? '' : preview.entries[selected.indexOf(Number(value))].description];
  }));
  return preview;
}

export function processingRoleMapping(preview, saved) {
  const mapping = {};
  for (const [role, description] of Object.entries(preview.roleDescriptions)) {
    if (!description) {mapping[role] = ''; continue;}
    const entry = saved.entries?.find(item => item.description === description && item.material === preview.materialName);
    if (!entry?.entry_ref) throw new Error('Could not identify a saved setting for its processing role.');
    mapping[role] = entry.entry_ref;
  }
  return {materials: {[preview.materialName]: mapping}};
}
