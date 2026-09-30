import {
  PEN_HOLE_FACTORS,
  fitTransform,
  gearOutline,
  pathData,
  rollingModel,
  rollingState,
  segmentPath,
  stableHardwareDistance,
  trackTickSegments,
} from "./geometry-v1.js";

const SVG_NS="http://www.w3.org/2000/svg";
const $=value=>document.querySelector(value);

function svgNode(name,attributes={},text=""){const node=document.createElementNS(SVG_NS,name);for(const[key,value]of Object.entries(attributes))node.setAttribute(key,String(value));if(text)node.textContent=text;return node}
function addSvgDescription(svg,titleText,description){svg.append(svgNode("title",{},titleText),svgNode("desc",{},description))}
function renderTrackHardware(svg,layer,model){
  svg.replaceChildren();addSvgDescription(svg,"Track plate",`${model.trackTeeth}-tooth ${layer.track} track with the ${layer.side} rolling side indicated.`);
  const ticks=trackTickSegments(model),project=fitTransform([...model.track,...ticks.flat()],28);
  svg.append(svgNode("path",{d:pathData(model.track,project,true),class:"hardware-outline"}),svgNode("path",{d:segmentPath(ticks,project),class:"hardware-ticks"}),svgNode("text",{x:120,y:226,class:"hardware-mark-label"},`${model.trackTeeth} schematic teeth · ${layer.side}`));
}
function appendDirection(svg,cx,cy,r,effectiveSpin){const clockwise=effectiveSpin<0,startX=cx-r*.65,endX=cx+r*.65,y=cy-r*.8,arc=`M${startX.toFixed(2)} ${y.toFixed(2)} A${(r*.78).toFixed(2)} ${(r*.78).toFixed(2)} 0 0 ${clockwise?1:0} ${endX.toFixed(2)} ${y.toFixed(2)}`;svg.append(svgNode("path",{d:arc,class:"hardware-direction"}),svgNode("text",{x:cx,y:y-7,class:"hardware-mark-label"},clockwise?"↻ clockwise spin":"↺ counterclockwise spin"))}
function appendGearMarks(svg,cx,cy,r,selectedMark){for(let mark=1;mark<=8;mark++){const angle=(mark-1)*Math.PI/4,x=cx+Math.cos(angle)*r,y=cy+Math.sin(angle)*r;svg.append(svgNode("circle",{cx:x,cy:y,r:mark===selectedMark?4:2.5,class:`hardware-mark${mark===selectedMark?" selected":""}`}),svgNode("text",{x:x,y:y-7,class:"hardware-mark-label"},String(mark)))}}
function appendHoleControls(svg,layer,cx,cy,r,angle){for(let hole=1;hole<=6;hole++){const factor=PEN_HOLE_FACTORS[hole],x=cx+Math.cos(angle)*r*factor,y=cy+Math.sin(angle)*r*factor,selected=Number(layer.pen_hole)===hole,group=svgNode("g",{class:"hardware-hole",role:"radio","aria-label":`Pen hole ${hole}${hole===1?", near center":hole===6?", near edge":", offset"}`,"aria-checked":selected?"true":"false",tabindex:selected?"0":"-1","data-hole":hole,focusable:"true"});group.append(svgNode("circle",{cx:x,cy:y,r:13,class:"hardware-hole-target"}),svgNode("circle",{cx:x,cy:y,r:5,class:"hardware-hole-visible"}),svgNode("text",{x:x,y:y+3.5,class:"hardware-hole-label"},String(hole)));svg.append(group)}}
function renderGearHardware(svg,layer,model){
  svg.replaceChildren();addSvgDescription(svg,"Rolling gear and pencil holes",`${model.gearTeeth}-tooth rolling gear. Choose one of six pencil holes.`);
  const cx=120,cy=124,r=70,gear=gearOutline([cx,cy],r,model.gearTeeth,model.phase);
  svg.append(svgNode("path",{d:pathData(gear,point=>point,true),class:"hardware-gear"}),svgNode("circle",{cx,cy,r:3,class:"hardware-contact"}));appendGearMarks(svg,cx,cy,r+13,Number(layer.start_mark));appendHoleControls(svg,layer,cx,cy,r,model.phase);appendDirection(svg,cx,cy,r,model.roll*model.side);
  svg.append(svgNode("text",{x:120,y:232,class:"hardware-mark-label"},`${model.gearTeeth}-tooth gear · mark ${layer.start_mark}`));
}
function renderAssembledHardware(svg,layer,model){
  svg.replaceChildren();addSvgDescription(svg,"Assembled hardware",`${model.gearTeeth}-tooth gear shown ${layer.side} the ${layer.track} track using pencil hole ${layer.pen_hole}.`);
  const distance=stableHardwareDistance(model,layer.track==="custom"),state=rollingState(model,distance),gear=gearOutline([state.cx,state.cy],model.gearRadius,model.gearTeeth,state.angle),selectedRadius=model.gearRadius*PEN_HOLE_FACTORS[Number(layer.pen_hole)],pen=[state.cx+Math.cos(state.angle)*selectedRadius,state.cy+Math.sin(state.angle)*selectedRadius],project=fitTransform([...model.track,...gear,pen],28),gearCenter=project([state.cx,state.cy]),contact=project([state.x,state.y]),penPoint=project(pen),scaledRadius=Math.hypot(project([state.cx+model.gearRadius,state.cy])[0]-gearCenter[0],project([state.cx+model.gearRadius,state.cy])[1]-gearCenter[1]);
  svg.append(svgNode("path",{d:pathData(model.track,project,true),class:"hardware-outline"}),svgNode("path",{d:pathData(gear,project,true),class:"hardware-gear"}),svgNode("line",{x1:gearCenter[0],y1:gearCenter[1],x2:penPoint[0],y2:penPoint[1],class:"hardware-direction"}),svgNode("circle",{cx:contact[0],cy:contact[1],r:4,class:"hardware-contact"}),svgNode("circle",{cx:penPoint[0],cy:penPoint[1],r:6,class:"hardware-contact"}));appendDirection(svg,gearCenter[0],gearCenter[1],Math.max(18,scaledRadius),model.roll*model.side);svg.append(svgNode("text",{x:120,y:232,class:"hardware-mark-label"},`${layer.side} · hole ${layer.pen_hole} · mark ${layer.start_mark}`));
}

