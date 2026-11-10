import {createAuthenticatedClient, createCredentialStore, CREDENTIAL_KEY, publicError} from './auth-client.js';

export function createPairingPanel({isBusy, setBusy}) {
  const client = createAuthenticatedClient({store: createCredentialStore(chrome.storage.local)});
  const pairingStatus = document.querySelector('#pairing-status');
  const libraryStatus = document.querySelector('#library-status');
  const summary = document.querySelector('#library-summary');
  const entries = document.querySelector('#library-entry');
  const details = document.querySelector('#entry-details');
  let generation = 0;
  function clear() {
    summary.textContent = ''; entries.replaceChildren(); entries.disabled = true;
    details.textContent = ''; libraryStatus.textContent = ''; libraryStatus.dataset.state = 'idle';
  }
  async function refreshPairing() {
    try {
      const saved = await client.hasPairing();
      pairingStatus.dataset.state = saved ? 'saved' : 'unpaired';
      pairingStatus.textContent = saved ? 'Pairing saved in this browser. Read the selected library to verify access.' : 'Not paired in this browser.';
    } catch (error) { pairingStatus.dataset.state = 'failed'; pairingStatus.textContent = error.message; }
  }
  function render(snapshot) {
    const {library, units, project} = snapshot;
    const count = library.entries.length;
    libraryStatus.dataset.state = count ? 'loaded' : 'empty';
    libraryStatus.textContent = count ? 'Authenticated library read succeeded. Snapshot only; nothing has been saved to Vault.' : 'Authenticated read succeeded, but the selected library has no entries. Select a nonempty library in LightBurn and read again.';
    summary.textContent = `${library.name || 'No selected library'} · ${count} settings · Speed: ${units.units} · Distance: ${units.distance_units} · Device: ${project.device?.name || 'Not specified'} · Project: ${project.name || 'Untitled'}`;
    for (const [index, entry] of library.entries.entries()) {
      const option = document.createElement('option'); option.value = String(index);
      option.textContent = `${entry.material || 'Material'} — ${entry.description || 'Unnamed setting'}`;
      entries.append(option);
    }
    entries.disabled = !count;
    entries.onchange = () => { details.textContent = JSON.stringify(library.entries[Number(entries.value)], null, 2); };
    if (count) entries.onchange();
  }
  async function read() {
    if (isBusy()) return {error: 'busy'};
    setBusy(true); clear(); const current = generation;
    libraryStatus.textContent = 'Reading the selected LightBurn library…';
    libraryStatus.dataset.state = 'reading';
    try {
      const snapshot = await client.readSnapshot();
      if (current !== generation) throw publicError('not_paired');
      render(snapshot);
      pairingStatus.dataset.state = 'paired'; pairingStatus.textContent = 'Paired. Authenticated reads succeeded.';
      return {result: snapshot};
    } catch (error) {
      clear(); libraryStatus.dataset.state = 'failed'; libraryStatus.textContent = error.message;
      if (error.code === 'unauthorized') { pairingStatus.dataset.state = 'failed'; pairingStatus.textContent = error.message; }
      return {error: error.code || 'invalid_response'};
    } finally { setBusy(false); }
  }
  document.querySelector('#read-library').addEventListener('click', read);
  document.querySelector('#pair').addEventListener('click', async () => {
    if (isBusy()) return;
    setBusy(true); clear();
    pairingStatus.dataset.state = 'pairing';
    pairingStatus.textContent = 'Approve “MOPA Rasterizer Connection POC” in LightBurn within 30 seconds.';
    try {
      await client.pair(); pairingStatus.dataset.state = 'paired';
      pairingStatus.textContent = 'Pairing saved. Read the selected library to verify access.';
    } catch (error) { pairingStatus.dataset.state = 'failed'; pairingStatus.textContent = error.message; }
    finally { setBusy(false); }
  });
  document.querySelector('#forget').addEventListener('click', async () => {
    if (isBusy()) return;
    setBusy(true); generation++; clear();
    try { await client.forget(); await refreshPairing(); pairingStatus.textContent = 'Local pairing forgotten. This does not revoke access in LightBurn.'; }
    catch (error) { pairingStatus.dataset.state = 'failed'; pairingStatus.textContent = error.message; }
    finally { setBusy(false); }
  });
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== 'local' || !changes[CREDENTIAL_KEY]) return;
    generation++; clear();
    if (!isBusy()) refreshPairing();
  });
  refreshPairing();
  return {read};
}
