import {sanitizeSnapshot} from './library-snapshot.js';

const BASE = 'http://localhost:19520';
export const CREDENTIAL_KEY = 'lightburnPairing';
const messages = {
  not_paired: 'Pair with LightBurn in the extension tab first.',
  unauthorized: 'LightBurn did not accept this pairing. Check the active LightBurn instance and your computer clock, then pair again if needed.',
  declined: 'LightBurn did not approve pairing. Try again when ready to approve its dialog.',
  timeout: 'LightBurn did not respond in time. Check the app before trying again.',
  network: 'Could not reach LightBurn. Check that it is open and localhost access is allowed.',
  invalid_response: 'LightBurn returned an unsupported response. Check the installed API version.',
  storage: 'Could not save or read the pairing in this browser profile.',
};
export function publicError(code) {
  return Object.assign(new Error(messages[code] || 'The LightBurn request failed.'), {code: messages[code] ? code : 'invalid_response'});
}
export async function deriveToken(secret, timeMs = Date.now()) {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey('raw', encoder.encode(secret), {name: 'HMAC', hash: 'SHA-256'}, false, ['sign']);
  const signature = await crypto.subtle.sign('HMAC', key, encoder.encode(String(Math.floor(timeMs / 60000))));
  return Array.from(new Uint8Array(signature), byte => byte.toString(16).padStart(2, '0')).join('');
}
export function createCredentialStore(local) {
  // No secrets in sync storage or untrusted/content-script contexts.
  async function trusted() { await local.setAccessLevel({accessLevel: 'TRUSTED_CONTEXTS'}); }
  return {
    async get() { await trusted(); return (await local.get(CREDENTIAL_KEY))[CREDENTIAL_KEY] || null; },
    async set(value) { await trusted(); await local.set({[CREDENTIAL_KEY]: value}); },
    async remove() { await trusted(); await local.remove(CREDENTIAL_KEY); },
  };
}
export function createAuthenticatedClient({store, fetchImpl = globalThis.fetch, now = Date.now,
  requestTimeoutMs = 5000, pairTimeoutMs = 40000} = {}) {
  async function storage(method, value) {
    try { return await store[method](value); } catch { throw publicError('storage'); }
  }
  async function request(path, {secret, pairing = false} = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), pairing ? pairTimeoutMs : requestTimeoutMs);
    try {
      const headers = pairing ? {'Content-Type': 'application/json'} : {Authorization: `Bearer ${await deriveToken(secret, now())}`};
      const response = await fetchImpl(BASE + path, {
        method: pairing ? 'POST' : 'GET', headers, signal: controller.signal,
        redirect: 'error', credentials: 'omit', cache: 'no-store',
        ...(pairing ? {body: JSON.stringify({application_name: 'MOPA Rasterizer Connection POC', capabilities: ['state', 'project', 'upload']})} : {}),
      });
      if (!response.ok) {
        try { await response.body?.cancel(); } catch { /* Status determines the error. */ }
        throw publicError(pairing && [401, 403, 408].includes(response.status) ? 'declined' : response.status === 401 || response.status === 403 ? 'unauthorized' : 'invalid_response');
      }
      // Bound the POC response; do not forward a huge library through extension messaging.
      const reader = response.body.getReader();
      const chunks = []; let length = 0;
      while (true) {
        const {done, value} = await reader.read(); if (done) break;
        length += value.byteLength;
        if (length > 4 * 1024 * 1024) { await reader.cancel(); throw publicError('invalid_response'); }
        chunks.push(value);
      }
      const bytes = new Uint8Array(length); let offset = 0;
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
      try { return JSON.parse(new TextDecoder().decode(bytes)); } catch { throw publicError('invalid_response'); }
    } catch (error) {
      if (error.code && messages[error.code]) throw error;
      throw publicError(controller.signal.aborted ? 'timeout' : 'network');
    } finally { clearTimeout(timer); }
  }
  return {
    async hasPairing() { return Boolean((await storage('get'))?.secret); },
    async pair() {
      const response = await request('/api/connect', {pairing: true});
      if (response?.status !== 'ok' || typeof response.secret !== 'string' || !response.secret.length || response.secret.length > 4096) throw publicError('invalid_response');
      await storage('set', {secret: response.secret, capabilities: ['state', 'project', 'upload']});
      return {paired: true};
    },
    async forget() { await storage('remove'); },
    async readSnapshot() {
      const record = await storage('get');
      if (!record?.secret) throw publicError('not_paired');
      const reads = await Promise.allSettled(
        ['/api/status', '/api/project', '/api/units', '/api/material-library'].map(path => request(path, {secret: record.secret})));
      const failed = reads.find(result => result.status === 'rejected');
      if (failed) throw failed.reason;
      const [status, project, units, library] = reads.map(result => result.value);
      if ((await storage('get'))?.secret !== record.secret) throw publicError('not_paired');
      try { return sanitizeSnapshot({status, project, units, library}); } catch { throw publicError('invalid_response'); }
    },
  };
}
