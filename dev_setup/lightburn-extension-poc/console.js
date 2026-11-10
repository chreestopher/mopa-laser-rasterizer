import {probeConnection} from './lightburn-client.js';
import {createPairingPanel} from './pairing-panel.js';

const button = document.querySelector('#check');
const status = document.querySelector('#status');
const results = document.querySelector('#results');
const setBusy = value => document.querySelectorAll('button').forEach(element => {element.disabled = value;});
const pairing = createPairingPanel({isBusy: () => button.disabled, setBusy});

document.querySelector('#extension-id').textContent = chrome.runtime.id;

async function runProbe() {
  if (button.disabled) return null;
  setBusy(true);
  status.textContent = 'Checking local LightBurn…';
  status.dataset.outcome = 'checking';
  results.replaceChildren();
  try {
    const result = await probeConnection();
    for (const check of result.checks) {
      const item = document.createElement('li');
      const detail = check.error === 'timeout' ? 'Request timed out.'
        : check.error ? 'No readable response. LightBurn may be closed or browser access may be blocked.'
        : `HTTP ${check.status}${check.ok ? ' (expected)' : `; expected HTTP ${check.expected}`}.`;
      item.textContent = `${check.label}: ${detail}`;
      results.append(item);
    }
    status.textContent = result.message;
    status.dataset.outcome = result.ok ? 'passed' : 'failed';
    return result;
  } catch {
    status.textContent = 'The connection test could not finish. Reload this tab and try again.';
    status.dataset.outcome = 'failed';
  } finally {
    setBusy(false);
  }
}

button.addEventListener('click', () => runProbe());

const bridgeStatus = document.querySelector('#bridge-status');
function connectBridge() {
  try {
    const port = chrome.runtime.connect({name: 'lightburn-console'});
    bridgeStatus.textContent = 'Website bridge ready. Keep this tab open while checking from staging.';
    port.onMessage.addListener(async message => {
      let response;
      if (message.command === 'getConnectionSummary') {
        const result = await runProbe(); response = result ? {result} : {error: 'busy'};
      } else if (message.command === 'readMaterialLibrary') response = await pairing.read();
      else return;
      try { port.postMessage({id: message.id, ...response}); }
      catch { /* A lost bridge does not replay a request. */ }
    });
    port.onDisconnect.addListener(() => {
      void chrome.runtime.lastError;
      bridgeStatus.textContent = 'Website bridge disconnected. Reconnecting…';
      setTimeout(connectBridge, 1000);
    });
  } catch {
    bridgeStatus.textContent = 'Extension was reloaded. Reload this tab to reconnect the website bridge.';
  }
}
connectBridge();
