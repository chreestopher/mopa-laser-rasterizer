// Explicitly select API fields before any snapshot crosses into a webpage.
const cutKeys = 'index name kind layer_index enabled priority in_use shape_count profile global_passes negative pass_through enable_cleanup sort_within_layer mode';
const paramKeys = 'speed min_power max_power min_power_2 max_power_2 default_speed default_power1 default_power2 laser1_enabled laser2_enabled alt_source num_passes z_offset z_per_pass u_offset angle_per_pass kerf frequency override_frequency q_pulse_width fiber_pulse_width bi_directional cross_hatch flood_fill auto_rotate scan_opt angle interval dot_width use_dot_correction ramp_length ramp_outer perforate perf_len perf_skip tabs_enabled overscan overscan_percent dpi dither_mode cells_per_inch halftone_angle link_dpi_to_interval';
const galvoKeys = 'override_timings laser_on_tc laser_off_tc end_tc polygon_tc jump_speed min_jump_delay max_jump_delay jump_dist_limit start_delay end_delay wobble_enable wobble_step wobble_size';
const gantryKeys = 'run_blower auto_blower blower_speed_override blower_speed_percent cut_through_start cut_through_end through_power through_power_2 start_delay end_delay lead_in lead_out lead_angle lead_length lead_style enable_ppi ppi dot_mode dot_time dot_spacing force_constant_power dcc_value overcut';
function pick(source, keys) {
  const result = {};
  for (const key of keys.split(' ')) {
    const value = source?.[key];
    if (typeof value === 'boolean' || typeof value === 'number' && Number.isFinite(value) ||
        typeof value === 'string' && value.length <= 4096) result[key] = value;
  }
  return result;
}
function parameters(source) {
  if (!source || typeof source !== 'object' || Array.isArray(source)) throw new Error('Invalid cut parameters');
  const result = pick(source, paramKeys);
  if (source.galvo) result.galvo = pick(source.galvo, galvoKeys);
  if (source.gantry) result.gantry = pick(source.gantry, gantryKeys);
  return result;
}
function cut(source) {
  if (!source || !['normal', 'image'].includes(source.kind)) throw new Error('Unsupported library cut');
  const result = {...pick(source, cutKeys), params: parameters(source.params)};
  if (source.tabs) result.tabs = pick(source.tabs, 'enabled manual size use_spacing count count_max limit_max spacing skip_inner cut_power');
  if (source.sub_layers !== undefined) {
    if (!Array.isArray(source.sub_layers) || source.sub_layers.length > 100) throw new Error('Invalid sublayers');
    result.sub_layers = source.sub_layers.map(layer => ({...pick(layer, 'index name enabled mode'), params: parameters(layer.params)}));
  }
  return result;
}
export function sanitizeSnapshot(source) {
  if (!source || source.library?.product !== 'lightburn' || !Array.isArray(source.library.entries) ||
      source.library.entries.length > 10000 || !['mm/s', 'mm/min', 'in/s', 'in/min'].includes(source.units?.units) ||
      !['mm', 'in'].includes(source.units?.distance_units) || !source.project || !source.status) throw new Error('Unsupported LightBurn response');
  const project = pick(source.project, 'modified shape_count');
  // Re-sanitizing the already sanitized snapshot is intentional at the bridge boundary.
  project.name = String(source.project.name ?? source.project.filename ?? '').split(/[\\/]/).pop().slice(0, 4096);
  project.device = pick(source.project.device, 'name supports_z');
  if (source.project.device?.laser) project.device.laser = pick(source.project.device.laser,
    'controller galvo flying_galvo uv sources sources_enabled mopa_source laser1_fiber laser2_fiber');
  return {
    status: pick(source.status, 'connected device_name'), project,
    units: pick(source.units, 'units distance_units'),
    library: {product: 'lightburn', ...pick(source.library, 'name'), entries: source.library.entries.map(entry => ({
      ...pick(entry, 'guid material description no_thick_title thickness locked'), cut: cut(entry.cut),
    }))},
  };
}
