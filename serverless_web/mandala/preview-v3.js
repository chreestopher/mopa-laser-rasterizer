import {builtInPath,drawComposedMotifs,drawFlowingPattern,drawMotif,supportBridgePath} from "./geometry-v1.js";

export const COLORS=["#e44d61","#f39c49","#e4d354","#72c66a","#43b7a7","#4c9dde","#6c70d8","#9b63c7","#d05aa8","#bc7c58","#8b9a52","#5e8792"];

export function createMandalaPreview({query,getLayers,getActiveLayer}){
  let previewFrame;

  function schedulePreview(){
    cancelAnimationFrame(previewFrame);
    previewFrame=requestAnimationFrame(drawPreviews);
  }

  async function customImage(layer){
    if(!layer.custom_svg)return null;
    if(layer._image)return layer._image;
    if(layer._imagePromise)return layer._imagePromise;
    layer._imagePromise=new Promise((resolve,reject)=>{
      const image=new Image(),url=URL.createObjectURL(new Blob([layer.custom_svg.svg],{type:"image/svg+xml"}));
      image.onload=()=>{URL.revokeObjectURL(url);layer._image=image;resolve(image)};
      image.onerror=()=>{URL.revokeObjectURL(url);reject(new Error("Custom image preview failed"))};
      image.src=url;
    }).catch(()=>null);
    return layer._imagePromise;
  }

  function drawLayer(canvas,layer,index,alpha=1){
    const context=canvas.getContext("2d"),size=canvas.width,center=size/2,projectRadius=size*.43;
    const projectDiameter=Math.max(20,Number(query("#diameter").value)||150),layerDiameter=Math.max(20,Math.min(projectDiameter,Number(layer.layer_diameter_mm)||projectDiameter));
    const radius=projectRadius*layerDiameter/projectDiameter,scale=projectRadius/projectDiameter*2;
    const inner=radius*Number(layer.inner_radius_ratio),rim=Math.max(2,Number(layer.rim_width_mm)*scale),outer=radius-rim*1.2;
    const rings=Math.max(1,Number(layer.rings)),repetitions=Math.max(4,Number(layer.repetitions)),ringStep=(outer-inner)/rings;
    const bridgeWidth=Math.min(Number(layer.bridge_width_mm)*scale,Math.max(.4*scale,ringStep*.24));
    context.save();context.globalAlpha=alpha;context.translate(center,center);
    context.beginPath();context.arc(0,0,radius,0,Math.PI*2);context.clip();
    context.fillStyle=COLORS[index%COLORS.length];
    if(layer.construction==="cutout"){context.beginPath();context.arc(0,0,radius,0,Math.PI*2);context.fill();context.globalCompositeOperation="destination-out"}
    else context.globalCompositeOperation="source-over";
    if((layer.motif_composition??"hybrid")!=="flow_character")drawComposedMotifs(context,layer,inner,outer,rings,repetitions);
    else if(layer.motif!=="custom"&&Number(layer.flow_amount??.92)>0)drawFlowingPattern(context,layer,inner,outer,rings,repetitions);
    else for(let ring=0;ring<rings;ring++){
      const fraction=(ring+.5)/rings,ringRadius=inner+fraction*(outer-inner),motifSize=ringStep*Number(layer.motif_scale),phase=Number(layer.rotation_degrees)+fraction*Number(layer.twist_degrees)+(layer.alternate_rotation&&ring%2?180/repetitions:0);
      for(let repeat=0;repeat<repetitions;repeat++){context.save();context.rotate((phase+repeat*360/repetitions)*Math.PI/180);context.translate(ringRadius,0);context.scale(Number(layer.radial_stretch),Number(layer.tangent_stretch)*(layer.mirror_alternating&&repeat%2?-1:1));drawMotif(context,layer,motifSize);context.restore()}
    }
    if(Number(layer.layer_openness??0)>0){
      context.globalCompositeOperation="destination-out";
      const openness=Number(layer.layer_openness),innerOpening=Math.max(Math.max(rim,inner*.42)*1.08,radius*Number(layer.opening_inner_ratio??.25)),outerOpening=radius-rim*1.15,sector=Math.PI*2/repetitions,half=sector*.41*openness,openingRotation=Number(layer.opening_rotation_degrees??0)*Math.PI/180;
      for(let repeat=0;repeat<repetitions;repeat++){
        const center=openingRotation+(repeat+.5)*sector;
        context.beginPath();context.arc(0,0,outerOpening,center-half,center+half);context.arc(0,0,innerOpening,center+half,center-half,true);context.closePath();context.fill();
      }
    }
    context.globalCompositeOperation="source-over";
    const rimStyle=layer.rim_style??"closed",petalRadial=Math.max(rim*3,radius*.1),outerAnchor=rimStyle==="petal"?radius-petalRadial*.58:rimStyle==="open"?radius-bridgeWidth/2:radius-rim/2;
    if(layer.support_mode!=="loose"){
      context.strokeStyle=COLORS[index%COLORS.length];context.lineWidth=rim;
      if(rimStyle==="closed"){context.beginPath();context.arc(0,0,radius-rim/2,0,Math.PI*2);context.stroke()}
      if(rimStyle==="petal"){
        const petal=builtInPath("petal"),tangentRoom=Math.PI*2*radius/repetitions,petalTangent=Math.min(petalRadial*.72,tangentRoom*.68);
        for(let repeat=0;repeat<repetitions;repeat++){context.save();context.rotate((Number(layer.support_sweep_degrees??0)+repeat*360/repetitions)*Math.PI/180);context.translate(outerAnchor,0);context.scale(petalRadial,petalTangent);context.fill(petal);context.restore()}
      }
      context.beginPath();context.arc(0,0,Math.max(rim,inner*.42),0,Math.PI*2);context.fill();
    }
    if(["automatic_bridges","fully_connected"].includes(layer.support_mode)){
      context.strokeStyle=COLORS[index%COLORS.length];context.lineWidth=Math.max(1,bridgeWidth*(layer.support_mode==="fully_connected"?1.35:1));
      context.lineCap="round";context.lineJoin="round";
      const hubRadius=Math.max(rim,inner*.42),waveAmplitude=Math.min(Number(layer.bridge_wave_amplitude_mm??6)*scale,ringStep*1.5);
      for(let repeat=0;repeat<repetitions;repeat++)context.stroke(supportBridgePath(hubRadius*.75,outerAnchor,repeat*360/repetitions,Number(layer.support_sweep_degrees??0),Number(layer.bridge_wave_amount??0),waveAmplitude,Number(layer.bridge_wave_position??.5)));
    }
    if(layer.support_mode==="fully_connected"){context.lineWidth=Math.max(1,bridgeWidth);context.beginPath();context.arc(0,0,(inner+outer)/2,0,Math.PI*2);context.stroke()}
    context.restore();
  }

  async function drawPreviews(){
    const layers=getLayers(),activeLayer=getActiveLayer();
    for(const layer of layers)if(layer.motif==="custom"&&layer.custom_svg&&!layer._image)customImage(layer).then(schedulePreview);
    for(const id of ["activePreview","stackPreview"]){const canvas=query("#"+id),context=canvas.getContext("2d");context.clearRect(0,0,canvas.width,canvas.height)}
    drawLayer(query("#activePreview"),layers[activeLayer],activeLayer,1);
    layers.forEach((layer,index)=>drawLayer(query("#stackPreview"),layer,index,.38));
  }

  return{schedulePreview,drawPreviews,drawLayer};
}
