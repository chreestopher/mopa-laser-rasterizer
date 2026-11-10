import {normalizeCustomImage} from "../custom-image-vectorizer-v1.js";

export function createMandalaAssetConstraints({query,getLayers,renderLayers,alertUser=message=>alert(message)}){
  function syncProjectDimensions(){
    const diameter=Math.max(20,Math.min(1000,Number(query("#diameter").value)||150));
    for(const input of [query("#workbedWidth"),query("#workbedHeight")]){
      input.min=String(diameter);
      if(Number(input.value)<diameter)input.value=String(diameter);
    }
    for(const layer of getLayers()){
      const layerDiameter=Math.max(20,Math.min(diameter,Number(layer.layer_diameter_mm)||diameter));
      layer.layer_diameter_mm=layerDiameter;
      layer.rim_width_mm=Math.min(Number(layer.rim_width_mm),layerDiameter*.15);
      layer.bridge_width_mm=Math.min(Number(layer.bridge_width_mm),layerDiameter*.08);
      layer.bridge_wave_amplitude_mm=Math.min(Number(layer.bridge_wave_amplitude_mm),layerDiameter*.2);
    }
    renderLayers();
  }

  async function handleCustomFileChange(event){
    if(event.target.dataset.field!=="custom_file")return;
    const card=event.target.closest("[data-layer]");
    const layer=getLayers()[Number(card.dataset.layer)];
    try{
      layer.custom_svg=await normalizeCustomImage(event.target.files[0]);
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
    query("#layerList").addEventListener("change",event=>event.target.dataset.field==="layer_diameter_mm"?syncProjectDimensions():handleCustomFileChange(event));
  }

  return{bindEvents,handleCustomFileChange,syncProjectDimensions};
}
