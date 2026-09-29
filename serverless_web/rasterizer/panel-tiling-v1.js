let dependencies=null;
let controlsBound=false;
let panelPreviewGeneration=0;

const element=id=>(dependencies?.documentRoot||document).querySelector(id);

export function panelTilingParameters(){
  const fitMode=element('#tileFitMode').value;
  const paddingMode=fitMode==='fit'?element('#tilePaddingMode').value:'unengraved';
  return {
    enabled:element('#panelTilingEnabled').checked,
    tile_width_mm:Number(element('#tileWidth').value),
    tile_height_mm:Number(element('#tileHeight').value),
    columns:Number(element('#tileColumns').value),
    rows:Number(element('#tileRows').value),
    gap_x_mm:Number(element('#tileGapX').value),
    gap_y_mm:Number(element('#tileGapY').value),
    edge_inset_mm:Number(element('#tileInset').value),
    workbed_width_mm:Number(element('#tileWorkbedWidth').value),
    workbed_height_mm:Number(element('#tileWorkbedHeight').value),
    order:element('#tileOrder').value,
    include_tile_ids:element('#tileIncludeIds').checked,
    fit_mode:fitMode,
    align_x:element('#tileAlignX').value,
    align_y:element('#tileAlignY').value,
    padding_mode:paddingMode,
    padding_swatch_hex:paddingMode==='swatch'?element('#tilePaddingSwatch').value:'',
    border_mode:element('#tileBorderMode').value,
    border_swatch_hex:element('#tileBorderSwatch').value,
    border_width_mm:Number(element('#tileBorderWidth').value),
  };
}

export function panelTilingDerivedDimensions(){
  const settings=panelTilingParameters();
  const pixel=Math.max(.01,Number(element('#pixel').value)||.01);
  const widthMm=settings.columns*settings.tile_width_mm+Math.max(0,settings.columns-1)*settings.gap_x_mm;
  const heightMm=settings.rows*settings.tile_height_mm+Math.max(0,settings.rows-1)*settings.gap_y_mm;
  return {widthMm,heightMm,width:Math.max(1,Math.round(widthMm/pixel)),height:Math.max(1,Math.round(heightMm/pixel))};
}

function syncPanelSwatchOptions(){
  const swatches=dependencies.previewSwatches();
  for(const id of ['tilePaddingSwatch','tileBorderSwatch']){
    const select=element('#'+id),previous=select.value;
    select.replaceChildren(...swatches.map(item=>new Option(`${item.name} · ${item.hex}`,item.hex)));
    select.value=dependencies.hasOption(select,previous)?previous:(swatches[0]?.hex||'');
  }
}

function panelAlignmentOffset(available,alignment){
  return alignment==='start'?0:alignment==='end'?available:available/2;
}

function syncRasterProcessingDimensionLimits(panelEnabled,dimensions=null){
  const width=element('#width'),height=element('#height'),help=element('#processingDimensionHelp');
  width.max=height.max=panelEnabled?'32000':'1600';
  width.disabled=height.disabled=panelEnabled;
  if(panelEnabled&&dimensions){
    width.value=dimensions.width;
    height.value=dimensions.height;
    help.textContent='Panel Tiling derives the full processing dimensions from tile size, tile count, gaps, and Pixel size. Oversized jobs use the high-resolution panel worker.';
  }else{
    if(Number(width.value)>1600)width.value=1600;
    if(Number(height.value)>1600)height.value=1600;
    help.textContent='Ordinary jobs are limited to 1,600 pixels per axis.';
  }
}

