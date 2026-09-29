let dependencies = null;
let preferenceTimer = null;

export const selectedPaletteHexes = new Set();
const paletteNameOverrides = new Map();

const element = selector => (dependencies?.documentRoot || document).querySelector(selector);
const resources = () => dependencies.getAccountResources();

export function configurePaletteResources(options) {
  dependencies = options;
  bindPaletteControls();
}

export function paletteDisplayName(entry) {
  const hex = String(entry.hex || entry.display_hex || '').toUpperCase();
  return paletteNameOverrides.get(hex) || entry.description || entry.name || hex;
}

export function paletteEntrySelectionKey(entry) {
  return String(entry.selection_key ?? entry.hex ?? '').toUpperCase();
}

export function selectedAsset() {
  const [kind, id] = String(element('#materialChoice').value || '').split(':', 2);
  return {kind, id};
}

export function svgOnlySelected() {
  return selectedAsset().kind === 'svg';
}

export function selectedMaterialLibrary() {
  const selection = selectedAsset();
  return selection.kind === 'library'
    ? (resources()?.material_libraries || []).find(item => item.library_id === selection.id)
    : null;
}

export function selectedRasterRecipe() {
  const selection = selectedAsset();
  const uploaded = dependencies.getUploadedHolographicProfile();
  if (selection.kind === 'holographic-upload' && uploaded) {
    const recipes = uploaded.recipes || [];
    return {
      name: String(uploaded.profile_name || 'Uploaded Fauxlographic Palette'),
      uploaded: true,
      metadata: {
        swatch_preview: recipes.map(item => ({
          name: item.name,
          hex: item.observed_hex,
          angle_degrees: item.angle_degrees,
          interval_mm: item.interval_mm,
        })),
        has_black_setting: Boolean(uploaded.black_setting),
      },
    };
  }
  return selection.kind === 'recipe'
    ? (resources()?.holographic_recipes || []).find(item => item.recipe_id === selection.id)
    : null;
}

export function recipeRasterEntries() {
  return (selectedRasterRecipe()?.metadata?.swatch_preview || []).map((item, index) => ({
    ...item,
    selection_key: String(index),
    recipe_index: index,
    display_hex: item.hex,
    description: item.name,
    angle: item.angle_degrees,
    interval: item.interval_mm,
  }));
}

export function explicitLibraryAssignments() {
  const selection = selectedAsset();
  const assignments = resources()?.preferences?.material_library_color_assignments || {};
  return selection.kind === 'library' && Object.prototype.hasOwnProperty.call(assignments, selection.id)
    ? assignments[selection.id] || {}
    : null;
}

export function visibleRasterPalette() {
  const recipe = selectedRasterRecipe();
  const library = selectedMaterialLibrary();
  const explicitAssignments = explicitLibraryAssignments();
  return recipe
    ? recipeRasterEntries()
    : library?.library_intent === 'hatch_palette'
      ? library.summary?.entries || []
      : (resources()?.palette || []).filter(item => explicitAssignments === null || Object.prototype.hasOwnProperty.call(explicitAssignments, String(item.hex).toUpperCase()));
}

function patternedColorCard(entry) {
  const hex = String(entry.hex || '#303842').toUpperCase();
  const key = paletteEntrySelectionKey(entry);
  const color = entry.display_hex || hex;
  const name = entry.description || entry.name || hex;
  const rawAngle = Number(entry.angle ?? entry.settings?.angle ?? 0);
  const rawInterval = Number(entry.interval ?? entry.settings?.interval ?? .05);
  const angle = (Number.isFinite(rawAngle) ? rawAngle : 0) + 90;
  const spacing = Math.max(3, Math.min(14, (Number.isFinite(rawInterval) && rawInterval > 0 ? rawInterval : .05) * 120));
  const selected = selectedPaletteHexes.has(key);
  return `<div class="color-card ${selected ? '' : 'off'}" data-key="${dependencies.esc(key)}"><span class="color-name" title="${dependencies.esc(name)}">${dependencies.esc(name)}</span><button class="color-square patterned" type="button" data-key="${dependencies.esc(key)}" aria-label="${selected ? 'Exclude' : 'Include'} ${dependencies.esc(name)}" aria-pressed="${selected}" style="--swatch-color:${dependencies.esc(color)};--swatch-angle:${angle}deg;--swatch-spacing:${spacing}px"></button><span class="color-hex">${dependencies.esc(hex)}</span></div>`;
}

function loadPaletteAssignments() {
  paletteNameOverrides.clear();
  const selection = selectedAsset();
  const preferences = resources()?.preferences || {};
  if (selection.kind === 'recipe') return;
  const mapping = selection.kind === 'library'
    ? (preferences.material_library_color_assignments || {})[selection.id]
    : preferences.color_name_overrides;
  for (const [hex, name] of Object.entries(mapping || {})) paletteNameOverrides.set(hex.toUpperCase(), name);
}

