import {createMandalaAssetConstraints} from "./mandala/asset-constraints-v1.js";
import {createMandalaJobLifecycle} from "./mandala/job-lifecycle-v1.js";
import {createMandalaLayerEditor} from "./mandala/layer-editor-v1.js";
import {createPaletteRouting} from "./mandala/palette-routing-v1.js";
import {createMandalaPreview} from "./mandala/preview-v1.js";

let resources={},preview;
const $=selector=>document.querySelector(selector);
const esc=value=>String(value??"").replace(/[&<>"']/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
const editor=createMandalaLayerEditor({escapeHtml:esc,schedulePreview:()=>preview.schedulePreview()});
const {getActiveLayer,getLayers,renderLayers,resetLayers}=editor;
const paletteRouting=createPaletteRouting({escapeHtml:esc,getResources:()=>resources});
const {populatePalette}=paletteRouting;
preview=createMandalaPreview({query:$,getLayers,getActiveLayer});
const assetConstraints=createMandalaAssetConstraints({query:$,getLayers,renderLayers});
paletteRouting.bindEvents();assetConstraints.bindEvents();editor.bind();
const jobLifecycle=createMandalaJobLifecycle({escapeHtml:esc,getLayers,onAuthenticated:accountResources=>{resources=accountResources;resetLayers();populatePalette();renderLayers()}});
jobLifecycle.bind();
jobLifecycle.start();
