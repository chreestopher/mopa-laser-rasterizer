export function builtInPath(name){const path=new Path2D();if(name==="circle"){path.arc(0,0,.5,0,Math.PI*2);return path}if(name==="diamond"){path.moveTo(-.5,0);path.lineTo(0,-.34);path.lineTo(.5,0);path.lineTo(0,.34);path.closePath();return path}if(name==="triangle"){path.moveTo(-.45,-.38);path.lineTo(-.45,.38);path.lineTo(.5,0);path.closePath();return path}if(name==="star"){for(let i=0;i<10;i++){const a=Math.PI*i/5,r=i%2?.22:.5,x=Math.cos(a)*r,y=Math.sin(a)*r;i?path.lineTo(x,y):path.moveTo(x,y)}path.closePath();return path}if(name==="heart"){for(let i=0;i<96;i++){const a=Math.PI*2*i/96,x=(13*Math.cos(a)-5*Math.cos(2*a)-2*Math.cos(3*a)-Math.cos(4*a))/34,y=-(16*Math.sin(a)**3)/34;i?path.lineTo(x,y):path.moveTo(x,y)}path.closePath();return path}path.moveTo(-.5,0);path.bezierCurveTo(-.15,name==="petal"?-.22:-.4,.3,name==="petal"?-.22:-.32,.5,0);path.bezierCurveTo(.3,name==="petal"?.22:.32,-.15,name==="petal"?.22:.4,-.5,0);path.closePath();return path}

export function drawMotif(context,layer,size){if(layer.motif==="custom"&&layer._image){context.drawImage(layer._image,-size/2,-size/2,size,size);return}const path=builtInPath(layer.motif==="custom"?"petal":layer.motif);context.scale(size,size);context.fill(path)}

export function supportBridgePath(startRadius,endRadius,startAngle,sweepDegrees,waveAmount,waveAmplitude,wavePosition){
  const path=new Path2D(),startAngleRadians=startAngle*Math.PI/180,endAngleRadians=(startAngle+sweepDegrees)*Math.PI/180;
  const start=[Math.cos(startAngleRadians)*startRadius,Math.sin(startAngleRadians)*startRadius],end=[Math.cos(endAngleRadians)*endRadius,Math.sin(endAngleRadians)*endRadius];
  const dx=end[0]-start[0],dy=end[1]-start[1],length=Math.hypot(dx,dy)||1,normal=[-dy/length,dx/length],position=Math.max(.1,Math.min(.9,wavePosition));
  for(let index=0;index<=64;index++){
    const fraction=index/64,waveFraction=fraction<=position?.5*fraction/position:.5+.5*(fraction-position)/(1-position),displacement=waveAmount*waveAmplitude*Math.sin(2*Math.PI*waveFraction);
    const x=start[0]+dx*fraction+normal[0]*displacement,y=start[1]+dy*fraction+normal[1]*displacement;
    index?path.lineTo(x,y):path.moveTo(x,y);
  }
  return path;
}

export function flowingPetalPath(innerRadius,outerRadius,centerAngle,sectorAngle,layer,handedness=1,widthScale=1){
  const left=[],right=[],style=layer.ornament_style??"lotus",motif=layer.motif??"petal",flow=Number(layer.flow_amount??.92),fullness=Number(layer.petal_fullness??1.15)*Number(layer.tangent_stretch??1)*widthScale,sharpness=Number(layer.tip_sharpness??1.4),curl=Number(layer.curl_degrees??28)*Math.PI/180*flow*handedness;
  for(let index=0;index<=48;index++){
    const fraction=index/48,smooth=fraction*fraction*(3-2*fraction),radius=innerRadius+(outerRadius-innerRadius)*fraction,envelope=Math.max(0,Math.sin(Math.PI*fraction))**sharpness;
    let billow=1,centerShift=curl*Math.sin(Math.PI*fraction);
    if(style==="billow"){billow=1+.28*Math.sin(2*Math.PI*fraction)**2;centerShift*=.72}
    else if(style==="paisley"){billow=.82+.42*fraction;centerShift*=1.45}
    else if(style==="rose_lace"){billow=.82+.26*Math.sin(3*Math.PI*fraction)**2;centerShift+=handedness*sectorAngle*.045*Math.sin(2*Math.PI*fraction)}
    else if(style==="leaf_lace"){billow=.72+.2*Math.sin(Math.PI*fraction);centerShift*=.82}
    if(motif==="circle")billow*=1.18-.18*Math.cos(2*Math.PI*fraction);
    else if(motif==="diamond")billow*=.78+.44*Math.abs(2*fraction-1);
    else if(motif==="triangle")billow*=.62+.62*fraction;
    else if(motif==="star")billow*=1+.18*Math.sin(4*Math.PI*fraction)**2;
    else if(motif==="heart")billow*=1+.24*Math.sin(2*Math.PI*fraction);
    else if(motif==="leaf")billow*=.78+.3*Math.sin(Math.PI*fraction);
    const halfWidth=sectorAngle*.39*fullness*envelope*billow,angle=centerAngle+centerShift+Number(layer.twist_degrees)*Math.PI/180*flow*smooth/Math.max(1,Number(layer.rings));
    left.push([Math.cos(angle-halfWidth)*radius,Math.sin(angle-halfWidth)*radius]);right.push([Math.cos(angle+halfWidth)*radius,Math.sin(angle+halfWidth)*radius]);
  }
  const path=new Path2D();[...left,...right.reverse()].forEach(([x,y],index)=>index?path.lineTo(x,y):path.moveTo(x,y));path.closePath();return path;
}