async function autoMatchPanelAspect(){
  const button=element('#tileAutoAspect'),status=element('#tileAutoAspectStatus'),file=dependencies.effectiveArtworkFile();
  if(!file){status.textContent='Choose artwork before automatically matching its aspect ratio.';return}
  button.disabled=true;
  try{
    const bitmap=await dependencies.loadPreviewBitmap(file),sourceWidth=bitmap.width||bitmap.naturalWidth,sourceHeight=bitmap.height||bitmap.naturalHeight,sourceRatio=sourceWidth/sourceHeight;
    bitmap.close?.();
    const current=panelTilingParameters(),total=current.columns*current.rows;
    if(total>100){status.textContent='Reduce the current layout to 100 panels or fewer before auto-matching.';return}
    const orientations=[{width:current.tile_width_mm,height:current.tile_height_mm,rotated:false}];
    if(current.tile_width_mm!==current.tile_height_mm)orientations.push({width:current.tile_height_mm,height:current.tile_width_mm,rotated:true});
    let best=null;
    for(const orientation of orientations){
      if(orientation.width>current.workbed_width_mm||orientation.height>current.workbed_height_mm)continue;
      for(let columns=1;columns<=20;columns++){
        if(total%columns)continue;
        const rows=total/columns;
        if(rows>20)continue;
        const width=columns*orientation.width+(columns-1)*current.gap_x_mm,height=rows*orientation.height+(rows-1)*current.gap_y_mm,error=Math.abs(Math.log((width/height)/sourceRatio)),change=Math.abs(columns-current.columns)+Math.abs(rows-current.rows)+(orientation.rotated?0.25:0),candidate={...orientation,columns,rows,error,change};
        if(!best||error<best.error-1e-9||Math.abs(error-best.error)<1e-9&&change<best.change)best=candidate;
      }
    }
    if(!best){status.textContent='No arrangement of the current panels fits inside the described workbed. Increase the workbed or adjust the blank size.';return}
    element('#tileWidth').value=best.width;
    element('#tileHeight').value=best.height;
    element('#tileColumns').value=best.columns;
    element('#tileRows').value=best.rows;
    element('#tileFitMode').value='fit';
    element('#tileAlignX').value='center';
    element('#tileAlignY').value='center';
    status.textContent=`Matched ${sourceWidth.toLocaleString()} × ${sourceHeight.toLocaleString()} artwork with ${best.columns} columns × ${best.rows} rows${best.rotated?' and rotated panel blanks':''}. Fit preserves the image; the highlighted preview shows any remaining extra space.`;
    syncPanelTiling();
  }catch(error){
    status.textContent=`Could not auto-match the panel layout: ${error.message}`;
  }finally{
    button.disabled=false;
  }
}

