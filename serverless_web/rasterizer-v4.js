import {renderRasterOutputs} from './rasterizer/output-rendering-v1.js';
import {
  createRasterJobPoller,
} from './rasterizer/jobs-v1.js';
import {
  createHolographicSubmissionHandler,
  createRasterSubmissionHandler,
} from './rasterizer/submission-v1.js';
import {
  applyArtworkCrop,
  configureArtworkPreview,
  effectiveArtworkFile,
  getAppliedCropShape,
  getCropSelection,
  loadPreviewBitmap,
  markQuantPreviewStale,
} from './rasterizer/artwork-preview-v1.js';
import {
  configurePanelTiling,
  panelTilingDerivedDimensions,
  panelTilingParameters,
  panelTilingPreferenceValues,
  restorePanelTiling,
  syncPanelTiling,
} from './rasterizer/panel-tiling-v1.js';
import {
  configurePaletteResources,
  currentColorNames,
  explicitLibraryAssignments,
  lastUsedValues,
  loadAccountResources,
  loadGuestResources,
  paletteDisplayName,
  recipeRasterEntries,
  renderRasterPalette,
  saveLastUsed,
  selectedAsset,
  selectedMaterialLibrary,
  selectedPaletteHexes,
  selectedRasterRecipe,
  setMaterialOptions,
  svgOnlySelected,
  syncMaterialChoicePresentation,
  visibleRasterPalette,
} from './rasterizer/palette-resources-v1.js';
import {
  configureFlowPainter,
  getFauxlogramFlow,
  resetFauxlogramFlow,
  restoreFauxlogramFlow,
} from './rasterizer/flow-painter-v1.js';
import {
  configureGeometryControls,
  effectiveGeometryStyle,
  geometryStyleParameters,
  renderGeometryControls,
  restoreGeometryControls,
  syncGeometryStyleAvailability,
} from './rasterizer/geometry-controls-v1.js';
import {
  bindColorMatchingControls,
  bindImageStyleControls,
  colorMatchingParameters,
  configureImageStyleMatching,
  effectiveColorMatching,
  filterParameters,
  previewSwatches,
  quantizePreviewPixels,
  renderImageStyleControls,
  restoreColorMatching,
  restoreImageStyle,
  syncColorMatchingAvailability,
  updateColorMatchingPresentation,
} from './rasterizer/image-style-matching-v1.js';
import {createRasterizerSessionApi} from './rasterizer/session-api-v1.js';
import {
  configureFormState,
  hasOption,
  holographicArtworkFormValues,
  rasterizerFormValues,
  restoreHolographicArtworkForm,
  restoreRasterizerForm,
} from './rasterizer/form-state-v1.js';
import {
  createJobThumbnail,
  createStatusPresenter,
  escapeHtml,
  swatchChip,
  userFacingStyleError,
} from './rasterizer/ui-helpers-v1.js';
import {bindMaterialInputControls} from './rasterizer/material-input-v1.js';