export function renderRasterPalette() {
  const selectedLibrary = selectedMaterialLibrary();
  const selectedRecipe = selectedRasterRecipe();
  const svgOnly = svgOnlySelected();
  const hatch = selectedLibrary?.library_intent === 'hatch_palette' || Boolean(selectedRecipe);
  const palette = selectedRecipe ? recipeRasterEntries() : hatch ? selectedLibrary.summary?.entries || [] : resources()?.palette || [];
  element('#paletteHelp').textContent = svgOnly
    ? 'SVG-Only creates color-separated vector geometry without a Material Library or embedded laser settings. Select the swatches the rasterizer may emit.'
    : hatch
      ? selectedRecipe
        ? `Showing ${selectedRecipe.name}. Submitting this palette launches the Fauxlographic Etching process: artwork colors match directly to measured fauxlographic swatch colors, and every enabled fauxlographic swatch receives its own LightBurn layer.`
        : `Showing ${selectedLibrary.name} hatch swatches. Line direction and spacing reflect each saved angle and interval; dimmed swatches are excluded.`
      : 'Select the colors the rasterizer may emit. Dimmed swatches are excluded.';
  element('#resetSwatches').classList.toggle('hidden', hatch);
  element('#imageStyleSection').classList.toggle('hidden', Boolean(selectedRecipe));
  const holographicSettings = element('#holographicRasterSettings');
  const preserveBlack = element('#rasterHoloBlack');
  const hasBlack = Boolean(selectedRecipe?.metadata?.has_black_setting);
  holographicSettings.classList.toggle('hidden', !selectedRecipe);
  preserveBlack.disabled = Boolean(selectedRecipe) && !hasBlack;
  if (!hasBlack) preserveBlack.checked = false;
  element('#rasterHoloBlackHelp').textContent = selectedRecipe && !hasBlack ? 'This palette has no stored Black setting.' : '';
  element('#submit').textContent = selectedRecipe ? 'Upload and build fauxlographic artwork' : svgOnly ? 'Upload and create SVG' : 'Upload and rasterize';
  const explicitAssignments = explicitLibraryAssignments();
  const availableHexes = explicitAssignments === null ? null : new Set(Object.keys(explicitAssignments).map(hex => hex.toUpperCase()));
  element('#rasterPalette').innerHTML = hatch
    ? palette.map(patternedColorCard).join('')
    : palette.map(item => {
      const hex = String(item.hex).toUpperCase();
      const available = availableHexes === null || availableHexes.has(hex);
      const name = paletteNameOverrides.get(hex) || item.name;
      return `<div class="color-card ${selectedPaletteHexes.has(hex) && available ? '' : 'off'}" data-hex="${dependencies.esc(hex)}"><span class="color-name" contenteditable="${available && explicitAssignments === null ? 'true' : 'false'}" spellcheck="false" title="${available ? 'Rasterizer swatch assignment' : 'Unassigned in the selected Swatch Palette'}">${dependencies.esc(name)}</span><button class="color-square" type="button" data-hex="${dependencies.esc(hex)}" aria-label="${available ? selectedPaletteHexes.has(hex) ? 'Exclude' : 'Include' : 'Unassigned'} ${dependencies.esc(name)}" aria-pressed="${selectedPaletteHexes.has(hex) && available}" ${available ? '' : 'disabled'} style="--swatch-color:${dependencies.esc(hex)}"></button><span class="color-hex">${dependencies.esc(hex)}</span></div>`;
    }).join('');
  dependencies.syncColorMatchingAvailability();
  dependencies.syncGeometryStyleAvailability();
  if (element('#panelTilingEnabled').checked) dependencies.syncPanelTiling();
  dependencies.markQuantPreviewStale();
}

export function setMaterialOptions(names, preferred = '', placeholder = 'Choose a material') {
  const select = element('#materialName');
  const unique = [...new Set((names || []).map(name => String(name || '').trim()).filter(Boolean))];
  select.replaceChildren(new Option(placeholder, ''), ...unique.map(name => new Option(name, name)));
  select.value = unique.includes(String(preferred || '')) ? String(preferred) : unique[0] || '';
}

