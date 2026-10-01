export function createJobLifecycle({escapeHtml,getLayers,onAuthenticated}){
  let config,pollTimer;
  let token=localStorage.getItem("id_token")||sessionStorage.getItem("id_token");
  let refreshToken=localStorage.getItem("refresh_token")||sessionStorage.getItem("refresh_token");
  const $=value=>document.querySelector(value);

  function payloadLayer(source){const{_trackPoints,...layer}=source;return layer}
  function payload(){const colorPaletteId=$("#colorPalette").value;return{project_name:$("#projectName").value,diameter_mm:$("#diameter").value,workbed_width_mm:$("#workbedWidth").value,workbed_height_mm:$("#workbedHeight").value,processing_palette_id:$("#processingPalette").value,color_palette_id:colorPaletteId,material:$("#processingMaterial").value,score_entry_ref:$("#scoreSetting").value,fill_entry_ref:$("#fillSetting").value,layers:getLayers().map(payloadLayer)}}
  function tokenExpiresSoon(){try{const part=token.split(".")[1].replace(/-/g,"+").replace(/_/g,"/");const claims=JSON.parse(atob(part.padEnd(Math.ceil(part.length/4)*4,"=")));return Number(claims.exp||0)*1000<=Date.now()+30000}catch{return true}}
  async function refreshSession(){if(!refreshToken)return false;const body=new URLSearchParams({grant_type:"refresh_token",client_id:config.client_id,refresh_token:refreshToken}),result=await fetch(`https://${config.cognito_domain}/oauth2/token`,{method:"POST",headers:{"content-type":"application/x-www-form-urlencoded"},body}).then(r=>r.json());if(!result.id_token)return false;token=result.id_token;localStorage.setItem("id_token",token);return true}
  async function api(path,options={},retry=true){const response=await fetch(config.api_url+path,{...options,headers:{authorization:`Bearer ${token}`,"content-type":"application/json",...(options.headers||{})}});if(response.status===401&&retry&&await refreshSession())return api(path,options,false);const data=await response.json();if(!response.ok)throw new Error(data.message||`HTTP ${response.status}`);return data}
  async function poll(taskId){clearTimeout(pollTimer);try{const job=await api(`/jobs/${taskId}`);$("#status").textContent=`${job.status.toUpperCase()} · ${taskId}`;if(job.status==="completed"){$("#generate").disabled=false;$("#outputs").innerHTML=(job.outputs||[]).map(output=>`<a class="spiralgrap-button" href="${escapeHtml(output.download_url)}">Download ${escapeHtml(String(output.name||"output").split("/").pop())}</a>`).join("");return}if(job.status==="failed")throw new Error(job.error||"SpiralGraph generation failed");pollTimer=setTimeout(()=>poll(taskId),3000)}catch(error){$("#status").textContent=`ERROR · ${error.message}`;$("#status").classList.add("error");$("#generate").disabled=false}}

  function bind(){
    $("#spiralgrapForm").addEventListener("submit",async event=>{event.preventDefault();$("#generate").disabled=true;$("#outputs").innerHTML="";$("#status").classList.remove("error");$("#status").textContent="Submitting SpiralGraph job…";try{const result=await api("/spiralgraph/jobs",{method:"POST",body:JSON.stringify(payload())});history.replaceState({},"",`${location.pathname}?task=${encodeURIComponent(result.task_id)}`);poll(result.task_id)}catch(error){$("#status").textContent=`ERROR · ${error.message}`;$("#status").classList.add("error");$("#generate").disabled=false}});
  }

  async function bootstrap(){config=await fetch("/config.json",{cache:"no-store"}).then(r=>r.json());if(!token||tokenExpiresSoon()&&!await refreshSession()){const state=crypto.randomUUID();sessionStorage.setItem("oauth_state",state);$("#loginLink").href=`https://${config.cognito_domain}/oauth2/authorize?client_id=${encodeURIComponent(config.client_id)}&response_type=code&scope=${encodeURIComponent("openid email")}&redirect_uri=${encodeURIComponent(config.callback_url)}&state=${encodeURIComponent(state)}`;$("#registeredAccess").hidden=false;return}const resources=await api("/account/resources");$("#registeredContent").hidden=false;onAuthenticated(resources);const task=new URLSearchParams(location.search).get("task");if(task)poll(task)}
  function start(){bootstrap().catch(error=>{$("#registeredContent").hidden=false;$("#status").textContent=`ERROR · ${error.message}`;$("#status").classList.add("error")})}

  return{bind,start};
}
