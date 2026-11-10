import {
  applyArtworkCrop,
  effectiveArtworkFile,
  getCropSelection,
} from './artwork-preview-v1.js';
import {
  base64ToBytes,
  normalizeShapeImage,
} from './shape-assets-v1.js';

const FLOW_COLORS=['#65d46e','#58b7ff','#ffb347','#e66fff','#ff637d','#50dbc8','#d8d85a','#b69cff'];
const newFlowRegion=(index,regionType='painted')=>({name:`${regionType==='image_mask'?'Image mask':'Painted region'} ${index+1}`,region_type:regionType,scope:'combined_region',guide_type:'linear',orientation:'parallel',start:[.25,.5],end:[.75,.5],gradient_start:165,gradient_end:90,curve:1,fixed_angle:0,angle_offset:0,reverse:false,mask:null,mask_name:'',mask_mode:'grayscale',mask_threshold:.01,mask_invert:false,mask_offset:[0,0]});

let configured=false, showStatus=()=>{}, flowBitmap=null, flowTool='paint', flowDrawing=null, flowActiveRegion=0;
let fauxlogramFlow={enabled:false,regions:[newFlowRegion(0)],strokes:[]};

export function getFauxlogramFlow(){return fauxlogramFlow}
function flowHasContent(){return fauxlogramFlow.strokes.some(stroke=>!stroke.erase)||fauxlogramFlow.regions.some(region=>region.mask)}
function updateFlowSummary(){const painted=fauxlogramFlow.strokes.filter(stroke=>!stroke.erase).length,masks=fauxlogramFlow.regions.filter(region=>region.mask).length,summary=document.querySelector('#flowPainterSummary');summary.textContent=fauxlogramFlow.enabled&&(painted||masks)?`${fauxlogramFlow.regions.length} flow region${fauxlogramFlow.regions.length===1?'':'s'} · ${painted} painted shape${painted===1?'':'s'} · ${masks} image mask${masks===1?'':'s'} · unassigned cells use the standard gradient.`:'Optional: paint regions or upload masks that use their own gradient and grating direction.'}
export function resetFauxlogramFlow(){fauxlogramFlow={enabled:false,regions:[newFlowRegion(0)],strokes:[]};flowActiveRegion=0;updateFlowSummary()}
export function restoreFauxlogramFlow(flow){fauxlogramFlow=flow;flowActiveRegion=0;updateFlowSummary()}
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
function flowMaskPreviewPixels(region,values,alphaValues,color){
  const grayscale=(region.mask_mode||'grayscale')==='grayscale',maskValues=!grayscale&&alphaValues?alphaValues:values,threshold=Math.round((region.mask_threshold??.5)*255),pixels=new Uint8ClampedArray(maskValues.length*4),red=parseInt(color.slice(1,3),16),green=parseInt(color.slice(3,5),16),blue=parseInt(color.slice(5,7),16);
  for(let pixel=0;pixel<maskValues.length;pixel++){
    const value=region.mask_invert?255-maskValues[pixel]:maskValues[pixel],position=pixel*4;
    if(grayscale){
      const coverage=alphaValues?alphaValues[pixel]:255,active=coverage>0&&value>=threshold;
      pixels[position]=value;pixels[position+1]=value;pixels[position+2]=value;pixels[position+3]=active?coverage:0;
    }else{
      const active=value>=threshold&&value>0;
      pixels[position]=red;pixels[position+1]=green;pixels[position+2]=blue;pixels[position+3]=active?Math.round(255*.55):0;
    }
  }
  return pixels;
}
function drawFlowMask(paint,region,index,width,height){if(!region.mask)return;const spec=region.mask,values=base64ToBytes(spec.data),alphaValues=spec.alpha?base64ToBytes(spec.alpha):null,source=document.createElement('canvas');source.width=spec.width;source.height=spec.height;const sourceContext=source.getContext('2d'),image=sourceContext.createImageData(spec.width,spec.height),color=FLOW_COLORS[index%FLOW_COLORS.length],offset=region.mask_offset||[0,0];image.data.set(flowMaskPreviewPixels(region,values,alphaValues,color));sourceContext.putImageData(image,0,0);paint.drawImage(source,offset[0]*width,offset[1]*height,width,height)}
function drawFlowPainter(){const canvas=document.querySelector('#flowCanvas');if(!canvas.width)return;const context=canvas.getContext('2d');context.clearRect(0,0,canvas.width,canvas.height);if(flowBitmap)context.drawImage(flowBitmap,0,0,canvas.width,canvas.height);const overlay=document.createElement('canvas');overlay.width=canvas.width;overlay.height=canvas.height;const paint=overlay.getContext('2d');fauxlogramFlow.regions.forEach((region,index)=>drawFlowMask(paint,region,index,canvas.width,canvas.height));paint.lineCap='round';paint.lineJoin='round';for(const stroke of fauxlogramFlow.strokes){const points=stroke.points||[];if(!points.length)continue;paint.save();paint.globalCompositeOperation=stroke.erase?'destination-out':'source-over';paint.strokeStyle=stroke.erase?'#000':FLOW_COLORS[stroke.region%FLOW_COLORS.length]+'b8';paint.fillStyle=paint.strokeStyle;paint.lineWidth=stroke.width*Math.min(canvas.width,canvas.height);paint.beginPath();paint.moveTo(points[0][0]*canvas.width,points[0][1]*canvas.height);for(const point of points.slice(1))paint.lineTo(point[0]*canvas.width,point[1]*canvas.height);if(points.length===1)paint.arc(points[0][0]*canvas.width,points[0][1]*canvas.height,paint.lineWidth/2,0,Math.PI*2);paint.stroke();if(points.length===1)paint.fill();paint.restore()}context.drawImage(overlay,0,0);fauxlogramFlow.regions.forEach((region,index)=>{if(region.region_type==='image_mask'&&(region.mask_mode||'grayscale')==='grayscale')return;const start=[region.start[0]*canvas.width,region.start[1]*canvas.height],end=[region.end[0]*canvas.width,region.end[1]*canvas.height],color=FLOW_COLORS[index%FLOW_COLORS.length];context.save();context.strokeStyle=color;context.fillStyle=color;context.lineWidth=index===flowActiveRegion?4:2;context.beginPath();if(region.guide_type==='radial'){const radius=Math.hypot(end[0]-start[0],end[1]-start[1]);context.arc(start[0],start[1],radius,0,Math.PI*2)}else{context.moveTo(...start);context.lineTo(...end)}context.stroke();context.beginPath();context.arc(start[0],start[1],6,0,Math.PI*2);context.fill();context.beginPath();context.arc(end[0],end[1],6,0,Math.PI*2);context.fill();context.restore()})}
async function openFlowPainter(){const cropSelection=getCropSelection();if(cropSelection&&cropSelection.width>=2&&cropSelection.height>=2)await applyArtworkCrop();const file=effectiveArtworkFile();if(!file){showStatus('Choose artwork before opening the Fauxlogram Flow Painter.');return}try{flowBitmap?.close?.();flowBitmap=await createImageBitmap(file);const dialog=document.querySelector('#flowPainter');dialog.showModal();await new Promise(resolve=>requestAnimationFrame(resolve));resizeFlowCanvas();syncFlowRegionEditor()}catch(error){document.querySelector('#flowPainter').close();showStatus(`Could not open Fauxlogram Flow Painter: ${error.message}`)}}
function setFlowTool(tool){flowTool=tool;document.querySelectorAll('[data-flow-tool]').forEach(button=>button.classList.toggle('active',button.dataset.flowTool===tool))}

