import {createHardwarePreview} from "./spiralgraph/hardware-preview-v1.js";
import {createCanvasPreview} from "./spiralgraph/canvas-preview-v1.js";
import {createDrawingEditor} from "./spiralgraph/drawing-editor-v1.js?v=2";
import {createJobLifecycle} from "./spiralgraph/job-lifecycle-v1.js";
import {createPaletteRouting} from "./spiralgraph/palette-routing-v1.js";
import {COLORS,GEARS,constrainWorkbedToDiameter,createDrawingState,newLayer} from "./spiralgraph/state-v1.js";

let resources={},canvasPreview;
const $=value=>document.querySelector(value);
const esc=value=>String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const drawingState=createDrawingState();
const getLayers=drawingState.getLayers,getActiveLayerIndex=drawingState.getActiveLayerIndex,setActiveLayerIndex=drawingState.setActiveLayerIndex;
const paletteRouting=createPaletteRouting({colors:COLORS,escapeHtml:esc,getResources:()=>resources,getLayers});
const {paletteSwatches,colorPalette,applySwatchMode,populatePalettes,updatePaletteStatus}=paletteRouting;

function schedulePreview(){canvasPreview.schedulePreview()}
const hardwarePreview=createHardwarePreview({getActiveLayer:()=>getLayers()[getActiveLayerIndex()],getActiveLayerIndex,schedulePreview});
canvasPreview=createCanvasPreview({colors:COLORS,getLayers,getActiveLayerIndex,getDiameter:()=>$("#diameter").value,renderHardware:()=>hardwarePreview.render()});
const drawingEditor=createDrawingEditor({colors:COLORS,gears:GEARS,escapeHtml:esc,getLayers,getActiveLayerIndex,setActiveLayerIndex,newLayer,paletteSwatches,colorPalette,applySwatchMode,updatePaletteStatus,schedulePreview});
const {renderLayers}=drawingEditor;

function syncDimensions(){constrainWorkbedToDiameter($("#diameter"),[$("#workbedWidth"),$("#workbedHeight")]);schedulePreview()}
paletteRouting.bindEvents(renderLayers);$("#diameter").addEventListener("input",syncDimensions);
const jobLifecycle=createJobLifecycle({escapeHtml:esc,getLayers,onAuthenticated:accountResources=>{resources=accountResources;drawingState.resetLayers();populatePalettes();renderLayers()}});
jobLifecycle.bind();
jobLifecycle.start();
