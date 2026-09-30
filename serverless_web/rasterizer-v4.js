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

let currentTask, pollTimer, accountResources, uploadedHolographicProfile=null;
configureFlowPainter({show});
function hasOption(select,value){return [...select.options].some(option=>option.value===String(value??''))}
function rasterizerFormValues(){return{material_choice:document.querySelector('#materialChoice').value,material_name:document.querySelector('#materialName').value,pixel_square_mm:document.querySelector('#pixel').value,new_width:document.querySelector('#width').value,new_height:document.querySelector('#height').value,white_is:document.querySelector('#whiteIs').value,image_preset:document.querySelector('#imagePreset').value,filter_parameters:filterParameters(),geometry_style:effectiveGeometryStyle(),geometry_style_parameters:geometryStyleParameters(),panel_tiling:panelTilingPreferenceValues(),...colorMatchingParameters(),cut_mode:document.querySelector('#rasterHoloCutMode').value,preserve_black_outlines:document.querySelector('#rasterHoloBlack').checked}}
function restoreRasterizerForm(values,restoreMaterial=true){if(!values)return;if(restoreMaterial&&values.material_name!==undefined)document.querySelector('#materialName').value=values.material_name;for(const [id,key] of [['pixel','pixel_square_mm'],['width','new_width'],['height','new_height']])if(values[key]!==undefined)document.querySelector('#'+id).value=values[key];if(hasOption(document.querySelector('#whiteIs'),values.white_is))document.querySelector('#whiteIs').value=values.white_is;restoreImageStyle(values);restoreGeometryControls(values);restoreColorMatching(values);if(hasOption(document.querySelector('#rasterHoloCutMode'),values.cut_mode))document.querySelector('#rasterHoloCutMode').value=values.cut_mode;document.querySelector('#rasterHoloBlack').checked=Boolean(values.preserve_black_outlines)&&!document.querySelector('#rasterHoloBlack').disabled;restorePanelTiling(values)}
function holographicArtworkFormValues(){return{recipe_id:document.querySelector('#holoRecipe').value,material_library_id:document.querySelector('#holoMaterial').value,max_dimension:document.querySelector('#holoDimension').value,pixel_mm:document.querySelector('#holoPixel').value,cut_mode:document.querySelector('#holoCutMode').value,preserve_black_outlines:document.querySelector('#holoBlack').checked}}
function restoreHolographicArtworkForm(values){if(!values)return;for(const [id,key] of [['holoRecipe','recipe_id'],['holoMaterial','material_library_id'],['holoCutMode','cut_mode']]){const select=document.querySelector('#'+id);if(hasOption(select,values[key]))select.value=values[key]}for(const [id,key] of [['holoDimension','max_dimension'],['holoPixel','pixel_mm']])if(values[key]!==undefined)document.querySelector('#'+id).value=values[key];document.querySelector('#holoBlack').checked=Boolean(values.preserve_black_outlines)}
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
const statusEl=document.querySelector('#status'), form=document.querySelector('#job'), holographicForm=document.querySelector('#holographicJob');
function show(message){statusEl.textContent=message}
function esc(value){return String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]))}
function swatchChip(entry,intent='color_palette'){
  const color=entry.display_hex||entry.hex||'#303842',rawAngle=Number(entry.angle??entry.settings?.angle??0),rawInterval=Number(entry.interval??entry.settings?.interval??.05),angle=(Number.isFinite(rawAngle)?rawAngle:0)+90,spacing=Math.max(3,Math.min(14,(Number.isFinite(rawInterval)&&rawInterval>0?rawInterval:.05)*120));
  const pattern=intent==='hatch_palette'?`;background-image:repeating-linear-gradient(${angle}deg,rgba(0,0,0,.88) 0 1px,rgba(255,255,255,.2) 1px 2px,transparent 2px ${spacing}px)`:'';
  return `<span class="swatch-chip" style="background-color:${color}${pattern}"></span><span class="swatch-name" title="${esc(entry.description||entry.name)}">${esc(entry.description||entry.name)}</span>`;
}
function readableLightBurnSnapshot(snapshot,depth=0){if(depth>4||!snapshot||Array.isArray(snapshot)||typeof snapshot!=='object')return false;const type=String(snapshot.type||''),settings=snapshot.settings;if(!type||type.length>40||!settings||Array.isArray(settings)||typeof settings!=='object'||Object.keys(settings).length>100)return false;for(const [name,value] of Object.entries(settings))if(!/^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(name)||value!==null&&typeof value==='object'||String(value).length>160)return false;const subLayers=snapshot.sub_layers||[];return Array.isArray(subLayers)&&subLayers.length<=20&&subLayers.every(layer=>readableLightBurnSnapshot(layer,depth+1))}
function readablePreservedBlack(setting){return !!setting&&typeof setting==='object'&&!Array.isArray(setting)&&readableLightBurnSnapshot(setting.laser_settings)}
async function createJobThumbnail(file){
  if(!file)return null;
  let bitmap;
  try{
    bitmap=await loadPreviewBitmap(file);const sourceWidth=bitmap.width||bitmap.naturalWidth,sourceHeight=bitmap.height||bitmap.naturalHeight;if(!sourceWidth||!sourceHeight)return null;
    const maximum=256,scale=Math.min(1,maximum/sourceWidth,maximum/sourceHeight),width=Math.max(1,Math.round(sourceWidth*scale)),height=Math.max(1,Math.round(sourceHeight*scale)),canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;const context=canvas.getContext('2d');context.imageSmoothingEnabled=true;context.imageSmoothingQuality='high';context.clearRect(0,0,width,height);context.drawImage(bitmap,0,0,width,height);
    let blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/webp',.8));if(!blob||blob.type!=='image/webp')blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));if(!blob)return null;const extension=blob.type==='image/webp'?'webp':'png';return new File([blob],`input-thumbnail.${extension}`,{type:blob.type,lastModified:Date.now()});
  }catch(error){console.warn('Job History thumbnail could not be generated:',error);return null}finally{bitmap?.close?.()}
}
async function load(){
  await sessionApi.initialize({
    loadAccountResources,
    loadGuestResources,
    onResumeTask:task=>{currentTask=task;document.querySelector('#submit').disabled=true;document.querySelector('#activity').classList.remove('hidden');poll()},
  });
}
function userFacingStyleError(message){const raw=String(message||''),value=raw.replace(/^ValueError:\s*/,'');return /^(?:Image style|Geometry style|Abstract filter) settings are not valid JSON$|^Invalid (?:abstract filter|geometry style) parameters:/.test(value)?"We couldn't read these style settings. Reload Rasterizer, choose the style again, and resubmit. If it keeps happening, report the problem.":raw}
const poll=createRasterJobPoller({
  getCurrentTask:()=>currentTask,
  isGuest:sessionApi.isGuest,
  guestApi,
  api,
  show,
  userFacingStyleError,
  jobAccessErrorMessage:sessionApi.jobAccessErrorMessage,
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
document.querySelector('#materialChoice').onchange=()=>{document.querySelector('#materialFile').value='';uploadedHolographicProfile=null;syncMaterialChoicePresentation()};
document.querySelector('#materialFile').onchange=async event=>{
  if(selectedAsset().kind!=='holographic-upload'){
    const file=event.target.files[0];setMaterialOptions([],"",'Upload a library to choose a material');if(!file)return;
    try{
      const documentNode=new DOMParser().parseFromString(await file.text(),'application/xml');if(documentNode.querySelector('parsererror'))throw new Error('The selected file is not valid XML');
      const materials=[...documentNode.querySelectorAll('Material')].filter(material=>[...material.children].some(node=>node.tagName==='Entry')).map(material=>String(material.getAttribute('name')||'').trim()).filter(Boolean);
      if(!materials.length)throw new Error('No named materials with settings were found');
      if(new Set(materials).size!==materials.length)throw new Error('Material names must be unique within the library');
      setMaterialOptions(materials);show(`Loaded ${materials.length} material${materials.length===1?'':'s'} from ${file.name}. Choose the material to use.`);
    }catch(error){event.target.value='';setMaterialOptions([],"",'Upload a library to choose a material');show(`Could not read Material Library: ${error.message}`)}
    return;
  }
  uploadedHolographicProfile=null;
  const file=event.target.files[0];if(!file){syncMaterialChoicePresentation();return}
  try{
    const profile=JSON.parse(await file.text()),recipes=profile?.recipes;
    if(profile?.kind!=='holographic_calibration_profile'||!Array.isArray(recipes)||!recipes.length)throw new Error('Choose a valid Fauxlographic Swatch Palette');
    const ignoredPreservedBlack=profile.black_setting!=null&&!readablePreservedBlack(profile.black_setting);
    if(ignoredPreservedBlack)profile.black_setting=null;
    const capacity=profile.black_setting?.laser_settings?29:30;
    if(recipes.length>capacity)throw new Error(`This Fauxlographic Swatch Palette has too many swatches. Keep at most ${capacity}${capacity===29?' plus preserved Black':''} for 30 LightBurn layers total.`);
    if(recipes.some(item=>!item||typeof item.name!=='string'||!/^#[0-9a-f]{6}$/i.test(String(item.observed_hex||''))||!item.laser_settings||typeof item.laser_settings!=='object'))throw new Error('One or more fauxlographic swatches are incomplete');
    uploadedHolographicProfile=profile;selectedPaletteHexes.clear();recipeRasterEntries().forEach(item=>selectedPaletteHexes.add(item.selection_key));syncMaterialChoicePresentation();show(`Loaded ${recipes.length} fauxlographic swatches from ${file.name}.${ignoredPreservedBlack?' Preserved Black was left unchecked because its settings could not be read.':''}`);
  }catch(error){event.target.value='';renderRasterPalette();show(`Could not load Fauxlographic Swatch Palette: ${error.message}`)}
};
form.onsubmit=createRasterSubmissionHandler({
  isGuest:sessionApi.isGuest,getCropSelection,applyArtworkCrop,effectiveArtworkFile,
  getSelectedPaletteHexes:()=>selectedPaletteHexes,selectedAsset,getUploadedHolographicProfile:()=>uploadedHolographicProfile,
  guestApi,api,setGuestAccessToken:sessionApi.setGuestAccessToken,
  createJobThumbnail,show,currentColorNames,selectedRasterRecipe,explicitLibraryAssignments,
  getAccountResources:()=>accountResources,recipeRasterEntries,filterParameters,colorMatchingParameters,
  effectiveGeometryStyle,geometryStyleParameters,panelTilingParameters,getAppliedCropShape,
  saveLastUsed,rasterizerFormValues,setCurrentTask:value=>{currentTask=value},poll,
});
holographicForm.onsubmit=createHolographicSubmissionHandler({
  api,createJobThumbnail,show,saveLastUsed,holographicArtworkFormValues,
  setCurrentTask:value=>{currentTask=value},poll,
});
load().catch(error=>{const message=error.message||'Unknown error';show(message==='Session expired. Sign in again.'||message.startsWith('Cognito sign-in')||message.startsWith('Sign-in attempt')?message:`Configuration error: ${message}`)});
