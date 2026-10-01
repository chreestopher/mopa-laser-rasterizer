import {
  drawShapePreview,
  drawSvgPreview,
  normalizeShapeImage,
  normalizeShapeSvg,
} from './shape-assets-v1.js';

let dependencies=null;
let customGlyphMask=null;
let customGlyphSvg=null;
let customCellSvg=null;
const geometryRouteAssignments=new Map();

const element=selector=>(dependencies?.documentRoot||document).querySelector(selector);
const GLYPH_GEOMETRY={selects:[['glyph_shape','diamond',[['circle','Circle'],['square','Square'],['diamond','Diamond'],['triangle','Triangle'],['hexagon','Hexagon'],['octagon','Octagon'],['star','Star'],['cross','Cross'],['bar','Bar'],['skull','Skull'],['heart','Heart'],['space_invader','Space Invader'],['ghost','Ghost'],['bat','Bat'],['alien_head','Alien Head'],['paw_print','Paw Print'],['fish_scale','Fish Scale'],['puzzle_piece','Puzzle Piece'],['mixed','Mixed Shapes'],['custom','Custom Uploaded Glyph']]],['glyph_size_source','source_brightness',[['source_brightness','Source Brightness'],['seeded_variation','Seeded Variation']]]],toggles:[['black_only',false],['invert',false],['invert_fill',false],['tight_pack_geometry',false],['random_rotation',false]],controls:[['cell_size_mm',.6,.2,5,.05],['minimum_glyph_ratio',.48,.16,.8,.01],['maximum_glyph_ratio',.97,.94,1,.01],['non_black_glyph_density',2.3,.6,4,.05],['tone_curve',.75,.2,1.3,.05],['contrast',2,1,3,.05],['grid_angle',-45,-90,0,1],['glyph_rotation',0,-180,180,1],['seed',1,0,999999,1]]};
const HALFTONE_GEOMETRY={description:'Rebuilds the prepared color regions as a shared newsprint matrix of circles or squares. Dot Size Source can preserve source-image tone or produce a repeatable seeded distribution within the selected size range. Black Only creates a conventional monochrome halftone; Choose by swatch keeps Halftone output on each routed swatch instead.',selects:[['dot_size_source','source_brightness',[['source_brightness','Source Brightness'],['seeded_variation','Seeded Variation']]]],toggles:[['black_only',false],['square_dots',false],['invert',false],['tight_pack_geometry',false]],controls:[['cell_size_mm',.6,.2,1,.05],['minimum_dot_ratio',.48,.16,.8,.01],['maximum_dot_ratio',.97,.94,1,.01],['non_black_dot_density',2.3,.6,4,.05],['tone_curve',.75,.2,1.3,.05],['contrast',2,1,3,.05],['grid_angle',-45,-90,0,1],['seed',1,0,999999,1]]};
const ROUTED_HALFTONE_GEOMETRY={...HALFTONE_GEOMETRY,toggles:HALFTONE_GEOMETRY.toggles.filter(([name])=>name!=='black_only')};
const KRASNOW_GEOMETRY={description:'Builds calibrated open parallel-line cells across the prepared artwork. Preserve Black keeps source Black as normal Black geometry; otherwise Black is rebuilt as gratings like other swatches. Cell Shape supports regular, decorative, and custom SVG cells. Tight Pack Geometry reduces empty space, while Random Rotation gives cells repeatable independent orientations. This requires a Fauxlographic Cut Setting in the selected palette; its main layer settings are cloned onto the generated LightBurn carrier layers. Explicit Lines preserves full-resolution vector gratings. LightBurn Fill is experimental and lets LightBurn generate lines using Line Spacing as its uniform Fill interval. Fauxlogram Gradient Scope and Direction control how carrier progression is evaluated.',selects:[['grating_render_mode','line',[['line','Explicit Lines'],['fill','LightBurn Fill (Experimental)']]],['cell_shape','square',[['square','Square'],['hexagon','Hexagon'],['triangle','Triangle'],['diamond','Diamond / Rhombus'],['skull','Skull'],['heart','Heart'],['space_invader','Space Invader'],['ghost','Ghost'],['bat','Bat'],['alien_head','Alien Head'],['paw_print','Paw Print'],['fish_scale','Fish Scale'],['puzzle_piece','Puzzle Piece'],['custom','Custom SVG']]],['fauxlogram_gradient_scope','entire_artwork',[['entire_artwork','Entire Artwork'],['each_shape','Each Shape']]],['fauxlogram_gradient_direction','top_to_bottom',[['top_to_bottom','Top to Bottom'],['bottom_to_top','Bottom to Top'],['left_to_right','Left to Right'],['right_to_left','Right to Left'],['center_to_edge','Center to Edge (Radial)'],['edge_to_center','Edge to Center (Radial)']]]],toggles:[['preserve_black',true],['tight_pack_geometry',false],['random_rotation',false]],controls:[['speed_spread',1,0,2,.001],['gradient_top',165,0,255,1],['gradient_bottom',90,0,255,1],['gradient_curve',1,.2,5,.05],['hue_rotation',.13,0,1,.01],['saturation_cutoff',.2,0,1,.01],['patch_size_mm',.4,.1,5,.05],['line_spacing_mm',.06,.01,.5,.005],['hue_line_spacing_minimum_mm',.06,.01,.5,.001],['hue_line_spacing_maximum_mm',.06,.01,.5,.001],['angle_min',-90,-180,180,1],['angle_max',90,-180,180,1]]};
const SPECIALIZED_GEOMETRY_PRESETS=new Set(['abstract_optical_color_mix']);
const friendly=name=>name.split('_').map(word=>word[0].toUpperCase()+word.slice(1)).join(' ');

