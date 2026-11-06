/**
 * Read-only browser connectivity probe. Requires Playwright and Chromium/Edge.
 * Run: node dev_setup/probe_lightburn_browser.mjs
 * Optional env: MOPA_PLAYWRIGHT_MODULE, MOPA_BROWSER_CHANNEL, MOPA_WEB_ORIGIN.
 * No pairing, credentials, project changes, or machine commands are performed.
 */
import {pathToFileURL} from 'node:url';
import {isAbsolute} from 'node:path';

const moduleName = process.env.MOPA_PLAYWRIGHT_MODULE || 'playwright';
const {chromium} = await import(isAbsolute(moduleName) ? pathToFileURL(moduleName).href : moduleName);
const origin = new URL(process.env.MOPA_WEB_ORIGIN || 'https://mopa-laser-rasterizer.com').origin;
const base = 'http://localhost:19520';
const report = {origin, base, preflight: {}, browser: {}};

// Node is not subject to browser CORS. Inspect what LightBurn actually returns.
for (const [path, method, headers] of [
  ['/api/connect', 'POST', 'content-type'],
  ['/api/status', 'GET', 'authorization'],
  ['/api/file/open', 'POST', 'authorization,content-type,x-filename'],
]) {
  try {
    const response = await fetch(base + path, {
      method: 'OPTIONS', redirect: 'error', signal: AbortSignal.timeout(5000),
      headers: {Origin: origin, 'Access-Control-Request-Method': method,
        'Access-Control-Request-Headers': headers},
    });
    report.preflight[path] = {status: response.status,
      allowOrigin: response.headers.get('access-control-allow-origin'),
      allowMethods: response.headers.get('access-control-allow-methods'),
      allowHeaders: response.headers.get('access-control-allow-headers')};
  } catch (error) {
    report.preflight[path] = {error: error.message};
  }
}

const browser = await chromium.launch({headless: true,
  ...(process.env.MOPA_BROWSER_CHANNEL ? {channel: process.env.MOPA_BROWSER_CHANNEL} : {})});
try {
  report.browser.version = browser.version();
  const context = await browser.newContext();
  // Grant the normal browser permission, without disabling CORS or web security.
  await context.grantPermissions(['local-network-access'], {origin});
  const page = await context.newPage();
  const messages = [];
  page.on('console', message => {
    if (/localhost:19520|CORS|loopback/i.test(message.text())) messages.push(message.text());
  });
  await page.goto(origin, {waitUntil: 'domcontentloaded'});
  report.browser.requests = await page.evaluate(async base => {
    const results = {};
    for (const [path, headers] of [['/', {}], ['/api/status', {Authorization: 'Bearer connectivity-probe-invalid'}]]) {
      try {
        const response = await fetch(base + path, {headers, redirect: 'error',
          signal: AbortSignal.timeout(5000)});
        results[path] = {status: response.status, type: response.type};
      } catch (error) {
        results[path] = {error: error.message};
      }
    }
    return results;
  }, base);
  report.browser.messages = messages;
} finally {
  await browser.close();
}
console.log(JSON.stringify(report, null, 2));
// A readable 401 is expected for the deliberately invalid token.
const readable = report.browser.requests?.['/api/status']?.status === 401;
const pairingPreflight = report.preflight['/api/connect'];
process.exitCode = readable && pairingPreflight.status >= 200 && pairingPreflight.status < 300 ? 0 : 1;
