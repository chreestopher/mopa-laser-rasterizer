let dependencies=null;
let controlsBound=false;
let cropBitmap=null;
let cropSelection=null;
let cropDragStart=null;
let cropDragMode='';
let cropDragReference=null;
let cropResizeAnchor=null;
let croppedArtworkFile=null;
let appliedCropShape='';
let transparencyCropOutline=null;

export function configureArtworkPreview(options){
  dependencies=options;
  if(controlsBound)return;
  controlsBound=true;
  document.querySelector('#generateQuantPreview').onclick=generateQuantizedPreview;
  document.querySelector('#whiteIs').onchange=markQuantPreviewStale;
  document.querySelector('#artwork').addEventListener('change',()=>{
    dependencies.resetFauxlogramFlow();
    markQuantPreviewStale();
    initializeCropPreview();
    dependencies.syncPanelTiling();
  });
  document.querySelector('#cropShape').onchange=()=>{
    cropSelection=null;
    cropDragStart=null;
    cropDragMode='';
    cropDragReference=null;
    cropResizeAnchor=null;
    document.querySelector('#applyCrop').disabled=true;
    drawCropPreview();
    document.querySelector('#cropStatus').textContent=appliedCropShape?`The ${appliedCropShape} crop remains applied. Drag a new ${document.querySelector('#cropShape').value} selection and click Apply crop to replace it.`:`Drag across the image to select a ${document.querySelector('#cropShape').value} crop.`;
  };
  document.querySelector('#applyCrop').onclick=applyArtworkCrop;
  document.querySelector('#cropTransparency').onclick=applyTransparencyCrop;
  document.querySelector('#resetCrop').onclick=resetArtworkCrop;
  document.querySelector('#cropCanvas').onpointerdown=event=>{
    if(!cropBitmap)return;
    event.currentTarget.setPointerCapture(event.pointerId);
    const point=cropPoint(event),handle=cropHandleAt(point);
    cropDragStart=point;
    cropDragReference=cropSelection?{...cropSelection}:null;
    if(handle){
      cropDragMode='resize';
      cropResizeAnchor=oppositeCropCorner(handle);
    }else if(cropPointInside(point)){
      cropDragMode='move';
      cropResizeAnchor=null;
    }else{
      cropDragMode='new';
      cropResizeAnchor=null;
      cropSelection={x:point.x,y:point.y,width:0,height:0};
    }
    document.querySelector('#applyCrop').disabled=true;
    drawCropPreview();
  };
  document.querySelector('#cropCanvas').onpointermove=event=>{
    if(!cropDragStart)return;
    const point=cropPoint(event),canvas=document.querySelector('#cropCanvas'),shape=document.querySelector('#cropShape').value;
    if(cropDragMode==='move'&&cropDragReference){
      const x=Math.max(0,Math.min(canvas.width-cropDragReference.width,cropDragReference.x+point.x-cropDragStart.x)),y=Math.max(0,Math.min(canvas.height-cropDragReference.height,cropDragReference.y+point.y-cropDragStart.y));
      cropSelection={...cropDragReference,x,y};
    }else if(cropDragMode==='resize'&&cropResizeAnchor)cropSelection=normalizedCropSelection(cropResizeAnchor,point,shape);
    else cropSelection=normalizedCropSelection(cropDragStart,point,shape);
    drawCropPreview();
  };
  document.querySelector('#cropCanvas').onpointerup=event=>{
    if(!cropDragStart)return;
    document.querySelector('#cropCanvas').onpointermove(event);
    cropDragStart=null;
    cropDragMode='';
    cropDragReference=null;
    cropResizeAnchor=null;
    const valid=cropSelection&&cropSelection.width>=2&&cropSelection.height>=2;
    document.querySelector('#applyCrop').disabled=!valid;
    document.querySelector('#cropStatus').textContent=valid?'Selection ready. Drag inside to move it or a corner to resize it. It will apply automatically on submission; click Crop preview to preview it now.':'Drag a larger crop selection.';
    drawCropPreview();
  };
  document.querySelector('#cropCanvas').onpointercancel=()=>{
    cropDragStart=null;
    cropDragMode='';
    cropDragReference=null;
    cropResizeAnchor=null;
  };
  document.querySelector('#pixel').addEventListener('input',markQuantPreviewStale);
  document.querySelector('#width').addEventListener('input',markQuantPreviewStale);
  document.querySelector('#height').addEventListener('input',markQuantPreviewStale);
}

