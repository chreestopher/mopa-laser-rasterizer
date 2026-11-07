import {createBridge, validateRequest} from './bridge-protocol.js';
import {createImportController} from './import-controller.js';
import {createNativeOpener} from './native-open.js';
import {createCredentialStore, createAuthenticatedClient} from './auth-client.js';
import {createBinaryStore} from './binary-store.js';

const files = createBinaryStore();
const libraryClient = createAuthenticatedClient({store: createCredentialStore(chrome.storage.local), fetchImpl: (...args) => fetch(...args)});
const filesReady = (async () => {
  const previous = (await chrome.storage.session.get('nativeImport')).nativeImport;
  if (!previous?.file?.fileId && previous?.state !== 'uploading') await files.clear();
})();
const nativeOpener = createNativeOpener({store: createCredentialStore(chrome.storage.local), fetchImpl: (...args) => fetch(...args), requestMs: 20000, uploadMs: 120000, completionMs: 300000});

const imports = createImportController({
  storage: {
    async get() {return (await chrome.storage.session.get('nativeImport')).nativeImport;},
    async set(value) {await chrome.storage.session.set({nativeImport: value});},
  },
  opener: {
    review: () => nativeOpener.review(),
    async open(file, options) {
      try {return await nativeOpener.open(file.fileId ? await files.read(file.fileId) : file, options);}
      finally {await files.clear();}
    },
  },
});
async function handle(message, sender) {
  if (!validateRequest(message, sender) || !Number.isInteger(sender.tab?.id)) return {version: 1, id: message?.id, ok: false, error: 'denied'};
  const reply = result => ({version: 1, id: message.id, ok: true, result});
  const owner = `${new URL(sender.url).origin}:${sender.tab.id}`;
  if (message.command === 'getExtensionInfo') return reply({nativeImport: true, materialImport: true, maxFileBytes: 262144000, version: chrome.runtime.getManifest().version});
  try {
    await filesReady;
    const previousOwner = (await chrome.storage.session.get('nativeImport')).nativeImport?.owner;
    if (previousOwner && previousOwner !== owner) {
      try {await chrome.tabs.get(Number(previousOwner.split(':').at(-1)));}
      catch {await imports.releaseOwner(previousOwner);}
    }
    switch (message.command) {
      case 'readPaletteLibrary': return reply(await libraryClient.readSnapshot());
      case 'beginNativeUpload': {
        const result = await imports.beginUpload(message.name, owner);
        await files.begin(result.uploadId, message.name); return reply(result);
      }
      case 'appendNativeUpload': {
        const current = await imports.status(owner);
        if (current.state !== 'uploading' || current.uploadId !== message.uploadId) throw new Error('This upload is no longer active.');
        return reply(await files.append(message.uploadId, message.offset, message.base64));
      }
      case 'finishNativeUpload': {
        const current = await imports.status(owner);
        if (current.state !== 'uploading' || current.uploadId !== message.uploadId) throw new Error('This upload is no longer active.');
        const file = await files.read(message.uploadId);
        return reply(await imports.finishUpload(message.uploadId, file.bytes.length, owner));
      }
      case 'prepareNativeImport': return reply(await imports.stage(message.file, owner));
      case 'getNativeImportStatus': return reply(await imports.status(owner));
      case 'reviewNativeImport': return reply(await imports.review(owner));
      case 'confirmNativeImport': return reply(await imports.open(message.reviewId, owner));
      case 'discardNativeImport': {const result = await imports.discard(owner); await files.clear(); return reply(result);}
      default: return bridge.handle(message, sender);
    }
  } catch (error) {return {version: 1, id: message.id, ok: false, error: 'import_failed', message: String(error.message).slice(0, 250)};}
}
chrome.tabs.onRemoved.addListener(tabId => {void imports.releaseOwner(`https://serverless-staging.mopa-laser-rasterizer.com:${tabId}`).catch(() => {});});

const bridge = createBridge();
chrome.runtime.onConnect.addListener(port => {
  if (port.name === 'lightburn-console' &&
      port.sender?.url === chrome.runtime.getURL('console.html')) bridge.attach(port);
});
chrome.runtime.onMessageExternal.addListener((message, sender, respond) => {
  handle(message, sender).then(respond, () => respond({version: 1, id: message?.id, ok: false, error: 'unavailable'}));
  return true;
});

chrome.action.onClicked.addListener(() => {
  chrome.tabs.create({url: chrome.runtime.getURL('console.html')});
});
