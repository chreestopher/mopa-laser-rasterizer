const ALLOWED_SVG_ELEMENTS=new Set(["svg","g","path","rect","circle","ellipse","polygon","polyline"]);

export async function normalizeSvg(file){
  if(!file||!(file.type==="image/svg+xml"||file.name.toLowerCase().endsWith(".svg")))throw new Error("Choose an SVG file.");
  if(file.size>65536)throw new Error("Custom SVG files must be no larger than 64 KB.");
  const text=await file.text();
  const documentNode=new DOMParser().parseFromString(text,"image/svg+xml");
  const root=documentNode.documentElement;
  if(root.nodeName.toLowerCase()==="parsererror"||root.localName!=="svg")throw new Error("The custom SVG could not be read.");
  for(const element of documentNode.querySelectorAll("*")){
    const name=element.localName?.toLowerCase();
    if(!ALLOWED_SVG_ELEMENTS.has(name))throw new Error(`SVG element <${name||"unknown"}> is not supported.`);
    for(const attribute of [...element.attributes]){
      const key=attribute.name.toLowerCase();
      const value=attribute.value.toLowerCase();
      if(key.startsWith("on")||key.includes("href")||value.includes("url(")||value.includes("javascript:")||value.includes("data:"))throw new Error("Embedded or external SVG content is not supported.");
    }
  }
  return{name:file.name.slice(0,120),svg:new XMLSerializer().serializeToString(root)};
}

export function createMandalaAssetConstraints({query,getLayers,renderLayers,alertUser=message=>alert(message)}){
  function syncProjectDimensions(){
    const diameter=Math.max(20,Math.min(1000,Number(query("#diameter").value)||150));
    for(const input of [query("#workbedWidth"),query("#workbedHeight")]){
      input.min=String(diameter);
      if(Number(input.value)<diameter)input.value=String(diameter);
    }
    for(const layer of getLayers()){
      layer.rim_width_mm=Math.min(Number(layer.rim_width_mm),diameter*.15);
      layer.bridge_width_mm=Math.min(Number(layer.bridge_width_mm),diameter*.08);
    }
    renderLayers();
  }

  async function handleCustomFileChange(event){
    if(event.target.dataset.field!=="custom_file")return;
    const card=event.target.closest("[data-layer]");
    const layer=getLayers()[Number(card.dataset.layer)];
    try{
      layer.custom_svg=await normalizeSvg(event.target.files[0]);
      delete layer._image;
      delete layer._imagePromise;
      renderLayers();
    }catch(error){
      alertUser(error.message);
      event.target.value="";
    }
  }

  function bindEvents(){
    query("#diameter").addEventListener("change",syncProjectDimensions);
    query("#layerList").addEventListener("change",handleCustomFileChange);
  }

  return{bindEvents,handleCustomFileChange,syncProjectDimensions};
}
