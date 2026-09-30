let dependencies = {};

export function configureFormState(options) {
  dependencies = options || {};
}

export function hasOption(select, value) {
  return [...select.options].some(option => option.value === String(value ?? ''));
}

export function rasterizerFormValues() {
  return {
    material_choice: document.querySelector('#materialChoice').value,
    material_name: document.querySelector('#materialName').value,
    pixel_square_mm: document.querySelector('#pixel').value,
    new_width: document.querySelector('#width').value,
    new_height: document.querySelector('#height').value,
    white_is: document.querySelector('#whiteIs').value,
    image_preset: document.querySelector('#imagePreset').value,
    filter_parameters: dependencies.filterParameters(),
    geometry_style: dependencies.effectiveGeometryStyle(),
    geometry_style_parameters: dependencies.geometryStyleParameters(),
    panel_tiling: dependencies.panelTilingPreferenceValues(),
    ...dependencies.colorMatchingParameters(),
    cut_mode: document.querySelector('#rasterHoloCutMode').value,
    preserve_black_outlines: document.querySelector('#rasterHoloBlack').checked,
  };
}

export function restoreRasterizerForm(values, restoreMaterial = true) {
  if (!values) return;
  if (restoreMaterial && values.material_name !== undefined) {
    document.querySelector('#materialName').value = values.material_name;
  }
  for (const [id, key] of [['pixel', 'pixel_square_mm'], ['width', 'new_width'], ['height', 'new_height']]) {
    if (values[key] !== undefined) document.querySelector('#' + id).value = values[key];
  }
  if (hasOption(document.querySelector('#whiteIs'), values.white_is)) {
    document.querySelector('#whiteIs').value = values.white_is;
  }
  dependencies.restoreImageStyle(values);
  dependencies.restoreGeometryControls(values);
  dependencies.restoreColorMatching(values);
  if (hasOption(document.querySelector('#rasterHoloCutMode'), values.cut_mode)) {
    document.querySelector('#rasterHoloCutMode').value = values.cut_mode;
  }
  const preserveBlack = document.querySelector('#rasterHoloBlack');
  preserveBlack.checked = Boolean(values.preserve_black_outlines) && !preserveBlack.disabled;
  dependencies.restorePanelTiling(values);
}

export function holographicArtworkFormValues() {
  return {
    recipe_id: document.querySelector('#holoRecipe').value,
    material_library_id: document.querySelector('#holoMaterial').value,
    max_dimension: document.querySelector('#holoDimension').value,
    pixel_mm: document.querySelector('#holoPixel').value,
    cut_mode: document.querySelector('#holoCutMode').value,
    preserve_black_outlines: document.querySelector('#holoBlack').checked,
  };
}

export function restoreHolographicArtworkForm(values) {
  if (!values) return;
  for (const [id, key] of [['holoRecipe', 'recipe_id'], ['holoMaterial', 'material_library_id'], ['holoCutMode', 'cut_mode']]) {
    const select = document.querySelector('#' + id);
    if (hasOption(select, values[key])) select.value = values[key];
  }
  for (const [id, key] of [['holoDimension', 'max_dimension'], ['holoPixel', 'pixel_mm']]) {
    if (values[key] !== undefined) document.querySelector('#' + id).value = values[key];
  }
  document.querySelector('#holoBlack').checked = Boolean(values.preserve_black_outlines);
}
