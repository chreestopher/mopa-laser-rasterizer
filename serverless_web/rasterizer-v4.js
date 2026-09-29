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

let config, token=localStorage.getItem('id_token')||sessionStorage.getItem('id_token'), refreshToken=localStorage.getItem('refresh_token')||sessionStorage.getItem('refresh_token'), currentTask, pollTimer, accountResources, guestMode=!token, guestAccessToken=sessionStorage.getItem('guest_access_token'), uploadedHolographicProfile=null;
if(token)localStorage.setItem('id_token',token);if(refreshToken)localStorage.setItem('refresh_token',refreshToken);sessionStorage.removeItem('id_token');sessionStorage.removeItem('refresh_token');
const PRESETS={
  cartoon:{description:'Best for logos, illustrations, and bold graphic art.',controls:[['min_island_area',0,0,100,1],['simplification_factor',0,0,5,.05],['smoothing_radius',.001,0,10,.001]]},
  color_photograph:{description:'Reduces a photograph to the selected engraving colors, then cleans its vector edges.',controls:[['min_island_area',8,0,100,1],['simplification_factor',.35,0,5,.05],['smoothing_radius',.5,0,10,.05]]},
  bw_dither_photograph:{description:'Turns a photograph into two-color dithered engraving geometry.',controls:[['min_island_area',2,0,100,1],['simplification_factor',.1,0,5,.05],['smoothing_radius',.1,0,10,.05]],toggles:[['transparent',false]]},
  abstract_wave:{description:'Bends every color boundary together in synchronized waves.',controls:[['amplitude_x',4,-30,30,.5],['amplitude_y',4,-30,30,.5],['frequency_x',.1,.01,1,.01],['frequency_y',.1,.01,1,.01],['phase',0,0,6.283,.05]]},
  abstract_voronoi:{description:'Rebuilds the artwork as an organic field of irregular cells.',controls:[['cell_size',15,3,100,1],['jitter',.45,0,.95,.01],['gap',.8,0,12,.1],['seed',1,0,999999,1]]},
  abstract_shear:{description:'Pulls the image into a directional, slanted look.',controls:[['shear_x',.5,-2,2,.05],['shear_y',0,-2,2,.05],['scale_x',1,.25,3,.05],['scale_y',.8,.25,3,.05]]},
  abstract_spiral:{description:'Draws the design into a movable vortex.',controls:[['twist',2.25,-8,8,.1],['falloff',1,.1,5,.1],['center_x',.5,0,1,.01],['center_y',.5,0,1,.01]]},
  abstract_mosaic:{description:'Turns color regions into clean rectangular tiles.',controls:[['tile_size',12,2,100,1],['gap',1,0,20,.1],['stagger',.5,0,1,.05]]},
  abstract_crystal:{description:'Converts the image into faceted triangular metal art.',controls:[['cell_size',18,3,120,1],['gap',.7,0,20,.1]]},
  abstract_ripple:{description:'Sends concentric rings outward from a movable center.',controls:[['amplitude',3,-30,30,.5],['frequency',.18,.01,1,.01],['phase',0,0,6.283,.05],['center_x',.5,0,1,.01],['center_y',.5,0,1,.01]]},
  abstract_glitch:{description:'Slices the image into coordinated digital stutters and echoes.',controls:[['slice_height',18,3,100,1],['fragment_width',70,8,240,1],['shift_amount',28,0,180,1],['echo_count',2,0,5,1],['echo_spacing',9,0,80,1],['density',.55,0,1,.05],['fibonacci_stride',2,1,8,1],['vertical_jitter',3,0,60,1],['seed',1,0,999999,1]]},
  abstract_deep_fryer:{description:'Creates compression blocks, damaged scan bands, smears, and echoes.',controls:[['block_size',24,4,120,1],['band_height',34,4,180,1],['compression_gap',.7,0,8,.1],['smear_amount',18,0,120,1],['echo_count',2,0,5,1],['echo_spacing',5,0,40,1],['degradation',.35,0,1,.05],['seed',1,0,999999,1]]},
  abstract_shattered:{description:'Breaks the artwork into glass-like shards around an impact point.',controls:[['min_shard_size',8,2,80,1],['max_shard_size',32,4,160,1],['density',.6,.1,1,.05],['minimum_gap',.7,0,10,.1],['gap_variation',2.2,0,15,.1],['horizontal_spread',12,0,100,1],['fall_distance',20,0,160,1],['gravity_bias',1.4,.2,4,.1],['rotation',22,0,180,1],['break_origin_x',.5,0,1,.01],['break_origin_y',.35,0,1,.01],['seed',1,0,999999,1]]},
  abstract_structure_tensor_flow:{description:'Redraws the image as curved ribbons following its local contour flow. Ribbon width varies between the requested minimum and maximum according to source tone and tensor coherence. When ribbons touch or cross, a small junction is removed from both so they remain distinct marks instead of joining into broad source-like vectors or double-engraving overlaps. Minimum Color Run merges tiny color fragments into the adjacent color sharing the longest boundary. The Photorealistic end clips ribbons to the original swatch silhouettes; moving toward Abstract lets a ribbon carry its starting color freely across those boundaries.',controls:[['abstraction',.5,0,1,.01],['line_spacing_mm',.9,.2,4,.05],['line_length_mm',5,.5,20,.25],['minimum_ribbon_width_mm',.1,.02,1,.01],['maximum_ribbon_width_mm',.35,.02,2,.01],['minimum_color_run_mm',.3,0,5,.05],['width_tone_influence',.65,0,1,.05],['width_coherence_influence',.35,0,1,.05],['step_size_mm',.15,.03,.5,.01],['source_blur_px',1.5,0,8,.1],['tensor_smoothing_px',6,.5,20,.5],['coherence_cutoff',0,0,1,.01],['coherence_influence',.5,0,1,.05],['flow_rotation',0,-90,90,1],['seed_jitter',.15,0,.45,.01],['seed',1,0,999999,1]]},
  abstract_optical_color_mix:{description:'Keeps ordinary continuous vector geometry wherever available palette swatches adequately represent the source. Only colors that benefit from a calculated two-swatch mixture become a shared dot matrix. Turn off Keep Available Colors as Vectors to render the entire artwork with dots. Lab is the recommended model; RGB and HSV provide alternate matching behavior. Direct Color Preference controls how strongly the filter favors normal vectors.',selects:[['mixing_model','lab',[['lab','Perceptual Lab'],['rgb','Linear RGB'],['hsv','Creative HSV']]]],toggles:[['keep_available_colors_as_vectors',true],['square_dots',false]],controls:[['dot_pitch_mm',.35,.15,3,.05],['mix_cell_dots',4,2,8,1],['dot_size_ratio',.72,.2,.95,.01],['direct_color_preference',.08,0,1,.01],['hue_shift',0,-90,90,1],['saturation_gain',1,.25,2,.05],['brightness_gamma',1,.4,2.5,.05],['dot_influence',1,.25,4,.05],['neutral_bias',0,-1,1,.05],['pattern_seed',1,0,999999,1]]},
  abstract_none:{description:'Keeps the abstract vector workflow without a geometric effect.',controls:[]}
};
const COLOR_MATCHING_MODES={
  balanced:{description:'Balances hue, saturation, and shade while protecting vivid colors from collapsing into gray.',hue:4,saturation:1,lightness:1},
  hue:{description:'Keeps assignments in the closest color family, even when another swatch is nearer in brightness.',hue:8,saturation:1,lightness:1},
  shades:{description:'More strongly separates lighter and darker swatches within the same color family.',hue:2,saturation:1,lightness:4},
  closest:{description:'Uses direct RGB proximity without hue protection or same-family shade separation.',hue:0,saturation:0,lightness:0},
  custom:{description:'Use the controls below to choose how strongly hue, saturation, and shade affect matching.',hue:4,saturation:1,lightness:1}
};
const friendly=name=>name.split('_').map(word=>word[0].toUpperCase()+word.slice(1)).join(' ');
function filterParameters(){return Object.fromEntries([...document.querySelectorAll('#filterControls [data-parameter]')].map(input=>[input.dataset.parameter,input.type==='checkbox'?Number(input.checked):input.tagName==='SELECT'?input.value:Number(input.value)]))}
configureFlowPainter({show});
function colorMatchingParameters(){return{color_matching_mode:document.querySelector('#colorMatchingMode').value,color_matching_hue_weight:Number(document.querySelector('#matchingHue').value),color_matching_saturation_weight:Number(document.querySelector('#matchingSaturation').value),color_matching_lightness_weight:Number(document.querySelector('#matchingLightness').value)}}
function effectiveColorMatching(){const mode=document.querySelector('#colorMatchingMode').value,preset=COLOR_MATCHING_MODES[mode]||COLOR_MATCHING_MODES.balanced;return mode==='custom'?{mode,hue:Number(document.querySelector('#matchingHue').value),saturation:Number(document.querySelector('#matchingSaturation').value),lightness:Number(document.querySelector('#matchingLightness').value)}:{mode,hue:preset.hue,saturation:preset.saturation,lightness:preset.lightness}}
function setMatchingControl(name,value){const range=document.querySelector(`#matching${name}`),number=document.querySelector(`#matching${name}Number`),clean=Math.max(0,Math.min(10,Number(value)));range.value=Number.isFinite(clean)?clean:0;number.value=range.value}
function updateColorMatchingPresentation(){const mode=document.querySelector('#colorMatchingMode').value,preset=COLOR_MATCHING_MODES[mode]||COLOR_MATCHING_MODES.balanced;document.querySelector('#colorMatchingDescription').textContent=preset.description;document.querySelector('#colorMatchingCustom').hidden=mode!=='custom';if(mode!=='custom'){setMatchingControl('Hue',preset.hue);setMatchingControl('Saturation',preset.saturation);setMatchingControl('Lightness',preset.lightness)}markQuantPreviewStale()}
function syncColorMatchingAvailability(){const unavailable=Boolean(selectedRasterRecipe())||document.querySelector('#imagePreset').value==='bw_dither_photograph';document.querySelector('#colorMatchingSection').classList.toggle('hidden',unavailable)}
function hasOption(select,value){return [...select.options].some(option=>option.value===String(value??''))}
function rasterizerFormValues(){return{material_choice:document.querySelector('#materialChoice').value,material_name:document.querySelector('#materialName').value,pixel_square_mm:document.querySelector('#pixel').value,new_width:document.querySelector('#width').value,new_height:document.querySelector('#height').value,white_is:document.querySelector('#whiteIs').value,image_preset:document.querySelector('#imagePreset').value,filter_parameters:filterParameters(),geometry_style:effectiveGeometryStyle(),geometry_style_parameters:geometryStyleParameters(),panel_tiling:panelTilingPreferenceValues(),...colorMatchingParameters(),cut_mode:document.querySelector('#rasterHoloCutMode').value,preserve_black_outlines:document.querySelector('#rasterHoloBlack').checked}}
function restoreRasterizerForm(values,restoreMaterial=true){if(!values)return;if(restoreMaterial&&values.material_name!==undefined)document.querySelector('#materialName').value=values.material_name;for(const [id,key] of [['pixel','pixel_square_mm'],['width','new_width'],['height','new_height']])if(values[key]!==undefined)document.querySelector('#'+id).value=values[key];if(hasOption(document.querySelector('#whiteIs'),values.white_is))document.querySelector('#whiteIs').value=values.white_is;const preset=document.querySelector('#imagePreset');if(hasOption(preset,values.image_preset)){preset.value=values.image_preset;renderFilter();for(const [name,value] of Object.entries(values.filter_parameters||{})){const input=[...document.querySelectorAll('#filterControls [data-parameter]')].find(item=>item.dataset.parameter===name);if(!input)continue;if(input.type==='checkbox')input.checked=Boolean(value);else{input.value=value;input.oninput?.()}}}restoreGeometryControls(values);const matching=document.querySelector('#colorMatchingMode');if(hasOption(matching,values.color_matching_mode))matching.value=values.color_matching_mode;for(const [name,key] of [['Hue','color_matching_hue_weight'],['Saturation','color_matching_saturation_weight'],['Lightness','color_matching_lightness_weight']])if(values[key]!==undefined)setMatchingControl(name,values[key]);updateColorMatchingPresentation();if(hasOption(document.querySelector('#rasterHoloCutMode'),values.cut_mode))document.querySelector('#rasterHoloCutMode').value=values.cut_mode;document.querySelector('#rasterHoloBlack').checked=Boolean(values.preserve_black_outlines)&&!document.querySelector('#rasterHoloBlack').disabled;restorePanelTiling(values)}
function holographicArtworkFormValues(){return{recipe_id:document.querySelector('#holoRecipe').value,material_library_id:document.querySelector('#holoMaterial').value,max_dimension:document.querySelector('#holoDimension').value,pixel_mm:document.querySelector('#holoPixel').value,cut_mode:document.querySelector('#holoCutMode').value,preserve_black_outlines:document.querySelector('#holoBlack').checked}}
function restoreHolographicArtworkForm(values){if(!values)return;for(const [id,key] of [['holoRecipe','recipe_id'],['holoMaterial','material_library_id'],['holoCutMode','cut_mode']]){const select=document.querySelector('#'+id);if(hasOption(select,values[key]))select.value=values[key]}for(const [id,key] of [['holoDimension','max_dimension'],['holoPixel','pixel_mm']])if(values[key]!==undefined)document.querySelector('#'+id).value=values[key];document.querySelector('#holoBlack').checked=Boolean(values.preserve_black_outlines)}
configurePaletteResources({
  getAccountResources:()=>accountResources,
  setAccountResources:value=>{accountResources=value},
  getUploadedHolographicProfile:()=>uploadedHolographicProfile,
  setUploadedHolographicProfile:value=>{uploadedHolographicProfile=value},
  isGuest:()=>guestMode,
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
function renderFilter(){const preset=PRESETS[document.querySelector('#imagePreset').value],box=document.querySelector('#filterControls');document.querySelector('#filterDescription').textContent=preset.description;box.replaceChildren();for(const [name,value] of preset.toggles||[]){const label=document.createElement('label');label.innerHTML=`<span>${friendly(name)}</span><input type="checkbox" data-parameter="${name}" ${value?'checked':''}>`;box.append(label)}for(const [name,value,options] of preset.selects||[]){const row=document.createElement('div'),label=document.createElement('label'),select=document.createElement('select');label.textContent=friendly(name);select.dataset.parameter=name;select.setAttribute('aria-label',friendly(name));for(const [optionValue,optionLabel] of options)select.add(new Option(optionLabel,optionValue,false,optionValue===value));row.className='filter-control';row.append(label,select);box.append(row)}for(const [name,value,min,max,step] of preset.controls){const row=document.createElement('div'),settingLabel=name==='abstraction'?'Overall recognizability':friendly(name);row.className='filter-control';row.setAttribute('role','group');row.setAttribute('aria-label',settingLabel);row.innerHTML=`<label><span>${settingLabel}</span><input type="number" value="${value}" min="${min}" max="${max}" step="${step}" aria-label="${settingLabel} value"></label><input type="range" data-parameter="${name}" value="${value}" min="${min}" max="${max}" step="${step}" aria-label="${settingLabel} slider">`;const number=row.querySelector('input[type=number]'),range=row.querySelector('input[type=range]');number.oninput=()=>range.value=number.value;range.oninput=()=>number.value=range.value;if(name==='abstraction'){const endpoints=document.createElement('div');endpoints.className='spectrum-endpoints';endpoints.innerHTML='<span>Photorealistic</span><span>Abstract</span>';row.append(endpoints)}box.append(row)}document.querySelector('#randomizeFilter').classList.toggle('hidden',!preset.controls.length);syncColorMatchingAvailability()}
document.querySelector('#imagePreset').onchange=()=>{renderFilter();syncGeometryStyleAvailability();markQuantPreviewStale()};document.querySelector('#resetFilter').onclick=renderFilter;document.querySelector('#randomizeFilter').onclick=()=>{document.querySelectorAll('#filterControls input[type=range]').forEach(range=>{const steps=Math.floor((Number(range.max)-Number(range.min))/Number(range.step));range.value=Number(range.min)+Math.floor(Math.random()*(steps+1))*Number(range.step);range.oninput()})};configureGeometryControls({selectedRasterRecipe,visibleRasterPalette,selectedPaletteHexes,paletteDisplayName,esc,hasOption,getFauxlogramFlow,restoreFauxlogramFlow,resetFauxlogramFlow});renderFilter();renderGeometryControls();syncGeometryStyleAvailability();configurePanelTiling({previewSwatches,hasOption,effectiveArtworkFile,loadPreviewBitmap,markQuantPreviewStale});
const statusEl=document.querySelector('#status'), form=document.querySelector('#job'), holographicForm=document.querySelector('#holographicJob');
function show(message){statusEl.textContent=message}
function setAuthState(authenticated){guestMode=!authenticated;form.classList.remove('hidden');holographicForm.classList.toggle('hidden',!authenticated);document.querySelector('#guestNotice').classList.toggle('hidden',authenticated);window.stagingShellSetAuthenticated?.(authenticated)}
function clearAuth(){token=null;refreshToken=null;localStorage.removeItem('id_token');localStorage.removeItem('refresh_token');setAuthState(false)}
function tokenExpiresSoon(){try{const part=token.split('.')[1].replace(/-/g,'+').replace(/_/g,'/');const claims=JSON.parse(atob(part.padEnd(Math.ceil(part.length/4)*4,'=')));return Number(claims.exp||0)*1000<=Date.now()+30000}catch{return true}}
async function refreshSession(){
  if(!refreshToken)return false;
  const body=new URLSearchParams({grant_type:'refresh_token',client_id:config.client_id,refresh_token:refreshToken});
  const result=await fetch(`https://${config.cognito_domain}/oauth2/token`,{method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},body}).then(r=>r.json());
  if(!result.id_token){clearAuth();return false}token=result.id_token;localStorage.setItem('id_token',token);return true;
}
function esc(value){return String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]))}
function authHeaders(){return {'authorization':`Bearer ${token}`,'content-type':'application/json'}}
function swatchChip(entry,intent='color_palette'){
  const color=entry.display_hex||entry.hex||'#303842',rawAngle=Number(entry.angle??entry.settings?.angle??0),rawInterval=Number(entry.interval??entry.settings?.interval??.05),angle=(Number.isFinite(rawAngle)?rawAngle:0)+90,spacing=Math.max(3,Math.min(14,(Number.isFinite(rawInterval)&&rawInterval>0?rawInterval:.05)*120));
  const pattern=intent==='hatch_palette'?`;background-image:repeating-linear-gradient(${angle}deg,rgba(0,0,0,.88) 0 1px,rgba(255,255,255,.2) 1px 2px,transparent 2px ${spacing}px)`:'';
  return `<span class="swatch-chip" style="background-color:${color}${pattern}"></span><span class="swatch-name" title="${esc(entry.description||entry.name)}">${esc(entry.description||entry.name)}</span>`;
}
function readableLightBurnSnapshot(snapshot,depth=0){if(depth>4||!snapshot||Array.isArray(snapshot)||typeof snapshot!=='object')return false;const type=String(snapshot.type||''),settings=snapshot.settings;if(!type||type.length>40||!settings||Array.isArray(settings)||typeof settings!=='object'||Object.keys(settings).length>100)return false;for(const [name,value] of Object.entries(settings))if(!/^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(name)||value!==null&&typeof value==='object'||String(value).length>160)return false;const subLayers=snapshot.sub_layers||[];return Array.isArray(subLayers)&&subLayers.length<=20&&subLayers.every(layer=>readableLightBurnSnapshot(layer,depth+1))}
function readablePreservedBlack(setting){return !!setting&&typeof setting==='object'&&!Array.isArray(setting)&&readableLightBurnSnapshot(setting.laser_settings)}
function hexRgb(hex){const value=String(hex||'').replace('#','');return value.length===6?[parseInt(value.slice(0,2),16),parseInt(value.slice(2,4),16),parseInt(value.slice(4,6),16)]:null}
function rgbHsv([r,g,b]){r/=255;g/=255;b/=255;const max=Math.max(r,g,b),min=Math.min(r,g,b),delta=max-min;let h=0;if(delta){if(max===r)h=60*((g-b)/delta%6);else if(max===g)h=60*((b-r)/delta+2);else h=60*((r-g)/delta+4)}if(h<0)h+=360;return{h,s:max?delta/max:0,v:max}}
function rgbHsl([r,g,b]){r/=255;g/=255;b/=255;const max=Math.max(r,g,b),min=Math.min(r,g,b),delta=max-min,l=(max+min)/2;let h=0,s=0;if(delta){s=delta/(1-Math.abs(2*l-1));if(max===r)h=60*((g-b)/delta%6);else if(max===g)h=60*((b-r)/delta+2);else h=60*((r-g)/delta+4)}if(h<0)h+=360;return{h,s,l}}
function hueDelta(a,b){const difference=Math.abs(a-b);return Math.min(difference,360-difference)/180}
function previewSwatches(){const entries=visibleRasterPalette(),unique=new Map();for(const entry of entries){const key=String(entry.selection_key??entry.hex??'').toUpperCase(),hex=String(entry.display_hex||entry.hex||'').toUpperCase();if(!selectedPaletteHexes.has(key)||!/^#[0-9A-F]{6}$/.test(hex)||unique.has(hex))continue;const rgb=hexRgb(hex);unique.set(hex,{hex,rgb,hsv:rgbHsv(rgb),hsl:rgbHsl(rgb),name:paletteDisplayName(entry)})}return [...unique.values()]}
function matchingDistance(source,target,matching,space='hsv'){const hue=hueDelta(source.h,target.h);return matching.hue*hue*hue+matching.saturation*(source.s-target.s)**2+matching.lightness*(source[space==='hsv'?'v':'l']-target[space==='hsv'?'v':'l'])**2}
function quantizePreviewPixels(data,swatches,matching,whiteIs='engraved'){const counts=new Map(swatches.map(item=>[item.hex,0])),chromatic=swatches.filter(item=>item.hsv.v>=.15&&item.hsv.s>=.15),blue=swatches.filter(item=>item.hsl.h>=210&&item.hsl.h<=250&&item.hsl.s>=.15);for(let offset=0;offset<data.length;offset+=4){if(data[offset+3]===0||(whiteIs==='unengraved'&&data[offset]===255&&data[offset+1]===255&&data[offset+2]===255)){data[offset]=0;data[offset+1]=0;data[offset+2]=0;data[offset+3]=0;continue}const sourceRgb=[data[offset],data[offset+1],data[offset+2]],sourceHsv=rgbHsv(sourceRgb),sourceHsl=rgbHsl(sourceRgb);let assigned=swatches[0],best=Infinity;for(const swatch of swatches){const distance=(sourceRgb[0]-swatch.rgb[0])**2+(sourceRgb[1]-swatch.rgb[1])**2+(sourceRgb[2]-swatch.rgb[2])**2;if(distance<best){best=distance;assigned=swatch}}if(matching.mode!=='closest'&&assigned.hsv.v>=.15&&assigned.hsv.s<.15&&sourceHsv.s>=.45&&sourceHsv.v>=.15&&chromatic.length){best=Infinity;for(const swatch of chromatic){const distance=matchingDistance(sourceHsv,swatch.hsv,matching,'hsv');if(distance<best){best=distance;assigned=swatch}}}if(matching.mode!=='closest'&&blue.length>=2&&blue.includes(assigned)){best=Infinity;for(const swatch of blue){const distance=matchingDistance(sourceHsl,swatch.hsl,matching,'hsl');if(distance<best){best=distance;assigned=swatch}}}data[offset]=assigned.rgb[0];data[offset+1]=assigned.rgb[1];data[offset+2]=assigned.rgb[2];data[offset+3]=255;counts.set(assigned.hex,counts.get(assigned.hex)+1)}return counts}
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
  config=await fetch('config.json',{cache:'no-store'}).then(r=>r.json());
  const params=new URLSearchParams(location.search), code=params.get('code');
  const requestedTask=params.get('task')||sessionStorage.getItem('pending_task');
  if(code){
    const verifier=sessionStorage.getItem('pkce_verifier');
    const redirectUri=sessionStorage.getItem('pkce_redirect_uri')||new URL('/',location.origin).href;
    const discardCallback=()=>{sessionStorage.removeItem('pkce_verifier');sessionStorage.removeItem('pkce_redirect_uri');history.replaceState({},'',location.pathname)};
    if(!verifier){discardCallback();throw new Error('Sign-in attempt expired or opened in another tab. Please sign in again.');}
    const body=new URLSearchParams({grant_type:'authorization_code',client_id:config.client_id,code,redirect_uri:redirectUri,code_verifier:verifier});
    let result,response;
    try{response=await fetch(`https://${config.cognito_domain}/oauth2/token`,{method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},body});result=await response.json()}
    catch(error){discardCallback();throw new Error('Cognito sign-in could not reach the token service. Please sign in again.');}
    if(!response.ok||!result.id_token){const reason=result.error_description||result.error||`HTTP ${response.status}`;discardCallback();throw new Error(`Cognito sign-in could not complete (${reason}). Please sign in again.`)}
    sessionStorage.removeItem('pkce_verifier');sessionStorage.removeItem('pkce_redirect_uri');token=result.id_token;refreshToken=result.refresh_token||refreshToken;localStorage.setItem('id_token',token);if(refreshToken)localStorage.setItem('refresh_token',refreshToken);history.replaceState({},'',requestedTask?`${location.pathname}?task=${encodeURIComponent(requestedTask)}`:location.pathname);const postLoginPath=sessionStorage.getItem('post_login_path');if(postLoginPath&&postLoginPath!=='/'){sessionStorage.removeItem('post_login_path');location.replace(postLoginPath);return}
  }
  if(token&&tokenExpiresSoon()&&!await refreshSession())clearAuth();
  setAuthState(!!token);
  show(token?'Authenticated. Choose artwork and an output-settings option to run an isolated job.':'Guest access. Upload a Material Library or choose SVG-Only to run a temporary Rasterizer job.');
  if(token)await loadAccountResources();else await loadGuestResources();
  const resumedTask=new URLSearchParams(location.search).get('task')||requestedTask;
  if(token&&resumedTask){sessionStorage.removeItem('pending_task');currentTask=resumedTask;history.replaceState({},'',`${location.pathname}?task=${encodeURIComponent(currentTask)}`);document.querySelector('#submit').disabled=true;document.querySelector('#activity').classList.remove('hidden');poll()}
}
function userFacingStyleError(message){const raw=String(message||''),value=raw.replace(/^ValueError:\s*/,'');return /^(?:Image style|Geometry style|Abstract filter) settings are not valid JSON$|^Invalid (?:abstract filter|geometry style) parameters:/.test(value)?"We couldn't read these style settings. Reload Rasterizer, choose the style again, and resubmit. If it keeps happening, report the problem.":raw}
function jobAccessErrorMessage(message){if(message==='Task not found'&& !guestMode)return "This job isn't available to this session. It may have expired or been deleted, or it may belong to another account. Check that you're signed into the right account; otherwise, start a new job.";if(message==='Guest task not found or access expired'&&guestMode)return "This guest job isn't available. Guest access lasts 24 hours, and the job may also have been deleted. If it's recent, try the original browser tab; otherwise, start a new job.";return message}
async function api(path,options={},retryAuth=true){const r=await fetch(config.api_url+path,{...options,headers:{...authHeaders(),...(options.headers||{})}});const data=await r.json();if(r.status===401&&retryAuth&&await refreshSession())return api(path,options,false);if(r.status===401){clearAuth();throw new Error('Session expired. Sign in again.')}if(!r.ok)throw new Error(userFacingStyleError(data.message||`HTTP ${r.status}`));return data}
async function guestApi(path,options={}){const headers={'content-type':'application/json',...(options.headers||{})};if(guestAccessToken)headers['x-guest-capability']=guestAccessToken;const r=await fetch(config.api_url+path,{...options,headers});const data=await r.json();if(!r.ok)throw new Error(userFacingStyleError(data.message||`HTTP ${r.status}`));return data}
const poll=createRasterJobPoller({
  getCurrentTask:()=>currentTask,
  isGuest:()=>guestMode,
  guestApi,
  api,
  show,
  userFacingStyleError,
  jobAccessErrorMessage,
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
document.querySelector('#colorMatchingMode').onchange=updateColorMatchingPresentation;
for(const name of ['Hue','Saturation','Lightness']){const range=document.querySelector(`#matching${name}`),number=document.querySelector(`#matching${name}Number`);range.oninput=()=>{number.value=range.value;markQuantPreviewStale()};number.oninput=()=>{setMatchingControl(name,number.value);markQuantPreviewStale()}}
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
  isGuest:()=>guestMode,getCropSelection,applyArtworkCrop,effectiveArtworkFile,
  getSelectedPaletteHexes:()=>selectedPaletteHexes,selectedAsset,getUploadedHolographicProfile:()=>uploadedHolographicProfile,
  guestApi,api,setGuestAccessToken:value=>{guestAccessToken=value;sessionStorage.setItem('guest_access_token',value)},
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