export function getCropSelection(){return cropSelection}
export function getAppliedCropShape(){return appliedCropShape}

export function markQuantPreviewStale(){
  const output=document.querySelector('#quantPreviewOutput'),status=document.querySelector('#quantPreviewStatus'),canvas=document.querySelector('#quantPreviewCanvas');
  canvas?.classList.toggle('transparency-grid',appliedCropShape==='transparency'||document.querySelector('#whiteIs').value==='unengraved');
  if(output&&!output.hidden){
    output.hidden=true;
    status.textContent='Preview settings changed. Generate it again to use the currently enabled swatches.';
  }
}

function renderQuantPreviewCounts(swatches,counts,total){
  document.querySelector('#quantPreviewCounts').innerHTML=swatches.map(item=>{
    const count=counts.get(item.hex)||0,percent=total?count/total*100:0;
    return `<div class="quant-preview-usage" title="${dependencies.esc(item.name)}"><span class="quant-preview-chip" style="background:${dependencies.esc(item.hex)}"></span><strong>${dependencies.esc(item.name)}</strong><small>${count.toLocaleString()} · ${percent.toFixed(1)}%</small></div>`;
  }).join('');
}

export async function loadPreviewBitmap(file){
  if(window.createImageBitmap)return createImageBitmap(file);
  const url=URL.createObjectURL(file);
  try{return await new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>resolve(image);image.onerror=()=>reject(new Error('The artwork image could not be decoded'));image.src=url})}
  finally{URL.revokeObjectURL(url)}
}

export function effectiveArtworkFile(){return croppedArtworkFile||document.querySelector('#artwork').files[0]||null}

function cropPoint(event){
  const canvas=document.querySelector('#cropCanvas'),bounds=canvas.getBoundingClientRect();
  return{x:Math.max(0,Math.min(canvas.width,(event.clientX-bounds.left)*canvas.width/bounds.width)),y:Math.max(0,Math.min(canvas.height,(event.clientY-bounds.top)*canvas.height/bounds.height))};
}

function normalizedCropSelection(start,end,shape){
  let endX=end.x,endY=end.y;
  if(shape==='square'||shape==='circle'){
    const side=Math.min(Math.abs(endX-start.x),Math.abs(endY-start.y));
    endX=start.x+(endX>=start.x?side:-side);
    endY=start.y+(endY>=start.y?side:-side);
  }
  return{x:Math.min(start.x,endX),y:Math.min(start.y,endY),width:Math.abs(endX-start.x),height:Math.abs(endY-start.y)};
}

function cropCorners(selection){return{nw:{x:selection.x,y:selection.y},ne:{x:selection.x+selection.width,y:selection.y},se:{x:selection.x+selection.width,y:selection.y+selection.height},sw:{x:selection.x,y:selection.y+selection.height}}}

function cropHandleAt(point){
  if(!cropSelection)return'';
  const threshold=Math.max(10,document.querySelector('#cropCanvas').width/80),corners=cropCorners(cropSelection);
  return Object.keys(corners).find(name=>Math.hypot(point.x-corners[name].x,point.y-corners[name].y)<=threshold)||'';
}

function cropPointInside(point){return Boolean(cropSelection&&point.x>=cropSelection.x&&point.x<=cropSelection.x+cropSelection.width&&point.y>=cropSelection.y&&point.y<=cropSelection.y+cropSelection.height)}
function oppositeCropCorner(handle){const corners=cropCorners(cropSelection);return corners[{nw:'se',ne:'sw',se:'nw',sw:'ne'}[handle]]}

