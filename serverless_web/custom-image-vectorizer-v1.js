const ALLOWED_SVG_ELEMENTS=new Set(["svg","g","path","rect","circle","ellipse","polygon","polyline"]);
const SVG_LIMIT=65536;
const RASTER_LIMIT=10*1024*1024;
const MAX_RASTER_DIMENSION=192;

function isSvg(file){return Boolean(file&&(file.type==="image/svg+xml"||file.name.toLowerCase().endsWith(".svg")))}

export async function normalizeSvg(file){
  if(!file)throw new Error("Choose an SVG or raster image.");
  if(file.size>SVG_LIMIT)throw new Error("Custom SVG files must be no larger than 64 KB.");
  const text=await file.text();
  const documentNode=new DOMParser().parseFromString(text,"image/svg+xml"),root=documentNode.documentElement;
  if(root.nodeName.toLowerCase()==="parsererror"||root.localName!=="svg")throw new Error("The custom SVG could not be read.");
  for(const element of documentNode.querySelectorAll("*")){
    const name=element.localName?.toLowerCase();
    if(!ALLOWED_SVG_ELEMENTS.has(name))throw new Error(`SVG element <${name||"unknown"}> is not supported.`);
    for(const attribute of [...element.attributes]){
      const key=attribute.name.toLowerCase(),value=attribute.value.toLowerCase();
      if(key.startsWith("on")||key.includes("href")||value.includes("url(")||value.includes("javascript:")||value.includes("data:"))throw new Error("Embedded or external SVG content is not supported.");
    }
  }
  return{name:file.name.slice(0,120),svg:new XMLSerializer().serializeToString(root)};
}

function simplifyLoop(points){
  if(points.length<4)return points;
  return points.filter((current,index)=>{
    const previous=points[(index+points.length-1)%points.length],next=points[(index+1)%points.length];
    return !((previous[0]===current[0]&&current[0]===next[0])||(previous[1]===current[1]&&current[1]===next[1]));
  });
}

export function maskToSvg(mask,width,height,{maxPoints=Infinity}={}){
  const edges=[],outgoing=new Map(),key=(x,y)=>`${x},${y}`;
  const filled=(x,y)=>x>=0&&y>=0&&x<width&&y<height&&Boolean(mask[y*width+x]);
  function add(x1,y1,x2,y2){const edge={x1,y1,x2,y2,used:false};edges.push(edge);const start=key(x1,y1);if(!outgoing.has(start))outgoing.set(start,[]);outgoing.get(start).push(edge)}
  for(let y=0;y<height;y++)for(let x=0;x<width;x++)if(filled(x,y)){
    if(!filled(x,y-1))add(x,y,x+1,y);
    if(!filled(x+1,y))add(x+1,y,x+1,y+1);
    if(!filled(x,y+1))add(x+1,y+1,x,y+1);
    if(!filled(x-1,y))add(x,y+1,x,y);
  }
  if(!edges.length)throw new Error("The raster image does not contain a traceable foreground shape.");
  const direction=edge=>edge.x2>edge.x1?0:edge.y2>edge.y1?1:edge.x2<edge.x1?2:3,turnOrder=[1,0,3,2],loops=[];let pointCount=0;
  for(const first of edges){
    if(first.used)continue;
    const points=[[first.x1,first.y1]];let edge=first,guard=0;
    while(edge&&!edge.used&&guard++<=edges.length){
      edge.used=true;points.push([edge.x2,edge.y2]);
      if(edge.x2===first.x1&&edge.y2===first.y1)break;
      const incoming=direction(edge),candidates=(outgoing.get(key(edge.x2,edge.y2))||[]).filter(candidate=>!candidate.used);
      candidates.sort((a,b)=>turnOrder.indexOf((direction(a)-incoming+4)%4)-turnOrder.indexOf((direction(b)-incoming+4)%4));
      edge=candidates[0];
    }
    if(points.length>3&&points.at(-1)[0]===points[0][0]&&points.at(-1)[1]===points[0][1]){
      points.pop();const loop=simplifyLoop(points);if(loop.length>=3){pointCount+=loop.length;loops.push(loop)}
    }
  }
  if(!loops.length)throw new Error("The raster image could not be converted into closed vector shapes.");
  if(pointCount>maxPoints){const error=new Error("The raster trace contains too many vector points.");error.code="TRACE_TOO_DETAILED";throw error}
  const paths=loops.map(loop=>`<path d="M${loop.map(point=>point.join(" ")).join("L")}Z"/>`).join("");
  return`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}">${paths}</svg>`;
}

