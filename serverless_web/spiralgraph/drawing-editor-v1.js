import {geometryPoints} from "./geometry-v1.js";
import {normalizeCustomImage} from "../custom-image-vectorizer-v1.js";

const $=value=>document.querySelector(value);

function options(values,current){return values.map(([value,label])=>`<option value="${value}" ${String(current)===String(value)?"selected":""}>${label}</option>`).join("")}

export function createDrawingEditor({
  colors,
  gears,
  escapeHtml,
  getLayers,
  getActiveLayerIndex,
  setActiveLayerIndex,
  newLayer,
  paletteSwatches,
  colorPalette,
  applySwatchMode,
  updatePaletteStatus,
  schedulePreview,
}){
  function swatchPicker(layer,index){const swatches=paletteSwatches(),selected=swatches.some(item=>item.hex===String(layer.swatch_hex||"").toUpperCase())?String(layer.swatch_hex).toUpperCase():swatches[index%Math.max(1,swatches.length)]?.hex||colors[index%colors.length];layer.swatch_hex=selected;applySwatchMode(layer);const selectedSwatch=swatches.find(item=>item.hex===selected);return`<fieldset class="preview-swatches"><legend>Layer swatch</legend><div>${swatches.map(item=>`<label title="${escapeHtml(item.name)} · ${item.hex} · ${item.mode||"preview"}"><input data-field="swatch_hex" type="radio" name="preview-swatch-${index}" value="${item.hex}" ${item.hex===selected?"checked":""}><span style="--preview-swatch:${item.hex}" aria-hidden="true"></span><span class="visually-hidden">${escapeHtml(item.name)}</span></label>`).join("")}</div><small>${colorPalette()?`${escapeHtml(selectedSwatch?.name||selected)} · ${selectedSwatch?.mode==="fill"?"Fill ribbon":"Line / Cut"} · controls preview and exported laser layer.`:"Built-in preview and SVG color; the Processing Palette controls LightBurn output."}</small></fieldset>`}
  function layerCard(layer,index){const layers=getLayers();return`<article class="layer-card" data-layer="${index}"><div class="layer-heading"><div class="layer-identity"><h3>Drawing ${index+1}</h3><p>${escapeHtml(layer.name)}</p></div><div class="layer-heading-swatches">${swatchPicker(layer,index)}</div><div class="layer-actions"><button type="button" class="spiralgrap-button" data-action="duplicate">Duplicate</button><button type="button" class="spiralgrap-button" data-action="up" ${index===0?"disabled":""}>Earlier</button><button type="button" class="spiralgrap-button" data-action="down" ${index===layers.length-1?"disabled":""}>Later</button><button type="button" class="spiralgrap-button" data-action="remove" ${layers.length===1?"disabled":""}>Remove</button></div></div><div class="layer-controls">
<label>Drawing name<input data-field="name" maxlength="80" value="${escapeHtml(layer.name)}"></label>
<label>Track plate<select data-field="track">${options([["circle","96 · Circle"],["oval","105 · Oval"],["rounded_triangle","105 · Rounded triangle"],["rounded_square","120 · Rounded square"],["custom","Custom image"]],layer.track)}</select></label>
<label class="custom-track" ${layer.track==="custom"?"":"hidden"}>Custom track image<input data-field="custom_file" type="file" accept="image/*,.svg"></label><p class="custom-status" ${layer.track==="custom"?"":"hidden"}>${layer.custom_svg?`Loaded ${escapeHtml(layer.custom_svg.name)}. The largest closed path is used.`:"Choose an SVG or raster image. Raster artwork is traced and its largest closed outline is used."}</p>
<label>Rolling gear<select data-field="gear_teeth">${options(gears.map(value=>[value,`${value} · Gear ${value}`]),layer.gear_teeth)}</select></label>
<label>Pen hole<select data-field="pen_hole">${options([1,2,3,4,5,6].map(value=>[value,`${value} · ${value===1?"near center":value===6?"near edge":"offset"}`]),layer.pen_hole)}</select></label>
<label>Rolling position<select data-field="side">${options([["inside","Inside the track"],["outside","Outside the track"]],layer.side)}</select></label>
<label>Starting mark<select data-field="start_mark">${options([1,2,3,4,5,6,7,8].map(value=>[value,`Mark ${value}`]),layer.start_mark)}</select></label>
<label>Rolling direction<select data-field="direction">${options([["clockwise","Clockwise"],["counterclockwise","Counterclockwise"]],layer.direction)}</select></label>
<label>Track orientation<select data-field="rotation_quarter_turns">${options([[0,"0°"],[1,"90°"],[2,"180°"],[3,"270°"]],layer.rotation_quarter_turns)}</select></label>
<label>Output mode<select data-field="output_mode" ${colorPalette()?"disabled":""}>${options([["line","Line / Cut · open path"],["fill","Filled ribbon · closed path"]],layer.output_mode)}</select></label>
<label class="fill-thickness" ${layer.output_mode==="fill"?"":"hidden"}>Ribbon thickness (mm)<input data-field="fill_thickness_mm" type="number" min="0.1" max="25" step="0.1" value="${layer.fill_thickness_mm}"></label>
<label class="check-control"><input data-field="include_track" type="checkbox" ${layer.include_track?"checked":""}> Include track outline</label>
</div></article>`}
  function syncSlider(){const layers=getLayers();let activeLayer=Math.max(0,Math.min(getActiveLayerIndex(),layers.length-1));setActiveLayerIndex(activeLayer);$("#layerPreviewSlider").max=String(layers.length);$("#layerPreviewSlider").value=String(activeLayer+1);$("#layerPreviewPosition").textContent=`Drawing ${activeLayer+1} of ${layers.length}`;$("#layerPreviewName").textContent=layers[activeLayer]?.name||"Drawing"}
  function renderLayers(){$("#layerList").innerHTML=getLayers().map(layerCard).join("");syncSlider();updatePaletteStatus();schedulePreview()}
  function activateLayerCard(card){if(!card)return;const layers=getLayers(),index=Number(card.dataset.layer);if(Number.isInteger(index)&&index>=0&&index<layers.length&&index!==getActiveLayerIndex()){setActiveLayerIndex(index);syncSlider();schedulePreview()}}

  $("#addLayer").addEventListener("click",()=>{const layers=getLayers();if(layers.length>=6)return;const added=newLayer(layers.length);if(colorPalette()){const swatches=paletteSwatches();added.swatch_hex=swatches[layers.length%Math.max(1,swatches.length)]?.hex||added.swatch_hex;applySwatchMode(added)}layers.push(added);setActiveLayerIndex(layers.length-1);renderLayers()});
  $("#layerList").addEventListener("click",event=>{const layers=getLayers(),card=event.target.closest("[data-layer]"),button=event.target.closest("[data-action]");if(!card||!button)return;const index=Number(card.dataset.layer),action=button.dataset.action;if(action==="duplicate"&&layers.length<6){const duplicate=structuredClone(layers[index]);duplicate.name+=` copy`;layers.splice(index+1,0,duplicate);setActiveLayerIndex(index+1)}else if(action==="remove"&&layers.length>1){layers.splice(index,1)}else if(action==="up"&&index>0){[layers[index-1],layers[index]]=[layers[index],layers[index-1]];setActiveLayerIndex(index-1)}else if(action==="down"&&index<layers.length-1){[layers[index+1],layers[index]]=[layers[index],layers[index+1]];setActiveLayerIndex(index+1)}renderLayers()});
  $("#layerList").addEventListener("focusin",event=>activateLayerCard(event.target.closest("[data-layer]")));
  $("#layerList").addEventListener("input",event=>{const layers=getLayers(),card=event.target.closest("[data-layer]"),field=event.target.dataset.field;if(!card||!field||field==="custom_file")return;const activeLayer=Number(card.dataset.layer);setActiveLayerIndex(activeLayer);const layer=layers[activeLayer];layer[field]=event.target.type==="checkbox"?event.target.checked:event.target.type==="number"?Number(event.target.value):["gear_teeth","pen_hole","start_mark","rotation_quarter_turns"].includes(field)?Number(event.target.value):event.target.value;if(field==="swatch_hex")applySwatchMode(layer);delete layer._trackPoints;if(["track","output_mode","swatch_hex"].includes(field))renderLayers();else{syncSlider();updatePaletteStatus();schedulePreview()}});
  $("#layerList").addEventListener("change",async event=>{if(event.target.dataset.field!=="custom_file")return;const layers=getLayers(),card=event.target.closest("[data-layer]"),activeLayer=Number(card.dataset.layer);setActiveLayerIndex(activeLayer);const layer=layers[activeLayer];try{layer.custom_svg=await normalizeCustomImage(event.target.files[0],{validateSvg:geometryPoints});delete layer._trackPoints;renderLayers()}catch(error){alert(error.message);event.target.value=""}});
  $("#layerPreviewSlider").addEventListener("input",event=>{setActiveLayerIndex(Number(event.target.value)-1);syncSlider();schedulePreview()});

  return{renderLayers,syncSlider};
}
