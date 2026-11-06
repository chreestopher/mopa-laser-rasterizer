// This module must run in an extension page, not an injected content script.
const API_BASE = 'http://localhost:19520';

export async function probeConnection({fetchImpl = globalThis.fetch, timeoutMs = 5000} = {}) {
  const checks = [];
  for (const specification of [
    {path: '/', label: 'API reachable', expected: 200, headers: {}},
    {path: '/api/status', label: 'Authentication response readable', expected: 401,
      headers: {Authorization: 'Bearer connectivity-probe-invalid'}},
  ]) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetchImpl(API_BASE + specification.path, {
        method: 'GET', headers: specification.headers, signal: controller.signal,
        redirect: 'error', credentials: 'omit', cache: 'no-store',
      });
      checks.push({label: specification.label, path: specification.path,
        expected: specification.expected, status: response.status,
        ok: response.status === specification.expected});
      // We only inspect response status; no project data is fetched or logged.
      try { await response.body?.cancel(); } catch { /* Status is already readable. */ }
    } catch {
      checks.push({label: specification.label, path: specification.path,
        expected: specification.expected, ok: false,
        error: controller.signal.aborted ? 'timeout' : 'network'});
    } finally {
      clearTimeout(timer);
    }
  }
  const ok = checks.length === 2 && checks.every(check => check.ok);
  return {ok, checks, message: ok
    ? 'Connection checks passed. LightBurn is reachable from this extension. This check does not verify pairing.'
    : 'Connection checks did not pass. Check that LightBurn is open and this extension has localhost permission, then try again.'};
}
