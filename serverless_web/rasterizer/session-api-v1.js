export function createRasterizerSessionApi({
  show,
  userFacingStyleError,
  fetchImpl = (...args) => fetch(...args),
  localStore = localStorage,
  sessionStore = sessionStorage,
  locationRoot = location,
  historyRoot = history,
  documentRoot = document,
  shellSetAuthenticated = authenticated => window.stagingShellSetAuthenticated?.(authenticated),
}) {
  let config;
  let token = localStore.getItem('id_token') || sessionStore.getItem('id_token');
  let refreshToken = localStore.getItem('refresh_token') || sessionStore.getItem('refresh_token');
  let guestAccessToken = sessionStore.getItem('guest_access_token');
  let guestMode = !token;

  if (token) localStore.setItem('id_token', token);
  if (refreshToken) localStore.setItem('refresh_token', refreshToken);
  sessionStore.removeItem('id_token');
  sessionStore.removeItem('refresh_token');

  const element = selector => documentRoot.querySelector(selector);
  const isGuest = () => guestMode;

  function clearTaskContext() {
    const params = new URLSearchParams(locationRoot.search);
    params.delete('task');
    sessionStore.removeItem('pending_task');
    const search = params.toString();
    historyRoot.replaceState(
      {},
      '',
      `${locationRoot.pathname}${search ? `?${search}` : ''}${locationRoot.hash || ''}`,
    );
  }

  function setTaskLocation(task) {
    const params = new URLSearchParams(locationRoot.search);
    params.set('task', task);
    historyRoot.replaceState(
      {},
      '',
      `${locationRoot.pathname}?${params.toString()}${locationRoot.hash || ''}`,
    );
  }

  function setAuthState(authenticated) {
    guestMode = !authenticated;
    element('#job').classList.remove('hidden');
    element('#holographicJob').classList.toggle('hidden', !authenticated);
    element('#guestNotice').classList.toggle('hidden', authenticated);
    shellSetAuthenticated(authenticated);
  }

  function clearAuth() {
    token = null;
    refreshToken = null;
    localStore.removeItem('id_token');
    localStore.removeItem('refresh_token');
    setAuthState(false);
  }

  function tokenExpiresSoon() {
    try {
      const part = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
      const claims = JSON.parse(atob(part.padEnd(Math.ceil(part.length / 4) * 4, '=')));
      return Number(claims.exp || 0) * 1000 <= Date.now() + 30000;
    } catch {
      return true;
    }
  }

  async function refreshSession() {
    if (!refreshToken) return false;
    const body = new URLSearchParams({
      grant_type: 'refresh_token',
      client_id: config.client_id,
      refresh_token: refreshToken,
    });
    const result = await fetchImpl(`https://${config.cognito_domain}/oauth2/token`, {
      method: 'POST',
      headers: {'content-type': 'application/x-www-form-urlencoded'},
      body,
    }).then(response => response.json());
    if (!result.id_token) {
      clearAuth();
      return false;
    }
    token = result.id_token;
    localStore.setItem('id_token', token);
    return true;
  }

  function authHeaders() {
    return {'authorization': `Bearer ${token}`, 'content-type': 'application/json'};
  }

  async function api(path, options = {}, retryAuth = true) {
    const response = await fetchImpl(config.api_url + path, {
      ...options,
      headers: {...authHeaders(), ...(options.headers || {})},
    });
    const data = await response.json();
    if (response.status === 401 && retryAuth && await refreshSession()) {
      return api(path, options, false);
    }
    if (response.status === 401) {
      clearAuth();
      throw new Error('Session expired. Sign in again.');
    }
    if (!response.ok) throw new Error(userFacingStyleError(data.message || `HTTP ${response.status}`));
    return data;
  }

  async function guestApi(path, options = {}) {
    const headers = {'content-type': 'application/json', ...(options.headers || {})};
    if (guestAccessToken) headers['x-guest-capability'] = guestAccessToken;
    const response = await fetchImpl(config.api_url + path, {...options, headers});
    const data = await response.json();
    if (!response.ok) throw new Error(userFacingStyleError(data.message || `HTTP ${response.status}`));
    return data;
  }

  function setGuestAccessToken(value) {
    guestAccessToken = value;
    sessionStore.setItem('guest_access_token', value);
  }

  function jobAccessErrorMessage(message) {
    if (message === 'Task not found' && !guestMode) {
      return "This job isn't available to this session. It may have expired or been deleted, or it may belong to another account. Check that you're signed into the right account; otherwise, start a new job.";
    }
    if (message === 'Guest task not found or access expired' && guestMode) {
      return "This guest job isn't available. Guest access lasts 24 hours, and the job may also have been deleted. If it's recent, try the original browser tab; otherwise, start a new job.";
    }
    return message;
  }

  function recoverUnavailableGuestTask(message) {
    if (!guestMode || message !== 'Guest task not found or access expired') return false;
    clearTaskContext();
    show("This guest job is no longer available. Start a new temporary Rasterizer job below.");
    return true;
  }

  async function initialize({loadAccountResources, loadGuestResources, onResumeTask}) {
    config = await fetchImpl('config.json', {cache: 'no-store'}).then(response => response.json());
    const params = new URLSearchParams(locationRoot.search);
    const code = params.get('code');
    const requestedTask = params.get('task') || sessionStore.getItem('pending_task');
    if (code) {
      const verifier = sessionStore.getItem('pkce_verifier');
      const redirectUri = sessionStore.getItem('pkce_redirect_uri') || new URL('/', locationRoot.origin).href;
      const discardCallback = () => {
        sessionStore.removeItem('pkce_verifier');
        sessionStore.removeItem('pkce_redirect_uri');
        historyRoot.replaceState({}, '', locationRoot.pathname);
      };
      if (!verifier) {
        discardCallback();
        throw new Error('Sign-in attempt expired or opened in another tab. Please sign in again.');
      }
      const body = new URLSearchParams({
        grant_type: 'authorization_code',
        client_id: config.client_id,
        code,
        redirect_uri: redirectUri,
        code_verifier: verifier,
      });
      let result;
      let response;
      try {
        response = await fetchImpl(`https://${config.cognito_domain}/oauth2/token`, {
          method: 'POST',
          headers: {'content-type': 'application/x-www-form-urlencoded'},
          body,
        });
        result = await response.json();
      } catch (_error) {
        discardCallback();
        throw new Error('Cognito sign-in could not reach the token service. Please sign in again.');
      }
      if (!response.ok || !result.id_token) {
        const reason = result.error_description || result.error || `HTTP ${response.status}`;
        discardCallback();
        throw new Error(`Cognito sign-in could not complete (${reason}). Please sign in again.`);
      }
      sessionStore.removeItem('pkce_verifier');
      sessionStore.removeItem('pkce_redirect_uri');
      token = result.id_token;
      refreshToken = result.refresh_token || refreshToken;
      localStore.setItem('id_token', token);
      if (refreshToken) localStore.setItem('refresh_token', refreshToken);
      historyRoot.replaceState({}, '', requestedTask ? `${locationRoot.pathname}?task=${encodeURIComponent(requestedTask)}` : locationRoot.pathname);
      const postLoginPath = sessionStore.getItem('post_login_path');
      if (postLoginPath && postLoginPath !== '/') {
        sessionStore.removeItem('post_login_path');
        locationRoot.replace(postLoginPath);
        return;
      }
    }
    if (token && tokenExpiresSoon() && !await refreshSession()) clearAuth();
    setAuthState(Boolean(token));
    show(token
      ? 'Authenticated. Choose artwork and an output-settings option to run an isolated job.'
      : 'Guest access. Upload a Material Library or choose SVG-Only to run a temporary Rasterizer job.');
    if (token) await loadAccountResources();
    else await loadGuestResources();
    const resumedTask = new URLSearchParams(locationRoot.search).get('task') || requestedTask;
    if (resumedTask && (token || guestAccessToken)) {
      sessionStore.removeItem('pending_task');
      setTaskLocation(resumedTask);
      onResumeTask(resumedTask);
    } else if (resumedTask && guestMode) {
      clearTaskContext();
    }
  }

  return {
    api,
    guestApi,
    initialize,
    isGuest,
    jobAccessErrorMessage,
    recoverUnavailableGuestTask,
    setGuestAccessToken,
  };
}
