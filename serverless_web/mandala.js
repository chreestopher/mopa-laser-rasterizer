import {createMandalaAssetConstraints} from "./mandala/asset-constraints-v3.js";
import {createMandalaJobLifecycle} from "./mandala/job-lifecycle-v2.js";
import {createMandalaLayerEditor} from "./mandala/layer-editor-v5.js";
import {createPaletteRouting} from "./mandala/palette-routing-v1.js";
import {createMandalaPreview} from "./mandala/preview-v3.js";

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

// Measure after the shared navigation and authenticated editor have settled.
const workspace=document.querySelector("#mandalaWorkspace");
function fitWorkspace(){
  const top=workspace.getBoundingClientRect().top+window.scrollY;
  workspace.style.setProperty("--workspace-height",`${Math.max(360,window.innerHeight-top-32)}px`);
}
new ResizeObserver(()=>requestAnimationFrame(fitWorkspace)).observe(document.body);
window.addEventListener("resize",fitWorkspace);
fitWorkspace();
