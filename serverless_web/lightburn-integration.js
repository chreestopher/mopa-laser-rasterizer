const LARGE_LIMIT = 250 * 1024 * 1024;
export async function uploadNativeFile(url, name, send, progress = () => {}, fetchImpl = globalThis.fetch) {
  if (new URL(url).protocol !== 'https:' || !/\.lbrn2$/i.test(name)) throw new Error('Choose a retained native LightBurn project.');
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 300000);
  let reader, started = false;
  try {
    let response;
    try {response = await fetchImpl(url, {credentials: 'omit', cache: 'no-store', signal: controller.signal});}
    catch {throw new Error('The native file download could not start. Check your connection and refresh Job History before trying again.');}
    if (!response.ok) throw new Error('Could not download this retained file. Refresh Job History and try again.');
    if (Number(response.headers.get('content-length')) > LARGE_LIMIT) throw new Error('Native projects up to 250 MiB are supported. Use Download for this file.');
    const {uploadId} = await send('beginNativeUpload', {name}); started = true;
    reader = response.body.getReader(); let offset = 0;
    while (true) {
      let chunkResult;
      try {chunkResult = await reader.read();}
      catch {throw new Error('The native file download was interrupted. Check your connection, then stage the file again.');}
      const {done, value} = chunkResult; if (done) break;
      if (offset + value.length > LARGE_LIMIT) throw new Error('Native projects up to 250 MiB are supported. Use Download for this file.');
      for (let index = 0; index < value.length; index += 262144) {
        const chunk = value.subarray(index, index + 262144); let raw = '';
        for (const byte of chunk) raw += String.fromCharCode(byte);
        await send('appendNativeUpload', {uploadId, offset, base64: btoa(raw)});
        offset += chunk.length; progress(offset);
      }
    }
    return await send('finishNativeUpload', {uploadId});
  } catch (error) {
    if (started) {try {await send('discardNativeImport');} catch {throw new Error(`${error.message} The partial transfer could not be cleared. Use Discard / clear result before staging again.`);}}
    throw error;
  } finally {clearTimeout(timer); controller.abort(); if (reader) void reader.cancel().catch(() => {});}
}
export function installLightBurn() {
  if (location.origin !== 'https://serverless-staging.mopa-laser-rasterizer.com') return;
  let extensionId = '', checking = false, dialog, status, confirm, consent, review, discard, stage, fileLabel, projectLabel;
  let current = {}, busy = false, timer, trigger, selectedAnchor, largeFiles = false;
  const buttons = new Set();
  function unavailable() {
    extensionId = ''; for (const button of buttons) button.remove(); buttons.clear();
    if (dialog) {dialog.close(); dialog.remove(); dialog = null;} clearTimeout(timer);
  }
  async function send(command, fields = {}, id = extensionId) {
    const request = {version: 1, id: crypto.randomUUID(), command, ...fields};
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('Response timed out. Check LightBurn before trying again.')), command === 'confirmNativeImport' ? 540000 : 12000);
      try {
        chrome.runtime.sendMessage(id, request, response => {
          clearTimeout(timeout);
          if (chrome.runtime.lastError) {unavailable(); return reject(new Error('The LightBurn extension is unavailable.'));}
          if (!response || response.id !== request.id || response.version !== 1) return reject(new Error('Reload the LightBurn extension and this page.'));
          if (!response.ok) return reject(new Error(response.message || (response.error === 'not_paired' ? 'Pair with LightBurn using the extension diagnostics page first.' : 'The extension could not complete this request.')));
          resolve(response.result);
        });
      } catch {clearTimeout(timeout); unavailable(); reject(new Error('The LightBurn extension is unavailable.'));}
    });
  }
  function paint(value) {
    current = value;
    if (!dialog) return;
    status.dataset.state = value.state; status.textContent = value.message || (value.state === 'idle' ? 'No file staged. Stage the selected file to continue.' : value.state);
    fileLabel.textContent = value.name ? `${value.name}${value.size ? ` (${value.size} bytes)` : ''}` : selectedAnchor ? `${selectedAnchor.dataset.lightburnName} — not staged yet.` : 'No staged file.';
    projectLabel.textContent = value.project ? `Replace: ${value.project.name} · Device: ${value.project.device || 'unspecified'} · Shapes: ${value.project.shape_count ?? 'unknown'}` : '';
    review.disabled = busy || !['staged', 'reviewed'].includes(value.state);
    discard.disabled = busy || value.state === 'opening' || value.state === 'idle';
    consent.disabled = busy || value.state !== 'reviewed';
    confirm.disabled = busy || value.state !== 'reviewed' || !consent.checked;
    stage.disabled = busy || value.state !== 'idle' || !selectedAnchor;
    stage.hidden = value.state !== 'idle';
  }
  async function action(fn) {
    if (busy) return;
    busy = true; paint(current);
    try {paint(await fn());} catch (error) {
      // A rejected review revokes its nonce; a transfer may have left partial
      // bytes. Reconcile controls without erasing the useful failure message.
      if (extensionId) {try {paint(await send('getNativeImportStatus'));} catch { /* Preserve the original failure. */ }}
      if (dialog) {consent.checked = false; status.textContent = error.message;}
    }
    finally {busy = false; if (dialog) paintControls();}
  }
  function paintControls() {
    const message = status.textContent; paint(current); status.textContent = message;
  }
  function createDialog() {
    if (dialog) return;
    dialog = document.createElement('dialog'); dialog.className = 'lightburn-dialog'; dialog.setAttribute('aria-labelledby', 'lightburn-title');
    // Fixed markup only; file/project strings use textContent.
    dialog.innerHTML = '<h2 id="lightburn-title">Load in LightBurn</h2><p data-lb-file></p><p data-lb-project></p><p>Opening replaces the current saved project. Keep one LightBurn instance open and avoid other imports or edits during this operation.</p><p data-lb-status role="status" aria-live="polite"></p><button type="button" data-lb-review>Review current project</button><label class="lightburn-consent"><input type="checkbox" data-lb-consent> I reviewed the project above and agree to replace it.</label><div class="lightburn-actions"><button type="button" data-lb-confirm>Confirm replacement</button><button type="button" data-lb-discard>Discard / clear result</button><button type="button" data-lb-close>Close</button></div><p>Closing this dialog does not cancel an import. If completion is unknown, check LightBurn before sending again.</p>';
    document.body.append(dialog);
    const find = key => dialog.querySelector(`[data-lb-${key}]`);
    status = find('status'); fileLabel = find('file'); projectLabel = find('project');
    review = find('review'); confirm = find('confirm'); discard = find('discard'); consent = find('consent');
    stage = document.createElement('button'); stage.type = 'button'; stage.dataset.lbStage = ''; stage.textContent = 'Stage selected file';
    review.before(stage);
    stage.onclick = () => action(stageSelected);
    consent.onchange = paintControls;
    review.onclick = () => {consent.checked = false; action(() => send('reviewNativeImport'));};
    confirm.onclick = () => {
      if (!consent.checked || !current.reviewId) return;
      const reviewId = current.reviewId; consent.checked = false;
      action(() => {paint({...current, state: 'opening', message: 'Opening in LightBurn…'}); return send('confirmNativeImport', {reviewId});});
    };
    discard.onclick = () => {consent.checked = false; action(() => send('discardNativeImport'));};
    find('close').onclick = () => dialog.close();
    dialog.addEventListener('close', () => {clearTimeout(timer); consent.checked = false; trigger?.focus();});
  }
  async function poll() {
    if (!dialog?.open) return;
    if (!busy && current.state === 'opening') {try {const value = await send('getNativeImportStatus'); if (!busy) paint(value);} catch (error) {if (dialog) status.textContent = error.message;}}
    timer = setTimeout(poll, 1500);
  }
  async function stageSelected() {
      if (!largeFiles) throw new Error('Reload extension version 0.7.2 or newer, then refresh this page to enable files up to 250 MiB.');
      const snapshot = await send('getNativeImportStatus');
      if (snapshot.state !== 'idle') return snapshot;
      paint(snapshot);
      status.textContent = 'Downloading native project…';
      return uploadNativeFile(selectedAnchor.href, selectedAnchor.dataset.lightburnName, send,
        bytes => {if (dialog) status.textContent = `Staging ${(bytes / 1048576).toFixed(1)} MiB of up to 250 MiB…`;});
  }
  async function open(anchor, button) {
    selectedAnchor = anchor;
    trigger = button; createDialog(); consent.checked = false; dialog.showModal();
    await action(stageSelected);
    clearTimeout(timer); timer = setTimeout(poll, 1500);
  }
  function decorate() {
    if (!extensionId) return;
    for (const button of buttons) if (!button.isConnected) buttons.delete(button);
    for (const anchor of document.querySelectorAll('a[data-lightburn-name]')) {
      if (anchor.parentElement.querySelector('[data-load-lightburn]')) continue;
      const button = document.createElement('button'); button.type = 'button'; button.textContent = 'Load in LightBurn';
      button.className = 'staging-action-button'; button.dataset.loadLightburn = '';
      button.onclick = event => {event.stopPropagation(); void open(anchor, button);};
      anchor.after(button); buttons.add(button);
    }
  }
  window.addEventListener('message', async event => {
    if (event.source !== window || event.origin !== location.origin || event.data?.type !== 'mopa-lightburn-available' || !/^[a-p]{32}$/.test(event.data.extensionId || '') || checking) return;
    checking = true;
    try {
      const info = await send('getExtensionInfo', {}, event.data.extensionId);
      if (info.nativeImport) {extensionId = event.data.extensionId; largeFiles = info.maxFileBytes >= LARGE_LIMIT; decorate();}
    } catch {unavailable();} finally {checking = false;}
  });
  new MutationObserver(decorate).observe(document.body, {childList: true, subtree: true});
  const discover = () => window.postMessage({type: 'mopa-lightburn-discover'}, location.origin);
  discover();
  setInterval(async () => {
    if (extensionId && !checking) {
      checking = true; try {await send('getExtensionInfo');} catch {unavailable();} finally {checking = false;}
    } else if (!extensionId) discover();
  }, 3000);
}
if (typeof document !== 'undefined') installLightBurn();
