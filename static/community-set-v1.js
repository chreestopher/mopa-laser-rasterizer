const form = document.getElementById('community_search');
const status = document.getElementById('community_status');
const table = document.getElementById('community_table');
const preferredParameters = ['speed','minPower','maxPower','frequency','QPulseWidth','interval','angle','numPasses'];
const labelFor = value => String(value).replace(/([a-z0-9])([A-Z])/g,'$1 $2').replaceAll('_',' ');
const valueFor = value => value == null || value === '' ? '-' : typeof value === 'object' ? JSON.stringify(value) : String(value);
const render = rows => {
  const parameterSet = new Set(rows.flatMap(row => Object.keys(row.settings || {})));
  const discoveredParameters = [...preferredParameters.filter(key => parameterSet.delete(key)), ...[...parameterSet].sort((a,b) => a.localeCompare(b))];
  const crossHatchIndex = discoveredParameters.findIndex(key => String(key).toLowerCase() === 'crosshatch');
  const parametersThroughCrossHatch = crossHatchIndex >= 0 ? discoveredParameters.slice(0,crossHatchIndex + 1) : discoveredParameters;
  const typeParameter = discoveredParameters.find(key => String(key).toLowerCase() === 'type');
  const parameters = typeParameter && !parametersThroughCrossHatch.includes(typeParameter)
    ? [...parametersThroughCrossHatch,typeParameter]
    : parametersThroughCrossHatch;
  const headers = ['Laser Model / Source','Lens','Material','Color','Operation',...parameters.map(labelFor)];
  const thead = document.createElement('thead');
  const headerRow = document.createElement('tr');
  headers.forEach(label => { const th=document.createElement('th'); th.textContent=label; headerRow.append(th); });
  thead.append(headerRow);
  const tbody = document.createElement('tbody');
  rows.forEach(row => {
    const tr = document.createElement('tr');
    [row.laser_source,row.lens,row.material].forEach(value => { const td=document.createElement('td'); td.textContent=valueFor(value); tr.append(td); });
    const color = document.createElement('td'); color.className='color-cell';
    const swatch = document.createElement('span'); swatch.className='color-swatch';
    if (/^#[0-9a-f]{6}$/i.test(row.swatch || '')) swatch.style.backgroundColor=row.swatch;
    const colorName=document.createElement('span'); colorName.textContent=valueFor(row.color); color.append(swatch,colorName); tr.append(color);
    const operation=document.createElement('td'); operation.textContent=valueFor(row.operation); tr.append(operation);
    parameters.forEach(key => { const td=document.createElement('td'); td.textContent=valueFor(row.settings?.[key]); tr.append(td); });
    tbody.append(tr);
  });
  table.replaceChildren(thead,tbody);
};

async function requestCommunitySettings(query) {
  if (form.dataset.apiMode !== 'serverless') {
    return fetch(`/community-set/settings?${query}`,{credentials:'same-origin'});
  }
  const config=await fetch('/config.json',{cache:'no-store'}).then(result=>result.json());
  let token=localStorage.getItem('id_token')||sessionStorage.getItem('id_token');
  const refreshToken=localStorage.getItem('refresh_token')||sessionStorage.getItem('refresh_token');
  if(!token) throw new Error('Sign in to search Community Set settings.');
  const request=()=>fetch(`${config.api_url}/community-set/settings?${query}`,
    {headers:{authorization:`Bearer ${token}`}});
  let response=await request();
  if(response.status===401&&refreshToken){
    const body=new URLSearchParams({grant_type:'refresh_token',client_id:config.client_id,refresh_token:refreshToken});
    const refreshed=await fetch(`https://${config.cognito_domain}/oauth2/token`,
      {method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},body}).then(result=>result.json());
    if(refreshed.id_token){token=refreshed.id_token;localStorage.setItem('id_token',token);response=await request();}
  }
  if(response.status===401)throw new Error('Session expired. Sign in again.');
  return response;
}

form.addEventListener('submit', async event => {
  event.preventDefault(); status.classList.remove('error');
  const query = new URLSearchParams(new FormData(form));
  if (![...query.values()].some(value => value.trim())) { status.textContent='Enter at least one filter.'; status.classList.add('error'); return; }
  status.textContent='Reading the community settings index…';
  try {
    const response=await requestCommunitySettings(query);
    const data=await response.json();
    if (!response.ok) throw new Error(data.message || 'Could not load community settings.');
    status.textContent=`${data.count} matching setting${data.count === 1 ? '' : 's'}.`;
    if (data.settings.length) render(data.settings);
    else table.innerHTML='<tbody><tr><td class="empty-cell">No contributed settings match this combination yet.</td></tr></tbody>';
  } catch (error) { status.textContent=error.message; status.classList.add('error'); }
});
