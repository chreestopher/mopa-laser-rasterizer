let config;
let token=localStorage.getItem("id_token")||sessionStorage.getItem("id_token");
let refreshToken=localStorage.getItem("refresh_token")||sessionStorage.getItem("refresh_token");
let resources={};
let layers=[];
let activeLayer=0;
let pollTimer;
const COLORS=["#e44d61","#f39c49","#e4d354","#72c66a","#43b7a7","#4c9dde","#6c70d8","#9b63c7","#d05aa8","#bc7c58","#8b9a52","#5e8792"];
const $=selector=>document.querySelector(selector);
const esc=value=>String(value??"").replace(/[&<>"']/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));

function newLayer(index){return{name:`Layer ${index+1}`,motif:["petal","leaf","star","diamond"][index%4],custom_svg:null,construction:"cutout",support_mode:"automatic_bridges",rim_style:"closed",repetitions:12,rings:3,inner_radius_ratio:.18,motif_scale:.72,radial_stretch:1,tangent_stretch:1,twist_degrees:index%2? -18:18,rotation_degrees:index*8,alternate_rotation:true,mirror_alternating:false,rim_width_mm:4,bridge_width_mm:2,support_sweep_degrees:0,bridge_wave_amount:0,bridge_wave_amplitude_mm:6,bridge_wave_position:.5,layer_openness:0,opening_inner_ratio:.25,opening_rotation_degrees:0}}
function processingPalettes(){return(resources.material_libraries||[]).filter(item=>item.library_intent==="processing_palette")}
function selectedPalette(){return processingPalettes().find(item=>item.library_id===$("#processingPalette").value)}
function materialNames(library){return[...new Set([...(library?.summary?.logical_material_names||[]),...(library?.summary?.entries||[]).map(entry=>entry.material)].map(value=>String(value||"").trim()).filter(Boolean))]}
function materialEntries(){const material=$("#processingMaterial").value;return(selectedPalette()?.summary?.entries||[]).filter(entry=>String(entry.material||"")===material)}
function defaultRoleEntry(library,material,role){const assignments=(resources.preferences?.processing_palette_role_assignments||{})[library?.library_id]||{},roles=assignments.materials&&typeof assignments.materials==="object"?(assignments.materials[material]||{}):assignments,value=String(roles[role]||"").trim(),entries=(library?.summary?.entries||[]).filter(entry=>String(entry.material||"")===material);return entries.find(entry=>String(entry.entry_ref||"")===value)||entries.find(entry=>String(entry.description||"").trim().toLowerCase()===value.toLowerCase())||entries.find(entry=>String(entry.description||"").trim().toLowerCase()===role.toLowerCase())}
function populatePalette(){const select=$("#processingPalette"),palettes=processingPalettes();select.innerHTML=palettes.map(item=>`<option value="${esc(item.library_id)}">${esc(item.name)}</option>`).join("");populateMaterials();$("#paletteStatus").textContent=palettes.length?"The material's assigned Cut role is selected automatically when available.":"Import or create a Processing Palette in the Swatch Palette Vault before generating.";$("#generate").disabled=!palettes.length}
function populateMaterials(){const library=selectedPalette(),select=$("#processingMaterial"),names=materialNames(library);select.innerHTML=names.map(name=>`<option value="${esc(name)}">${esc(name)}</option>`).join("");populateCutSettings()}
function updateCutStatus(){const library=selectedPalette(),material=$("#processingMaterial").value,entries=materialEntries().filter(entry=>String(entry.type||"").toLowerCase()==="cut"),select=$("#cutSetting");$("#generate").disabled=!library||!entries.length;$("#paletteStatus").textContent=!library?"Choose a Processing Palette.":!entries.length?"This material has no LightBurn Line setting. Add or select a Cut setting in the Vault.":`Using ${material} · ${select.selectedOptions[0]?.textContent||"Cut"}.`}
function populateCutSettings(){const library=selectedPalette(),material=$("#processingMaterial").value,entries=materialEntries().filter(entry=>String(entry.type||"").toLowerCase()==="cut"),preferred=defaultRoleEntry(library,material,"Cut"),select=$("#cutSetting");select.innerHTML=entries.map(entry=>`<option value="${esc(entry.entry_ref)}">${esc(entry.description)}</option>`).join("");if(preferred&&entries.some(entry=>entry.entry_ref===preferred.entry_ref))select.value=preferred.entry_ref;updateCutStatus()}

function layerCard(layer,index){return`<article class="layer-card" data-layer="${index}"><div class="layer-heading"><div><h3>Layer ${index+1}</h3><p>Front-to-back position ${index+1}</p></div><div class="layer-actions"><button type="button" class="mandala-button" data-action="duplicate">Duplicate</button><button type="button" class="mandala-button" data-action="up" ${index===0?"disabled":""}>Earlier</button><button type="button" class="mandala-button" data-action="down" ${index===layers.length-1?"disabled":""}>Later</button><button type="button" class="mandala-button" data-action="remove" ${layers.length===1?"disabled":""}>Remove</button></div></div><div class="layer-controls">
<label>Layer name<input data-field="name" maxlength="80" value="${esc(layer.name)}"></label>
<label>Motif<select data-field="motif">${[["petal","Petal"],["leaf","Leaf"],["diamond","Diamond"],["circle","Circle"],["triangle","Triangle"],["star","Star"],["heart","Heart"],["custom","Custom SVG"]].map(([value,label])=>`<option value="${value}" ${layer.motif===value?"selected":""}>${label}</option>`).join("")}</select></label>
<label class="custom-svg-field" ${layer.motif==="custom"?"":"hidden"}>Custom SVG<input data-field="custom_file" type="file" accept="image/svg+xml,.svg"></label>
<p class="custom-svg-status" ${layer.motif==="custom"?"":"hidden"}>${layer.custom_svg?`Loaded ${esc(layer.custom_svg.name)}`:"Choose a plain SVG containing closed vector shapes."}</p>
<label>Construction<select data-field="construction"><option value="cutout" ${layer.construction==="cutout"?"selected":""}>Cutout lace</option><option value="positive" ${layer.construction==="positive"?"selected":""}>Built-up motif</option></select></label>
<label>Structural support<select data-field="support_mode"><option value="outer_rim" ${layer.support_mode==="outer_rim"?"selected":""}>Rim and hub; motifs may remain loose</option><option value="automatic_bridges" ${layer.support_mode==="automatic_bridges"?"selected":""}>Automatic bridges — one piece</option><option value="fully_connected" ${layer.support_mode==="fully_connected"?"selected":""}>Fully connected — one piece</option><option value="loose" ${layer.support_mode==="loose"?"selected":""}>Loose pieces allowed</option></select></label>
<label>Outer edge<select data-field="rim_style"><option value="closed" ${(layer.rim_style??"closed")==="closed"?"selected":""}>Closed rim</option><option value="petal" ${layer.rim_style==="petal"?"selected":""}>Petal crown</option><option value="open" ${layer.rim_style==="open"?"selected":""}>Open support ends</option></select></label>
${numberControl("repetitions","Radial repetitions",layer.repetitions,4,32,1)}${numberControl("rings","Concentric rings",layer.rings,1,8,1)}${numberControl("inner_radius_ratio","Inner radius",layer.inner_radius_ratio,.05,.55,.01)}${numberControl("motif_scale","Motif scale",layer.motif_scale,.2,.95,.01)}${numberControl("radial_stretch","Radial stretch",layer.radial_stretch,.4,1.8,.05)}${numberControl("tangent_stretch","Tangential stretch",layer.tangent_stretch,.4,1.8,.05)}${numberControl("twist_degrees","Outward twist",layer.twist_degrees,-180,180,1)}${numberControl("rotation_degrees","Layer rotation",layer.rotation_degrees,-180,180,1)}${numberControl("rim_width_mm","Outer rim (mm)",layer.rim_width_mm,.5,30,.1)}${numberControl("bridge_width_mm","Bridge width (mm)",layer.bridge_width_mm,.4,20,.1)}${numberControl("support_sweep_degrees","Support sweep angle (°)",layer.support_sweep_degrees??0,-75,75,1)}${numberControl("bridge_wave_amount","Bridge wave amount",layer.bridge_wave_amount??0,0,1,.01)}${numberControl("bridge_wave_amplitude_mm","Wave amplitude (mm)",layer.bridge_wave_amplitude_mm??6,0,30,.1)}${numberControl("bridge_wave_position","Wave position along bridge",layer.bridge_wave_position??.5,.1,.9,.01)}${numberControl("layer_openness","Layer openness",layer.layer_openness??0,0,1,.01)}${numberControl("opening_inner_ratio","Opening inner position",layer.opening_inner_ratio??.25,.05,.85,.01)}${numberControl("opening_rotation_degrees","Opening rotation (°)",layer.opening_rotation_degrees??0,-180,180,1)}
<label class="check-control"><input data-field="alternate_rotation" type="checkbox" ${layer.alternate_rotation?"checked":""}> Alternate ring phase</label><label class="check-control"><input data-field="mirror_alternating" type="checkbox" ${layer.mirror_alternating?"checked":""}> Mirror alternating motifs</label>
</div></article>`}
function numberControl(field,label,value,min,max,step){return`<label>${label}<input data-field="${field}" type="number" value="${value}" min="${min}" max="${max}" step="${step}"></label>`}
function syncPreviewSelector(){activeLayer=Math.max(0,Math.min(activeLayer,layers.length-1));const slider=$("#layerPreviewSlider"),layer=layers[activeLayer];slider.max=String(Math.max(1,layers.length));slider.value=String(activeLayer+1);$("#layerPreviewPosition").textContent=`Layer ${activeLayer+1} of ${layers.length}`;$("#layerPreviewName").textContent=layer?.name||`Layer ${activeLayer+1}`}
function renderLayers(){$("#layerList").innerHTML=layers.map(layerCard).join("");syncPreviewSelector();schedulePreview()}

let previewFrame;
function schedulePreview(){cancelAnimationFrame(previewFrame);previewFrame=requestAnimationFrame(drawPreviews)}
function builtInPath(name){const path=new Path2D();if(name==="circle"){path.arc(0,0,.5,0,Math.PI*2);return path}if(name==="diamond"){path.moveTo(-.5,0);path.lineTo(0,-.34);path.lineTo(.5,0);path.lineTo(0,.34);path.closePath();return path}if(name==="triangle"){path.moveTo(-.45,-.38);path.lineTo(-.45,.38);path.lineTo(.5,0);path.closePath();return path}if(name==="star"){for(let i=0;i<10;i++){const a=Math.PI*i/5,r=i%2?.22:.5,x=Math.cos(a)*r,y=Math.sin(a)*r;i?path.lineTo(x,y):path.moveTo(x,y)}path.closePath();return path}if(name==="heart"){for(let i=0;i<96;i++){const a=Math.PI*2*i/96,x=(13*Math.cos(a)-5*Math.cos(2*a)-2*Math.cos(3*a)-Math.cos(4*a))/34,y=-(16*Math.sin(a)**3)/34;i?path.lineTo(x,y):path.moveTo(x,y)}path.closePath();return path}path.moveTo(-.5,0);path.bezierCurveTo(-.15,name==="petal"?-.22:-.4,.3,name==="petal"?-.22:-.32,.5,0);path.bezierCurveTo(.3,name==="petal"?.22:.32,-.15,name==="petal"?.22:.4,-.5,0);path.closePath();return path}
async function customImage(layer){if(!layer.custom_svg)return null;if(layer._image)return layer._image;if(layer._imagePromise)return layer._imagePromise;layer._imagePromise=new Promise((resolve,reject)=>{const image=new Image(),url=URL.createObjectURL(new Blob([layer.custom_svg.svg],{type:"image/svg+xml"}));image.onload=()=>{URL.revokeObjectURL(url);layer._image=image;resolve(image)};image.onerror=()=>{URL.revokeObjectURL(url);reject(new Error("Custom SVG preview failed"))};image.src=url}).catch(()=>null);return layer._imagePromise}
function drawMotif(context,layer,size){if(layer.motif==="custom"&&layer._image){context.drawImage(layer._image,-size/2,-size/2,size,size);return}const path=builtInPath(layer.motif==="custom"?"petal":layer.motif);context.scale(size,size);context.fill(path)}
function supportBridgePath(startRadius,endRadius,startAngle,sweepDegrees,waveAmount,waveAmplitude,wavePosition){
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
function drawLayer(canvas,layer,index,alpha=1){
  const context=canvas.getContext("2d"),size=canvas.width,center=size/2,radius=size*.43;
  const scale=radius/(Number($("#diameter").value)||150)*2;
  const inner=radius*Number(layer.inner_radius_ratio),rim=Math.max(2,Number(layer.rim_width_mm)*scale),outer=radius-rim*1.2;
  const rings=Math.max(1,Number(layer.rings)),repetitions=Math.max(4,Number(layer.repetitions)),ringStep=(outer-inner)/rings;
  const bridgeWidth=Math.min(Number(layer.bridge_width_mm)*scale,Math.max(.4*scale,ringStep*.24));
  context.save();context.globalAlpha=alpha;context.translate(center,center);
  context.beginPath();context.arc(0,0,radius,0,Math.PI*2);context.clip();
  context.fillStyle=COLORS[index%COLORS.length];
  if(layer.construction==="cutout"){context.beginPath();context.arc(0,0,radius,0,Math.PI*2);context.fill();context.globalCompositeOperation="destination-out"}
  else context.globalCompositeOperation="source-over";
  for(let ring=0;ring<rings;ring++){
    const fraction=(ring+.5)/rings,ringRadius=inner+fraction*(outer-inner),motifSize=ringStep*Number(layer.motif_scale);
    const phase=Number(layer.rotation_degrees)+fraction*Number(layer.twist_degrees)+(layer.alternate_rotation&&ring%2?180/repetitions:0);
    for(let repeat=0;repeat<repetitions;repeat++){
      context.save();context.rotate((phase+repeat*360/repetitions)*Math.PI/180);context.translate(ringRadius,0);
      context.scale(Number(layer.radial_stretch),Number(layer.tangent_stretch)*(layer.mirror_alternating&&repeat%2?-1:1));
      context.fillStyle=layer.construction==="cutout"?"#000":COLORS[index%COLORS.length];drawMotif(context,layer,motifSize);context.restore();
    }
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
  const rimStyle=layer.rim_style??"closed",petalRadial=Math.max(rim*3,radius*.1),outerAnchor=rimStyle==="petal"?radius-petalRadial*.42:rimStyle==="open"?radius-bridgeWidth/2:radius-rim/2;
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
    for(let repeat=0;repeat<repetitions;repeat++){
      context.stroke(supportBridgePath(hubRadius*.75,outerAnchor,repeat*360/repetitions,Number(layer.support_sweep_degrees??0),Number(layer.bridge_wave_amount??0),waveAmplitude,Number(layer.bridge_wave_position??.5)));
    }
  }
  if(layer.support_mode==="fully_connected"){context.lineWidth=Math.max(1,bridgeWidth);context.beginPath();context.arc(0,0,(inner+outer)/2,0,Math.PI*2);context.stroke()}
  context.restore();
}
async function drawPreviews(){for(const layer of layers)if(layer.motif==="custom"&&layer.custom_svg&&!layer._image)customImage(layer).then(schedulePreview);for(const id of ["activePreview","stackPreview"]){const canvas=$("#"+id),context=canvas.getContext("2d");context.clearRect(0,0,canvas.width,canvas.height)}drawLayer($("#activePreview"),layers[activeLayer],activeLayer,1);layers.forEach((layer,index)=>drawLayer($("#stackPreview"),layer,index,.38))}

async function normalizeSvg(file){if(!file||!(file.type==="image/svg+xml"||file.name.toLowerCase().endsWith(".svg")))throw new Error("Choose an SVG file.");if(file.size>65536)throw new Error("Custom SVG files must be no larger than 64 KB.");const text=await file.text(),documentNode=new DOMParser().parseFromString(text,"image/svg+xml"),root=documentNode.documentElement;if(root.nodeName.toLowerCase()==="parsererror"||root.localName!=="svg")throw new Error("The custom SVG could not be read.");const allowed=new Set(["svg","g","path","rect","circle","ellipse","polygon","polyline"]);for(const element of documentNode.querySelectorAll("*")){const name=element.localName?.toLowerCase();if(!allowed.has(name))throw new Error(`SVG element <${name||"unknown"}> is not supported.`);for(const attribute of [...element.attributes]){const key=attribute.name.toLowerCase(),value=attribute.value.toLowerCase();if(key.startsWith("on")||key.includes("href")||value.includes("url(")||value.includes("javascript:")||value.includes("data:"))throw new Error("Embedded or external SVG content is not supported.")}}return{name:file.name.slice(0,120),svg:new XMLSerializer().serializeToString(root)}}

function payload(){return{project_name:$("#projectName").value,diameter_mm:$("#diameter").value,workbed_width_mm:$("#workbedWidth").value,workbed_height_mm:$("#workbedHeight").value,processing_palette_id:$("#processingPalette").value,material:$("#processingMaterial").value,cut_entry_ref:$("#cutSetting").value,layers:layers.map(({_image,_imagePromise,...layer})=>layer)}}
function syncProjectDimensions(){const diameter=Math.max(20,Math.min(1000,Number($("#diameter").value)||150));for(const input of [$("#workbedWidth"),$("#workbedHeight")]){input.min=String(diameter);if(Number(input.value)<diameter)input.value=String(diameter)}for(const layer of layers){layer.rim_width_mm=Math.min(Number(layer.rim_width_mm),diameter*.15);layer.bridge_width_mm=Math.min(Number(layer.bridge_width_mm),diameter*.08)}renderLayers()}
function tokenExpiresSoon(){try{const part=token.split(".")[1].replace(/-/g,"+").replace(/_/g,"/");const claims=JSON.parse(atob(part.padEnd(Math.ceil(part.length/4)*4,"=")));return Number(claims.exp||0)*1000<=Date.now()+30000}catch{return true}}
async function refreshSession(){if(!refreshToken)return false;const body=new URLSearchParams({grant_type:"refresh_token",client_id:config.client_id,refresh_token:refreshToken}),result=await fetch(`https://${config.cognito_domain}/oauth2/token`,{method:"POST",headers:{"content-type":"application/x-www-form-urlencoded"},body}).then(response=>response.json());if(!result.id_token)return false;token=result.id_token;localStorage.setItem("id_token",token);return true}
async function api(path,options={},retry=true){const response=await fetch(config.api_url+path,{...options,headers:{authorization:`Bearer ${token}`,"content-type":"application/json",...(options.headers||{})}});if(response.status===401&&retry&&await refreshSession())return api(path,options,false);const data=await response.json();if(!response.ok)throw new Error(data.message||`HTTP ${response.status}`);return data}
function outputsHtml(outputs){return(outputs||[]).map(output=>`<a class="mandala-button" href="${esc(output.download_url)}">Download ${esc(String(output.name||"output").split("/").pop())}</a>`).join("")}
async function poll(taskId){clearTimeout(pollTimer);try{const job=await api(`/jobs/${taskId}`);$("#status").textContent=`${job.status.toUpperCase()} · ${taskId}`;if(job.status==="completed"){$("#generate").disabled=false;$("#outputs").innerHTML=outputsHtml(job.outputs);return}if(job.status==="failed"){throw new Error(job.error||"Mandala generation failed")}pollTimer=setTimeout(()=>poll(taskId),3000)}catch(error){$("#status").textContent=`ERROR · ${error.message}`;$("#status").classList.add("error");$("#generate").disabled=false}}

$("#processingPalette").addEventListener("change",populateMaterials);$("#processingMaterial").addEventListener("change",populateCutSettings);$("#cutSetting").addEventListener("change",updateCutStatus);$("#diameter").addEventListener("change",syncProjectDimensions);$("#diameter").addEventListener("input",schedulePreview);
$("#addLayer").addEventListener("click",()=>{if(layers.length>=12)return;layers.push(newLayer(layers.length));activeLayer=layers.length-1;renderLayers()});
$("#layerList").addEventListener("click",event=>{const card=event.target.closest("[data-layer]"),button=event.target.closest("[data-action]");if(!card||!button)return;const index=Number(card.dataset.layer),action=button.dataset.action;if(action==="duplicate"&&layers.length<12){const copy=JSON.parse(JSON.stringify(layers[index],(key,value)=>key.startsWith("_")?undefined:value));copy.name=`${copy.name} copy`;layers.splice(index+1,0,copy);activeLayer=index+1}if(action==="remove"&&layers.length>1){layers.splice(index,1);activeLayer=Math.min(activeLayer,layers.length-1)}if(action==="up"&&index>0){[layers[index-1],layers[index]]=[layers[index],layers[index-1]];activeLayer=index-1}if(action==="down"&&index<layers.length-1){[layers[index+1],layers[index]]=[layers[index],layers[index+1]];activeLayer=index+1}renderLayers()});
$("#layerList").addEventListener("input",event=>{const card=event.target.closest("[data-layer]"),field=event.target.dataset.field;if(!card||!field||field==="custom_file")return;const layer=layers[Number(card.dataset.layer)],value=event.target.type==="checkbox"?event.target.checked:event.target.type==="number"?Number(event.target.value):event.target.value;layer[field]=value;if(field==="motif")renderLayers();else{if(field==="name")syncPreviewSelector();schedulePreview()}});
$("#layerPreviewSlider").addEventListener("input",event=>{activeLayer=Math.max(0,Math.min(layers.length-1,Number(event.target.value)-1));syncPreviewSelector();schedulePreview()});
$("#layerList").addEventListener("change",async event=>{if(event.target.dataset.field!=="custom_file")return;const card=event.target.closest("[data-layer]"),layer=layers[Number(card.dataset.layer)];try{layer.custom_svg=await normalizeSvg(event.target.files[0]);delete layer._image;delete layer._imagePromise;renderLayers()}catch(error){alert(error.message);event.target.value=""}});
$("#mandalaForm").addEventListener("submit",async event=>{event.preventDefault();const button=$("#generate");button.disabled=true;$("#outputs").innerHTML="";$("#status").classList.remove("error");$("#status").textContent="Submitting Layered Mandala job…";try{const result=await api("/mandala/jobs",{method:"POST",body:JSON.stringify(payload())});$("#status").textContent=`PENDING · ${result.task_id}`;history.replaceState({},"",`${location.pathname}?task=${encodeURIComponent(result.task_id)}`);poll(result.task_id)}catch(error){$("#status").textContent=`ERROR · ${error.message}`;$("#status").classList.add("error");button.disabled=false}});

async function start(){config=await fetch("/config.json",{cache:"no-store"}).then(response=>response.json());if(token)localStorage.setItem("id_token",token);if(refreshToken)localStorage.setItem("refresh_token",refreshToken);sessionStorage.removeItem("id_token");sessionStorage.removeItem("refresh_token");if(!token||tokenExpiresSoon()&&!await refreshSession()){const state=crypto.randomUUID();sessionStorage.setItem("oauth_state",state);$("#loginLink").href=`https://${config.cognito_domain}/oauth2/authorize?client_id=${encodeURIComponent(config.client_id)}&response_type=code&scope=${encodeURIComponent("openid email")}&redirect_uri=${encodeURIComponent(config.callback_url)}&state=${encodeURIComponent(state)}`;$("#registeredAccess").hidden=false;return}resources=await api("/account/resources");$("#registeredContent").hidden=false;layers=[newLayer(0),newLayer(1),newLayer(2)];populatePalette();renderLayers();const taskId=new URLSearchParams(location.search).get("task");if(taskId)poll(taskId)}
start().catch(error=>{$("#registeredContent").hidden=false;$("#status").textContent=`ERROR · ${error.message}`;$("#status").classList.add("error")});
