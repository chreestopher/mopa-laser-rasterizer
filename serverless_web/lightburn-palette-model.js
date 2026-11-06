const fields = {
  speed: ['speed', 'speed'], min_power: ['minPower'], max_power: ['maxPower'], min_power_2: ['minPower2'], max_power_2: ['maxPower2'],
  frequency: ['frequency'], override_frequency: ['overrideFrequency'], q_pulse_width: ['QPulseWidth'],
  num_passes: ['numPasses'], interval: ['interval', 'distance'], angle: ['angle'], angle_per_pass: ['anglePerPass'],
  bi_directional: ['bidir'], cross_hatch: ['crossHatch'], flood_fill: ['floodFill'], auto_rotate: ['autoRotate'],
  overscan: ['overscan'], overscan_percent: ['overscanPercent'], z_offset: ['zOffset', 'distance'], z_per_pass: ['zPerPass', 'distance'],
};
const galvoFields = {laser_on_tc: 'LaserOn_TC', laser_off_tc: 'LaserOff_TC', polygon_tc: 'Polygon_TC',
  end_tc: 'End_TC', jump_speed: 'JumpSpeed', min_jump_delay: 'MinJumpDelay', max_jump_delay: 'MaxJumpDelay'};
const xml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&apos;'}[c]));
const valueXml = (key, value) => `<${key} Value="${xml(value)}"/>`;
function label(value) {const result = String(value || '').trim(); if (!result || result.length > 160 || /[\x00-\x1f\x7f]/.test(result)) throw new Error('Use a name of 1–160 characters without control characters.'); return result;}

export function buildPaletteImport(snapshot, selected, paletteName) {
  const name = label(paletteName), units = snapshot?.units;
  const speeds = {'mm/s': 1, 'mm/min': 1 / 60, 'in/s': 25.4, 'in/min': 25.4 / 60};
  if (!Object.hasOwn(speeds, units?.units) || !['mm', 'in'].includes(units?.distance_units)) throw new Error('Unsupported LightBurn units. Read the library again.');
  if (!Array.isArray(selected) || !selected.length || selected.length > 100 || new Set(selected).size !== selected.length) throw new Error('Select between 1 and 100 distinct settings.');
  const warnings = [], descriptions = new Set();
  function convert(layer, context, kind = 'normal') {
    const type = kind === 'image' ? 'Image' : {cut: 'Cut', scan: 'Scan', offset: 'Offset'}[layer.mode];
    if (!type) throw new Error(`${context}: unsupported operation type.`);
    const settings = {};
    if (typeof layer.enabled === 'boolean') settings.doOutput = Number(layer.enabled);
    for (const [key, value] of Object.entries(layer.params || {})) {
      if (key === 'scan_opt' && ['individual', 'by_group', 'merge_all'].includes(value)) {settings.scanOpt = {individual: 'individual', by_group: 'byGroup', merge_all: ''}[value]; continue;}
      if (key === 'galvo' && value && typeof value === 'object') {
        for (const [field, setting] of Object.entries(value)) {
          if (Object.hasOwn(galvoFields, field) && typeof setting === 'number' && Number.isFinite(setting)) settings[galvoFields[field]] = field === 'jump_speed' ? setting * speeds[units.units] : setting;
          else warnings.push(`${context}: galvo.${field} is retained in the source snapshot only.`);
        }
        continue;
      }
      if (!Object.hasOwn(fields, key)) {warnings.push(`${context}: ${key} is retained in the source snapshot only.`); continue;}
      if (typeof value !== 'boolean' && (typeof value !== 'number' || !Number.isFinite(value))) throw new Error(`${context}: invalid ${key}.`);
      const [target, dimension] = fields[key];
      settings[target] = typeof value === 'boolean' ? Number(value) : Number((value * (dimension === 'speed' ? speeds[units.units] : dimension === 'distance' && units.distance_units === 'in' ? 25.4 : 1)).toPrecision(14));
    }
    for (const key of ['global_passes', 'negative', 'pass_through', 'enable_cleanup', 'sort_within_layer', 'tabs']) if (layer[key] !== undefined) warnings.push(`${context}: ${key} is retained in the source snapshot only.`);
    return {type, settings, subLayers: (layer.sub_layers || []).map((sub, index) => convert(sub, `${context}, sublayer ${index + 1}`))};
  }
  const entries = selected.map(index => {
    if (!Number.isInteger(index) || !snapshot.library?.entries?.[index]) throw new Error('A selected setting is no longer available.');
    const source = snapshot.library.entries[index];
    if (!['normal', 'image'].includes(source.cut?.kind)) throw new Error('Unsupported LightBurn setting kind.');
    const base = label(source.description || source.material || `Setting ${index + 1}`);
    let description = base, suffix = 2;
    while (descriptions.has(description.toLowerCase())) description = `${base.slice(0, 145)} (${suffix++})`;
    descriptions.add(description.toLowerCase());
    if (description !== base) warnings.push(`${base}: renamed to ${description} to avoid a duplicate.`);
    return {description, material: source.material || '', ...convert(source.cut, description, source.cut.kind), source};
  });
  const cutXml = (entry, tag = 'CutSetting') => `<${tag} type="${entry.type}">${Object.entries(entry.settings).map(([key, value]) => valueXml(key, value)).join('')}${entry.subLayers.map(sub => cutXml(sub, 'SubLayer')).join('')}</${tag}>`;
  const contents = entries.map(entry => {
    const provenance = {library: snapshot.library.name || '', units, entry: entry.source};
    return `<Entry Desc="${xml(entry.description)}" Thickness="-1.0000" RasterizerLightBurnSource="${xml(JSON.stringify(provenance))}">${cutXml(entry)}</Entry>`;
  }).join('');
  return {name, materialName: name, entries, warnings, conversions: `Speed: ${units.units} → mm/s. Distance: ${units.distance_units} → mm. Frequency stays Hz; pulse width stays ns.`,
    xml: `<?xml version="1.0" encoding="utf-8"?><LightBurnLibrary><Material name="${xml(name)}">${contents}</Material></LightBurnLibrary>`};
}


export function defaultSwatchAssignments(entries, palette) {
  const claimed = new Set();
  return entries.map(entry => {
    const match = palette.find(swatch => swatch.name.trim().toLowerCase() === entry.description.trim().toLowerCase());
    const hex = match?.hex.toUpperCase() || '';
    if (!hex || claimed.has(hex)) return '';
    claimed.add(hex); return hex;
  });
}

export function paletteSwatchMapping(entries, assignments, palette) {
  const allowed = new Set(palette.map(swatch => swatch.hex.toUpperCase())), mapping = {};
  entries.forEach((entry, index) => {
    const hex = assignments[index] || '';
    if (!hex) return;
    if (!allowed.has(hex)) throw new Error('Choose an official swatch.');
    if (Object.hasOwn(mapping, hex)) throw new Error('This swatch is already assigned to another setting.');
    mapping[hex] = entry.description;
  });
  return mapping;
}