function cropSelectionPath(context,selection,shape){
  context.beginPath();
  if(shape==='oval'||shape==='circle')context.ellipse(selection.x+selection.width/2,selection.y+selection.height/2,selection.width/2,selection.height/2,0,0,Math.PI*2);
  else context.rect(selection.x,selection.y,selection.width,selection.height);
}

function drawCropPreview(){
  const canvas=document.querySelector('#cropCanvas');
  if(!cropBitmap||!canvas.width)return;
  const context=canvas.getContext('2d');
  context.clearRect(0,0,canvas.width,canvas.height);
  context.drawImage(cropBitmap,0,0,canvas.width,canvas.height);
  if(transparencyCropOutline)context.drawImage(transparencyCropOutline,0,0);
  if(cropSelection&&cropSelection.width>1&&cropSelection.height>1){
    context.save();
    context.fillStyle='rgba(4,9,14,.58)';
    context.fillRect(0,0,canvas.width,canvas.height);
    context.globalCompositeOperation='destination-out';
    cropSelectionPath(context,cropSelection,document.querySelector('#cropShape').value);
    context.fill();
    context.globalCompositeOperation='source-over';
    cropSelectionPath(context,cropSelection,document.querySelector('#cropShape').value);
    context.strokeStyle='#8ee474';
    context.lineWidth=Math.max(2,canvas.width/350);
    context.setLineDash([8,5]);
    context.stroke();
    context.setLineDash([]);
    const handleSize=Math.max(8,canvas.width/65);
    context.fillStyle='#8ee474';
    context.strokeStyle='#101419';
    context.lineWidth=Math.max(1,canvas.width/700);
    for(const point of Object.values(cropCorners(cropSelection))){
      context.fillRect(point.x-handleSize/2,point.y-handleSize/2,handleSize,handleSize);
      context.strokeRect(point.x-handleSize/2,point.y-handleSize/2,handleSize,handleSize);
    }
    context.restore();
  }
}

async function initializeCropPreview(){
  const file=document.querySelector('#artwork').files[0],panel=document.querySelector('#artworkCropPanel'),status=document.querySelector('#cropStatus');
  cropBitmap?.close?.();
  cropBitmap=null;
  cropSelection=null;
  cropDragStart=null;
  cropDragMode='';
  cropDragReference=null;
  cropResizeAnchor=null;
  croppedArtworkFile=null;
  appliedCropShape='';
  transparencyCropOutline=null;
  document.querySelector('#applyCrop').disabled=true;
  document.querySelector('#cropTransparency').disabled=true;
  document.querySelector('#resetCrop').disabled=true;
  if(!file){panel.hidden=true;return}
  panel.hidden=false;
  status.textContent='Loading artwork for cropping…';
  try{
    cropBitmap=await loadPreviewBitmap(file);
    const sourceWidth=cropBitmap.width||cropBitmap.naturalWidth,sourceHeight=cropBitmap.height||cropBitmap.naturalHeight,scale=Math.min(1,1000/sourceWidth,600/sourceHeight),canvas=document.querySelector('#cropCanvas');
    canvas.width=Math.max(1,Math.round(sourceWidth*scale));
    canvas.height=Math.max(1,Math.round(sourceHeight*scale));
    document.querySelector('#cropTransparency').disabled=false;
    drawCropPreview();
    status.textContent=`Original artwork · ${sourceWidth.toLocaleString()} × ${sourceHeight.toLocaleString()} pixels. Drag to select a crop or crop all transparent regions automatically.`;
  }catch(error){
    panel.hidden=true;
    status.textContent=`Could not prepare crop preview: ${error.message}`;
  }
}

function cropOutputName(file){const base=String(file.name||'artwork').replace(/\.[^.]*$/,'').slice(0,160)||'artwork';return `${base}-cropped.png`}