export function createHardwarePreview({getActiveLayer,getActiveLayerIndex,schedulePreview}){
  function render(){const layer=getActiveLayer();if(!layer)return;const activeLayer=getActiveLayerIndex(),trackSvg=$("#trackHardware"),gearSvg=$("#gearHardware"),assembledSvg=$("#assembledHardware");try{const model=rollingModel(layer);renderTrackHardware(trackSvg,layer,model);renderGearHardware(gearSvg,layer,model);renderAssembledHardware(assembledSvg,layer,model);$("#hardwareLayerName").textContent=`Drawing ${activeLayer+1} — ${layer.name}`;$("#hardwareSummary").textContent=`${model.trackTeeth}-tooth ${layer.track.replaceAll("_"," ")} · ${model.gearTeeth}-tooth gear · ${layer.side} · hole ${layer.pen_hole} · ${layer.direction} · mark ${layer.start_mark}`}catch(error){for(const svg of[trackSvg,gearSvg,assembledSvg]){svg.replaceChildren();svg.append(svgNode("text",{x:120,y:120,class:"hardware-mark-label"},"Choose a valid closed track"))}$("#hardwareSummary").textContent="Hardware preview unavailable"}}
  function selectPenHole(hole,announce=true){hole=Number(hole);const activeLayer=getActiveLayerIndex(),layer=getActiveLayer();if(!Number.isInteger(hole)||hole<1||hole>6||!layer)return;layer.pen_hole=hole;const select=document.querySelector(`[data-layer="${activeLayer}"] [data-field="pen_hole"]`);if(select)select.value=String(hole);if(announce)$("#holeSelectionStatus").textContent=`Drawing ${activeLayer+1} now uses pen hole ${hole}.`;schedulePreview()}
  function hardwareHoleTarget(event){return event.target.closest?.("[data-hole]")}
  $("#gearHardware").addEventListener("click",event=>{const target=hardwareHoleTarget(event);if(target)selectPenHole(target.dataset.hole)});
  $("#gearHardware").addEventListener("keydown",event=>{const target=hardwareHoleTarget(event);if(!target)return;const current=Number(target.dataset.hole);let next=current;if(["Enter"," "].includes(event.key))next=current;else if(["ArrowRight","ArrowDown"].includes(event.key))next=current===6?1:current+1;else if(["ArrowLeft","ArrowUp"].includes(event.key))next=current===1?6:current-1;else if(event.key==="Home")next=1;else if(event.key==="End")next=6;else return;event.preventDefault();selectPenHole(next);requestAnimationFrame(()=>$("#gearHardware").querySelector(`[data-hole="${next}"]`)?.focus())});
  return{render};
}
