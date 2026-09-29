export function uploadPhase(message, value = null, documentRoot = document) {
  const panel = documentRoot.querySelector('#uploadProgressPanel');
  const progress = documentRoot.querySelector('#uploadProgress');
  const status = documentRoot.querySelector('#uploadProgressStatus');
  panel.hidden = false;
  status.textContent = message;
  if (value === null) progress.removeAttribute('value');
  else progress.value = Math.max(0, Math.min(100, value));
}

export function upload(file, target, onProgress) {
  return new Promise((resolve, reject) => {
    const formData = new FormData();
    Object.entries(target.fields).forEach(([key, value]) => formData.append(key, value));
    formData.append('file', file);
    const request = new XMLHttpRequest();
    request.open('POST', target.url);
    request.upload.onprogress = event => {
      const total = Math.max(Number(file.size) || Number(event.total) || 0, 1);
      const loaded = event.lengthComputable && event.total
        ? event.loaded / event.total * total
        : Math.min(event.loaded, total);
      onProgress?.(loaded, total);
    };
    request.onerror = () => reject(new Error('The upload was interrupted.'));
    request.onabort = () => reject(new Error('The upload was canceled.'));
    request.onload = () => request.status >= 200 && request.status < 300
      ? resolve()
      : reject(new Error(
        request.status === 403
          ? 'This upload session is no longer valid.'
          : `We couldn't upload the file (HTTP ${request.status}). Check its size and format.`,
      ));
    request.send(formData);
  });
}

export function submissionErrorMessage(error, button) {
  const message = String(error?.message || error);
  const label = button.textContent.trim();
  if (/upload capability|upload session is no longer valid/i.test(message)) {
    return `This upload session is no longer valid. Click "${label}" again to retry.`;
  }
  if (message === "We couldn't verify the uploaded file.") {
    return `${message} Click "${label}" again to upload it again.`;
  }
  if (message === 'The uploaded file is empty.') {
    return `${message} Choose a non-empty file, then click "${label}" again.`;
  }
  if (/^The uploaded file exceeds the [\d.]+ MB limit\.$/.test(message)) {
    return `${message} Choose a smaller file, then click "${label}" again.`;
  }
  if (message === 'The upload was interrupted.') {
    return `The upload was interrupted. Check your connection, then click "${label}" again to retry.`;
  }
  if (message.startsWith("We couldn't upload the file (HTTP ")) {
    return `${message} Click "${label}" again to retry.`;
  }
  return message;
}

export async function uploadBatch(entries, documentRoot = document) {
  const state = entries.map(({file}) => ({
    loaded: 0,
    total: Math.max(Number(file.size) || 0, 1),
  }));
  const total = state.reduce((sum, item) => sum + item.total, 0);
  const update = () => {
    const loaded = state.reduce((sum, item) => sum + item.loaded, 0);
    const percentage = Math.round(loaded / total * 100);
    uploadPhase(`Uploading securely to private storage · ${percentage}%`, percentage, documentRoot);
  };
  update();
  await Promise.all(entries.map(({file, target}, index) => upload(file, target, loaded => {
    state[index].loaded = Math.min(loaded, state[index].total);
    update();
  }).then(() => {
    state[index].loaded = state[index].total;
    update();
  })));
  uploadPhase('Uploads complete · preparing job submission', 100, documentRoot);
}

export function createRasterJobPoller({
  getCurrentTask,
  isGuest,
  guestApi,
  api,
  show,
  userFacingStyleError,
  jobAccessErrorMessage,
  renderOutputs,
  setPollTimer = () => {},
  schedule = (callback, delay) => setTimeout(callback, delay),
  documentRoot = document,
}) {
  const element = selector => documentRoot.querySelector(selector);

  async function poll() {
    const currentTask = getCurrentTask();
    try {
      const job = await (isGuest()
        ? guestApi(`/guest/jobs/${currentTask}`)
        : api(`/jobs/${currentTask}`));
      show(`${job.status.toUpperCase()} · ${currentTask}\n\n${(job.logs || []).join('\n')}`);
      if (job.status === 'completed') {
        element('#activity').classList.add('hidden');
        element('#submit').disabled = false;
        element('#holoSubmit').disabled = false;
        element('#outputs').innerHTML = renderOutputs(job.outputs);
        return;
      }
      if (job.status === 'failed') {
        const reason = userFacingStyleError(job.error || job.logs?.at(-1) || 'Worker failed');
        show(`FAILED · ${currentTask}\n\n${(job.logs || []).join('\n')}\n\nFailure reason: ${reason}`);
        element('#activity').classList.add('hidden');
        element('#submit').disabled = false;
        return;
      }
      setPollTimer(schedule(poll, 3000));
    } catch (error) {
      show(`ERROR: ${jobAccessErrorMessage(error.message)}`);
      element('#activity').classList.add('hidden');
      element('#submit').disabled = false;
      element('#holoSubmit').disabled = false;
    }
  }

  return poll;
}