function buildTransparencyOutline(bitmap,width,height){
  const mask=document.createElement('canvas');
  mask.width=width;
  mask.height=height;
  const maskContext=mask.getContext('2d',{willReadFrequently:true});
  maskContext.imageSmoothingEnabled=false;
  maskContext.drawImage(bitmap,0,0,width,height);
  const source=maskContext.getImageData(0,0,width,height),outline=maskContext.createImageData(width,height);
  for(let y=0;y<height;y++)for(let x=0;x<width;x++){
    const offset=(y*width+x)*4;
    if(source.data[offset+3]===0)continue;
    let edge=x===0||y===0||x===width-1||y===height-1;
    for(let dy=-1;!edge&&dy<=1;dy++)for(let dx=-1;!edge&&dx<=1;dx++){
      if(!dx&&!dy)continue;
      const neighbor=((y+dy)*width+x+dx)*4;
      if(source.data[neighbor+3]===0)edge=true;
    }
    if(edge){
      outline.data[offset]=142;
      outline.data[offset+1]=228;
      outline.data[offset+2]=116;
      outline.data[offset+3]=255;
    }
  }
  maskContext.clearRect(0,0,width,height);
  maskContext.putImageData(outline,0,0);
  return mask;
}

async function applyTransparencyCrop(){
  const source=document.querySelector('#artwork').files[0],status=document.querySelector('#cropStatus'),button=document.querySelector('#cropTransparency');
  if(!source||!cropBitmap)return false;
  button.disabled=true;
  try{
    const sourceWidth=cropBitmap.width||cropBitmap.naturalWidth,sourceHeight=cropBitmap.height||cropBitmap.naturalHeight,canvas=document.createElement('canvas');
    canvas.width=sourceWidth;
    canvas.height=sourceHeight;
    const context=canvas.getContext('2d',{willReadFrequently:true});
    context.drawImage(cropBitmap,0,0);
    const pixels=context.getImageData(0,0,sourceWidth,sourceHeight).data;
    let minX=sourceWidth,minY=sourceHeight,maxX=-1,maxY=-1,transparentPixels=0;
    for(let y=0;y<sourceHeight;y++)for(let x=0;x<sourceWidth;x++){
      const alpha=pixels[(y*sourceWidth+x)*4+3];
      if(alpha>0){minX=Math.min(minX,x);minY=Math.min(minY,y);maxX=Math.max(maxX,x);maxY=Math.max(maxY,y)}
      else transparentPixels++;
    }
    if(maxX<minX||maxY<minY)throw new Error('The artwork is entirely transparent');
    if(!transparentPixels){status.textContent='No transparent pixels were found, so the artwork was not changed.';return false}
    const width=maxX-minX+1,height=maxY-minY+1,output=document.createElement('canvas');
    output.width=width;
    output.height=height;
    output.getContext('2d').drawImage(canvas,minX,minY,width,height,0,0,width,height);
    const blob=await new Promise((resolve,reject)=>output.toBlob(value=>value?resolve(value):reject(new Error('The browser could not create the transparency-cropped image')),'image/png'));
    croppedArtworkFile=new File([blob],cropOutputName(source),{type:'image/png',lastModified:Date.now()});
    appliedCropShape='transparency';
    cropSelection=null;
    transparencyCropOutline=buildTransparencyOutline(cropBitmap,document.querySelector('#cropCanvas').width,document.querySelector('#cropCanvas').height);
    dependencies.resetFauxlogramFlow();
    document.querySelector('#applyCrop').disabled=true;
    document.querySelector('#resetCrop').disabled=false;
    drawCropPreview();
    status.textContent=`Transparency crop applied · ${width.toLocaleString()} × ${height.toLocaleString()} pixels. Exterior transparency and enclosed transparent holes will produce no geometry.`;
    markQuantPreviewStale();
    dependencies.syncPanelTiling();
    return true;
  }catch(error){
    status.textContent=`Could not crop transparency: ${error.message}`;
    return false;
  }finally{button.disabled=false}
}

