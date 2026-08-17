(() => {
  const themeSwitch = document.getElementById('theme_switch');
  const loginLink = document.getElementById('login_link');
  const authConsole = document.getElementById('auth_console');

  const applyTheme = light => {
    document.body.classList.toggle('light-machine', light);
    if (themeSwitch) themeSwitch.checked = light;
  };

  let savedTheme = 'dark';
  try { savedTheme = localStorage.getItem('mopa-machine-theme') || 'dark'; } catch (_) {}
  applyTheme(savedTheme === 'light');
  themeSwitch?.addEventListener('change', () => {
    applyTheme(themeSwitch.checked);
    try { localStorage.setItem('mopa-machine-theme', themeSwitch.checked ? 'light' : 'dark'); } catch (_) {}
  });

  const showAuthStatus = ({signed_in: signedIn = false} = {}) => {
    if (loginLink) loginLink.hidden = Boolean(signedIn);
    if (authConsole) authConsole.hidden = !signedIn;
  };

  const authStatus = fetch('/auth-status', {credentials:'same-origin'})
    .then(response => response.ok ? response.json() : {signed_in:false})
    .then(data => {
      showAuthStatus(data);
      return data;
    })
    .catch(() => {
      const fallbackStatus = {signed_in:false};
      showAuthStatus(fallbackStatus);
      return fallbackStatus;
    });

  window.machineChrome = Object.freeze({authStatus, applyTheme, showAuthStatus});
})();
