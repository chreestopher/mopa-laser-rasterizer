// Announces only the public extension ID. Requests still use the external
// message allowlist; no DOM injection and no credentials cross this boundary.
window.addEventListener('message', event => {
  if (event.source !== window || event.origin !== location.origin || event.data?.type !== 'mopa-lightburn-discover') return;
  window.postMessage({type: 'mopa-lightburn-available', extensionId: chrome.runtime.id}, location.origin);
});
