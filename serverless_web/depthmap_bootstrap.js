let token = localStorage.getItem("id_token") || sessionStorage.getItem("id_token");
let refreshToken = localStorage.getItem("refresh_token") || sessionStorage.getItem("refresh_token");
if (token) localStorage.setItem("id_token", token);
if (refreshToken) localStorage.setItem("refresh_token", refreshToken);
sessionStorage.removeItem("id_token");
sessionStorage.removeItem("refresh_token");

function tokenExpiresSoon() {
  try {
    const part = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const claims = JSON.parse(atob(part.padEnd(Math.ceil(part.length / 4) * 4, "=")));
    return Number(claims.exp || 0) * 1000 <= Date.now() + 30000;
  } catch (_) {
    return true;
  }
}

function fail(message) {
  const status = document.querySelector("#depth_status");
  if (status) status.textContent = message;
}

async function start() {
  const config = await fetch("/config.json", {cache: "no-store"}).then(response => response.json());
  async function refreshSession() {
    if (!refreshToken) return false;
    const body = new URLSearchParams({
      grant_type: "refresh_token", client_id: config.client_id, refresh_token: refreshToken,
    });
    const result = await fetch(`https://${config.cognito_domain}/oauth2/token`, {
      method: "POST", headers: {"content-type": "application/x-www-form-urlencoded"}, body,
    }).then(response => response.json());
    if (!result.id_token) return false;
    token = result.id_token;
    localStorage.setItem("id_token", token);
    return true;
  }
  if (token && tokenExpiresSoon() && !await refreshSession()) {
    token = null;
    refreshToken = null;
    localStorage.removeItem("id_token");
    localStorage.removeItem("refresh_token");
    window.stagingShellSetAuthenticated?.(false);
  }
  async function api(path, retry = true) {
    const response = await fetch(config.api_url + path, {headers: {authorization: `Bearer ${token}`}});
    if (response.status === 401 && retry && await refreshSession()) return api(path, false);
    const data = await response.json();
    if (!response.ok) throw new Error(data.message || `HTTP ${response.status}`);
    return data;
  }
  if (token) {
    window.serverlessDepthResources = await api("/account/resources");
    window.serverlessDepthGuest = false;
  } else {
    const response = await fetch(`${config.api_url}/guest/config`);
    const guest = await response.json();
    if (!response.ok) throw new Error(guest.message || `HTTP ${response.status}`);
    window.serverlessDepthResources = {palette: guest.palette || [], depth_palettes: []};
    window.serverlessDepthGuest = true;
  }
  document.querySelector("#depth_palette_data").textContent = JSON.stringify(
    window.serverlessDepthResources.palette || [],
  );
await import("/depthmap_generator.js?v=20");
  if (window.serverlessDepthGuest) {
    fail("Guest access ready. Choose an image to create a depth map entirely in this browser.");
  }
}

start().catch(error => fail(`Depthmap staging initialization failed: ${error.message}`));
