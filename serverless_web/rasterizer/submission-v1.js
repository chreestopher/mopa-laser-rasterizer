import {
  submissionErrorMessage,
  upload,
  uploadBatch,
  uploadPhase,
} from './jobs-v1.js';

export function buildRasterUploadGrantPayload({
  artwork,
  thumbnail,
  material,
  svgOnly,
  holographicUpload,
  materialLibraryId,
  savedRecipeId,
}) {
  return {
    artwork_name: artwork.name,
    artwork_content_type: artwork.type || 'application/octet-stream',
    thumbnail_content_type: thumbnail?.type || '',
    material_name: svgOnly || holographicUpload ? '' : material?.name || 'materials.clb',
    material_content_type: material?.type || 'application/octet-stream',
    holographic_palette_name: holographicUpload ? material.name : '',
    holographic_palette_content_type: holographicUpload ? (material.type || 'application/json') : '',
    upload_holographic_palette: holographicUpload,
    saved_material_library_id: materialLibraryId,
    saved_holographic_recipe_id: savedRecipeId,
    svg_only: svgOnly,
  };
}

export function buildRasterSubmissionPayload({
  grant,
  thumbnailUploaded,
  pixelSquareMm,
  newWidth,
  newHeight,
  cropShape,
  whiteIs,
  material,
  selected,
  selectedRecipeIndexes,
  imagePreset,
  filterParameters,
  colorMatchingParameters,
  geometryStyle,
  geometryStyleParameters,
  panelTiling,
  colorNameOverrides,
  cutMode,
  preserveBlackOutlines,
  svgOnly,
}) {
  return {
    upload_token: grant.upload_token,
    artwork_key: grant.artwork.key,
    thumbnail_key: thumbnailUploaded ? grant.thumbnail.key : '',
    material_key: grant.material?.key || '',
    holographic_palette_key: grant.holographic_palette?.key || '',
    pixel_square_mm: pixelSquareMm,
    new_width: newWidth,
    new_height: newHeight,
    crop_shape: cropShape,
    white_is: whiteIs,
    material,
    colors: selected.map(item => item.name).join(','),
    selected_color_hexes: selected.map(item => item.hex),
    selected_holographic_recipe_indexes: selectedRecipeIndexes,
    image_preset: imagePreset,
    abstract_filter: imagePreset.startsWith('abstract_') ? imagePreset.slice(9) : 'none',
    abstract_filter_parameters: JSON.stringify(filterParameters),
    ...colorMatchingParameters,
    geometry_style: geometryStyle,
    geometry_style_parameters: JSON.stringify(geometryStyleParameters),
    panel_tiling: panelTiling,
    color_name_overrides: JSON.stringify(colorNameOverrides),
    cut_mode: cutMode,
    preserve_black_outlines: preserveBlackOutlines,
    svg_only: svgOnly,
  };
}

export function buildHolographicUploadGrantPayload({artwork, thumbnail, recipeId, materialLibraryId}) {
  return {
    artwork_name: artwork.name,
    artwork_content_type: artwork.type || 'application/octet-stream',
    thumbnail_content_type: thumbnail?.type || '',
    saved_holographic_recipe_id: recipeId,
    saved_material_library_id: materialLibraryId,
  };
}

export function buildHolographicSubmissionPayload({grant, thumbnailUploaded, maxDimension, pixelMm, cutMode, preserveBlackOutlines}) {
  return {
    upload_token: grant.upload_token,
    artwork_key: grant.artwork.key,
    thumbnail_key: thumbnailUploaded ? grant.thumbnail.key : '',
    recipe_key: grant.recipe.key,
    material_key: grant.material.key,
    max_dimension: maxDimension,
    pixel_mm: pixelMm,
    cut_mode: cutMode,
    preserve_black_outlines: preserveBlackOutlines,
  };
}

