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
  base64ToBytes,
  drawShapePreview,
  drawSvgPreview,
  normalizeShapeImage,
  normalizeShapeSvg,
} from './rasterizer/shape-assets-v1.js';

let config, token=localStorage.getItem('id_token')||sessionStorage.getItem('id_token'), refreshToken=localStorage.getItem('refresh_token')||sessionStorage.getItem('refresh_token'), currentTask, pollTimer, accountResources, guestMode=!token, guestAccessToken=sessionStorage.getItem('guest_access_token'), uploadedHolographicProfile=null, flowBitmap=null, flowTool='paint', flowDrawing=null, flowActiveRegion=0, customGlyphMask=null, customGlyphSvg=null, customCellSvg=null;
const FLOW_COLORS=['#65d46e','#58b7ff','#ffb347','#e66fff','#ff637d','#50dbc8','#d8d85a','#b69cff'];
const newFlowRegion=(index,regionType='painted')=>({name:`${regionType==='image_mask'?'Image mask':'Painted region'} ${index+1}`,region_type:regionType,scope:'combined_region',guide_type:'linear',orientation:'parallel',start:[.25,.5],end:[.75,.5],gradient_start:165,gradient_end:90,curve:1,fixed_angle:0,angle_offset:0,reverse:false,mask:null,mask_name:'',mask_mode:'grayscale',mask_threshold:.01,mask_invert:false,mask_offset:[0,0]});
let fauxlogramFlow={enabled:false,regions:[newFlowRegion(0)],strokes:[]};
if(token)localStorage.setItem('id_token',token);if(refreshToken)localStorage.setItem('refresh_token',refreshToken);sessionStorage.removeItem('id_token');sessionStorage.removeItem('refresh_token');
const geometryRouteAssignments=new Map();
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
const GLYPH_GEOMETRY={selects:[['glyph_shape','diamond',[['circle','Circle'],['square','Square'],['diamond','Diamond'],['triangle','Triangle'],['hexagon','Hexagon'],['octagon','Octagon'],['star','Star'],['cross','Cross'],['bar','Bar'],['skull','Skull'],['heart','Heart'],['space_invader','Space Invader'],['ghost','Ghost'],['bat','Bat'],['alien_head','Alien Head'],['paw_print','Paw Print'],['fish_scale','Fish Scale'],['puzzle_piece','Puzzle Piece'],['mixed','Mixed Shapes'],['custom','Custom Uploaded Glyph']]],['glyph_size_source','source_brightness',[['source_brightness','Source Brightness'],['seeded_variation','Seeded Variation']]]],toggles:[['black_only',false],['invert',false],['invert_fill',false],['tight_pack_geometry',false],['random_rotation',false]],controls:[['cell_size_mm',.6,.2,5,.05],['minimum_glyph_ratio',.48,.16,.8,.01],['maximum_glyph_ratio',.97,.94,1,.01],['non_black_glyph_density',2.3,.6,4,.05],['tone_curve',.75,.2,1.3,.05],['contrast',2,1,3,.05],['grid_angle',-45,-90,0,1],['glyph_rotation',0,-180,180,1],['seed',1,0,999999,1]]};
const HALFTONE_GEOMETRY={description:'Rebuilds the prepared color regions as a shared newsprint matrix of circles or squares. Dot Size Source can preserve source-image tone or produce a repeatable seeded distribution within the selected size range. Black Only creates a conventional monochrome halftone; Choose by swatch keeps Halftone output on each routed swatch instead.',selects:[['dot_size_source','source_brightness',[['source_brightness','Source Brightness'],['seeded_variation','Seeded Variation']]]],toggles:[['black_only',false],['square_dots',false],['invert',false],['tight_pack_geometry',false]],controls:[['cell_size_mm',.6,.2,1,.05],['minimum_dot_ratio',.48,.16,.8,.01],['maximum_dot_ratio',.97,.94,1,.01],['non_black_dot_density',2.3,.6,4,.05],['tone_curve',.75,.2,1.3,.05],['contrast',2,1,3,.05],['grid_angle',-45,-90,0,1],['seed',1,0,999999,1]]};
const ROUTED_HALFTONE_GEOMETRY={...HALFTONE_GEOMETRY,toggles:HALFTONE_GEOMETRY.toggles.filter(([name])=>name!=='black_only')};
const KRASNOW_GEOMETRY={description:'Builds calibrated open parallel-line cells across the prepared artwork. Preserve Black keeps source Black as normal Black geometry; otherwise Black is rebuilt as gratings like other swatches. Cell Shape supports regular, decorative, and custom SVG cells. Tight Pack Geometry reduces empty space, while Random Rotation gives cells repeatable independent orientations. This requires a Fauxlographic Cut Setting in the selected palette; its main layer settings are cloned onto the generated LightBurn carrier layers. Explicit Lines preserves full-resolution vector gratings. LightBurn Fill is experimental and lets LightBurn generate lines using Line Spacing as its uniform Fill interval. Fauxlogram Gradient Scope and Direction control how carrier progression is evaluated.',selects:[['grating_render_mode','line',[['line','Explicit Lines'],['fill','LightBurn Fill (Experimental)']]],['cell_shape','square',[['square','Square'],['hexagon','Hexagon'],['triangle','Triangle'],['diamond','Diamond / Rhombus'],['skull','Skull'],['heart','Heart'],['space_invader','Space Invader'],['ghost','Ghost'],['bat','Bat'],['alien_head','Alien Head'],['paw_print','Paw Print'],['fish_scale','Fish Scale'],['puzzle_piece','Puzzle Piece'],['custom','Custom SVG']]],['fauxlogram_gradient_scope','entire_artwork',[['entire_artwork','Entire Artwork'],['each_shape','Each Shape']]],['fauxlogram_gradient_direction','top_to_bottom',[['top_to_bottom','Top to Bottom'],['bottom_to_top','Bottom to Top'],['left_to_right','Left to Right'],['right_to_left','Right to Left'],['center_to_edge','Center to Edge (Radial)'],['edge_to_center','Edge to Center (Radial)']]]],toggles:[['preserve_black',true],['tight_pack_geometry',false],['random_rotation',false]],controls:[['speed_spread',1,0,2,.001],['gradient_top',165,0,255,1],['gradient_bottom',90,0,255,1],['gradient_curve',1,.2,5,.05],['hue_rotation',.13,0,1,.01],['saturation_cutoff',.2,0,1,.01],['patch_size_mm',.4,.1,5,.05],['line_spacing_mm',.06,.01,.5,.005],['hue_line_spacing_minimum_mm',.06,.01,.5,.001],['hue_line_spacing_maximum_mm',.06,.01,.5,.001],['angle_min',-90,-180,180,1],['angle_max',90,-180,180,1]]};
const SPECIALIZED_GEOMETRY_PRESETS=new Set(['abstract_optical_color_mix']);
const friendly=name=>name.split('_').map(word=>word[0].toUpperCase()+word.slice(1)).join(' ');
function filterParameters(){return Object.fromEntries([...document.querySelectorAll('#filterControls [data-parameter]')].map(input=>[input.dataset.parameter,input.type==='checkbox'?Number(input.checked):input.tagName==='SELECT'?input.value:Number(input.value)]))}
function geometryStyleCompatible(){return !selectedRasterRecipe()&&!SPECIALIZED_GEOMETRY_PRESETS.has(document.querySelector('#imagePreset').value)}
function effectiveGeometryStyle(){return geometryStyleCompatible()?document.querySelector('#geometryStyle').value:'vectors'}
function geometryStyleConfiguration(){return effectiveGeometryStyle()==='glyphs'?GLYPH_GEOMETRY:effectiveGeometryStyle()==='halftone_newsprint'?HALFTONE_GEOMETRY:effectiveGeometryStyle()==='krasnow_grating'?KRASNOW_GEOMETRY:null}
function geometryControlValues(selector){const values=Object.fromEntries([...document.querySelectorAll(`${selector} [data-geometry-parameter]`)].map(input=>[input.dataset.geometryParameter,input.type==='checkbox'?Number(input.checked):input.tagName==='SELECT'?input.value:Number(input.value)]));if(values.glyph_shape==='custom'){if(customGlyphSvg)values.custom_glyph_svg=structuredClone(customGlyphSvg);else if(customGlyphMask)values.custom_glyph_mask=structuredClone(customGlyphMask)}if(values.cell_shape==='custom'&&customCellSvg)values.custom_cell_svg=structuredClone(customCellSvg);return values}
function flowHasContent(){return fauxlogramFlow.strokes.some(stroke=>!stroke.erase)||fauxlogramFlow.regions.some(region=>region.mask)}
function krasnowGeometryValues(){const values=geometryControlValues('#routedKrasnowControls');if(fauxlogramFlow.enabled&&flowHasContent())values.fauxlogram_flow=structuredClone(fauxlogramFlow);return values}
function geometryStyleParameters(){const style=effectiveGeometryStyle();if(style==='by_swatch'){const assignments=Object.fromEntries([...document.querySelectorAll('#geometryRoutingGrid [data-route-style]')].map(input=>[input.dataset.hex,input.value])),used=new Set(Object.values(assignments)),parameters={assignments};if(used.has('glyphs'))parameters.glyphs=geometryControlValues('#routedGlyphControls');if(used.has('halftone_newsprint'))parameters.halftone_newsprint=geometryControlValues('#routedHalftoneControls');if(used.has('krasnow_grating'))parameters.krasnow_grating=krasnowGeometryValues();return parameters}if(style==='glyphs')return geometryControlValues('#routedGlyphControls');if(style==='halftone_newsprint')return geometryControlValues('#routedHalftoneControls');if(style==='krasnow_grating')return krasnowGeometryValues();return{}}
function buildGeometryControls(box,configuration){
  box.replaceChildren();
  if(!configuration)return;
  for(const [name,value] of configuration.toggles||[]){
    const label=document.createElement('label');
    label.innerHTML=`<span>${friendly(name)}</span><input type="checkbox" data-geometry-parameter="${name}" ${value?'checked':''}>`;
    box.append(label);
  }
  for(const [name,value,options] of configuration.selects||[]){
    const row=document.createElement('div'),label=document.createElement('label'),select=document.createElement('select');
    label.textContent=friendly(name);select.dataset.geometryParameter=name;select.setAttribute('aria-label',friendly(name));
    for(const [optionValue,optionLabel] of options)select.add(new Option(optionLabel,optionValue,false,optionValue===value));
    row.className='filter-control';row.append(label,select);box.append(row);
  }
  for(const [name,value,min,max,step] of configuration.controls||[]){
    const row=document.createElement('div'),settingLabel=name==='gradient_top'?'Fauxlogram Gradient Start':name==='gradient_bottom'?'Fauxlogram Gradient End':friendly(name);
    row.className='filter-control';row.setAttribute('role','group');row.setAttribute('aria-label',settingLabel);
    row.innerHTML=`<label><span>${settingLabel}</span><input type="number" value="${value}" min="${min}" max="${max}" step="${step}" aria-label="${settingLabel} value"></label><input type="range" data-geometry-parameter="${name}" value="${value}" min="${min}" max="${max}" step="${step}" aria-label="${settingLabel} slider">`;
    const number=row.querySelector('input[type=number]'),range=row.querySelector('input[type=range]');
    number.oninput=()=>range.value=number.value;range.oninput=()=>number.value=range.value;box.append(row);
  }
  if(configuration===GLYPH_GEOMETRY){
    const panel=document.createElement('section');
    panel.className='custom-shape-panel';panel.hidden=true;
    panel.innerHTML=`<h4>Custom glyph</h4><p class="custom-shape-status">Upload an SVG, PNG, JPEG, or WebP. SVG files retain their closed vector paths.</p><input type="file" accept=".svg,image/svg+xml,image/png,image/jpeg,image/webp" data-custom-glyph-file><canvas class="custom-shape-preview" width="96" height="96" aria-label="Custom glyph preview"></canvas><div data-raster-glyph-options><label><span>Threshold</span><input type="range" min="0" max="1" step="0.01" value="0.5" data-geometry-parameter="custom_glyph_threshold"></label><label><span>Invert Custom Glyph</span><input type="checkbox" data-geometry-parameter="custom_glyph_invert"></label></div><label><span>Padding</span><input type="range" min="0" max="0.3" step="0.01" value="0.06" data-geometry-parameter="custom_glyph_padding"></label><button type="button" data-remove-custom-glyph>Remove uploaded glyph</button>`;
    box.append(panel);
    const glyphSelect=box.querySelector('[data-geometry-parameter="glyph_shape"]'),file=panel.querySelector('[data-custom-glyph-file]'),status=panel.querySelector('.custom-shape-status'),preview=panel.querySelector('canvas'),invert=panel.querySelector('[data-geometry-parameter="custom_glyph_invert"]'),padding=panel.querySelector('[data-geometry-parameter="custom_glyph_padding"]'),rasterOptions=panel.querySelector('[data-raster-glyph-options]');
    const sync=async()=>{panel.hidden=glyphSelect.value!=='custom';rasterOptions.hidden=Boolean(customGlyphSvg);preview.getContext('2d').clearRect(0,0,preview.width,preview.height);if(customGlyphSvg){try{await drawSvgPreview(preview,customGlyphSvg,Number(padding.value));status.textContent=`Custom SVG ready: ${customGlyphSvg.name}.`}catch(error){status.textContent=error.message}}else if(customGlyphMask){drawShapePreview(preview,customGlyphMask,Boolean(invert.checked),Number(padding.value));status.textContent=`Custom image ready (${customGlyphMask.width} × ${customGlyphMask.height}).`}else status.textContent='Upload an SVG, PNG, JPEG, or WebP. SVG files retain their closed vector paths.'};
    glyphSelect.addEventListener('change',sync);invert.addEventListener('change',sync);padding.addEventListener('input',sync);
    file.onchange=async()=>{try{const selected=file.files[0];if(selected?.type==='image/svg+xml'||selected?.name?.toLowerCase().endsWith('.svg')){customGlyphSvg=await normalizeShapeSvg(selected);customGlyphMask=null}else{customGlyphMask=await normalizeShapeImage(selected);customGlyphSvg=null}await sync()}catch(error){customGlyphMask=null;customGlyphSvg=null;await sync();status.textContent=error.message}};
    panel.querySelector('[data-remove-custom-glyph]').onclick=()=>{customGlyphMask=null;customGlyphSvg=null;file.value='';sync()};sync();
  }
  if(configuration===KRASNOW_GEOMETRY){
    const panel=document.createElement('section');
    panel.className='custom-shape-panel';panel.hidden=true;
    panel.innerHTML=`<h4>Custom cell shape</h4><p class="custom-shape-status">Upload an SVG made from one or more closed vector paths. Open paths, text, images, scripts, and linked content are not supported.</p><input type="file" accept=".svg,image/svg+xml" data-custom-cell-file><canvas class="custom-shape-preview" width="96" height="96" aria-label="Custom cell preview"></canvas><label><span>Padding</span><input type="range" min="0" max="0.3" step="0.01" value="0.06" data-geometry-parameter="custom_cell_padding"></label><button type="button" data-remove-custom-cell>Remove uploaded cell</button>`;
    box.append(panel);
    const cellSelect=box.querySelector('[data-geometry-parameter="cell_shape"]'),file=panel.querySelector('[data-custom-cell-file]'),status=panel.querySelector('.custom-shape-status'),preview=panel.querySelector('canvas'),padding=panel.querySelector('[data-geometry-parameter="custom_cell_padding"]');
    const sync=async()=>{panel.hidden=cellSelect.value!=='custom';preview.getContext('2d').clearRect(0,0,preview.width,preview.height);if(customCellSvg){try{await drawSvgPreview(preview,customCellSvg,Number(padding.value));status.textContent=`Custom SVG ready: ${customCellSvg.name}.`}catch(error){status.textContent=error.message}}else status.textContent='Upload an SVG made from one or more closed vector paths. Open paths, text, images, scripts, and linked content are not supported.'};
    cellSelect.addEventListener('change',sync);padding.addEventListener('input',sync);
    file.onchange=async()=>{try{customCellSvg=await normalizeShapeSvg(file.files[0]);await sync()}catch(error){customCellSvg=null;await sync();status.textContent=error.message}};
    panel.querySelector('[data-remove-custom-cell]').onclick=()=>{customCellSvg=null;file.value='';sync()};sync();
  }
  const renderMode=box.querySelector('[data-geometry-parameter="grating_render_mode"]');
  if(renderMode){const syncRenderMode=()=>{const nativeFill=renderMode.value==='fill';for(const name of ['hue_line_spacing_minimum_mm','hue_line_spacing_maximum_mm']){const control=box.querySelector(`[data-geometry-parameter="${name}"]`);if(control)control.closest('.filter-control').hidden=nativeFill}};renderMode.addEventListener('change',syncRenderMode);syncRenderMode()}
  const invertFill=box.querySelector('[data-geometry-parameter="invert_fill"]');if(invertFill)invertFill.onchange=()=>syncGeometryToggleCompatibility(box);syncGeometryToggleCompatibility(box);
}
function syncGeometryToggleCompatibility(box=document.querySelector('#geometryStyleControls')){const invertFill=box.querySelector('[data-geometry-parameter="invert_fill"]'),blackOnly=box.querySelector('[data-geometry-parameter="black_only"]');if(!invertFill||!blackOnly)return;if(invertFill.checked)blackOnly.checked=false;blackOnly.disabled=invertFill.checked;blackOnly.closest('label')?.classList.toggle('disabled',invertFill.checked)}
function routedPaletteEntries(){const unique=new Map();for(const item of visibleRasterPalette()){const key=String(item.selection_key??item.hex).toUpperCase(),hex=String(item.hex||item.display_hex||'').toUpperCase();if(!selectedPaletteHexes.has(key)||!/^#[0-9A-F]{6}$/.test(hex)||unique.has(hex))continue;unique.set(hex,{hex,name:paletteDisplayName(item)})}return [...unique.values()]}
function syncRoutedSettingsVisibility(){const style=effectiveGeometryStyle(),styles=style==='by_swatch'?new Set([...document.querySelectorAll('#geometryRoutingGrid [data-route-style]')].map(input=>input.value)):new Set([style]);document.querySelector('#routedGlyphSettings').hidden=!styles.has('glyphs');document.querySelector('#routedHalftoneSettings').hidden=!styles.has('halftone_newsprint');document.querySelector('#routedKrasnowSettings').hidden=!styles.has('krasnow_grating')}
function renderGeometryRouting(){const grid=document.querySelector('#geometryRoutingGrid');if(!document.querySelector('#routedGlyphControls').childElementCount)buildGeometryControls(document.querySelector('#routedGlyphControls'),GLYPH_GEOMETRY);if(!document.querySelector('#routedHalftoneControls').childElementCount)buildGeometryControls(document.querySelector('#routedHalftoneControls'),ROUTED_HALFTONE_GEOMETRY);if(!document.querySelector('#routedKrasnowControls').childElementCount)buildGeometryControls(document.querySelector('#routedKrasnowControls'),KRASNOW_GEOMETRY);grid.innerHTML=routedPaletteEntries().map(item=>{const fixed=item.hex==='#000000',style=fixed?'vectors':geometryRouteAssignments.get(item.hex)||'vectors';geometryRouteAssignments.set(item.hex,style);return `<label class="geometry-route-card ${fixed?'fixed':''}"><input type="checkbox" data-route-selected ${fixed?'disabled':''}><span class="geometry-route-chip" style="--swatch-color:${esc(item.hex)}"></span><strong title="${esc(item.name)}">${esc(item.name)}</strong><select data-route-style data-hex="${esc(item.hex)}" aria-label="Geometry for ${esc(item.name)}" ${fixed?'disabled':''}><option value="vectors" ${style==='vectors'?'selected':''}>Vectors</option><option value="glyphs" ${style==='glyphs'?'selected':''}>Glyphs</option><option value="halftone_newsprint" ${style==='halftone_newsprint'?'selected':''}>Halftone</option><option value="krasnow_grating" ${style==='krasnow_grating'?'selected':''}>Krasnow</option></select></label>`}).join('');syncRoutedSettingsVisibility()}
function renderGeometryControls(reset=false){const box=document.querySelector('#geometryStyleControls'),style=effectiveGeometryStyle();box.dataset.style=style;if((reset||!document.querySelector('#routedGlyphControls').childElementCount)&&style==='glyphs')buildGeometryControls(document.querySelector('#routedGlyphControls'),GLYPH_GEOMETRY);if((reset||!document.querySelector('#routedHalftoneControls').childElementCount)&&style==='halftone_newsprint')buildGeometryControls(document.querySelector('#routedHalftoneControls'),HALFTONE_GEOMETRY);if((reset||!document.querySelector('#routedKrasnowControls').childElementCount)&&style==='krasnow_grating')buildGeometryControls(document.querySelector('#routedKrasnowControls'),KRASNOW_GEOMETRY);if(style==='by_swatch')renderGeometryRouting();syncRoutedSettingsVisibility()}
function applyGeometryValues(box,values){
  if(values?.fauxlogram_flow){
    fauxlogramFlow=JSON.parse(JSON.stringify(values.fauxlogram_flow));
    // Existing mask-only plans predate region types. Upgrade them without
    // changing mixed painted-and-masked regions or silhouette guidance.
    fauxlogramFlow.regions?.forEach((region,index)=>{
      if(region.mask&&region.region_type!=='image_mask'&&!fauxlogramFlow.strokes?.some(stroke=>stroke.region===index))region.region_type='image_mask';
    });
    flowActiveRegion=0;updateFlowSummary();
  }
  if(values?.custom_glyph_mask)customGlyphMask=JSON.parse(JSON.stringify(values.custom_glyph_mask));
  if(values?.custom_glyph_svg)customGlyphSvg=JSON.parse(JSON.stringify(values.custom_glyph_svg));
  if(values?.custom_cell_svg)customCellSvg=JSON.parse(JSON.stringify(values.custom_cell_svg));
  for(const [name,value] of Object.entries(values||{})){const input=[...box.querySelectorAll('[data-geometry-parameter]')].find(item=>item.dataset.geometryParameter===name);if(!input)continue;if(input.type==='checkbox')input.checked=Boolean(value);else{input.value=value;input.oninput?.()}}
  box.querySelector('[data-geometry-parameter="glyph_shape"]')?.dispatchEvent(new Event('change'));
  box.querySelector('[data-geometry-parameter="cell_shape"]')?.dispatchEvent(new Event('change'));
  syncGeometryToggleCompatibility(box)
}
function syncGeometryStyleAvailability(){const section=document.querySelector('#geometryStyleSection'),compatible=geometryStyleCompatible(),style=effectiveGeometryStyle(),configuration=geometryStyleConfiguration(),controls=document.querySelector('#geometryStyleControls'),routing=document.querySelector('#geometryRouting');section.classList.toggle('hidden',!compatible);controls.hidden=true;routing.hidden=style!=='by_swatch';document.querySelector('#geometryStyleActions').hidden=!configuration;if(controls.dataset.style!==style||style==='by_swatch')renderGeometryControls();else syncRoutedSettingsVisibility();document.querySelector('#geometryStyleDescription').textContent=style==='glyphs'?'Rebuild the filtered color regions on a shared matrix using solid glyphs. Invert Fill keeps the vectors and cuts glyph-shaped holes from their owning layers. Every output layer is made mutually exclusive before export.':style==='halftone_newsprint'?HALFTONE_GEOMETRY.description:style==='krasnow_grating'?KRASNOW_GEOMETRY.description:style==='by_swatch'?'Route each enabled palette swatch independently to normal vectors, Glyphs, Halftone Newsprint, or Krasnow Grating. Each source region receives exactly one treatment.':'Keep the selected Image Style’s ordinary continuous vector geometry.'}
function updateFlowSummary(){const painted=fauxlogramFlow.strokes.filter(stroke=>!stroke.erase).length,masks=fauxlogramFlow.regions.filter(region=>region.mask).length,summary=document.querySelector('#flowPainterSummary');summary.textContent=fauxlogramFlow.enabled&&(painted||masks)?`${fauxlogramFlow.regions.length} flow region${fauxlogramFlow.regions.length===1?'':'s'} · ${painted} painted shape${painted===1?'':'s'} · ${masks} image mask${masks===1?'':'s'} · unassigned cells use the standard gradient.`:'Optional: paint regions or upload masks that use their own gradient and grating direction.'}
function resetFauxlogramFlow(){fauxlogramFlow={enabled:false,regions:[newFlowRegion(0)],strokes:[]};flowActiveRegion=0;updateFlowSummary()}
function flowPoint(event){const canvas=document.querySelector('#flowCanvas'),rect=canvas.getBoundingClientRect();return[Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)),Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height))]}
function resizeFlowCanvas(){if(!flowBitmap)return;const canvas=document.querySelector('#flowCanvas'),wrap=canvas.closest('.flow-canvas-wrap'),availableWidth=Math.max(1,wrap.clientWidth-2),availableHeight=Math.max(1,wrap.clientHeight-2),scale=Math.min(availableWidth/flowBitmap.width,availableHeight/flowBitmap.height),width=Math.max(1,Math.floor(flowBitmap.width*scale)),height=Math.max(1,Math.floor(flowBitmap.height*scale));if(canvas.width!==width||canvas.height!==height){canvas.width=width;canvas.height=height}drawFlowPainter()}
function activeFlowRegion(){return fauxlogramFlow.regions[flowActiveRegion]||fauxlogramFlow.regions[0]}
function syncFlowRegionEditor(){
  const select=document.querySelector('#flowRegion');
  select.replaceChildren(...fauxlogramFlow.regions.map((region,index)=>new Option(region.name,String(index),false,index===flowActiveRegion)));
  const region=activeFlowRegion(),imageRegion=region.region_type==='image_mask',grayscaleImage=imageRegion&&(region.mask_mode||'grayscale')==='grayscale';
  document.querySelector('#flowScope').value=region.scope;
  document.querySelector('#flowGuideType').value=region.guide_type;
  document.querySelector('#flowOrientation').value=region.orientation;
  document.querySelector('#flowGradientStart').value=region.gradient_start;
  document.querySelector('#flowGradientEnd').value=region.gradient_end;
  document.querySelector('#flowCurve').value=region.curve;
  document.querySelector('#flowFixedAngle').value=region.fixed_angle;
  document.querySelector('#flowAngleOffset').value=region.angle_offset;
  document.querySelector('#flowReverse').checked=Boolean(region.reverse);
  document.querySelector('#flowMaskMode').value=region.mask_mode||'silhouette';
  document.querySelector('#flowMaskThreshold').value=region.mask_threshold??.5;
  document.querySelector('#flowMaskInvert').checked=Boolean(region.mask_invert);
  document.querySelector('#flowMaskStatus').textContent=region.mask?`${region.mask_name||'Image mask'} is attached to this region (${region.mask.width} × ${region.mask.height}).`:'Upload a mask to activate this region.';
  document.querySelector('#flowRemoveMask').disabled=!region.mask;
  document.querySelector('#flowDeleteRegion').disabled=fauxlogramFlow.regions.length===1&&!imageRegion;
  document.querySelector('.flow-mask-panel').hidden=!imageRegion&&!region.mask;
  document.querySelector('#flowBrush').closest('label').hidden=imageRegion;
  document.querySelector('#flowScope').closest('label').hidden=grayscaleImage;
  document.querySelector('#flowGuideType').closest('label').hidden=grayscaleImage;
  document.querySelector('#flowFixedAngle').closest('label').firstChild.textContent=grayscaleImage?'Flat-area fallback angle':'Fixed angle';
  document.querySelector('.flow-help').textContent=grayscaleImage?'This mask is its own region. Brightness sets its gradient; tonal changes set grating direction. Flat areas use the fallback angle, not a painted-region guide. Place multiple masks independently; if they overlap, the later region takes precedence.':imageRegion?'This silhouette is its own region. Its active pixels select the area; the guide sets the gradient inside it. Move each mask independently.':'Paint a region and move its guide to set the gradient. Add an image-mask region to use an uploaded image independently.';
  const allowed=imageRegion?(grayscaleImage?['move']:['move','guide']):region.mask?['paint','erase','guide','move']:['paint','erase','guide'];
  for(const button of document.querySelectorAll('[data-flow-tool]'))button.hidden=!allowed.includes(button.dataset.flowTool);
  if(!allowed.includes(flowTool))setFlowTool(imageRegion?(grayscaleImage?'move':'guide'):'paint');
  document.querySelector('#flowMaskFile').value='';
  drawFlowPainter();
}
function saveFlowRegionEditor(){const region=activeFlowRegion();if(!region)return;region.scope=document.querySelector('#flowScope').value;region.guide_type=document.querySelector('#flowGuideType').value;region.orientation=document.querySelector('#flowOrientation').value;region.gradient_start=Math.max(0,Math.min(255,Number(document.querySelector('#flowGradientStart').value)||0));region.gradient_end=Math.max(0,Math.min(255,Number(document.querySelector('#flowGradientEnd').value)||0));region.curve=Math.max(.2,Math.min(5,Number(document.querySelector('#flowCurve').value)||1));region.fixed_angle=Math.max(-180,Math.min(180,Number(document.querySelector('#flowFixedAngle').value)||0));region.angle_offset=Math.max(-180,Math.min(180,Number(document.querySelector('#flowAngleOffset').value)||0));region.reverse=document.querySelector('#flowReverse').checked;region.mask_mode=document.querySelector('#flowMaskMode').value;region.mask_threshold=Math.max(0,Math.min(1,Number(document.querySelector('#flowMaskThreshold').value)||0));region.mask_invert=document.querySelector('#flowMaskInvert').checked;drawFlowPainter()}
function drawFlowMask(paint,region,index,width,height){if(!region.mask)return;const spec=region.mask,values=base64ToBytes(spec.data),source=document.createElement('canvas');source.width=spec.width;source.height=spec.height;const sourceContext=source.getContext('2d'),image=sourceContext.createImageData(spec.width,spec.height),color=FLOW_COLORS[index%FLOW_COLORS.length],red=parseInt(color.slice(1,3),16),green=parseInt(color.slice(3,5),16),blue=parseInt(color.slice(5,7),16),threshold=Math.round((region.mask_threshold??.5)*255),offset=region.mask_offset||[0,0];for(let pixel=0;pixel<values.length;pixel++){const value=region.mask_invert?255-values[pixel]:values[pixel],position=pixel*4,active=value>=threshold?(region.mask_mode==='grayscale'?value:255):0;image.data[position]=red;image.data[position+1]=green;image.data[position+2]=blue;image.data[position+3]=Math.round(active*.55)}sourceContext.putImageData(image,0,0);paint.drawImage(source,offset[0]*width,offset[1]*height,width,height)}
function drawFlowPainter(){const canvas=document.querySelector('#flowCanvas');if(!canvas.width)return;const context=canvas.getContext('2d');context.clearRect(0,0,canvas.width,canvas.height);if(flowBitmap)context.drawImage(flowBitmap,0,0,canvas.width,canvas.height);const overlay=document.createElement('canvas');overlay.width=canvas.width;overlay.height=canvas.height;const paint=overlay.getContext('2d');fauxlogramFlow.regions.forEach((region,index)=>drawFlowMask(paint,region,index,canvas.width,canvas.height));paint.lineCap='round';paint.lineJoin='round';for(const stroke of fauxlogramFlow.strokes){const points=stroke.points||[];if(!points.length)continue;paint.save();paint.globalCompositeOperation=stroke.erase?'destination-out':'source-over';paint.strokeStyle=stroke.erase?'#000':FLOW_COLORS[stroke.region%FLOW_COLORS.length]+'b8';paint.fillStyle=paint.strokeStyle;paint.lineWidth=stroke.width*Math.min(canvas.width,canvas.height);paint.beginPath();paint.moveTo(points[0][0]*canvas.width,points[0][1]*canvas.height);for(const point of points.slice(1))paint.lineTo(point[0]*canvas.width,point[1]*canvas.height);if(points.length===1)paint.arc(points[0][0]*canvas.width,points[0][1]*canvas.height,paint.lineWidth/2,0,Math.PI*2);paint.stroke();if(points.length===1)paint.fill();paint.restore()}context.drawImage(overlay,0,0);fauxlogramFlow.regions.forEach((region,index)=>{if(region.region_type==='image_mask'&&(region.mask_mode||'grayscale')==='grayscale')return;const start=[region.start[0]*canvas.width,region.start[1]*canvas.height],end=[region.end[0]*canvas.width,region.end[1]*canvas.height],color=FLOW_COLORS[index%FLOW_COLORS.length];context.save();context.strokeStyle=color;context.fillStyle=color;context.lineWidth=index===flowActiveRegion?4:2;context.beginPath();if(region.guide_type==='radial'){const radius=Math.hypot(end[0]-start[0],end[1]-start[1]);context.arc(start[0],start[1],radius,0,Math.PI*2)}else{context.moveTo(...start);context.lineTo(...end)}context.stroke();context.beginPath();context.arc(start[0],start[1],6,0,Math.PI*2);context.fill();context.beginPath();context.arc(end[0],end[1],6,0,Math.PI*2);context.fill();context.restore()})}
async function openFlowPainter(){const cropSelection=getCropSelection();if(cropSelection&&cropSelection.width>=2&&cropSelection.height>=2)await applyArtworkCrop();const file=effectiveArtworkFile();if(!file){show('Choose artwork before opening the Fauxlogram Flow Painter.');return}try{flowBitmap?.close?.();flowBitmap=await createImageBitmap(file);const dialog=document.querySelector('#flowPainter');dialog.showModal();await new Promise(resolve=>requestAnimationFrame(resolve));resizeFlowCanvas();syncFlowRegionEditor()}catch(error){document.querySelector('#flowPainter').close();show(`Could not open Fauxlogram Flow Painter: ${error.message}`)}}
function setFlowTool(tool){flowTool=tool;document.querySelectorAll('[data-flow-tool]').forEach(button=>button.classList.toggle('active',button.dataset.flowTool===tool))}
document.querySelector('[data-flow-tool="guide"]').insertAdjacentHTML('afterend','<button type="button" data-flow-tool="move">Move mask</button>');
document.querySelector('#flowAddMaskRegion').onclick=()=>{if(fauxlogramFlow.regions.length>=8)return;saveFlowRegionEditor();if(fauxlogramFlow.regions.length===1&&!flowHasContent()&&activeFlowRegion().region_type==='painted'){fauxlogramFlow.regions[0]=newFlowRegion(0,'image_mask');flowActiveRegion=0}else{flowActiveRegion=fauxlogramFlow.regions.length;fauxlogramFlow.regions.push(newFlowRegion(flowActiveRegion,'image_mask'))}syncFlowRegionEditor()};
document.querySelector('#flowMaskMode').addEventListener('change',()=>{saveFlowRegionEditor();syncFlowRegionEditor()});
document.querySelector('#openFlowPainter').onclick=openFlowPainter;document.querySelector('#closeFlowPainter').onclick=()=>document.querySelector('#flowPainter').close();document.querySelector('#flowDone').onclick=()=>{saveFlowRegionEditor();fauxlogramFlow.enabled=flowHasContent();updateFlowSummary();document.querySelector('#flowPainter').close()};document.querySelector('#flowDisable').onclick=()=>{fauxlogramFlow.enabled=false;updateFlowSummary();document.querySelector('#flowPainter').close()};document.querySelectorAll('[data-flow-tool]').forEach(button=>button.onclick=()=>setFlowTool(button.dataset.flowTool));document.querySelector('#flowRegion').onchange=event=>{saveFlowRegionEditor();flowActiveRegion=Number(event.target.value)||0;syncFlowRegionEditor()};document.querySelector('#flowAddRegion').onclick=()=>{if(fauxlogramFlow.regions.length>=8)return;saveFlowRegionEditor();flowActiveRegion=fauxlogramFlow.regions.length;fauxlogramFlow.regions.push(newFlowRegion(flowActiveRegion));syncFlowRegionEditor()};document.querySelector('#flowDeleteRegion').onclick=()=>{if(fauxlogramFlow.regions.length<=1){if(activeFlowRegion().region_type==='image_mask'){fauxlogramFlow.regions=[newFlowRegion(0)];fauxlogramFlow.strokes=[];fauxlogramFlow.enabled=false;flowActiveRegion=0;updateFlowSummary();syncFlowRegionEditor()}return}fauxlogramFlow.regions.splice(flowActiveRegion,1);fauxlogramFlow.strokes=fauxlogramFlow.strokes.filter(stroke=>stroke.region!==flowActiveRegion).map(stroke=>({...stroke,region:stroke.region>flowActiveRegion?stroke.region-1:stroke.region}));flowActiveRegion=Math.max(0,flowActiveRegion-1);syncFlowRegionEditor()};document.querySelector('#flowClearRegion').onclick=()=>{fauxlogramFlow.strokes=fauxlogramFlow.strokes.filter(stroke=>stroke.region!==flowActiveRegion);const region=activeFlowRegion();region.mask=null;region.mask_name='';syncFlowRegionEditor()};document.querySelector('#flowMaskFile').onchange=async event=>{const region=activeFlowRegion(),file=event.target.files[0];if(!file)return;try{region.mask=await normalizeShapeImage(file);region.mask_name=file.name;syncFlowRegionEditor()}catch(error){region.mask=null;region.mask_name='';document.querySelector('#flowMaskStatus').textContent=error.message;drawFlowPainter()}};document.querySelector('#flowRemoveMask').onclick=()=>{const region=activeFlowRegion();region.mask=null;region.mask_name='';document.querySelector('#flowMaskFile').value='';syncFlowRegionEditor()};for(const id of ['flowScope','flowGuideType','flowOrientation','flowGradientStart','flowGradientEnd','flowCurve','flowFixedAngle','flowAngleOffset','flowReverse','flowMaskMode','flowMaskThreshold','flowMaskInvert'])document.querySelector('#'+id).oninput=saveFlowRegionEditor;
document.querySelector('#flowCanvas').onpointerdown=event=>{event.currentTarget.setPointerCapture(event.pointerId);const point=flowPoint(event),region=activeFlowRegion();if(flowTool==='guide'){region.start=point;region.end=point;flowDrawing={guide:true}}else if(flowTool==='move'){if(!region.mask){show('Upload an image mask for this region before moving it.');return}flowDrawing={move:true,start:point,offset:[...(region.mask_offset||[0,0])]}}else{const width=Number(document.querySelector('#flowBrush').value)/100;flowDrawing={region:flowActiveRegion,erase:flowTool==='erase',width,points:[point]};fauxlogramFlow.strokes.push(flowDrawing)}drawFlowPainter()};document.querySelector('#flowCanvas').onpointermove=event=>{if(!flowDrawing)return;const point=flowPoint(event);if(flowDrawing.guide)activeFlowRegion().end=point;else if(flowDrawing.move){activeFlowRegion().mask_offset=[Math.max(-1,Math.min(1,flowDrawing.offset[0]+point[0]-flowDrawing.start[0])),Math.max(-1,Math.min(1,flowDrawing.offset[1]+point[1]-flowDrawing.start[1]))]}else{const last=flowDrawing.points.at(-1);if(Math.hypot(point[0]-last[0],point[1]-last[1])>=.003&&flowDrawing.points.length<512)flowDrawing.points.push(point)}drawFlowPainter()};document.querySelector('#flowCanvas').onpointerup=event=>{if(!flowDrawing)return;document.querySelector('#flowCanvas').onpointermove(event);flowDrawing=null};document.querySelector('#flowCanvas').onpointercancel=()=>{flowDrawing=null};
window.addEventListener('resize',()=>{if(document.querySelector('#flowPainter').open)resizeFlowCanvas()});
function colorMatchingParameters(){return{color_matching_mode:document.querySelector('#colorMatchingMode').value,color_matching_hue_weight:Number(document.querySelector('#matchingHue').value),color_matching_saturation_weight:Number(document.querySelector('#matchingSaturation').value),color_matching_lightness_weight:Number(document.querySelector('#matchingLightness').value)}}
function effectiveColorMatching(){const mode=document.querySelector('#colorMatchingMode').value,preset=COLOR_MATCHING_MODES[mode]||COLOR_MATCHING_MODES.balanced;return mode==='custom'?{mode,hue:Number(document.querySelector('#matchingHue').value),saturation:Number(document.querySelector('#matchingSaturation').value),lightness:Number(document.querySelector('#matchingLightness').value)}:{mode,hue:preset.hue,saturation:preset.saturation,lightness:preset.lightness}}
function setMatchingControl(name,value){const range=document.querySelector(`#matching${name}`),number=document.querySelector(`#matching${name}Number`),clean=Math.max(0,Math.min(10,Number(value)));range.value=Number.isFinite(clean)?clean:0;number.value=range.value}
function updateColorMatchingPresentation(){const mode=document.querySelector('#colorMatchingMode').value,preset=COLOR_MATCHING_MODES[mode]||COLOR_MATCHING_MODES.balanced;document.querySelector('#colorMatchingDescription').textContent=preset.description;document.querySelector('#colorMatchingCustom').hidden=mode!=='custom';if(mode!=='custom'){setMatchingControl('Hue',preset.hue);setMatchingControl('Saturation',preset.saturation);setMatchingControl('Lightness',preset.lightness)}markQuantPreviewStale()}
function syncColorMatchingAvailability(){const unavailable=Boolean(selectedRasterRecipe())||document.querySelector('#imagePreset').value==='bw_dither_photograph';document.querySelector('#colorMatchingSection').classList.toggle('hidden',unavailable)}
function hasOption(select,value){return [...select.options].some(option=>option.value===String(value??''))}
function rasterizerFormValues(){return{material_choice:document.querySelector('#materialChoice').value,material_name:document.querySelector('#materialName').value,pixel_square_mm:document.querySelector('#pixel').value,new_width:document.querySelector('#width').value,new_height:document.querySelector('#height').value,white_is:document.querySelector('#whiteIs').value,image_preset:document.querySelector('#imagePreset').value,filter_parameters:filterParameters(),geometry_style:effectiveGeometryStyle(),geometry_style_parameters:geometryStyleParameters(),panel_tiling:panelTilingPreferenceValues(),...colorMatchingParameters(),cut_mode:document.querySelector('#rasterHoloCutMode').value,preserve_black_outlines:document.querySelector('#rasterHoloBlack').checked}}
function restoreRasterizerForm(values,restoreMaterial=true){if(!values)return;if(restoreMaterial&&values.material_name!==undefined)document.querySelector('#materialName').value=values.material_name;for(const [id,key] of [['pixel','pixel_square_mm'],['width','new_width'],['height','new_height']])if(values[key]!==undefined)document.querySelector('#'+id).value=values[key];if(hasOption(document.querySelector('#whiteIs'),values.white_is))document.querySelector('#whiteIs').value=values.white_is;const preset=document.querySelector('#imagePreset');if(hasOption(preset,values.image_preset)){preset.value=values.image_preset;renderFilter();for(const [name,value] of Object.entries(values.filter_parameters||{})){const input=[...document.querySelectorAll('#filterControls [data-parameter]')].find(item=>item.dataset.parameter===name);if(!input)continue;if(input.type==='checkbox')input.checked=Boolean(value);else{input.value=value;input.oninput?.()}}}if(geometryStyleCompatible()&&hasOption(document.querySelector('#geometryStyle'),values.geometry_style))document.querySelector('#geometryStyle').value=values.geometry_style;renderGeometryControls();if(values.geometry_style==='by_swatch'){geometryRouteAssignments.clear();for(const [hex,style] of Object.entries(values.geometry_style_parameters?.assignments||{}))geometryRouteAssignments.set(hex.toUpperCase(),style);renderGeometryRouting();applyGeometryValues(document.querySelector('#routedGlyphControls'),values.geometry_style_parameters?.glyphs);applyGeometryValues(document.querySelector('#routedHalftoneControls'),values.geometry_style_parameters?.halftone_newsprint);applyGeometryValues(document.querySelector('#routedKrasnowControls'),values.geometry_style_parameters?.krasnow_grating)}else if(values.geometry_style==='glyphs')applyGeometryValues(document.querySelector('#routedGlyphControls'),values.geometry_style_parameters);else if(values.geometry_style==='halftone_newsprint')applyGeometryValues(document.querySelector('#routedHalftoneControls'),values.geometry_style_parameters);else if(values.geometry_style==='krasnow_grating')applyGeometryValues(document.querySelector('#routedKrasnowControls'),values.geometry_style_parameters);syncGeometryStyleAvailability();const matching=document.querySelector('#colorMatchingMode');if(hasOption(matching,values.color_matching_mode))matching.value=values.color_matching_mode;for(const [name,key] of [['Hue','color_matching_hue_weight'],['Saturation','color_matching_saturation_weight'],['Lightness','color_matching_lightness_weight']])if(values[key]!==undefined)setMatchingControl(name,values[key]);updateColorMatchingPresentation();if(hasOption(document.querySelector('#rasterHoloCutMode'),values.cut_mode))document.querySelector('#rasterHoloCutMode').value=values.cut_mode;document.querySelector('#rasterHoloBlack').checked=Boolean(values.preserve_black_outlines)&&!document.querySelector('#rasterHoloBlack').disabled;restorePanelTiling(values)}
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
document.querySelector('#imagePreset').onchange=()=>{renderFilter();syncGeometryStyleAvailability();markQuantPreviewStale()};document.querySelector('#resetFilter').onclick=renderFilter;document.querySelector('#randomizeFilter').onclick=()=>{document.querySelectorAll('#filterControls input[type=range]').forEach(range=>{const steps=Math.floor((Number(range.max)-Number(range.min))/Number(range.step));range.value=Number(range.min)+Math.floor(Math.random()*(steps+1))*Number(range.step);range.oninput()})};document.querySelector('#geometryStyle').onchange=syncGeometryStyleAvailability;document.querySelector('#resetGeometryStyle').onclick=()=>{resetFauxlogramFlow();renderGeometryControls(true);syncGeometryStyleAvailability()};document.querySelector('#geometryRoutingGrid').onchange=event=>{const select=event.target.closest('[data-route-style]');if(!select)return;geometryRouteAssignments.set(select.dataset.hex.toUpperCase(),select.value);syncRoutedSettingsVisibility()};document.querySelector('#geometryRouting').onclick=event=>{const button=event.target.closest('[data-route-bulk]');if(!button)return;const style=button.dataset.routeBulk;document.querySelectorAll('#geometryRoutingGrid .geometry-route-card').forEach(card=>{const checked=card.querySelector('[data-route-selected]'),select=card.querySelector('[data-route-style]');if(!checked?.checked||select?.disabled)return;select.value=style;geometryRouteAssignments.set(select.dataset.hex.toUpperCase(),select.value)});syncRoutedSettingsVisibility()};renderFilter();renderGeometryControls();syncGeometryStyleAvailability();configurePanelTiling({previewSwatches,hasOption,effectiveArtworkFile,loadPreviewBitmap,markQuantPreviewStale});
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