export function syncMaterialChoicePresentation() {
  const choice = element('#materialChoice');
  const selection = selectedAsset();
  const holographicUpload = selection.kind === 'holographic-upload';
  const recipe = selectedRasterRecipe();
  const uploading = !choice.value || holographicUpload;
  const svgOnly = svgOnlySelected();
  const selected = selectedMaterialLibrary();
  const needsMaterialSelection = !svgOnly && !holographicUpload && !recipe && !selected;
  const file = element('#materialFile');
  const materialField = element('#materialNameField');
  const materialSelect = element('#materialName');
  const selectedMaterialField = element('#selectedMaterialField');
  const selectedMaterialName = element('#selectedMaterialName');
  element('#materialUpload').classList.toggle('hidden', !uploading);
  file.required = uploading;
  file.disabled = !uploading;
  file.accept = holographicUpload ? '.json,application/json' : '.clb';
  element('#materialFileLabel').textContent = holographicUpload ? 'Fauxlographic Swatch Palette file' : 'Library file';
  element('#holographicUploadInfo').classList.toggle('hidden', !holographicUpload || !dependencies.isGuest());
  materialField.classList.toggle('hidden', !needsMaterialSelection);
  materialSelect.required = needsMaterialSelection;
  materialSelect.disabled = !needsMaterialSelection;
  selectedMaterialField.hidden = !selected;
  if (!holographicUpload) dependencies.setUploadedHolographicProfile(null);
  if (selected) {
    const names = selected.summary?.material_names || [selected.material_name];
    setMaterialOptions(names, selected.material_name);
    selectedMaterialName.textContent = selected.material_name || names.find(Boolean) || '';
  } else if (!choice.value) {
    setMaterialOptions([], '', 'Upload a library to choose a material');
    selectedMaterialName.textContent = '';
  } else if (!needsMaterialSelection) {
    setMaterialOptions([], '');
    selectedMaterialName.textContent = '';
  }
  loadPaletteAssignments();
  selectedPaletteHexes.clear();
  visibleRasterPalette().forEach(item => selectedPaletteHexes.add(paletteEntrySelectionKey(item)));
  renderRasterPalette();
}

export function currentColorNames() {
  const explicitAssignments = explicitLibraryAssignments();
  return Object.fromEntries((resources()?.palette || [])
    .filter(item => explicitAssignments === null || Object.prototype.hasOwnProperty.call(explicitAssignments, String(item.hex).toUpperCase()))
    .map(item => {
      const hex = String(item.hex).toUpperCase();
      return [hex, paletteNameOverrides.get(hex) || item.name];
    }));
}

function savePalettePreferences() {
  if (dependencies.isGuest()) return;
  clearTimeout(preferenceTimer);
  const accountResources = resources();
  const preferences = accountResources.preferences || {};
  const selection = selectedAsset();
  const names = currentColorNames();
  if (selection.kind === 'library') preferences.material_library_color_assignments = {...(preferences.material_library_color_assignments || {}), [selection.id]: names};
  else if (selection.kind !== 'recipe') preferences.color_name_overrides = names;
  preferences.selected_color_hexes = [...selectedPaletteHexes];
  accountResources.preferences = preferences;
  const payload = {
    selected_color_hexes: preferences.selected_color_hexes,
    color_name_overrides: preferences.color_name_overrides || {},
    material_library_color_assignments: preferences.material_library_color_assignments || {},
  };
  preferenceTimer = setTimeout(() => dependencies.api('/account/preferences', {method: 'PATCH', body: JSON.stringify(payload)})
    .then(result => { accountResources.preferences = result.preferences || preferences; })
    .catch(error => dependencies.show(`Could not save swatch assignments: ${error.message}`)), 350);
}

export function lastUsedValues(name) {
  return resources()?.preferences?.[name]?.values || null;
}

export async function saveLastUsed(name, values) {
  if (dependencies.isGuest()) return;
  const result = await dependencies.api('/account/preferences', {method: 'PATCH', body: JSON.stringify({[name]: values})});
  const accountResources = resources();
  accountResources.preferences = result.preferences || accountResources.preferences || {};
}

