export const COLORS=["#f45b69","#ffb34d","#8bd450","#43c7bb","#5596f6","#b56ce2"];
export const GEARS=[24,30,32,36,40,42,45,48,56,60];

export function newLayer(index){return{name:`Drawing ${index+1}`,swatch_hex:COLORS[index%COLORS.length],track:["circle","oval","rounded_triangle"][index%3],custom_svg:null,gear_teeth:[40,32,56][index%3],pen_hole:[5,4,6][index%3],side:"inside",start_mark:index+1,direction:index%2?"counterclockwise":"clockwise",rotation_quarter_turns:index%4,include_track:false,output_mode:"line",fill_thickness_mm:1.2}}

export function createDrawingState(){
  let layers=[],activeLayer=0;
  return{
    getLayers:()=>layers,
    getActiveLayerIndex:()=>activeLayer,
    setActiveLayerIndex:value=>{activeLayer=value},
    resetLayers(count=3){layers=Array.from({length:count},(_,index)=>newLayer(index));activeLayer=0;return layers},
  };
}

export function constrainWorkbedToDiameter(diameterInput,workbedInputs){const diameter=Math.max(20,Math.min(1000,Number(diameterInput.value)||150));for(const input of workbedInputs){input.min=String(diameter);if(Number(input.value)<diameter)input.value=String(diameter)}return diameter}
