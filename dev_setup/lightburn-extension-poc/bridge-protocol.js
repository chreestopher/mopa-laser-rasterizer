const ALLOWED_ORIGIN = 'https://serverless-staging.mopa-laser-rasterizer.com';
import {validateNativeFile} from './native-open.js';

export function validateRequest(message, sender) {
  try {
    const uploadKeys = {beginNativeUpload: 'command,id,name,version', appendNativeUpload: 'base64,command,id,offset,uploadId,version', finishNativeUpload: 'command,id,uploadId,version'};
    if (uploadKeys[message?.command]) {
      if (new URL(sender.url).origin !== ALLOWED_ORIGIN || sender.frameId !== 0 || message.version !== 1 || typeof message.id !== 'string' || !/^[a-zA-Z0-9_-]{1,80}$/.test(message.id) || Object.keys(message).sort().join(',') !== uploadKeys[message.command]) return false;
      if (message.command === 'beginNativeUpload') {validateNativeFile({name: message.name, base64: btoa('<LightBurnProject/>')}); return true;}
      if (typeof message.uploadId !== 'string' || !/^[a-zA-Z0-9_-]{1,80}$/.test(message.uploadId)) return false;
      return message.command === 'finishNativeUpload' || (Number.isInteger(message.offset) && message.offset >= 0 && message.offset < 104857600 && typeof message.base64 === 'string' && message.base64.length > 0 && message.base64.length <= 349528);
    }
    const staging = message?.command === 'prepareNativeImport';
    const confirming = message?.command === 'confirmNativeImport';
    if (confirming && (typeof message.reviewId !== 'string' || !/^[a-zA-Z0-9_-]{1,80}$/.test(message.reviewId))) return false;
    if (staging) {
      if (Object.keys(message.file || {}).sort().join(',') !== 'base64,name') return false;
      validateNativeFile(message.file);
    }
    return new URL(sender.url).origin === ALLOWED_ORIGIN && sender.frameId === 0 &&
      message !== null && typeof message === 'object' && !Array.isArray(message) &&
      Object.keys(message).sort().join(',') === (staging ? 'command,file,id,version' : confirming ? 'command,id,reviewId,version' : 'command,id,version') &&
      message.version === 1 && ['getConnectionSummary', 'readMaterialLibrary', 'readPaletteLibrary', 'prepareNativeImport', 'getNativeImportStatus', 'reviewNativeImport', 'confirmNativeImport', 'discardNativeImport', 'getExtensionInfo'].includes(message.command) &&
      typeof message.id === 'string' && /^[a-zA-Z0-9_-]{1,80}$/.test(message.id);
  } catch { return false; }
}

function sanitizeResult(value) {
  if (!value || !Array.isArray(value.checks) || value.checks.length !== 2) return null;
  const checks = [];
  for (const [index, expected] of [200, 401].entries()) {
    const check = value.checks[index];
    const path = index === 0 ? '/' : '/api/status';
    if (!check || check.path !== path) return null;
    if (check.error === 'network' || check.error === 'timeout') {
      checks.push({path, expected, error: check.error, ok: false});
    } else if (Number.isInteger(check.status) && check.status >= 100 && check.status <= 599) {
      checks.push({path, expected, status: check.status, ok: check.status === expected});
    } else return null;
  }
  return {ok: checks.every(check => check.ok), checks};
}

export function createBridge({timeoutMs = 12000} = {}) {
  let consolePort = null;
  let pending = null;
  let sequence = 0;
  function finish(response) {
    if (!pending) return;
    const {resolve, timer, requestId} = pending;
    pending = null;
    clearTimeout(timer);
    resolve({version: 1, id: requestId, ...response});
  }
  return {
    attach(port) {
      finish({ok: false, error: 'console_changed'});
      consolePort = port;
      port.onDisconnect.addListener(() => {
        if (consolePort !== port) return;
        consolePort = null;
        finish({ok: false, error: 'console_closed'});
      });
      port.onMessage.addListener(message => {
        if (consolePort !== port || !pending || message?.id !== pending.internalId) return;
        if (['busy', 'not_paired', 'unauthorized', 'network', 'timeout', 'invalid_response', 'storage'].includes(message.error)) return finish({ok: false, error: message.error});
        let result;
        try { result = pending.command === 'readMaterialLibrary' ? sanitizeSnapshot(message.result) : ['prepareNativeImport', 'getNativeImportStatus'].includes(pending.command) ? sanitizeImportStatus(message.result) : sanitizeResult(message.result); }
        catch { result = null; }
        finish(result ? {ok: true, result} : {ok: false, error: 'invalid_response'});
      });
    },
    async handle(message, sender) {
      if (!validateRequest(message, sender)) return {version: 1, ok: false, error: 'denied'};
      const failure = error => ({version: 1, id: message.id, ok: false, error});
      if (!consolePort) return failure('console_closed');
      if (pending) return failure('busy');
      return new Promise(resolve => {
        const internalId = `probe-${++sequence}`;
        pending = {resolve, internalId, requestId: message.id, command: message.command,
          timer: setTimeout(() => finish({ok: false, error: 'timeout'}), timeoutMs)};
        try { consolePort.postMessage({id: internalId, command: message.command, ...(message.file ? {file: message.file} : {})}); }
        catch { finish({ok: false, error: 'console_closed'}); }
      });
    },
  };
}
import {sanitizeSnapshot} from './library-snapshot.js';
function sanitizeImportStatus(value) {
  if (!['idle', 'staged', 'reviewed', 'preflight', 'listening', 'sending', 'accepted', 'loaded', 'blocked', 'failed', 'unknown'].includes(value?.state)) return null;
  return {state: value.state, name: typeof value.name === 'string' ? value.name.slice(0, 166) : '',
    size: Number.isInteger(value.size) && value.size >= 0 && value.size <= 1048576 ? value.size : 0};
}