export async function loadAccountResources() {
  const accountResources = await dependencies.api('/account/resources');
  dependencies.setAccountResources(accountResources);
  const choice = element('#materialChoice');
  choice.replaceChildren(new Option('Upload a new LightBurn Material Library', ''), new Option('SVG-Only (no laser settings)', 'svg'));
  for (const library of accountResources.material_libraries.filter(item => item.library_intent !== 'processing_palette')) {
    const kind = library.library_intent === 'hatch_palette' ? 'Hatch' : 'Color';
    choice.add(new Option(`${library.name} (${kind})`, `library:${library.library_id}`));
  }
  for (const recipe of accountResources.holographic_recipes.filter(item => item.metadata?.self_contained === true || Number(item.metadata?.schema_version) >= 2)) choice.add(new Option(`${recipe.name} (Fauxlographic)`, `recipe:${recipe.recipe_id}`));
  const requestedRecipe = new URLSearchParams(location.search).get('recipe');
  const requestedValue = requestedRecipe ? `recipe:${requestedRecipe}` : '';
  const lastRasterizer = lastUsedValues('last_rasterizer_form');
  if (requestedValue && dependencies.hasOption(choice, requestedValue)) choice.value = requestedValue;
  else if (lastRasterizer && dependencies.hasOption(choice, lastRasterizer.material_choice)) choice.value = lastRasterizer.material_choice;
  const holoMaterial = element('#holoMaterial');
  holoMaterial.replaceChildren(new Option('Choose a library…', ''));
  for (const library of accountResources.material_libraries) holoMaterial.add(new Option(library.name, library.library_id));
  const holoRecipe = element('#holoRecipe');
  holoRecipe.replaceChildren(new Option('Choose a Fauxlographic Palette…', ''));
  for (const recipe of accountResources.holographic_recipes) holoRecipe.add(new Option(recipe.name, recipe.recipe_id));
  syncMaterialChoicePresentation();
  selectedPaletteHexes.clear();
  const selectedRecipe = selectedRasterRecipe();
  const saved = accountResources.preferences?.selected_color_hexes;
  if (selectedRecipe) {
    recipeRasterEntries().forEach(item => selectedPaletteHexes.add(item.selection_key));
    element('#materialName').value = selectedRecipe.name;
  } else if (Array.isArray(saved)) saved.forEach(hex => selectedPaletteHexes.add(String(hex).toUpperCase()));
  else (accountResources.palette || []).forEach(item => selectedPaletteHexes.add(item.hex.toUpperCase()));
  renderRasterPalette();
  dependencies.restoreRasterizerForm(lastRasterizer, !requestedRecipe);
  dependencies.restoreHolographicArtworkForm(lastUsedValues('last_holographic_artwork_form'));
}

export async function loadGuestResources() {
  const guest = await dependencies.guestApi('/guest/config');
  const accountResources = {palette: guest.palette || [], material_libraries: [], holographic_recipes: [], preferences: {}};
  dependencies.setAccountResources(accountResources);
  const choice = element('#materialChoice');
  choice.replaceChildren(new Option('Upload a new LightBurn Material Library', ''), new Option('Upload a Fauxlographic Swatch Palette', 'holographic-upload'), new Option('SVG-Only (no laser settings)', 'svg'));
  paletteNameOverrides.clear();
  selectedPaletteHexes.clear();
  accountResources.palette.forEach(item => selectedPaletteHexes.add(item.hex.toUpperCase()));
  syncMaterialChoicePresentation();
}

function bindPaletteControls() {
  const palette = element('#rasterPalette');
  palette.onclick = event => {
    const button = event.target.closest('button[data-key],button[data-hex]');
    if (!button) return;
    const key = String(button.dataset.key ?? button.dataset.hex).toUpperCase();
    if (selectedPaletteHexes.has(key)) selectedPaletteHexes.delete(key);
    else selectedPaletteHexes.add(key);
    renderRasterPalette();
    if (!selectedRasterRecipe()) savePalettePreferences();
  };
  palette.onkeydown = event => {
    if (event.target.matches('.color-name') && event.key === 'Enter') {
      event.preventDefault();
      event.target.blur();
    }
  };
  palette.oninput = event => {
    if (!event.target.matches('.color-name')) return;
    const card = event.target.closest('.color-card');
    const name = event.target.textContent.replace(/[\r\n]+/g, ' ').trim().slice(0, 80);
    paletteNameOverrides.set(card.dataset.hex.toUpperCase(), name || card.dataset.hex.toUpperCase());
    savePalettePreferences();
  };
  palette.onfocusout = event => {
    if (!event.target.matches('.color-name')) return;
    const card = event.target.closest('.color-card');
    const hex = card.dataset.hex.toUpperCase();
    const fallback = (resources()?.palette || []).find(item => item.hex.toUpperCase() === hex)?.name || hex;
    const name = event.target.textContent.replace(/[\r\n]+/g, ' ').trim().slice(0, 80) || fallback;
    event.target.textContent = name;
    paletteNameOverrides.set(hex, name);
    savePalettePreferences();
  };
  element('#selectAllSwatches').onclick = () => {
    visibleRasterPalette().forEach(item => selectedPaletteHexes.add(paletteEntrySelectionKey(item)));
    renderRasterPalette();
    if (!selectedRasterRecipe()) savePalettePreferences();
  };
  element('#clearSwatches').onclick = () => {
    selectedPaletteHexes.clear();
    renderRasterPalette();
    if (!selectedRasterRecipe()) savePalettePreferences();
  };
  element('#resetSwatches').onclick = () => {
    paletteNameOverrides.clear();
    loadPaletteAssignments();
    selectedPaletteHexes.clear();
    visibleRasterPalette().forEach(item => selectedPaletteHexes.add(String(item.hex).toUpperCase()));
    renderRasterPalette();
    if (explicitLibraryAssignments() === null) savePalettePreferences();
  };
}