export function configureFlowPainter({show}){
  if(configured)return;
  configured=true;
  showStatus=show;
  document.querySelector('[data-flow-tool="guide"]').insertAdjacentHTML('afterend','<button type="button" data-flow-tool="move">Move mask</button>');
  document.querySelector('#flowAddMaskRegion').onclick=()=>{if(fauxlogramFlow.regions.length>=8)return;saveFlowRegionEditor();if(fauxlogramFlow.regions.length===1&&!flowHasContent()&&activeFlowRegion().region_type==='painted'){fauxlogramFlow.regions[0]=newFlowRegion(0,'image_mask');flowActiveRegion=0}else{flowActiveRegion=fauxlogramFlow.regions.length;fauxlogramFlow.regions.push(newFlowRegion(flowActiveRegion,'image_mask'))}syncFlowRegionEditor()};
  document.querySelector('#flowMaskMode').addEventListener('change',()=>{saveFlowRegionEditor();syncFlowRegionEditor()});
  document.querySelector('#openFlowPainter').onclick=openFlowPainter;document.querySelector('#closeFlowPainter').onclick=()=>document.querySelector('#flowPainter').close();document.querySelector('#flowDone').onclick=()=>{saveFlowRegionEditor();fauxlogramFlow.enabled=flowHasContent();updateFlowSummary();document.querySelector('#flowPainter').close()};document.querySelector('#flowDisable').onclick=()=>{fauxlogramFlow.enabled=false;updateFlowSummary();document.querySelector('#flowPainter').close()};document.querySelectorAll('[data-flow-tool]').forEach(button=>button.onclick=()=>setFlowTool(button.dataset.flowTool));document.querySelector('#flowRegion').onchange=event=>{saveFlowRegionEditor();flowActiveRegion=Number(event.target.value)||0;syncFlowRegionEditor()};document.querySelector('#flowAddRegion').onclick=()=>{if(fauxlogramFlow.regions.length>=8)return;saveFlowRegionEditor();flowActiveRegion=fauxlogramFlow.regions.length;fauxlogramFlow.regions.push(newFlowRegion(flowActiveRegion));syncFlowRegionEditor()};document.querySelector('#flowDeleteRegion').onclick=()=>{if(fauxlogramFlow.regions.length<=1){if(activeFlowRegion().region_type==='image_mask'){fauxlogramFlow.regions=[newFlowRegion(0)];fauxlogramFlow.strokes=[];fauxlogramFlow.enabled=false;flowActiveRegion=0;updateFlowSummary();syncFlowRegionEditor()}return}fauxlogramFlow.regions.splice(flowActiveRegion,1);fauxlogramFlow.strokes=fauxlogramFlow.strokes.filter(stroke=>stroke.region!==flowActiveRegion).map(stroke=>({...stroke,region:stroke.region>flowActiveRegion?stroke.region-1:stroke.region}));flowActiveRegion=Math.max(0,flowActiveRegion-1);syncFlowRegionEditor()};document.querySelector('#flowClearRegion').onclick=()=>{fauxlogramFlow.strokes=fauxlogramFlow.strokes.filter(stroke=>stroke.region!==flowActiveRegion);const region=activeFlowRegion();region.mask=null;region.mask_name='';syncFlowRegionEditor()};document.querySelector('#flowMaskFile').onchange=async event=>{const region=activeFlowRegion(),file=event.target.files[0];if(!file)return;try{region.mask=await normalizeShapeImage(file,96,'grayscale');region.mask_name=file.name;syncFlowRegionEditor()}catch(error){region.mask=null;region.mask_name='';document.querySelector('#flowMaskStatus').textContent=error.message;drawFlowPainter()}};document.querySelector('#flowRemoveMask').onclick=()=>{const region=activeFlowRegion();region.mask=null;region.mask_name='';document.querySelector('#flowMaskFile').value='';syncFlowRegionEditor()};for(const id of ['flowScope','flowGuideType','flowOrientation','flowGradientStart','flowGradientEnd','flowCurve','flowFixedAngle','flowAngleOffset','flowReverse','flowMaskMode','flowMaskThreshold','flowMaskInvert'])document.querySelector('#'+id).oninput=saveFlowRegionEditor;
  document.querySelector('#flowCanvas').onpointerdown=event=>{event.currentTarget.setPointerCapture(event.pointerId);const point=flowPoint(event),region=activeFlowRegion();if(flowTool==='guide'){region.start=point;region.end=point;flowDrawing={guide:true}}else if(flowTool==='move'){if(!region.mask){showStatus('Upload an image mask for this region before moving it.');return}flowDrawing={move:true,start:point,offset:[...(region.mask_offset||[0,0])]}}else{const width=Number(document.querySelector('#flowBrush').value)/100;flowDrawing={region:flowActiveRegion,erase:flowTool==='erase',width,points:[point]};fauxlogramFlow.strokes.push(flowDrawing)}drawFlowPainter()};document.querySelector('#flowCanvas').onpointermove=event=>{if(!flowDrawing)return;const point=flowPoint(event);if(flowDrawing.guide)activeFlowRegion().end=point;else if(flowDrawing.move){activeFlowRegion().mask_offset=[Math.max(-1,Math.min(1,flowDrawing.offset[0]+point[0]-flowDrawing.start[0])),Math.max(-1,Math.min(1,flowDrawing.offset[1]+point[1]-flowDrawing.start[1]))]}else{const last=flowDrawing.points.at(-1);if(Math.hypot(point[0]-last[0],point[1]-last[1])>=.003&&flowDrawing.points.length<512)flowDrawing.points.push(point)}drawFlowPainter()};document.querySelector('#flowCanvas').onpointerup=event=>{if(!flowDrawing)return;document.querySelector('#flowCanvas').onpointermove(event);flowDrawing=null};document.querySelector('#flowCanvas').onpointercancel=()=>{flowDrawing=null};
  window.addEventListener('resize',()=>{if(document.querySelector('#flowPainter').open)resizeFlowCanvas()});
}
