const form = document.querySelector('#connection-form');
const button = document.querySelector('#check');
const status = document.querySelector('#status');
const results = document.querySelector('#results');
const explanations = {
  console_closed: 'Open the extension’s connection-test tab in this browser, keep it open, and try again.',
  console_changed: 'The active extension tab changed. Keep one connection-test tab open and try again.',
  busy: 'A connection check is already running. Wait for it to finish and try again.',
  timeout: 'The extension did not finish in time. Check its tab and try again.',
  denied: 'This page or request is not allowed by the extension. Reload the current POC extension.',
  not_paired: 'Pair with LightBurn in the extension tab first.',
  unauthorized: 'LightBurn did not accept this pairing. Check the active instance and clock, then pair again in the extension if needed.',
  network: 'The extension could not reach LightBurn. Check that LightBurn is open.',
  invalid_response: 'LightBurn returned an unsupported response. Check the installed API version.',
  storage: 'The extension could not read its saved pairing. Check the extension tab.',
};

function send(extensionId, request) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('The extension did not respond. Open its connection-test tab and try again.')), 15000);
    try {
      if (!globalThis.chrome?.runtime?.sendMessage) throw new Error('Load the extension in this Edge or Chrome browser, then reload this page.');
      chrome.runtime.sendMessage(extensionId, request, response => {
        clearTimeout(timer);
        if (chrome.runtime.lastError) return reject(new Error('Could not reach that extension. Check the ID, reload the extension, and reload this page.'));
        if (!response || response.version !== 1 || response.id !== request.id) return reject(new Error('The extension returned an unexpected reply. Reload it and try again.'));
        resolve(response);
      });
    } catch (error) { clearTimeout(timer); reject(error); }
  });
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  if (button.disabled) return;
  button.disabled = true;
  results.replaceChildren();
  status.textContent = 'Checking website → extension → LightBurn…';
  status.dataset.outcome = 'checking';
  try {
    const response = await send(document.querySelector('#extension-id').value.trim(),
      {version: 1, id: crypto.randomUUID(), command: 'getConnectionSummary'});
    if (!response.ok) throw new Error(explanations[response.error] || 'The extension could not complete this check. Reload its tab and try again.');
    for (const check of response.result.checks) {
      const item = document.createElement('li');
      item.textContent = `${check.path}: ${check.error || `HTTP ${check.status} (expected ${check.expected})`}`;
      results.append(item);
    }
    status.dataset.outcome = response.result.ok ? 'passed' : 'failed';
    status.textContent = response.result.ok
      ? 'Website connection passed. This page reached LightBurn through your extension. Pairing is checked separately.'
      : 'The extension responded, but LightBurn connection checks failed. Check LightBurn and localhost permission in the extension.';
  } catch (error) {
    status.dataset.outcome = 'failed';
    status.textContent = error.message;
  } finally { button.disabled = false; }
});

const libraryButton = document.querySelector('#read-library');
const libraryStatus = document.querySelector('#library-status');
const librarySummary = document.querySelector('#library-summary');
const libraryEntry = document.querySelector('#library-entry');
const entryDetails = document.querySelector('#entry-details');
libraryButton.addEventListener('click', async () => {
  if (libraryButton.disabled || !form.reportValidity()) return;
  libraryButton.disabled = true;
  librarySummary.textContent = ''; libraryEntry.replaceChildren(); libraryEntry.disabled = true; entryDetails.textContent = '';
  libraryStatus.dataset.state = 'reading'; libraryStatus.textContent = 'Reading the selected library through the extension…';
  try {
    const response = await send(document.querySelector('#extension-id').value.trim(),
      {version: 1, id: crypto.randomUUID(), command: 'readMaterialLibrary'});
    if (!response.ok) throw new Error(explanations[response.error] || 'Could not read the library. Check the extension tab and try again.');
    const {library, units, project} = response.result;
    librarySummary.textContent = `${library.name || 'No selected library'} · ${library.entries.length} settings · Speed: ${units.units} · Distance: ${units.distance_units} · Device: ${project.device?.name || 'Not specified'} · Project: ${project.name || 'Untitled'}`;
    for (const [index, entry] of library.entries.entries()) {
      const option = document.createElement('option'); option.value = String(index);
      option.textContent = `${entry.material || 'Material'} — ${entry.description || 'Unnamed setting'}`;
      libraryEntry.append(option);
    }
    libraryEntry.disabled = !library.entries.length;
    libraryEntry.onchange = () => { entryDetails.textContent = JSON.stringify(library.entries[Number(libraryEntry.value)], null, 2); };
    if (library.entries.length) libraryEntry.onchange();
    libraryStatus.dataset.state = library.entries.length ? 'loaded' : 'empty';
    libraryStatus.textContent = library.entries.length ? 'Library snapshot received through the extension. Nothing saved to Vault.' : 'Authenticated read succeeded, but the selected library has no entries. Select a nonempty library in LightBurn and read again.';
  } catch (error) { libraryStatus.dataset.state = 'failed'; libraryStatus.textContent = error.message; }
  finally { libraryButton.disabled = false; }
});
