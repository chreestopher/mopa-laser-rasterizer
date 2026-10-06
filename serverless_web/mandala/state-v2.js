export function newLayer(index,diameterValue=150){const layerDiameter=Math.max(20,Math.min(1000,Number(diameterValue)||150));return{name:`Layer ${index+1}`,layer_diameter_mm:layerDiameter,motif:["petal","leaf","star","diamond"][index%4],ornament_style:["lotus","billow","paisley","rose_lace"][index%4],motif_composition:["hybrid","whole_repeat","kaleidoscope"][index%3],custom_svg:null,construction:"cutout",support_mode:"automatic_bridges",rim_style:index===0?"petal":"open",repetitions:12,rings:3,inner_radius_ratio:.18,motif_scale:.72,motif_radial_position:0,motif_tangential_position:0,fragment_scale:1.7,radial_stretch:1,tangent_stretch:1,twist_degrees:index%2?-28:28,rotation_degrees:index*8,alternate_rotation:true,mirror_alternating:false,flow_amount:.92,petal_fullness:1.15,tip_sharpness:1.4,curl_degrees:index%2?-28:28,band_overlap:.25,mirror_wedges:true,rim_width_mm:Math.min(4,layerDiameter*.15),bridge_width_mm:Math.min(1.5,layerDiameter*.08),support_sweep_degrees:index%2?-18:18,bridge_wave_amount:.65,bridge_wave_amplitude_mm:Math.min(8,layerDiameter*.2),bridge_wave_position:.5,layer_openness:.1,opening_inner_ratio:.25,opening_rotation_degrees:0}}

export function randomizedLayer(layer,index,diameterValue,random=Math.random){
  const choose=values=>values[Math.floor(random()*values.length)];
  const randomBetween=(minimum,maximum,step=.01)=>Math.round((minimum+random()*(maximum-minimum))/step)*step;
  const randomized={...layer},diameter=Math.max(20,Math.min(Number(diameterValue)||150,Number(layer.layer_diameter_mm)||Number(diameterValue)||150));
  if(layer.motif!=="custom")randomized.motif=choose(["petal","leaf","diamond","circle","triangle","star","heart"]);
  Object.assign(randomized,{
    ornament_style:choose(["lotus","billow","paisley","rose_lace","leaf_lace"]),
    motif_composition:choose(["hybrid","whole_repeat","kaleidoscope","flow_character"]),
    repetitions:choose([6,8,10,12,14,16,18,20]),rings:choose([2,3,4,5,6]),
    inner_radius_ratio:randomBetween(.08,.38),motif_scale:randomBetween(.42,.92),
    motif_radial_position:randomBetween(-.32,.32),motif_tangential_position:randomBetween(-.38,.38),
    fragment_scale:randomBetween(1.2,2.4,.05),radial_stretch:randomBetween(.65,1.5,.05),
    tangent_stretch:randomBetween(.65,1.5,.05),twist_degrees:randomBetween(-120,120,1),
    rotation_degrees:randomBetween(-180,180,1),alternate_rotation:random()>=.3,
    mirror_alternating:random()>=.55,flow_amount:randomBetween(.35,1),
    petal_fullness:randomBetween(.55,1.65,.05),tip_sharpness:randomBetween(.55,2.7,.05),
    curl_degrees:randomBetween(-80,80,1),band_overlap:randomBetween(.05,.55,.01),
    mirror_wedges:random()>=.35,support_sweep_degrees:randomBetween(-45,45,1),
    bridge_wave_amount:randomBetween(0,.85),bridge_wave_amplitude_mm:randomBetween(Math.max(.5,diameter*.02),diameter*.14,.1),
    bridge_wave_position:randomBetween(.18,.82),layer_openness:randomBetween(0,.65,.01),
    opening_inner_ratio:randomBetween(.12,.7,.01),opening_rotation_degrees:randomBetween(-180,180,1),
  });
  randomized.name=layer.name||`Layer ${index+1}`;
  return randomized;
}

export function resetLayer(layer,index,diameterValue){const reset=newLayer(index,diameterValue);reset.name=layer.name;return reset}

export function duplicateLayer(layer){const copy=JSON.parse(JSON.stringify(layer,(key,value)=>key.startsWith("_")?undefined:value));copy.name=`${copy.name} copy`;return copy}