export async function applyArtworkCrop(){
  const source=document.querySelector('#artwork').files[0],status=document.querySelector('#cropStatus'),button=document.querySelector('#applyCrop');
  if(!source||!cropBitmap||!cropSelection||cropSelection.width<2||cropSelection.height<2)return false;
  button.disabled=true;
  try{
    const canvas=document.querySelector('#cropCanvas'),sourceWidth=cropBitmap.width||cropBitmap.naturalWidth,sourceHeight=cropBitmap.height||cropBitmap.naturalHeight,scaleX=sourceWidth/canvas.width,scaleY=sourceHeight/canvas.height,sx=Math.max(0,Math.floor(cropSelection.x*scaleX)),sy=Math.max(0,Math.floor(cropSelection.y*scaleY)),ex=Math.min(sourceWidth,Math.ceil((cropSelection.x+cropSelection.width)*scaleX)),ey=Math.min(sourceHeight,Math.ceil((cropSelection.y+cropSelection.height)*scaleY)),width=Math.max(1,ex-sx),height=Math.max(1,ey-sy),shape=document.querySelector('#cropShape').value,output=document.createElement('canvas');
    output.width=width;
    output.height=height;
    const context=output.getContext('2d');
    if(shape==='oval'||shape==='circle'){
      context.beginPath();
      context.ellipse(width/2,height/2,width/2,height/2,0,0,Math.PI*2);
      context.clip();
    }
    context.drawImage(cropBitmap,sx,sy,width,height,0,0,width,height);
    const blob=await new Promise((resolve,reject)=>output.toBlob(value=>value?resolve(value):reject(new Error('The browser could not create the cropped image')),'image/png'));
    croppedArtworkFile=new File([blob],cropOutputName(source),{type:'image/png',lastModified:Date.now()});
    appliedCropShape=shape;
    transparencyCropOutline=null;
    dependencies.resetFauxlogramFlow();
    document.querySelector('#resetCrop').disabled=false;
    status.textContent=`Crop applied · ${shape} · ${width.toLocaleString()} × ${height.toLocaleString()} pixels. This cropped image will be previewed and processed.`;
    markQuantPreviewStale();
    dependencies.syncPanelTiling();
    return true;
  }catch(error){
    status.textContent=`Could not apply crop: ${error.message}`;
    return false;
  }finally{button.disabled=false}
}

function resetArtworkCrop(){
  croppedArtworkFile=null;
  appliedCropShape='';
  transparencyCropOutline=null;
  cropSelection=null;
  cropDragStart=null;
  cropDragMode='';
  cropDragReference=null;
  cropResizeAnchor=null;
  dependencies.resetFauxlogramFlow();
  document.querySelector('#applyCrop').disabled=true;
  document.querySelector('#resetCrop').disabled=true;
  drawCropPreview();
  const source=document.querySelector('#artwork').files[0],width=cropBitmap?.width||cropBitmap?.naturalWidth,height=cropBitmap?.height||cropBitmap?.naturalHeight;
  document.querySelector('#cropStatus').textContent=source?`Crop reset · original artwork ${width.toLocaleString()} × ${height.toLocaleString()} pixels will be processed.`:'Choose artwork to crop.';
  markQuantPreviewStale();
  dependencies.syncPanelTiling();
}

function rasterPreviewDimensions(sourceWidth,sourceHeight,requestedWidth,requestedHeight){
  const width=Math.max(0,Math.trunc(Number(requestedWidth)||0)),height=Math.max(0,Math.trunc(Number(requestedHeight)||0));
  if(height===0&&width!==0)return{width,height:Math.max(1,Math.trunc(sourceHeight*width/sourceWidth))};
  if(width===0&&height!==0)return{width:Math.max(1,Math.trunc(sourceWidth*height/sourceHeight)),height};
  return{width:sourceWidth,height:sourceHeight};
}

function previewMillimeters(pixels,pixelSize){const value=pixels*pixelSize;return value.toLocaleString(undefined,{maximumFractionDigits:4})}
function niceRulerStep(length){const rough=Math.max(length/8,Number.EPSILON),power=10**Math.floor(Math.log10(rough)),scaled=rough/power,multiple=scaled<=1?1:scaled<=2?2:scaled<=5?5:10;return Math.max(1,multiple*power)}

