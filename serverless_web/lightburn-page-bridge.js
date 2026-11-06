export function observeLightBurn(onChange) {
  let id = '', checking = false;
  const changed = value => {if (id !== value) {id = value; onChange(Boolean(id));}};
  async function send(command, target = id) {
    const request = {version: 1, id: crypto.randomUUID(), command};
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('The extension did not respond. Reload it and try again.')), 15000);
      try {
        chrome.runtime.sendMessage(target, request, response => {
          clearTimeout(timer);
          if (chrome.runtime.lastError) {changed(''); return reject(new Error('The LightBurn extension is unavailable.'));}
          if (response?.id !== request.id || response.version !== 1) return reject(new Error('Unexpected extension response. Reload the extension.'));
          if (!response.ok) return reject(new Error(response.message || ({not_paired: 'Pair with LightBurn in extension diagnostics first.', unauthorized: 'LightBurn rejected this pairing. Pair again in extension diagnostics.', network: 'Open LightBurn and try reading the library again.'}[response.error]) || 'Could not read LightBurn. Check extension diagnostics.'));
          resolve(response.result);
        });
      } catch {clearTimeout(timer); changed(''); reject(new Error('The LightBurn extension is unavailable.'));}
    });
  }
  window.addEventListener('message', async event => {
    const candidate = event.data?.extensionId;
    if (event.source !== window || event.origin !== location.origin || event.data?.type !== 'mopa-lightburn-available' || !/^[a-p]{32}$/.test(candidate || '') || checking) return;
    checking = true;
    try {if ((await send('getExtensionInfo', candidate)).materialImport) changed(candidate);}
    catch {changed('');} finally {checking = false;}
  });
  const discover = () => window.postMessage({type: 'mopa-lightburn-discover'}, location.origin);
  discover();
  setInterval(async () => {
    if (!id) return discover();
    if (checking) return;
    checking = true; try {await send('getExtensionInfo');} catch {changed('');} finally {checking = false;}
  }, 3000);
  return {send};
}
