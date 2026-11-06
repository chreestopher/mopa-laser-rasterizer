import {deriveToken, publicError} from './auth-client.js';
export const MAX_NATIVE_BYTES = 100 * 1024 * 1024;
export function validateNativeBytes({name, bytes}) {
  if (typeof name !== 'string' || !/^[\x20-\x7e]{1,160}\.lbrn2$/i.test(name) || /[\\/:]/.test(name)) throw new Error('Choose a native .lbrn2 file with a simple filename.');
  if (!(bytes instanceof Uint8Array) || bytes.length > MAX_NATIVE_BYTES) throw new Error('Native projects must be no larger than 100 MiB.');
  const decoder = new TextDecoder('utf-8', {fatal: true}); let prefix = '', tail = '';
  for (let offset = 0; offset < bytes.length; offset += 65536) {
    const text = decoder.decode(bytes.subarray(offset, offset + 65536), {stream: true});
    if (!offset) prefix = text;
    if (/<!DOCTYPE|<!ENTITY/i.test(tail + text)) throw new Error('Unsupported native XML declarations.');
    tail = text.slice(-16);
  }
  decoder.decode();
  if (!/^\s*(?:<\?xml[^?]*\?>\s*)?<LightBurnProject(?:\s|>|\/)/.test(prefix)) throw new Error('Expected a native LightBurn project.');
  return {name, bytes};
}

export function validateNativeFile(value) {
  if (!value || typeof value.name !== 'string' || !/^[\x20-\x7e]{1,160}\.lbrn2$/i.test(value.name) || /[\\/:]/.test(value.name)) throw new Error('Choose a native .lbrn2 file with a simple filename.');
  const encoded = value.base64;
  if (typeof encoded !== 'string' || encoded.length > 1398104 || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(encoded)) throw new Error('Invalid file encoding or file exceeds 1 MiB.');
  const raw = atob(encoded);
  if (btoa(raw) !== encoded || raw.length > 1048576) throw new Error('Invalid file encoding or size.');
  const bytes = Uint8Array.from(raw, character => character.charCodeAt(0));
  const xml = new TextDecoder('utf-8', {fatal: true}).decode(bytes);
  if (/<!DOCTYPE|<!ENTITY/i.test(xml) || !/^\s*(?:<\?xml[^?]*\?>\s*)?<LightBurnProject(?:\s|>|\/)/.test(xml)) throw new Error('Expected a native LightBurn project.');
  return {name: value.name, bytes};
}

export function createSseParser({onReady, onImport}) {
  const decoder = new TextDecoder('utf-8', {fatal: true});
  let buffer = '', event = '', data = [], size = 0, ready = false;
  return {push(bytes) {
    buffer += decoder.decode(bytes, {stream: true});
    let end;
    while ((end = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, end).replace(/\r$/, ''); buffer = buffer.slice(end + 1);
      size += line.length + 1;
      if (size > 65536) throw new Error('Event too large.');
      if (!line) {
        if (event === 'file_imported') {
          const value = JSON.parse(data.join('\n'));
          if (typeof value?.success !== 'boolean') throw new Error('Invalid import event.');
          onImport(value);
        }
        event = ''; data = []; size = 0;
      } else if (line === ':connected' && !ready) { ready = true; onReady(); }
      else if (line.startsWith('event:')) event = line.slice(6).trim();
      else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
    }
    if (size + buffer.length > 65536) throw new Error('Event too large.');
  }};
}

const deferred = () => { let resolve; const promise = new Promise(done => {resolve = done;}); return {promise, resolve}; };
async function bounded(promise, ms) {
  let timer;
  try { return await Promise.race([promise, new Promise((_, reject) => {timer = setTimeout(() => reject(new Error('Timed out.')), ms);})]); }
  finally { clearTimeout(timer); }
}
const sameProject = (a, b) => a?.modified === false && b?.modified === false && a.filename === b.filename && a.shape_count === b.shape_count && a.device?.name === b.device?.name;