export function createRasterSubmissionHandler({
  documentRoot = document,
  locationRoot = location,
  historyRoot = history,
  isGuest,
  getCropSelection,
  applyArtworkCrop,
  effectiveArtworkFile,
  getSelectedPaletteHexes,
  selectedAsset,
  getUploadedHolographicProfile,
  guestApi,
  api,
  setGuestAccessToken,
  createJobThumbnail,
  show,
  currentColorNames,
  selectedRasterRecipe,
  explicitLibraryAssignments,
  getAccountResources,
  recipeRasterEntries,
  filterParameters,
  colorMatchingParameters,
  effectiveGeometryStyle,
  geometryStyleParameters,
  panelTilingParameters,
  getAppliedCropShape,
  saveLastUsed,
  rasterizerFormValues,
  setCurrentTask,
  poll,
}) {
  const element = selector => documentRoot.querySelector(selector);
  return async event => {
    event.preventDefault();
    const submit = element('#submit');
    submit.disabled = true;
    element('#activity').classList.remove('hidden');
    element('#outputs').innerHTML = '';
    uploadPhase('Preparing secure upload permissions', null, documentRoot);
    try {
      const cropSelection = getCropSelection();
      if (cropSelection && cropSelection.width >= 2 && cropSelection.height >= 2 && !(await applyArtworkCrop())) {
        throw new Error('The selected artwork crop could not be applied');
      }
      const artwork = effectiveArtworkFile();
      const materialFile = element('#materialFile').files[0];
      if (!artwork) throw new Error('Choose an artwork image');
      const selectedPaletteHexes = getSelectedPaletteHexes();
      if (!selectedPaletteHexes.size) throw new Error('Select at least one raster palette swatch');
      const guestMode = isGuest();
      const thumbnail = guestMode ? null : await createJobThumbnail(artwork);
      show('Requesting short-lived upload permissions…');
      const selectedAssetChoice = selectedAsset();
      const svgOnly = selectedAssetChoice.kind === 'svg';
      const holographicUpload = selectedAssetChoice.kind === 'holographic-upload';
      const materialLibraryId = selectedAssetChoice.kind === 'library' ? selectedAssetChoice.id : '';
      const savedRecipeId = selectedAssetChoice.kind === 'recipe' ? selectedAssetChoice.id : '';
      if (holographicUpload && !getUploadedHolographicProfile()) throw new Error('Choose a valid Fauxlographic Swatch Palette file');
      if (guestMode && !svgOnly && !materialFile) throw new Error('Guest jobs require a freshly uploaded Material Library, a Fauxlographic Swatch Palette, or SVG-Only');
      const request = guestMode ? guestApi : api;
      const grant = await request(guestMode ? '/guest/uploads' : '/uploads', {
        method: 'POST',
        body: JSON.stringify(buildRasterUploadGrantPayload({
          artwork,
          thumbnail,
          material: materialFile,
          svgOnly,
          holographicUpload,
          materialLibraryId,
          savedRecipeId,
        })),
      });
      if (guestMode) setGuestAccessToken(grant.guest_access_token);
      show(svgOnly
        ? 'Uploading artwork directly to private S3…'
        : holographicUpload
          ? 'Uploading artwork and Fauxlographic Swatch Palette directly to private S3…'
          : grant.material?.saved
            ? 'Uploading artwork directly to private S3…'
            : 'Uploading artwork and Material Library directly to private S3…');
      const uploads = [{file: artwork, target: grant.artwork}];
      if (holographicUpload) uploads.push({file: materialFile, target: grant.holographic_palette});
      else if (grant.material && !grant.material.saved) uploads.push({file: materialFile, target: grant.material});
      await uploadBatch(uploads, documentRoot);
      let thumbnailUploaded = false;
      if (thumbnail && grant.thumbnail) {
        try {
          await upload(thumbnail, grant.thumbnail);
          thumbnailUploaded = true;
        } catch (error) {
          console.warn('Optional Job History thumbnail upload failed:', error);
        }
      }
      show('Uploads verified. Submitting task ID to SQS…');
      const overrides = currentColorNames();
      const recipe = selectedRasterRecipe();
      const assignments = explicitLibraryAssignments();
      const selected = (getAccountResources().palette || [])
        .filter(item => {
          const hex = item.hex.toUpperCase();
          return selectedPaletteHexes.has(hex) && (assignments === null || Object.prototype.hasOwnProperty.call(assignments, hex));
        })
        .map(item => ({...item, name: overrides[item.hex.toUpperCase()] || item.name}));
      const selectedRecipeIndexes = recipe
        ? recipeRasterEntries().filter(item => selectedPaletteHexes.has(item.selection_key)).map(item => item.recipe_index)
        : [];
      const imagePreset = element('#imagePreset').value;
      const payload = buildRasterSubmissionPayload({
        grant,
        thumbnailUploaded,
        pixelSquareMm: element('#pixel').value,
        newWidth: element('#width').value,
        newHeight: element('#height').value,
        cropShape: getAppliedCropShape(),
        whiteIs: element('#whiteIs').value,
        material: svgOnly ? '' : element('#materialName').value,
        selected,
        selectedRecipeIndexes,
        imagePreset,
        filterParameters: filterParameters(),
        colorMatchingParameters: colorMatchingParameters(),
        geometryStyle: effectiveGeometryStyle(),
        geometryStyleParameters: geometryStyleParameters(),
        panelTiling: panelTilingParameters(),
        colorNameOverrides: overrides,
        cutMode: recipe ? element('#rasterHoloCutMode').value : 'setting',
        preserveBlackOutlines: recipe && element('#rasterHoloBlack').checked,
        svgOnly,
      });
      await request(guestMode ? `/guest/jobs/${grant.task_id}/submit` : `/jobs/${grant.task_id}/submit`, {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      uploadPhase('Upload complete · job submitted', 100, documentRoot);
      if (!guestMode) saveLastUsed('last_rasterizer_form', rasterizerFormValues()).catch(() => {});
      setCurrentTask(grant.task_id);
      if (!guestMode) historyRoot.replaceState({}, '', `${locationRoot.pathname}?task=${encodeURIComponent(grant.task_id)}`);
      poll();
    } catch (error) {
      const message = submissionErrorMessage(error, submit);
      uploadPhase(`Upload or submission failed · ${message}`, 0, documentRoot);
      show(`ERROR: ${message}`);
      element('#activity').classList.add('hidden');
      submit.disabled = false;
    }
  };
}

export function createHolographicSubmissionHandler({
  documentRoot = document,
  locationRoot = location,
  historyRoot = history,
  api,
  createJobThumbnail,
  show,
  saveLastUsed,
  holographicArtworkFormValues,
  setCurrentTask,
  poll,
}) {
  const element = selector => documentRoot.querySelector(selector);
  return async event => {
    event.preventDefault();
    const submit = element('#holoSubmit');
    submit.disabled = true;
    element('#activity').classList.remove('hidden');
    element('#outputs').innerHTML = '';
    uploadPhase('Preparing secure upload permissions', null, documentRoot);
    try {
      const artwork = element('#holoArtwork').files[0];
      const thumbnail = await createJobThumbnail(artwork);
      show('Requesting short-lived fauxlographic artwork upload permission…');
      const grant = await api('/holographic/uploads', {
        method: 'POST',
        body: JSON.stringify(buildHolographicUploadGrantPayload({
          artwork,
          thumbnail,
          recipeId: element('#holoRecipe').value,
          materialLibraryId: element('#holoMaterial').value,
        })),
      });
      show('Uploading artwork directly to private S3…');
      await uploadBatch([{file: artwork, target: grant.artwork}], documentRoot);
      let thumbnailUploaded = false;
      if (thumbnail && grant.thumbnail) {
        try {
          await upload(thumbnail, grant.thumbnail);
          thumbnailUploaded = true;
        } catch (error) {
          console.warn('Optional Job History thumbnail upload failed:', error);
        }
      }
      show('Uploads verified. Launching fauxlographic Fargate job…');
      await api(`/holographic/jobs/${grant.task_id}/submit`, {
        method: 'POST',
        body: JSON.stringify(buildHolographicSubmissionPayload({
          grant,
          thumbnailUploaded,
          maxDimension: element('#holoDimension').value,
          pixelMm: element('#holoPixel').value,
          cutMode: element('#holoCutMode').value,
          preserveBlackOutlines: element('#holoBlack').checked,
        })),
      });
      uploadPhase('Upload complete · job submitted', 100, documentRoot);
      saveLastUsed('last_holographic_artwork_form', holographicArtworkFormValues()).catch(() => {});
      setCurrentTask(grant.task_id);
      historyRoot.replaceState({}, '', `${locationRoot.pathname}?task=${encodeURIComponent(grant.task_id)}`);
      poll();
    } catch (error) {
      const message = submissionErrorMessage(error, submit);
      uploadPhase(`Upload or submission failed · ${message}`, 0, documentRoot);
      show(`ERROR: ${message}`);
      element('#activity').classList.add('hidden');
      submit.disabled = false;
    }
  };
}
