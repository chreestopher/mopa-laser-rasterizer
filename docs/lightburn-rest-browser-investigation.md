# LightBurn REST browser connection investigation

Branch: `feature/lightburn-rest-browser`, based on `origin/staging` at `a5af8cc`.

## Requested scope

Implement Send to LightBurn and import of the currently selected LightBurn
Material Library as compartmentalized frontend components. Establish working
browser authentication and connectivity before wiring either feature into the UI.

## Observations from the installed application

On November 5, 2026, the LightBurn installation identified by the operator as
2.22 responded on `http://localhost:19520/` with HTTP 200.

An OPTIONS preflight for `POST /api/connect` from
`https://mopa-laser-rasterizer.com` returned HTTP 404 without CORS headers.
In an unmodified Edge browser, requests initially failed because local-network
access had not been granted. After granting `local-network-access`, requests
still failed:

- GET `/`: no `Access-Control-Allow-Origin` response header.
- POST `/api/connect` with JSON: preflight failed for the same missing header.

The hosted site's current `connect-src` policy also reports localhost requests,
but that policy is report-only. It did not cause these failures.

These observations establish that the current installation cannot be paired
directly from the hosted web app. No pairing secret was received. No project,
library, or machine state was changed.

## Reproduce without pairing

With LightBurn open and Playwright available:

```powershell
$env:MOPA_BROWSER_CHANNEL = 'msedge'
node dev_setup/probe_lightburn_browser.mjs
```

If Playwright is installed outside this repository, set
`MOPA_PLAYWRIGHT_MODULE` to its absolute JavaScript entrypoint. Set
`MOPA_WEB_ORIGIN` to test a different deployed origin. The probe uses a fresh
browser context, grants the normal local-network permission, and leaves CORS
and browser security enabled. It checks OPTIONS responses and read-only fetches
with a deliberately invalid token. A readable HTTP 401 would demonstrate that
authenticated requests can cross the origin boundary; it would not demonstrate
successful authentication. The script returns nonzero when connectivity fails.

## Connection decision

Pending operator preference:

1. A browser extension with explicit access to the Rasterizer origin and local
   LightBurn API. Pairing and secrets belong in the extension; the page sends
   narrowly defined commands, not arbitrary HTTP requests.
2. A local companion with an authenticated, origin-restricted browser interface.
3. Direct browser integration after LightBurn implements the required CORS
   responses and OPTIONS handling.

`mode: no-cors` cannot solve this: the page cannot read the pairing secret or
library responses, or supply the required authorization headers. AWS cannot
reach the user's loopback listener. Changing Rasterizer's CSP alone cannot
supply LightBurn's missing CORS support.

## Shared implementation requirements

- Request `state`, `project`, and `upload`; neither requested feature needs
  `project_write`.
- Pair once through LightBurn's consent dialog; derive the Bearer token with
  HMAC-SHA256 over the current Unix minute for each authenticated request.
- Open the SSE stream before uploading and wait for `file_imported`.
  A 202 response alone is not import success; polling cannot retrieve that event.
- Distinguish opening a native project from merging artwork; inspect the current
  project's modified flag before replacement.
- Read `/api/material-library` and `/api/units`; normalize units and preserve
  supported cut settings before importing through the existing Vault validation
  flow. The selected library is a snapshot; REST does not write library files.
- Keep API transport, connection UI, project handoff, and library conversion in
  separate modules. Do not expose unfinished controls in production pages.

References: [overview](https://github.com/LightBurnSoftware/LightBurn-REST/blob/main/docs/overview.md),
[authentication](https://github.com/LightBurnSoftware/LightBurn-REST/blob/main/docs/getting-started.md),
[uploads](https://github.com/LightBurnSoftware/LightBurn-REST/blob/main/docs/uploading.md),
[OpenAPI](https://github.com/LightBurnSoftware/LightBurn-REST/blob/main/docs/openapi.yaml).
