import {validateNativeFile} from './native-open.js';

// One owner per staged file. Persist intent before opening; never replay intent
// after worker termination. storage.session survives worker suspension, not a
// browser restart. No secrets or artwork are included in public snapshots.
export function createImportController({storage, opener}) {
  let record, busy = false;
  const releasedOwners = new Set();
  const initialized = (async () => {
    record = await storage.get() || {state: 'idle'};
    if (record.state === 'opening') {
      record = {...record, state: 'unknown', message: 'Completion was interrupted. Check LightBurn before sending again.'};
      delete record.file; delete record.reviewId; delete record.project;
      await storage.set(record);
    }
  })();
  const snapshot = () => {
    const {state, name, size, message, reviewId, project, uploadId} = record;
    return {state, name, size, message, reviewId, uploadId, project: project ? {name: String(project.filename || 'Untitled').replaceAll('\\', '/').split('/').pop(), device: project.device?.name || '', shape_count: project.shape_count} : undefined};
  };
  const checkOwner = owner => {if (record.owner !== undefined && record.owner !== owner) throw new Error('Another page owns this staged file. Return to that page or close this browser session.');};
  async function locked(action) {
    await initialized;
    if (busy) throw new Error('An import operation is already in progress.');
    busy = true; try {return await action();} finally {busy = false;}
  }
  async function save(next) {
    if (releasedOwners.has(next.owner)) next = {...next, owner: undefined, reviewId: undefined, project: undefined, state: next.state === 'reviewed' ? 'staged' : next.state};
    await storage.set(next); record = next;
  }
  return {
    async releaseOwner(owner) {
      await initialized; releasedOwners.add(owner);
      if (!busy && record.owner === owner) await save({...record});
    },
    async status(owner) {await initialized; checkOwner(owner); return snapshot();},
    beginUpload(name, owner) {return locked(async () => {
      if (record.file || ['unknown', 'uploading'].includes(record.state)) throw new Error('Discard the existing staged file before uploading another.');
      validateNativeFile({name, base64: btoa('<LightBurnProject/>')});
      await save({state: 'uploading', name, owner, uploadId: crypto.randomUUID(), message: 'Receiving native file…'});
      return snapshot();
    });},
    finishUpload(uploadId, size, owner) {return locked(async () => {
      checkOwner(owner);
      if (!Number.isInteger(size) || size <= 0 || size > 262144000) throw new Error('Native projects must be no larger than 250 MiB.');
      if (record.state !== 'uploading' || record.uploadId !== uploadId) throw new Error('This upload is no longer active.');
      await save({...record, state: 'staged', size, file: {fileId: uploadId, name: record.name}, message: 'File staged. Review the current LightBurn project.'});
      return snapshot();
    });},
    stage(file, owner) {return locked(async () => {
      if (record.file || ['unknown', 'uploading'].includes(record.state)) throw new Error('Review or discard the existing import before staging another file.');
      const validated = validateNativeFile(file);
      await save({state: 'staged', file: {...file}, owner, name: validated.name, size: validated.bytes.length, message: 'File staged. Review the current LightBurn project.'});
      return snapshot();
    });},
    review(owner) {return locked(async () => {
      checkOwner(owner); if (!record.file) throw new Error('Stage a native project first.');
      await save({...record, owner, reviewId: undefined, project: undefined, state: 'staged'});
      const project = await opener.review();
      if (project.modified !== false) throw new Error('Save your current LightBurn work before continuing.');
      await save({...record, project, reviewId: crypto.randomUUID(), state: 'reviewed', message: 'Opening will replace this saved project.'});
      return snapshot();
    });},
    open(reviewId, owner) {return locked(async () => {
      checkOwner(owner);
      if (!record.file || !reviewId || record.reviewId !== reviewId || record.state !== 'reviewed') throw new Error('Review the current project again before confirming.');
      const file = record.file, project = record.project;
      await save({state: 'opening', name: record.name, size: record.size, owner, message: 'Opening in LightBurn. You can close this dialog; the import will continue.'});
      let result;
      try {result = await opener.open(file, {confirmed: true, reviewedProject: project});}
      catch {result = {state: 'unknown', message: 'Check LightBurn before sending this file again.'};}
      await save({...record, state: result.state, message: result.message});
      return snapshot();
    });},
    discard(owner) {return locked(async () => {checkOwner(owner); await save({state: 'idle'}); return snapshot();});},
  };
}