export function createNativeOpener({store, fetchImpl = globalThis.fetch, readinessMs = 5000, completionMs = 15000, requestMs = 5000, onState = () => {}}) {
  let active = false;
  async function request(path, secret, signal, options = {}) {
    try {
      return await bounded(fetchImpl('http://localhost:19520' + path, {method: 'GET', redirect: 'error', credentials: 'omit', cache: 'no-store', signal,
        ...options, headers: {Authorization: `Bearer ${await deriveToken(secret)}`, ...options.headers}}), requestMs);
    } catch (error) {throw publicError(error.message === 'Timed out.' || signal?.aborted ? 'timeout' : 'network');}
  }
  async function project(secret, signal) {
    const response = await request('/api/project', secret, signal);
    if (!response.ok) {
      void response.body?.cancel().catch(() => {});
      throw publicError([401, 403].includes(response.status) ? 'unauthorized' : 'invalid_response');
    }
    const reader = response.body.getReader(); let text = ''; const decoder = new TextDecoder();
    try {
      await bounded((async () => { while (true) { const {done, value} = await reader.read(); if (done) break; text += decoder.decode(value, {stream: true}); if (text.length > 1048576) throw new Error('Project response too large.'); } })(), requestMs);
      return JSON.parse(text);
    } finally { void reader.cancel().catch(() => {}); }
  }
  return {
    async review() {
      const record = await store.get(); if (!record?.secret) throw new Error('Pair with LightBurn first.');
      const controller = new AbortController();
      try { return await project(record.secret, controller.signal); } finally { controller.abort(); }
    },
    async open(payload, {confirmed, reviewedProject} = {}) {
      const finish = (state, message, metadata) => {onState(state); return {state, message, ...(metadata ? {project: metadata} : {})};};
      if (active || !confirmed) return finish('blocked', 'Review and confirm the replacement first.');
      active = true;
      const controller = new AbortController(); let reader, sent = false, lost = false, interference = false;
      const ready = deferred(), imported = deferred();
      try {
        const file = payload.bytes ? validateNativeBytes(payload) : validateNativeFile(payload);
        const record = await store.get(); if (!record?.secret) throw new Error('Pair with LightBurn first.');
        onState('preflight');
        if (!sameProject(await project(record.secret, controller.signal), reviewedProject)) throw new Error('Project changed or contains unsaved work. Review it again.');
        onState('listening');
        const response = await request('/api/events', record.secret, controller.signal);
        if ([401, 403].includes(response.status)) {void response.body?.cancel().catch(() => {}); throw publicError('unauthorized');}
        if (!response.ok || !response.headers.get('content-type')?.includes('text/event-stream')) throw new Error('Completion stream unavailable.');
        reader = response.body.getReader();
        const parser = createSseParser({onReady: () => ready.resolve(true), onImport: value => {if (!sent) interference = true; imported.resolve(value);}});
        void (async () => {
          try { while (true) { const {done, value} = await reader.read(); if (done) break; parser.push(value); } }
          catch { /* A lost or malformed stream cannot confirm completion. */ }
          finally { lost = true; ready.resolve(false); imported.resolve(null); }
        })();
        if (!await bounded(ready.promise, readinessMs)) throw new Error('Completion stream disconnected.');
        if (!sameProject(await project(record.secret, controller.signal), reviewedProject) || lost || interference) throw new Error('Project or import activity changed. Review again.');
        if ((await store.get())?.secret !== record.secret) throw new Error('Pairing changed. Review again.');
        if (lost || interference) throw new Error('Completion stream or import activity changed. Review again.');
        onState('sending'); sent = true;
        const accepted = await request('/api/file/open', record.secret, controller.signal, {method: 'POST', headers: {'Content-Type': 'application/octet-stream', 'X-Filename': file.name}, body: file.bytes});
        void accepted.body?.cancel().catch(() => {});
        if (accepted.status >= 400 && accepted.status < 500) return finish('failed', [401, 403].includes(accepted.status) ? publicError('unauthorized').message : `LightBurn rejected the file (HTTP ${accepted.status}).`);
        if (accepted.status !== 202) throw new Error('Unexpected upload response.');
        onState('accepted');
        const event = await bounded(imported.promise, completionMs);
        if (!event) throw new Error('Completion stream disconnected.');
        if (!event.success) return finish('failed', 'LightBurn reported that the native file could not be opened.');
        const metadata = await project(record.secret, controller.signal);
        return finish('loaded', 'LightBurn reported completion. Inspect the artwork and settings in LightBurn.', metadata);
      } catch (error) {
        return finish(sent ? 'unknown' : 'blocked', sent ? 'Completion could not be verified. Check LightBurn before staging or sending this file again.' : error.message);
      } finally { controller.abort(); if (reader) void reader.cancel().catch(() => {}); active = false; }
    },
  };
}