function geometryStyleCompatible(){return !dependencies.selectedRasterRecipe()&&!SPECIALIZED_GEOMETRY_PRESETS.has(element('#imagePreset').value)}
export function effectiveGeometryStyle(){return geometryStyleCompatible()?element('#geometryStyle').value:'vectors'}
function geometryStyleConfiguration(){return effectiveGeometryStyle()==='glyphs'?GLYPH_GEOMETRY:effectiveGeometryStyle()==='halftone_newsprint'?HALFTONE_GEOMETRY:effectiveGeometryStyle()==='krasnow_grating'?KRASNOW_GEOMETRY:null}
function geometryControlValues(selector){const values=Object.fromEntries([...element(selector).querySelectorAll('[data-geometry-parameter]')].map(input=>[input.dataset.geometryParameter,input.type==='checkbox'?Number(input.checked):input.tagName==='SELECT'?input.value:Number(input.value)]));if(values.glyph_shape==='custom'){if(customGlyphSvg)values.custom_glyph_svg=structuredClone(customGlyphSvg);else if(customGlyphMask)values.custom_glyph_mask=structuredClone(customGlyphMask)}if(values.cell_shape==='custom'&&customCellSvg)values.custom_cell_svg=structuredClone(customCellSvg);return values}
function flowHasContent(){const flow=dependencies.getFauxlogramFlow();return flow.strokes.some(stroke=>!stroke.erase)||flow.regions.some(region=>region.mask)}
function krasnowGeometryValues(){const values=geometryControlValues('#routedKrasnowControls'),flow=dependencies.getFauxlogramFlow();if(flow.enabled&&flowHasContent())values.fauxlogram_flow=structuredClone(flow);return values}
export function geometryStyleParameters(){const style=effectiveGeometryStyle();if(style==='by_swatch'){const assignments=Object.fromEntries([...element('#geometryRoutingGrid').querySelectorAll('[data-route-style]')].map(input=>[input.dataset.hex,input.value])),used=new Set(Object.values(assignments)),parameters={assignments};if(used.has('glyphs'))parameters.glyphs=geometryControlValues('#routedGlyphControls');if(used.has('halftone_newsprint'))parameters.halftone_newsprint=geometryControlValues('#routedHalftoneControls');if(used.has('krasnow_grating'))parameters.krasnow_grating=krasnowGeometryValues();return parameters}if(style==='glyphs')return geometryControlValues('#routedGlyphControls');if(style==='halftone_newsprint')return geometryControlValues('#routedHalftoneControls');if(style==='krasnow_grating')return krasnowGeometryValues();return{}}

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