async function renderPanelLayoutPreview(){
  const generation=++panelPreviewGeneration,canvas=element('#panelLayoutPreview'),status=element('#panelLayoutPreviewStatus'),file=dependencies.effectiveArtworkFile();
  if(!element('#panelTilingEnabled').checked||!file){
    canvas.width=0;
    canvas.height=0;
    status.textContent=file?'Enable Panel Tiling to preview the layout.':'Choose artwork to preview the assembled panel layout.';
    return;
  }
  try{
    const bitmap=await dependencies.loadPreviewBitmap(file);
    if(generation!==panelPreviewGeneration){bitmap.close?.();return}
    const settings=panelTilingParameters(),dimensions=panelTilingDerivedDimensions(),scale=Math.min(1,760/dimensions.width,460/dimensions.height),width=Math.max(1,Math.round(dimensions.width*scale)),height=Math.max(1,Math.round(dimensions.height*scale)),context=canvas.getContext('2d');
    canvas.width=width;
    canvas.height=height;
    context.clearRect(0,0,width,height);
    if(settings.fit_mode==='fit'&&settings.padding_mode==='swatch'&&settings.padding_swatch_hex){context.fillStyle=settings.padding_swatch_hex;context.fillRect(0,0,width,height)}
    const sourceWidth=bitmap.width||bitmap.naturalWidth,sourceHeight=bitmap.height||bitmap.naturalHeight;
    let drawWidth=width,drawHeight=height,drawX=0,drawY=0;
    if(settings.fit_mode!=='stretch'){
      const ratio=settings.fit_mode==='fit'?Math.min(width/sourceWidth,height/sourceHeight):Math.max(width/sourceWidth,height/sourceHeight);
      drawWidth=sourceWidth*ratio;
      drawHeight=sourceHeight*ratio;
      drawX=panelAlignmentOffset(width-drawWidth,settings.align_x);
      drawY=panelAlignmentOffset(height-drawHeight,settings.align_y);
    }
    context.drawImage(bitmap,drawX,drawY,drawWidth,drawHeight);
    bitmap.close?.();
    if(settings.fit_mode==='fit'&&(drawX>0||drawY>0)){
      context.fillStyle='rgba(243,222,104,.24)';
      if(drawX>0){context.fillRect(0,0,drawX,height);context.fillRect(drawX+drawWidth,0,width-drawX-drawWidth,height)}
      if(drawY>0){context.fillRect(0,0,width,drawY);context.fillRect(0,drawY+drawHeight,width,height-drawY-drawHeight)}
    }
    if(settings.border_mode!=='none'&&settings.border_swatch_hex&&settings.border_width_mm>0){
      context.strokeStyle=settings.border_swatch_hex;
      context.lineWidth=Math.max(1,settings.border_width_mm/dimensions.widthMm*width);
      if(settings.border_mode==='assembly')context.strokeRect(context.lineWidth/2,context.lineWidth/2,width-context.lineWidth,height-context.lineWidth);
      else for(let row=0;row<settings.rows;row++)for(let column=0;column<settings.columns;column++){
        const x=column*(settings.tile_width_mm+settings.gap_x_mm)/dimensions.widthMm*width,y=row*(settings.tile_height_mm+settings.gap_y_mm)/dimensions.heightMm*height,w=settings.tile_width_mm/dimensions.widthMm*width,h=settings.tile_height_mm/dimensions.heightMm*height;
        context.strokeRect(x+context.lineWidth/2,y+context.lineWidth/2,w-context.lineWidth,h-context.lineWidth);
      }
    }
    context.save();
    context.globalCompositeOperation='destination-in';
    context.fillStyle='#fff';
    for(let row=0;row<settings.rows;row++)for(let column=0;column<settings.columns;column++){
      const x=(column*(settings.tile_width_mm+settings.gap_x_mm)+settings.edge_inset_mm)/dimensions.widthMm*width,y=(row*(settings.tile_height_mm+settings.gap_y_mm)+settings.edge_inset_mm)/dimensions.heightMm*height,w=(settings.tile_width_mm-settings.edge_inset_mm*2)/dimensions.widthMm*width,h=(settings.tile_height_mm-settings.edge_inset_mm*2)/dimensions.heightMm*height;
      context.fillRect(x,y,w,h);
    }
    context.restore();
    context.save();
    context.strokeStyle='#ffbf47';
    context.lineWidth=Math.max(1.5,Math.min(width,height)/350);
    context.setLineDash([8,4]);
    context.strokeRect(drawX+context.lineWidth/2,drawY+context.lineWidth/2,drawWidth-context.lineWidth,drawHeight-context.lineWidth);
    context.restore();
    context.save();
    context.strokeStyle='rgba(72,221,255,.95)';
    context.lineWidth=Math.max(1,Math.min(width,height)/450);
    context.setLineDash([6,4]);
    for(let row=0;row<settings.rows;row++)for(let column=0;column<settings.columns;column++){
      const x=column*(settings.tile_width_mm+settings.gap_x_mm)/dimensions.widthMm*width,y=row*(settings.tile_height_mm+settings.gap_y_mm)/dimensions.heightMm*height,w=settings.tile_width_mm/dimensions.widthMm*width,h=settings.tile_height_mm/dimensions.heightMm*height;
      context.strokeRect(x,y,w,h);
    }
    context.restore();
    context.save();
    context.strokeStyle=(dependencies.documentRoot||document).body.classList.contains('light-machine')?'#111':'#fff';
    context.lineWidth=Math.max(1.5,Math.min(width,height)/350);
    context.strokeRect(context.lineWidth/2,context.lineWidth/2,width-context.lineWidth,height-context.lineWidth);
    context.restore();
    const sourceRatio=sourceWidth/sourceHeight,layoutRatio=dimensions.widthMm/dimensions.heightMm;
    if(settings.fit_mode==='stretch')status.textContent=`Stretch fills the ${dimensions.widthMm.toFixed(1)} × ${dimensions.heightMm.toFixed(1)} mm assembled layout; aspect ratio changes from ${sourceRatio.toFixed(3)} to ${layoutRatio.toFixed(3)}.`;
    else if(settings.fit_mode==='fit'){
      const fittedWidth=sourceRatio>layoutRatio?dimensions.widthMm:dimensions.heightMm*sourceRatio,fittedHeight=sourceRatio>layoutRatio?dimensions.widthMm/sourceRatio:dimensions.heightMm;
      status.textContent=`Fit preserves the whole image · total horizontal extra space ${(dimensions.widthMm-fittedWidth).toFixed(1)} mm · total vertical extra space ${(dimensions.heightMm-fittedHeight).toFixed(1)} mm. Orange outlines image placement; yellow marks extra space.`;
    }else status.textContent='Fill preserves aspect ratio and crops the source outside the assembled layout. Orange outlines source placement; cyan outlines panels; the solid outer line is the assembled layout.';
  }catch(error){
    if(generation===panelPreviewGeneration)status.textContent=`Could not preview Panel Tiling: ${error.message}`;
  }
}