function otsuThreshold(luminance){
  const histogram=new Uint32Array(256);for(const value of luminance)histogram[value]++;
  let totalSum=0;for(let value=0;value<256;value++)totalSum+=value*histogram[value];
  let backgroundWeight=0,backgroundSum=0,bestVariance=-1,threshold=127;
  for(let value=0;value<256;value++){
    backgroundWeight+=histogram[value];if(!backgroundWeight)continue;
    const foregroundWeight=luminance.length-backgroundWeight;if(!foregroundWeight)break;
    backgroundSum+=value*histogram[value];
    const backgroundMean=backgroundSum/backgroundWeight,foregroundMean=(totalSum-backgroundSum)/foregroundWeight;
    const variance=backgroundWeight*foregroundWeight*(backgroundMean-foregroundMean)**2;
    if(variance>bestVariance){bestVariance=variance;threshold=value}
  }
  return threshold;
}

function imageMask(image,width,height){
  const canvas=document.createElement("canvas");canvas.width=width;canvas.height=height;
  const context=canvas.getContext("2d",{willReadFrequently:true});context.clearRect(0,0,width,height);context.drawImage(image,0,0,width,height);
  const pixels=context.getImageData(0,0,width,height).data,luminance=new Uint8Array(width*height),alpha=new Uint8Array(width*height);let hasTransparency=false;
  for(let index=0;index<luminance.length;index++){
    const offset=index*4;alpha[index]=pixels[offset+3];if(alpha[index]<250)hasTransparency=true;
    luminance[index]=Math.round(.2126*pixels[offset]+.7152*pixels[offset+1]+.0722*pixels[offset+2]);
  }
  if(hasTransparency)return Uint8Array.from(alpha,value=>value>=64?1:0);
  let minimum=255,maximum=0;for(const value of luminance){minimum=Math.min(minimum,value);maximum=Math.max(maximum,value)}
  if(minimum===maximum)return Uint8Array.from(luminance,()=>1);
  const threshold=otsuThreshold(luminance),border=[];
  for(let x=0;x<width;x++){border.push(luminance[x],luminance[(height-1)*width+x])}
  for(let y=1;y<height-1;y++){border.push(luminance[y*width],luminance[y*width+width-1])}
  const borderMean=border.reduce((sum,value)=>sum+value,0)/Math.max(1,border.length),darkForeground=borderMean>threshold;
  return Uint8Array.from(luminance,value=>(darkForeground?value<=threshold:value>threshold)?1:0);
}

function loadRaster(file){
  return new Promise((resolve,reject)=>{
    const image=new Image(),url=URL.createObjectURL(file);
    image.onload=()=>{URL.revokeObjectURL(url);resolve(image)};
    image.onerror=()=>{URL.revokeObjectURL(url);reject(new Error("The raster image could not be read."))};
    image.src=url;
  });
}

async function normalizeRaster(file){
  if(!file.type.startsWith("image/"))throw new Error("Choose an SVG or raster image.");
  if(file.size>RASTER_LIMIT)throw new Error("Raster images must be no larger than 10 MB.");
  const image=await loadRaster(file),sourceWidth=image.naturalWidth||image.width,sourceHeight=image.naturalHeight||image.height;
  if(!sourceWidth||!sourceHeight)throw new Error("The raster image has no usable dimensions.");
  let maximum=MAX_RASTER_DIMENSION;
  while(maximum>=24){
    const scale=Math.min(1,maximum/Math.max(sourceWidth,sourceHeight)),width=Math.max(1,Math.round(sourceWidth*scale)),height=Math.max(1,Math.round(sourceHeight*scale));
    let svg;
    try{svg=maskToSvg(imageMask(image,width,height),width,height,{maxPoints:4096})}catch(error){if(error.code!=="TRACE_TOO_DETAILED")throw error}
    if(svg&&new Blob([svg]).size<=SVG_LIMIT)return{name:file.name.slice(0,120),svg};
    maximum=Math.floor(maximum*.75);
  }
  throw new Error("The raster image is too detailed to convert into a 64 KB vector shape.");
}

export async function normalizeCustomImage(file,{validateSvg}={}){
  if(!file)throw new Error("Choose an SVG or raster image.");
  const normalized=isSvg(file)?await normalizeSvg(file):await normalizeRaster(file);
  if(validateSvg)validateSvg(normalized.svg);
  return normalized;
}