function syncGeometryToggleCompatibility(box=element('#geometryStyleControls')){const invertFill=box.querySelector('[data-geometry-parameter="invert_fill"]'),blackOnly=box.querySelector('[data-geometry-parameter="black_only"]');if(!invertFill||!blackOnly)return;if(invertFill.checked)blackOnly.checked=false;blackOnly.disabled=invertFill.checked;blackOnly.closest('label')?.classList.toggle('disabled',invertFill.checked)}
function routedPaletteEntries(){const unique=new Map();for(const item of dependencies.visibleRasterPalette()){const key=String(item.selection_key??item.hex).toUpperCase(),hex=String(item.hex||item.display_hex||'').toUpperCase();if(!dependencies.selectedPaletteHexes.has(key)||!/^#[0-9A-F]{6}$/.test(hex)||unique.has(hex))continue;unique.set(hex,{hex,name:dependencies.paletteDisplayName(item)})}return [...unique.values()]}
function syncRoutedSettingsVisibility(){const style=effectiveGeometryStyle(),styles=style==='by_swatch'?new Set([...element('#geometryRoutingGrid').querySelectorAll('[data-route-style]')].map(input=>input.value)):new Set([style]);element('#routedGlyphSettings').hidden=!styles.has('glyphs');element('#routedHalftoneSettings').hidden=!styles.has('halftone_newsprint');element('#routedKrasnowSettings').hidden=!styles.has('krasnow_grating')}
function renderGeometryRouting(){const grid=element('#geometryRoutingGrid');if(!element('#routedGlyphControls').childElementCount)buildGeometryControls(element('#routedGlyphControls'),GLYPH_GEOMETRY);if(!element('#routedHalftoneControls').childElementCount)buildGeometryControls(element('#routedHalftoneControls'),ROUTED_HALFTONE_GEOMETRY);if(!element('#routedKrasnowControls').childElementCount)buildGeometryControls(element('#routedKrasnowControls'),KRASNOW_GEOMETRY);grid.innerHTML=routedPaletteEntries().map(item=>{const fixed=item.hex==='#000000',style=fixed?'vectors':geometryRouteAssignments.get(item.hex)||'vectors';geometryRouteAssignments.set(item.hex,style);return `<label class="geometry-route-card ${fixed?'fixed':''}"><input type="checkbox" data-route-selected ${fixed?'disabled':''}><span class="geometry-route-chip" style="--swatch-color:${dependencies.esc(item.hex)}"></span><strong title="${dependencies.esc(item.name)}">${dependencies.esc(item.name)}</strong><select data-route-style data-hex="${dependencies.esc(item.hex)}" aria-label="Geometry for ${dependencies.esc(item.name)}" ${fixed?'disabled':''}><option value="vectors" ${style==='vectors'?'selected':''}>Vectors</option><option value="glyphs" ${style==='glyphs'?'selected':''}>Glyphs</option><option value="halftone_newsprint" ${style==='halftone_newsprint'?'selected':''}>Halftone</option><option value="krasnow_grating" ${style==='krasnow_grating'?'selected':''}>Krasnow</option></select></label>`}).join('');syncRoutedSettingsVisibility()}
export function renderGeometryControls(reset=false){const box=element('#geometryStyleControls'),style=effectiveGeometryStyle();box.dataset.style=style;if((reset||!element('#routedGlyphControls').childElementCount)&&style==='glyphs')buildGeometryControls(element('#routedGlyphControls'),GLYPH_GEOMETRY);if((reset||!element('#routedHalftoneControls').childElementCount)&&style==='halftone_newsprint')buildGeometryControls(element('#routedHalftoneControls'),HALFTONE_GEOMETRY);if((reset||!element('#routedKrasnowControls').childElementCount)&&style==='krasnow_grating')buildGeometryControls(element('#routedKrasnowControls'),KRASNOW_GEOMETRY);if(style==='by_swatch')renderGeometryRouting();syncRoutedSettingsVisibility()}

function applyGeometryValues(box,values){
  if(values?.fauxlogram_flow){
    const flow=JSON.parse(JSON.stringify(values.fauxlogram_flow));
    flow.regions?.forEach((region,index)=>{
      if(region.mask&&region.region_type!=='image_mask'&&!flow.strokes?.some(stroke=>stroke.region===index))region.region_type='image_mask';
    });
    dependencies.restoreFauxlogramFlow(flow);
  }
  if(values?.custom_glyph_mask)customGlyphMask=JSON.parse(JSON.stringify(values.custom_glyph_mask));
  if(values?.custom_glyph_svg)customGlyphSvg=JSON.parse(JSON.stringify(values.custom_glyph_svg));
  if(values?.custom_cell_svg)customCellSvg=JSON.parse(JSON.stringify(values.custom_cell_svg));
  for(const [name,value] of Object.entries(values||{})){const input=[...box.querySelectorAll('[data-geometry-parameter]')].find(item=>item.dataset.geometryParameter===name);if(!input)continue;if(input.type==='checkbox')input.checked=Boolean(value);else{input.value=value;input.oninput?.()}}
  box.querySelector('[data-geometry-parameter="glyph_shape"]')?.dispatchEvent(new Event('change'));
  box.querySelector('[data-geometry-parameter="cell_shape"]')?.dispatchEvent(new Event('change'));
  syncGeometryToggleCompatibility(box)
}

export function restoreGeometryControls(values){
  if(geometryStyleCompatible()&&dependencies.hasOption(element('#geometryStyle'),values.geometry_style))element('#geometryStyle').value=values.geometry_style;
  renderGeometryControls();
  if(values.geometry_style==='by_swatch'){
    geometryRouteAssignments.clear();
    for(const [hex,style] of Object.entries(values.geometry_style_parameters?.assignments||{}))geometryRouteAssignments.set(hex.toUpperCase(),style);
    renderGeometryRouting();
    applyGeometryValues(element('#routedGlyphControls'),values.geometry_style_parameters?.glyphs);
    applyGeometryValues(element('#routedHalftoneControls'),values.geometry_style_parameters?.halftone_newsprint);
    applyGeometryValues(element('#routedKrasnowControls'),values.geometry_style_parameters?.krasnow_grating);
  }else if(values.geometry_style==='glyphs')applyGeometryValues(element('#routedGlyphControls'),values.geometry_style_parameters);
  else if(values.geometry_style==='halftone_newsprint')applyGeometryValues(element('#routedHalftoneControls'),values.geometry_style_parameters);
  else if(values.geometry_style==='krasnow_grating')applyGeometryValues(element('#routedKrasnowControls'),values.geometry_style_parameters);
  syncGeometryStyleAvailability();
}

export function syncGeometryStyleAvailability(){const section=element('#geometryStyleSection'),compatible=geometryStyleCompatible(),style=effectiveGeometryStyle(),configuration=geometryStyleConfiguration(),controls=element('#geometryStyleControls'),routing=element('#geometryRouting');section.classList.toggle('hidden',!compatible);controls.hidden=true;routing.hidden=style!=='by_swatch';element('#geometryStyleActions').hidden=!configuration;if(controls.dataset.style!==style||style==='by_swatch')renderGeometryControls();else syncRoutedSettingsVisibility();element('#geometryStyleDescription').textContent=style==='glyphs'?'Rebuild the filtered color regions on a shared matrix using solid glyphs. Invert Fill keeps the vectors and cuts glyph-shaped holes from their owning layers. Every output layer is made mutually exclusive before export.':style==='halftone_newsprint'?HALFTONE_GEOMETRY.description:style==='krasnow_grating'?KRASNOW_GEOMETRY.description:style==='by_swatch'?'Route each enabled palette swatch independently to normal vectors, Glyphs, Halftone Newsprint, or Krasnow Grating. Each source region receives exactly one treatment.':'Keep the selected Image Style’s ordinary continuous vector geometry.'}

export function configureGeometryControls(options){
  dependencies=options;
  element('#geometryStyle').onchange=syncGeometryStyleAvailability;
  element('#resetGeometryStyle').onclick=()=>{dependencies.resetFauxlogramFlow();renderGeometryControls(true);syncGeometryStyleAvailability()};
  element('#geometryRoutingGrid').onchange=event=>{const select=event.target.closest('[data-route-style]');if(!select)return;geometryRouteAssignments.set(select.dataset.hex.toUpperCase(),select.value);syncRoutedSettingsVisibility()};
  element('#geometryRouting').onclick=event=>{const selectionButton=event.target.closest('[data-route-selection]'),grid=element('#geometryRoutingGrid');if(selectionButton){const checked=selectionButton.dataset.routeSelection==='all';grid.querySelectorAll('[data-route-selected]:not(:disabled)').forEach(input=>{input.checked=checked});return}const button=event.target.closest('[data-route-bulk]');if(!button)return;const style=button.dataset.routeBulk;grid.querySelectorAll('.geometry-route-card').forEach(card=>{const checked=card.querySelector('[data-route-selected]'),select=card.querySelector('[data-route-style]');if(!checked?.checked||select?.disabled)return;select.value=style;geometryRouteAssignments.set(select.dataset.hex.toUpperCase(),select.value)});syncRoutedSettingsVisibility()};
}