let currentTask, pollTimer, accountResources, uploadedHolographicProfile=null;
const statusEl=document.querySelector('#status'), form=document.querySelector('#job'), holographicForm=document.querySelector('#holographicJob');
const show=createStatusPresenter(statusEl),esc=escapeHtml;
configureFlowPainter({show});
configureFormState({
  filterParameters,
  effectiveGeometryStyle,
  geometryStyleParameters,
  panelTilingPreferenceValues,
  colorMatchingParameters,
  restoreImageStyle,
  restoreGeometryControls,
  restoreColorMatching,
  restorePanelTiling,
});
const sessionApi=createRasterizerSessionApi({show,userFacingStyleError});
const {api,guestApi}=sessionApi;
configurePaletteResources({
  getAccountResources:()=>accountResources,
  setAccountResources:value=>{accountResources=value},
  getUploadedHolographicProfile:()=>uploadedHolographicProfile,
  setUploadedHolographicProfile:value=>{uploadedHolographicProfile=value},
  isGuest:sessionApi.isGuest,
  api,
  guestApi,
  show,
  esc,
  hasOption,
  syncColorMatchingAvailability,
  syncGeometryStyleAvailability,
  syncPanelTiling,
  markQuantPreviewStale,
  restoreRasterizerForm,
  restoreHolographicArtworkForm,
});
configureImageStyleMatching({selectedRasterRecipe,visibleRasterPalette,selectedPaletteHexes,paletteDisplayName,hasOption,syncGeometryStyleAvailability,markQuantPreviewStale});bindImageStyleControls();configureGeometryControls({selectedRasterRecipe,visibleRasterPalette,selectedPaletteHexes,paletteDisplayName,esc,hasOption,getFauxlogramFlow,restoreFauxlogramFlow,resetFauxlogramFlow});renderImageStyleControls();renderGeometryControls();syncGeometryStyleAvailability();configurePanelTiling({previewSwatches,hasOption,effectiveArtworkFile,loadPreviewBitmap,markQuantPreviewStale});
async function load(){
  await sessionApi.initialize({
    loadAccountResources,
    loadGuestResources,
    onResumeTask:task=>{currentTask=task;document.querySelector('#submit').disabled=true;document.querySelector('#activity').classList.remove('hidden');poll()},
  });
  form.dataset.ready='true';
}
const poll=createRasterJobPoller({
  getCurrentTask:()=>currentTask,
  isGuest:sessionApi.isGuest,
  guestApi,
  api,
  show,
  userFacingStyleError,
  jobAccessErrorMessage:sessionApi.jobAccessErrorMessage,
  recoverUnavailableGuestTask:sessionApi.recoverUnavailableGuestTask,
  renderOutputs:renderRasterOutputs,
  setPollTimer:timer=>{pollTimer=timer},
});
configureArtworkPreview({
  resetFauxlogramFlow,
  syncPanelTiling,
  previewSwatches,
  effectiveColorMatching,
  panelTilingDerivedDimensions,
  quantizePreviewPixels,
  esc,
});
bindColorMatchingControls();
updateColorMatchingPresentation();
bindMaterialInputControls({
  selectedAsset,
  setMaterialOptions,
  setUploadedHolographicProfile:value=>{uploadedHolographicProfile=value},
  syncMaterialChoicePresentation,
  selectedPaletteHexes,
  recipeRasterEntries,
  renderRasterPalette,
  show,
});
const thumbnailForJob=file=>createJobThumbnail(file,loadPreviewBitmap);
form.onsubmit=createRasterSubmissionHandler({
  isGuest:sessionApi.isGuest,getCropSelection,applyArtworkCrop,effectiveArtworkFile,
  getSelectedPaletteHexes:()=>selectedPaletteHexes,selectedAsset,getUploadedHolographicProfile:()=>uploadedHolographicProfile,
  guestApi,api,setGuestAccessToken:sessionApi.setGuestAccessToken,
  createJobThumbnail:thumbnailForJob,show,currentColorNames,selectedRasterRecipe,explicitLibraryAssignments,
  getAccountResources:()=>accountResources,recipeRasterEntries,filterParameters,colorMatchingParameters,
  effectiveGeometryStyle,geometryStyleParameters,panelTilingParameters,getAppliedCropShape,
  saveLastUsed,rasterizerFormValues,setCurrentTask:value=>{currentTask=value},poll,
});
holographicForm.onsubmit=createHolographicSubmissionHandler({
  api,createJobThumbnail:thumbnailForJob,show,saveLastUsed,holographicArtworkFormValues,
  setCurrentTask:value=>{currentTask=value},poll,
});
load().catch(error=>{const message=error.message||'Unknown error';show(message==='Session expired. Sign in again.'||message.startsWith('Cognito sign-in')||message.startsWith('Sign-in attempt')?message:`Configuration error: ${message}`)});
