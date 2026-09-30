const TRACK_TEETH={circle:96,oval:105,rounded_square:120,rounded_triangle:105,custom:120};
export const PEN_HOLE_FACTORS=[0,.2,.36,.52,.68,.82,.94];

function builtInPoints(track){const count=720,points=[];for(let i=0;i<count;i++){const t=Math.PI*2*i/count;let x,y;if(track==="circle"){x=.5*Math.cos(t);y=.5*Math.sin(t)}else if(track==="oval"){x=.5*Math.cos(t);y=.34*Math.sin(t)}else if(track==="rounded_triangle"){const r=.39+.07*Math.cos(3*t);x=r*Math.sin(t);y=-r*Math.cos(t)}else{const p=4,r=.49/(Math.abs(Math.cos(t))**p+Math.abs(Math.sin(t))**p)**(1/p);x=r*Math.cos(t);y=r*Math.sin(t)}points.push([x,y])}points.push(points[0]);return points}
function rotatePoints(points,turns){const angle=turns*Math.PI/2,c=Math.cos(angle),s=Math.sin(angle);return points.map(([x,y])=>[x*c-y*s,x*s+y*c])}
export function geometryPoints(svg){
  const documentNode=new DOMParser().parseFromString(svg,"image/svg+xml"),host=document.createElement("div");
  host.style.cssText="position:fixed;left:-10000px;top:-10000px;visibility:hidden";
  host.append(document.importNode(documentNode.documentElement,true));document.body.append(host);
  try{
    let best=null,bestLength=0;
    for(const node of host.querySelectorAll("path,circle,ellipse,rect,polygon,polyline")){
      if(typeof node.getTotalLength!=="function")continue;
      const length=node.getTotalLength(),first=node.getPointAtLength(0),last=node.getPointAtLength(length);
      if(Math.hypot(first.x-last.x,first.y-last.y)>Math.max(.01,length*.0001))continue;
      if(length>bestLength){best=node;bestLength=length}
    }
    if(!best)throw new Error("The custom track must contain a closed vector path.");
    const points=[];for(let i=0;i<=720;i++){const point=best.getPointAtLength(bestLength*i/720);points.push([point.x,point.y])}
    const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]),minX=Math.min(...xs),maxX=Math.max(...xs),minY=Math.min(...ys),maxY=Math.max(...ys),extent=Math.max(maxX-minX,maxY-minY)||1,cx=(minX+maxX)/2,cy=(minY+maxY)/2;
    return points.map(([x,y])=>[(x-cx)/extent,(y-cy)/extent]);
  }finally{host.remove()}
}
export function trackPoints(layer){if(layer.track!=="custom")return rotatePoints(builtInPoints(layer.track),layer.rotation_quarter_turns);if(!layer.custom_svg)return rotatePoints(builtInPoints("circle"),layer.rotation_quarter_turns);if(!layer._trackPoints)layer._trackPoints=rotatePoints(geometryPoints(layer.custom_svg.svg),layer.rotation_quarter_turns);return layer._trackPoints}
function cumulative(points){const values=[0];for(let i=1;i<points.length;i++)values.push(values[i-1]+Math.hypot(points[i][0]-points[i-1][0],points[i][1]-points[i-1][1]));return values}
function sample(points,lengths,distance){const total=lengths.at(-1),target=((distance%total)+total)%total;let low=0,high=lengths.length-1;while(low+1<high){const mid=(low+high)>>1;if(lengths[mid]<=target)low=mid;else high=mid}const span=lengths[high]-lengths[low]||1,f=(target-lengths[low])/span,a=points[low],b=points[high],dx=b[0]-a[0],dy=b[1]-a[1],m=Math.hypot(dx,dy)||1;return[a[0]+dx*f,a[1]+dy*f,dx/m,dy/m]}
function gcd(a,b){while(b)[a,b]=[b,a%b];return a}
export function rollingModel(layer){
  const track=trackPoints(layer),lengths=cumulative(track),perimeter=lengths.at(-1),trackTeeth=TRACK_TEETH[layer.track],gearTeeth=Number(layer.gear_teeth);
  return{track,lengths,perimeter,trackTeeth,gearTeeth,gearRadius:perimeter/(2*Math.PI)*gearTeeth/trackTeeth,phase:(Number(layer.start_mark)-1)*Math.PI/4,roll:layer.direction==="clockwise"?-1:1,side:layer.side==="inside"?-1:1};
}
export function rollingState(model,distance){
  const[x,y,tx,ty]=sample(model.track,model.lengths,distance),nx=ty,ny=-tx,cx=x+nx*model.gearRadius*model.side,cy=y+ny*model.gearRadius*model.side,angle=model.phase+model.roll*model.side*distance/model.gearRadius;
  return{x,y,tx,ty,nx,ny,cx,cy,angle};
}
export function curvePoints(layer){const model=rollingModel(layer),penRadius=model.gearRadius*PEN_HOLE_FACTORS[Number(layer.pen_hole)],loops=model.gearTeeth/gcd(model.trackTeeth,model.gearTeeth),samples=Math.min(10000,Math.max(1200,loops*model.trackTeeth*5)),result=[];for(let i=0;i<=samples;i++){const state=rollingState(model,model.perimeter*loops*i/samples);result.push([state.cx+Math.cos(state.angle)*penRadius,state.cy+Math.sin(state.angle)*penRadius])}return result}
export function bounds(points){const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);return[Math.min(...xs),Math.min(...ys),Math.max(...xs),Math.max(...ys)]}
function finitePoints(points){return points.filter(point=>point.length>=2&&Number.isFinite(point[0])&&Number.isFinite(point[1]))}
export function fitTransform(points,padding=22){const clean=finitePoints(points),b=bounds(clean.length?clean:[[0,0],[1,1]]),extent=Math.max(b[2]-b[0],b[3]-b[1])||1,scale=(240-padding*2)/extent,cx=(b[0]+b[2])/2,cy=(b[1]+b[3])/2;return([x,y])=>[120+(x-cx)*scale,120+(y-cy)*scale]}
export function pathData(points,project=point=>point,close=false){const clean=finitePoints(points);if(!clean.length)return"";return clean.map((point,index)=>`${index?"L":"M"}${project(point).map(value=>value.toFixed(2)).join(" ")}`).join(" ")+(close?" Z":"")}
export function gearOutline(center,radius,teeth,phase=0){const points=[],count=Math.max(1,Number(teeth))*2;for(let index=0;index<count;index++){const angle=phase+Math.PI*2*index/count,r=radius*(index%2?0.91:1);points.push([center[0]+Math.cos(angle)*r,center[1]+Math.sin(angle)*r])}return points}
export function stableHardwareDistance(model,custom){if(!custom)return 0;let bestDistance=0,bestScore=-Infinity;const window=model.perimeter/180;for(let index=0;index<64;index++){const distance=model.perimeter*index/64,a=rollingState(model,distance-window),b=rollingState(model,distance+window),score=a.tx*b.tx+a.ty*b.ty;if(Number.isFinite(score)&&score>bestScore){bestScore=score;bestDistance=distance}}return bestDistance}
export function trackTickSegments(model){const result=[],length=Math.max(.008,model.perimeter/model.trackTeeth*.34);for(let index=0;index<model.trackTeeth;index++){const state=rollingState(model,model.perimeter*index/model.trackTeeth),start=[state.x+state.nx*model.side*.004,state.y+state.ny*model.side*.004],end=[state.x+state.nx*model.side*(length+.004),state.y+state.ny*model.side*(length+.004)];result.push([start,end])}return result}
export function segmentPath(segments,project){return segments.map(([start,end])=>`M${project(start).map(value=>value.toFixed(2)).join(" ")} L${project(end).map(value=>value.toFixed(2)).join(" ")}`).join(" ")}