function rulerTickMarkup(length,axis){
  if(!(length>0))return'';
  const step=niceRulerStep(length),values=[0];
  for(let value=step;value<length;value+=step)values.push(value);
  const endpointGap=length-values.at(-1);
  if(endpointGap>step*.55)values.push(length);
  else values[values.length-1]=length;
  const coordinate=axis==='x'?'left':'top';
  return values.map(value=>`<i class="quant-ruler-tick" style="${coordinate}:${value/length*100}%"><span>${value.toLocaleString(undefined,{maximumFractionDigits:0})}</span></i>`).join('');
}

function renderPreviewRulers(widthMm,heightMm){
  document.querySelector('#quantPreviewRulerX').innerHTML=rulerTickMarkup(widthMm,'x');
  document.querySelector('#quantPreviewRulerY').innerHTML=rulerTickMarkup(heightMm,'y');
}

export async function generateQuantizedPreview(){
  const button=document.querySelector('#generateQuantPreview'),status=document.querySelector('#quantPreviewStatus'),file=effectiveArtworkFile(),swatches=dependencies.previewSwatches(),matching=dependencies.effectiveColorMatching(),whiteIs=document.querySelector('#whiteIs').value;
  if(!file){status.textContent='Choose an artwork image first.';return}
  if(!swatches.length){status.textContent='Enable at least one assigned swatch first.';return}
  if(matching.mode==='custom'&&!matching.hue&&!matching.saturation&&!matching.lightness){status.textContent='Give at least one Custom influence a value above zero.';return}
  button.disabled=true;
  status.textContent='Generating preview in this browser…';
  try{
    const bitmap=await loadPreviewBitmap(file),sourceWidth=bitmap.width||bitmap.naturalWidth,sourceHeight=bitmap.height||bitmap.naturalHeight,dimensions=document.querySelector('#panelTilingEnabled').checked?dependencies.panelTilingDerivedDimensions():rasterPreviewDimensions(sourceWidth,sourceHeight,document.querySelector('#width').value,document.querySelector('#height').value),processingWidth=dimensions.width,processingHeight=dimensions.height,previewScale=Math.min(1,1600/processingWidth,1600/processingHeight),width=Math.max(1,Math.round(processingWidth*previewScale)),height=Math.max(1,Math.round(processingHeight*previewScale)),pixelSize=Math.max(0,Number(document.querySelector('#pixel').value)||0),widthMm=processingWidth*pixelSize,heightMm=processingHeight*pixelSize,canvas=document.querySelector('#quantPreviewCanvas'),context=canvas.getContext('2d',{willReadFrequently:true});
    canvas.width=width;
    canvas.height=height;
    context.imageSmoothingEnabled=true;
    context.imageSmoothingQuality='high';
    context.clearRect(0,0,width,height);
    context.drawImage(bitmap,0,0,width,height);
    bitmap.close?.();
    const imageData=context.getImageData(0,0,width,height),counts=dependencies.quantizePreviewPixels(imageData.data,swatches,matching,whiteIs),opaqueTotal=[...counts.values()].reduce((sum,count)=>sum+count,0);
    context.putImageData(imageData,0,0);
    canvas.classList.toggle('transparency-grid',appliedCropShape==='transparency'||whiteIs==='unengraved');
    renderQuantPreviewCounts(swatches,counts,opaqueTotal);
    renderPreviewRulers(widthMm,heightMm);
    document.querySelector('#quantPreviewOutput').hidden=false;
    status.textContent=`Preview ready${previewScale<1?' · display preview reduced to fit 1,600 pixels':''}${appliedCropShape?` · ${appliedCropShape} crop`:''}${whiteIs==='unengraved'?' · white unengraved':''} · ${processingWidth.toLocaleString()} × ${processingHeight.toLocaleString()} processing pixels · ${previewMillimeters(processingWidth,pixelSize)} × ${previewMillimeters(processingHeight,pixelSize)} mm engraving · ${swatches.length} enabled swatches.`;
  }catch(error){status.textContent=`Could not generate preview: ${error.message}`}
  finally{button.disabled=false}
}
