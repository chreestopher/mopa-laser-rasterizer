import {bounds,curvePoints,trackPoints} from "./geometry-v2.js";

const $=value=>document.querySelector(value);

export function createCanvasPreview({colors,getLayers,getActiveLayerIndex,getDiameter,renderHardware}){
  let previewFrame;
  function previewColor(layer,index){const value=String(layer?.swatch_hex||"").toUpperCase();return/^#[0-9A-F]{6}$/.test(value)?value:colors[index%colors.length]}
  function drawLayer(canvas,layer,index,alpha=1,clear=false){const context=canvas.getContext("2d");if(clear)context.clearRect(0,0,canvas.width,canvas.height);let curve,track;try{curve=curvePoints(layer);track=layer.include_track?trackPoints(layer):null}catch{return}const b=bounds(track?[...curve,...track]:curve),extent=Math.max(b[2]-b[0],b[3]-b[1])||1,drawingScale=Math.max(.2,Math.min(1,Number(layer.drawing_size_percent??100)/100)),scale=canvas.width*.84/extent*drawingScale,cx=(b[0]+b[2])/2,cy=(b[1]+b[3])/2;context.save();context.globalAlpha=alpha;context.translate(canvas.width/2-cx*scale,canvas.height/2-cy*scale);context.scale(scale,scale);context.beginPath();curve.forEach(([x,y],i)=>i?context.lineTo(x,y):context.moveTo(x,y));context.strokeStyle=previewColor(layer,index);context.lineJoin="round";context.lineCap="round";context.lineWidth=layer.output_mode==="fill"?Math.max(.002,Number(layer.fill_thickness_mm)/(Number(getDiameter())||150)*extent/drawingScale):.0025/drawingScale;context.stroke();if(track){context.beginPath();track.forEach(([x,y],i)=>i?context.lineTo(x,y):context.moveTo(x,y));context.closePath();context.globalAlpha=alpha*.4;context.lineWidth=.002/drawingScale;context.stroke()}context.restore()}
  function schedulePreview(){cancelAnimationFrame(previewFrame);previewFrame=requestAnimationFrame(()=>{renderHardware();const layers=getLayers(),activeLayer=getActiveLayerIndex();drawLayer($("#activePreview"),layers[activeLayer],activeLayer,1,true);const canvas=$("#stackPreview"),context=canvas.getContext("2d");context.clearRect(0,0,canvas.width,canvas.height);layers.forEach((layer,index)=>drawLayer(canvas,layer,index,.68,false))})}
  return{schedulePreview};
}
