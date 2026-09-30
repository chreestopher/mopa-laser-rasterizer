function readableLightBurnSnapshot(snapshot, depth = 0) {
  if (depth > 4 || !snapshot || Array.isArray(snapshot) || typeof snapshot !== 'object') return false;
  const type = String(snapshot.type || '');
  const settings = snapshot.settings;
  if (!type || type.length > 40 || !settings || Array.isArray(settings) || typeof settings !== 'object' || Object.keys(settings).length > 100) return false;
  for (const [name, value] of Object.entries(settings)) {
    if (!/^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(name) || value !== null && typeof value === 'object' || String(value).length > 160) return false;
  }
  const subLayers = snapshot.sub_layers || [];
  return Array.isArray(subLayers) && subLayers.length <= 20 && subLayers.every(layer => readableLightBurnSnapshot(layer, depth + 1));
}

function readablePreservedBlack(setting) {
  return !!setting && typeof setting === 'object' && !Array.isArray(setting) && readableLightBurnSnapshot(setting.laser_settings);
}

export function bindMaterialInputControls(options) {
  const root = options.documentRoot || document;
  const element = selector => root.querySelector(selector);

  element('#materialChoice').onchange = () => {
    element('#materialFile').value = '';
    options.setUploadedHolographicProfile(null);
    options.syncMaterialChoicePresentation();
  };

  element('#materialFile').onchange = async event => {
    if (options.selectedAsset().kind !== 'holographic-upload') {
      const file = event.target.files[0];
      options.setMaterialOptions([], '', 'Upload a library to choose a material');
      if (!file) return;
      try {
        const documentNode = new DOMParser().parseFromString(await file.text(), 'application/xml');
        if (documentNode.querySelector('parsererror')) throw new Error('The selected file is not valid XML');
        const materials = [...documentNode.querySelectorAll('Material')]
          .filter(material => [...material.children].some(node => node.tagName === 'Entry'))
          .map(material => String(material.getAttribute('name') || '').trim())
          .filter(Boolean);
        if (!materials.length) throw new Error('No named materials with settings were found');
        if (new Set(materials).size !== materials.length) throw new Error('Material names must be unique within the library');
        options.setMaterialOptions(materials);
        options.show(`Loaded ${materials.length} material${materials.length === 1 ? '' : 's'} from ${file.name}. Choose the material to use.`);
      } catch (error) {
        event.target.value = '';
        options.setMaterialOptions([], '', 'Upload a library to choose a material');
        options.show(`Could not read Material Library: ${error.message}`);
      }
      return;
    }

    options.setUploadedHolographicProfile(null);
    const file = event.target.files[0];
    if (!file) {
      options.syncMaterialChoicePresentation();
      return;
    }
    try {
      const profile = JSON.parse(await file.text());
      const recipes = profile?.recipes;
      if (profile?.kind !== 'holographic_calibration_profile' || !Array.isArray(recipes) || !recipes.length) throw new Error('Choose a valid Fauxlographic Swatch Palette');
      const ignoredPreservedBlack = profile.black_setting != null && !readablePreservedBlack(profile.black_setting);
      if (ignoredPreservedBlack) profile.black_setting = null;
      const capacity = profile.black_setting?.laser_settings ? 29 : 30;
      if (recipes.length > capacity) throw new Error(`This Fauxlographic Swatch Palette has too many swatches. Keep at most ${capacity}${capacity === 29 ? ' plus preserved Black' : ''} for 30 LightBurn layers total.`);
      if (recipes.some(item => !item || typeof item.name !== 'string' || !/^#[0-9a-f]{6}$/i.test(String(item.observed_hex || '')) || !item.laser_settings || typeof item.laser_settings !== 'object')) throw new Error('One or more fauxlographic swatches are incomplete');
      options.setUploadedHolographicProfile(profile);
      options.selectedPaletteHexes.clear();
      options.recipeRasterEntries().forEach(item => options.selectedPaletteHexes.add(item.selection_key));
      options.syncMaterialChoicePresentation();
      options.show(`Loaded ${recipes.length} fauxlographic swatches from ${file.name}.${ignoredPreservedBlack ? ' Preserved Black was left unchecked because its settings could not be read.' : ''}`);
    } catch (error) {
      event.target.value = '';
      options.renderRasterPalette();
      options.show(`Could not load Fauxlographic Swatch Palette: ${error.message}`);
    }
  };
}
