import {MAX_NATIVE_BYTES, validateNativeBytes} from './native-open.js';
export const CHUNK_BYTES = 256 * 1024;
export function createBinaryStore() {
  const database = new Promise((resolve, reject) => {
    const request = indexedDB.open('lightburn-native-files', 1);
    request.onupgradeneeded = () => {request.result.createObjectStore('parts'); request.result.createObjectStore('meta');};
    request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
  });
  async function transaction(action) {
    const db = await database;
    return new Promise((resolve, reject) => {
      const tx = db.transaction(['parts', 'meta'], 'readwrite'); let result, failure;
      tx.oncomplete = () => resolve(result); tx.onerror = tx.onabort = () => reject(failure || tx.error || new Error('Could not store native file.'));
      action(tx, value => {result = value;}, error => {failure = error; tx.abort();});
    });
  }
  return {
    clear() {return transaction(tx => {tx.objectStore('parts').clear(); tx.objectStore('meta').clear();});},
    begin(id, name) {return transaction(tx => {tx.objectStore('parts').clear(); tx.objectStore('meta').put({id, name, size: 0}, 'current');});},
    append(id, offset, base64) {
      if (typeof base64 !== 'string' || base64.length > 349528) throw new Error('File chunk is too large.');
      const raw = atob(base64);
      if (!raw.length || raw.length > CHUNK_BYTES || btoa(raw) !== base64) throw new Error('Invalid file chunk.');
      const bytes = Uint8Array.from(raw, c => c.charCodeAt(0));
      return transaction((tx, done, fail) => {
        const request = tx.objectStore('meta').get('current');
        request.onsuccess = () => {
          const meta = request.result;
          if (!meta || meta.id !== id || meta.size !== offset || meta.size + bytes.length > MAX_NATIVE_BYTES) return fail(new Error('Invalid upload offset or file exceeds 100 MiB.'));
          tx.objectStore('parts').put(bytes, offset); meta.size += bytes.length; tx.objectStore('meta').put(meta, 'current'); done({size: meta.size});
        };
      });
    },
    async read(id) {
      const data = await transaction((tx, done, fail) => {
        const meta = tx.objectStore('meta').get('current');
        meta.onsuccess = () => {
          if (!meta.result || meta.result.id !== id) return fail(new Error('Staged file is unavailable. Stage it again.'));
          const parts = tx.objectStore('parts').getAll();
          parts.onsuccess = () => done({meta: meta.result, parts: parts.result});
        };
      });
      const bytes = new Uint8Array(await new Blob(data.parts).arrayBuffer());
      if (bytes.length !== data.meta.size) throw new Error('Incomplete staged file.');
      return validateNativeBytes({name: data.meta.name, bytes});
    },
  };
}