export function drawFlowingPattern(context,layer,inner,outer,rings,repetitions){
  const span=(outer-inner)/rings,sector=Math.PI*2/repetitions;
  for(let ring=0;ring<rings;ring++){
    const center=inner+(ring+.5)*span,halfSpan=span*(.5+Number(layer.band_overlap??.25))*Number(layer.motif_scale??.72)/.72*Number(layer.radial_stretch??1),bandInner=Math.max(inner,center-halfSpan),bandOuter=Math.min(outer,center+halfSpan),fraction=(ring+.5)/rings;
    let phase=(Number(layer.rotation_degrees)+fraction*Number(layer.twist_degrees)*.34)*Math.PI/180;if(layer.alternate_rotation&&ring%2)phase+=sector/2;
    for(let repeat=0;repeat<repetitions;repeat++){
      const angle=phase+repeat*sector;
      if(layer.mirror_wedges!==false){context.fill(flowingPetalPath(bandInner,bandOuter,angle-sector*.105,sector,layer,-1,.67));context.fill(flowingPetalPath(bandInner,bandOuter,angle+sector*.105,sector,layer,1,.67))}
      else context.fill(flowingPetalPath(bandInner,bandOuter,angle,sector,layer,layer.mirror_alternating&&repeat%2?-1:1));
    }
  }
}

export function drawComposedMotifs(context,layer,inner,outer,rings,repetitions){
  const ringStep=(outer-inner)/rings,sector=Math.PI*2/repetitions,composition=layer.motif_composition??"hybrid";
  for(let ring=0;ring<rings;ring++){
    const fraction=(ring+.5)/rings,ringRadius=inner+fraction*(outer-inner),radialSize=ringStep*Number(layer.motif_scale)*Number(layer.radial_stretch),tangentRoom=Math.PI*2*ringRadius/repetitions,tangentSize=Math.min(ringStep*Number(layer.motif_scale),tangentRoom*.72)*Number(layer.tangent_stretch),radialOffset=ringStep*Number(layer.motif_radial_position??0),tangentOffset=tangentSize*Number(layer.motif_tangential_position??0);
    let phase=(Number(layer.rotation_degrees)+fraction*Number(layer.twist_degrees))*Math.PI/180;if(layer.alternate_rotation&&ring%2)phase+=sector/2;
    const whole=composition==="whole_repeat"||(composition==="hybrid"&&ring%3===0);
    for(let repeat=0;repeat<repetitions;repeat++){
      context.save();context.rotate(phase+repeat*sector);
      if(whole){
        context.translate(ringRadius+radialOffset,tangentOffset);context.scale(Number(layer.radial_stretch),Number(layer.tangent_stretch)*(layer.mirror_alternating&&ring%2?-1:1));drawMotif(context,layer,ringStep*Number(layer.motif_scale));
      }else{
        const wedgeInner=Math.max(inner,ringRadius-ringStep*.62),wedgeOuter=Math.min(outer,ringRadius+ringStep*.62),half=sector*.48;
        context.beginPath();context.arc(0,0,wedgeOuter,-half,half);context.arc(0,0,wedgeInner,half,-half,true);context.closePath();context.clip();
        for(const mirror of [1,-1]){context.save();context.scale(1,mirror);context.translate(ringRadius+radialOffset+radialSize*(ring%2?.16:-.12),tangentOffset+tangentSize*.42);context.rotate((ring%2?Math.PI:0)*mirror);context.scale(Number(layer.fragment_scale??1.7)*Number(layer.radial_stretch),Number(layer.fragment_scale??1.7)*Number(layer.tangent_stretch));drawMotif(context,layer,ringStep*Number(layer.motif_scale));context.restore()}
        if(composition==="hybrid"&&ring%3===2){context.save();context.translate(ringRadius+radialOffset,-tangentOffset);context.scale(.58*Number(layer.radial_stretch),-.58*Number(layer.tangent_stretch));drawMotif(context,layer,ringStep*Number(layer.motif_scale));context.restore()}
      }
      context.restore();
    }
  }
}