export function syncPanelTiling(){
  const toggle=element('#panelTilingEnabled'),details=element('#panelTilingDetails');
  details.hidden=!toggle.checked;
  toggle.setAttribute('aria-expanded',String(toggle.checked));
  if(!toggle.checked){syncRasterProcessingDimensionLimits(false);panelPreviewGeneration++;return}
  syncPanelSwatchOptions();
  const settings=panelTilingParameters(),fitUsesAlignment=settings.fit_mode!=='stretch',showPadding=settings.fit_mode==='fit';
  element('#tileAlignX').disabled=!fitUsesAlignment;
  element('#tileAlignY').disabled=!fitUsesAlignment;
  element('#tilePaddingModeField').hidden=!showPadding;
  element('#tilePaddingSwatchField').hidden=!showPadding||settings.padding_mode!=='swatch';
  element('#tileBorderSwatchField').hidden=settings.border_mode==='none';
  element('#tileBorderWidthField').hidden=settings.border_mode==='none';
  const borderLegend=element('#panelBorderLegend');
  borderLegend.hidden=settings.border_mode==='none';
  element('#panelBorderLegendKey').style.borderColor=settings.border_swatch_hex||'currentColor';
  const dimensions=panelTilingDerivedDimensions(),highResolution=Math.max(dimensions.width,dimensions.height)>1600,mode=highResolution?'Oversized layouts are divided before vectorization and sent to the high-resolution panel worker; every individual panel must remain at or below 1,600 pixels per axis.':'Panel Tiling controls the processing dimensions while enabled.';
  syncRasterProcessingDimensionLimits(true,dimensions);
  element('#panelTilingSummary').textContent=`${settings.columns*settings.rows} tile projects · assembled artwork ${dimensions.widthMm.toFixed(1)} × ${dimensions.heightMm.toFixed(1)} mm · processing ${dimensions.width} × ${dimensions.height} px. ${mode}`;
  renderPanelLayoutPreview();
  dependencies.markQuantPreviewStale();
}

export function restorePanelTiling(values){
  const toggle=element('#panelTilingEnabled'),settings=values?.panel_tiling;
  toggle.checked=false;
  if(!settings||typeof settings!=='object'){syncPanelTiling();return}
  for(const [id,key,legacyKey] of [['tileWidth','tile_width_mm'],['tileHeight','tile_height_mm'],['tileColumns','columns'],['tileRows','rows'],['tileGapX','gap_x_mm'],['tileGapY','gap_y_mm'],['tileInset','edge_inset_mm'],['tileWorkbedWidth','workbed_width_mm','origin_x_mm'],['tileWorkbedHeight','workbed_height_mm','origin_y_mm'],['tileBorderWidth','border_width_mm']]){
    const saved=settings[key]??settings[legacyKey];
    if(saved!==undefined)element('#'+id).value=saved;
  }
  for(const [id,key] of [['tileOrder','order'],['tileFitMode','fit_mode'],['tileAlignX','align_x'],['tileAlignY','align_y'],['tilePaddingMode','padding_mode'],['tileBorderMode','border_mode']])if(dependencies.hasOption(element('#'+id),settings[key]))element('#'+id).value=settings[key];
  syncPanelSwatchOptions();
  for(const [id,key] of [['tilePaddingSwatch','padding_swatch_hex'],['tileBorderSwatch','border_swatch_hex']])if(dependencies.hasOption(element('#'+id),settings[key]))element('#'+id).value=settings[key];
  if(settings.include_tile_ids!==undefined)element('#tileIncludeIds').checked=Boolean(settings.include_tile_ids);
  syncPanelTiling();
}

export function panelTilingPreferenceValues(){
  const settings=panelTilingParameters();
  delete settings.enabled;
  return settings;
}

export function configurePanelTiling(options){
  dependencies=options;
  if(controlsBound)return;
  controlsBound=true;
  element('#panelTilingEnabled').onchange=syncPanelTiling;
  element('#panelTilingControls').oninput=syncPanelTiling;
  element('#panelTilingControls').onchange=syncPanelTiling;
  element('#tileAutoAspect').onclick=autoMatchPanelAspect;
  element('#pixel').addEventListener('input',syncPanelTiling);
  syncPanelTiling();
}
