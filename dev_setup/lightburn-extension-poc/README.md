# LightBurn Connection POC — version 0.7.0

## Current review: import a new swatch palette

1. Reload this unpacked extension (0.7.0) in Edge/Chrome; pairing is retained.
2. Refresh the staging Vault. With LightBurn open and a populated Material
   Library selected, click **Import swatch palette from LightBurn**.
3. Read the library, select one or more settings, name the new palette, and
   preview. Review converted settings and acknowledge any reference-only fields.
4. Click **Create palette**, inspect the saved entries, then use existing Vault
   swatch assignments to assign Rasterizer colors. No colors are guessed.
5. Repeat in both browsers. Disable the extension and refresh: the import
   control should be absent. Diagnostics need not stay open during import.

This reads LightBurn only. Unsupported fields remain source reference data,
not applied settings. An uncertain save is never retried automatically: refresh
Vault and check whether the palette exists before starting again.

Automated validation: 55 focused Node tests, 26 Python checks, and the palette
browser scenario in Edge and Chrome pass. Live palette import awaits review.
The per-palette + button and processing palette builder are later checkpoints.

Version 0.6.1 is the failure-handling review checkpoint. Failed re-review now
clears stale confirmation controls. Offline/timeouts and lost pairing give
recovery instructions; interrupted downloads can be explicitly retried or
discarded. Unknown completion remains unknown after page reload and is never
automatically resent. The 100 MiB limit is unchanged.

52 focused tests and 25 web checks pass. Edge and Chrome passed
`node tests/lightburn_extension_browser.mjs --inline --failures` with synthetic
faults. For a safe manual check, save and close LightBurn, attempt Review current
project, then reopen LightBurn and review again. Confirm only when ready to
replace the displayed saved project. No live failures were forced by automation.

Operator confirmed the updated in-page native loading workflow works in both
Edge and Chrome on November 6, 2026. The tested real-file size was not reported;
exact 100 MiB transfers were separately verified with synthetic LightBurn.

This unpacked Manifest V3 extension connects to LightBurn on the same computer,
pairs on explicit request, and reads the selected Material Library. It stores
the pairing secret inside this browser profile's extension storage. It opens
native projects only after explicit review/confirmation; it never operates the
laser. It is not yet published in an extension store.

## Previously reviewed: in-page Job History loading

1. Reload the unpacked extension in Edge/Chrome and refresh Job History. Existing
   pairing is retained. If needed, use the extension icon to open diagnostics and
   pair first. The diagnostics tab can be closed during file loading.
2. Expand a retained job. **Load in LightBurn** appears beside `.lbrn2` downloads
   only after the enabled extension is detected. There is no manual ID entry.
3. Save current LightBurn work and keep one instance open. Click the new button,
   then **Review current project** inside the page dialog. Check the displayed
   project/device, tick the replacement confirmation, and confirm.
4. Closing the dialog does not cancel or repeat an import. Reopen it to see the
   result. If unknown, inspect LightBurn before clearing and sending again.
5. Check geometry/settings in LightBurn without operating the laser. Repeat in
   both browsers. Disable the extension and refresh: all new controls should be
   absent and ordinary downloads should still work.

Current limit: 100 MiB native files, simple ASCII filenames. Files transfer in
bounded 256 KiB chunks and are held in extension IndexedDB; session storage
contains only the small operation journal and file reference. Files are cleared
after an open attempt or discard; orphaned bytes are cleared on worker startup
when no matching session exists. No large base64 message or large session-storage
entry is required. Files over the limit are rejected by both streaming transfer
and extension byte validation. Download/staging errors remain visible and offer
**Stage selected file** for recovery; idle polling cannot overwrite the error.

The worker holds one
staged/imported result at a time. Use **Discard / clear result** before staging
another file. A review identifier binds confirmation to the reviewed operation;
other tabs cannot confirm it. Closed tabs release ownership. Browser restart or
extension reload clears session data; an interrupted worker open becomes unknown
when its journal is recovered. There is no automatic resend.

The toolbar still opens diagnostics. No popup or separate tab is needed for
normal file loading. The website confirmation path was explicitly approved by
the operator, superseding the earlier extension-only confirmation design below.
The scoped discovery content script shares only the public extension ID.

Validation at version 0.5.0: 43 focused Node tests, 40 web/deployment checks, History browser
integration and auth regressions in Edge/Chrome, plus real signed artifact CORS
reads in both browsers. Run `node tests/lightburn_extension_browser.mjs --inline`
for the synthetic import suite. Manual live in-page acceptance is pending.

## Review feature 3: pairing and selected Material Library

Version **0.3.0** adds the storage permission and pairing/read controls. Review
separately in Edge and Chrome:

1. Reload the unpacked extension at `edge://extensions` or `chrome://extensions`.
   Close its old test tab, then reopen it from the Extensions menu.
2. In LightBurn, select a nonempty Material Library. Keep one LightBurn instance
   open for the POC.
3. In the extension tab, click **Pair with LightBurn**, then approve **MOPA
   Rasterizer Connection POC** in LightBurn within 30 seconds. This requests
   `state`, `project`, and `upload`; native loading uses upload access.
   Camera images fall within project scope, but the extension never fetches them.
4. Click **Read selected Material Library**. Check the name/count, displayed
   speed and distance units, and use **Inspect a library setting** to compare
   a real MOPA entry against LightBurn. Frequency is Hz; MOPA pulse width is ns.
   Sublayers and the active galvo/gantry block are preserved when returned.
5. Reload the extension tab and read again. Saved pairing should work without
   another consent prompt. Keep this tab open for website reads.
6. Refresh the [staging test page](https://serverless-staging.mopa-laser-rasterizer.com/lightburn-connection-test.html),
   enter this browser's extension ID, then click **Read selected Material Library**.
   The same library and units should appear. This is a snapshot; nothing is saved
   to Vault or sent to the Rasterizer backend.
7. Optional: **Forget local pairing** clears the secret from this browser.
   Subsequent reads require pairing again. It does not revoke the grant in
   LightBurn or erase a snapshot already delivered to a webpage.

The automated live tests use disposable browser profiles. Their pairings are
not installed in your normal Edge/Chrome profile, so your first manual pairing
will still prompt. The test grants remain in LightBurn; there is no documented
REST revocation endpoint. No secret is retained in test artifacts or logs.

Failures clear the current library preview. A 401 never triggers automatic
pairing or deletes a saved secret. An empty library is a successful read but
does not complete the nonempty-library acceptance check. API responses are
bounded to 4 MiB and snapshots to 10,000 entries for this POC. Known documented
settings are selected explicitly; unknown fields and local filesystem paths
are not forwarded to the webpage. No units or laser parameters are converted.

## Review feature 2: website bridge in Edge and Chrome

Feature 2 connects the isolated staging diagnostic page to the extension
tab. The tab performs the same read-only connection checks from feature 1.

1. In Edge, open `edge://extensions` and **Reload** the existing POC extension.
   Close its old tab, then open a fresh tab through the Extensions menu.
2. Confirm **Website bridge ready** appears. Copy the Extension ID displayed
   in that tab, and keep the tab open.
3. Visit [the staging connection test](https://serverless-staging.mopa-laser-rasterizer.com/lightburn-connection-test.html).
   Use your existing staging access credentials if prompted.
4. Paste the ID and click **Check through extension**. Expect **Website
   connection passed**, HTTP 200, and HTTP 401. Pairing is checked separately.
5. Close the extension tab and check again. Expect instructions to open it.
   Reopen it and recheck to recover.
6. Repeat in Chrome: open `chrome://extensions`, enable Developer mode, choose
   **Load unpacked**, and select this same directory. Use the ID shown by
   Chrome's extension tab; do not assume the Edge ID is the same. Open the
   staging test in Chrome and repeat steps 2–5.

Only the exact HTTPS staging origin is allowed to message this development
extension. No production website, arbitrary HTTP proxy, or pairing command is
exposed. The worker validates the sender and request, forwards one bounded
read-only request to the open tab, and returns only sanitized results.
Concurrent checks are rejected. Closing the tab, timeout, or worker restart
cannot cause an automatic replay. If the worker restarts, the tab reconnects;
the user can initiate a fresh check. With multiple console tabs, the most
recently connected one receives checks; keep one open for this POC.

## Review in Edge or Chrome

1. Leave LightBurn open.
2. Open `edge://extensions` (Edge) or `chrome://extensions` (Chrome).
3. Enable **Developer mode**, then choose **Load unpacked**.
4. Select this directory, which contains `manifest.json`:
   `E:\Code\mopa-lightburn-rest\dev_setup\lightburn-extension-poc`.
5. Open the browser's Extensions menu and click **MOPA Rasterizer — LightBurn
   Connection POC**. It opens a connection-test tab.
6. Click **Check connection**.

Expected: **Connection checks passed**, with HTTP **200** for API reachable and
HTTP **401** for Authentication response readable. The 401 is intentional: this
test uses an invalid token to verify that authentication responses can be read.
Passing does not establish a paired connection or indicate machine readiness.

Localhost host access and extension storage are requested; the code fixes the destination to port
19520. The browser's localhost permission can cover other ports, but the extension
does not offer arbitrary destinations. No browser-security settings need to be
disabled. On failure, check LightBurn is open and localhost access is allowed in
the extension's site permissions. A failed fetch alone cannot distinguish a
closed application from a browser permission block.

You may recheck repeatedly. Each click runs exactly two GET requests, with a
five-second timeout per request and no automatic retries. The button is disabled
while a check runs. Remove the extension from the extensions page when finished.
To review subsequent code changes, use **Reload** on its extensions-page card
and reopen/reload the connection-test tab.

## Development checks

Dependency-free unit tests:

```powershell
node --test tests/test_lightburn_extension_transport.mjs
node --test tests/test_lightburn_extension_bridge.mjs
node --test tests/test_lightburn_extension_auth.mjs
```

Browser checks require Playwright and its Chromium browser. They run in a fresh,
temporary browser profile with only this extension loaded. They never install it
into your normal browser profile. Optional `MOPA_PLAYWRIGHT_MODULE` points to an
absolute Playwright JS entrypoint, and `MOPA_BROWSER_BIN` selects a Chromium
executable supporting unpacked extension loading.

```powershell
node tests/lightburn_extension_browser.mjs
node tests/lightburn_extension_browser.mjs --live
node tests/lightburn_extension_browser.mjs --bridge
node tests/lightburn_extension_browser.mjs --bridge --deployed
node tests/lightburn_extension_browser.mjs --auth
node tests/lightburn_extension_browser.mjs --pair-live --deployed --minute-rollover
```

The default browser test mocks success and network failure to check UI recovery.
The `--live` test makes the two read-only requests to installed LightBurn and
writes an ignored screenshot to `scratch/lightburn-extension/connection.png`.
It does not grant broad permissions, disable CORS, or proxy the requests.

Set `MOPA_BROWSER_CHANNEL` to `msedge` or `chrome` to exercise the installed
branded browser. Automation uses CDP extension loading in its disposable profile
because modern branded browsers restrict command-line sideloading. This does
not disable web security or change the normal user profile. The default
`--bridge` test substitutes local page files at the staging origin; `--deployed`
uses the actual served staging files. If staging Basic authentication is enabled,
provide its Base64 username:password in `MOPA_STAGING_BASIC_AUTH` for that test
process only. Credentials are origin-scoped and never logged. Do not commit them.
`--auth` uses fake API responses to exercise pairing, persistence, failed reads,
and website handoff. `--pair-live` requests real consent and reads the real library;
the operator must approve the dialog. `--minute-rollover` verifies a fresh request
after the minute changes. Only the consent request uses POST; all reads use GET.

## Evidence — November 5, 2026

- Tests ran before implementation and failed for the missing module.
- Seven unit tests pass, including unexpected status, network/timeout, partial
  failure, and response cleanup cases; the cleanup regression also failed before
  its fix.
- Browser UI checks pass for success, failure on recheck, and button recovery.
- Live unpacked extension in Chromium **153.0.8010.12** received actual HTTP
  **200** and **401** from the installed LightBurn API. Exactly two GET requests;
  no pairing, project mutations, or machine commands.
- LightBurn version **2.22** is operator-reported; the executable did not expose
  a product/file version through Windows file metadata.
- The operator installed feature 1 in Edge, confirmed the pass result, and
  signed off. Feature 2 was then manually confirmed in both Edge and Chrome.
- Feature 2 bridge tests ran red before implementation. All **13 unit tests**
  pass, along with **25 serverless JavaScript regression checks** and shell
  syntax validation for staging deployment.
- The real HTTPS staging page passed against live LightBurn in installed
  **Edge 156.0.4314.58** and **Chrome 156.0.8078.80**. No response interception
  in these final runs. Exactly two GETs per successful check, unsupported command
  rejected without an API request, and closed-console recovery checked in both.
- Only `lightburn-connection-test.js`, `.css`, and `.html` were published under
  staging's existing `web/` prefix. The normal staging deployment script includes
  these assets behind its staging-only condition. No production page changed.

Feature 3 development adds 11 focused auth/snapshot/bridge tests (24 total).
The browser auth suite covers declined pairing, approved pairing, reload,
library units and sublayers, website handoff, empty library, unauthorized reads,
and forgetting. Live results are recorded in the approved plan.

Features 3 and 4 were confirmed by the operator in both Chrome and Edge.
Live native opening passed operator review on November 5, 2026. Detailed
numerical geometry/settings comparisons were not separately reported.

## Feature 4 review: native open

1. Reload the unpacked extension in Edge/Chrome (version 0.4.0), then reopen its
   console. Keep only one console and one LightBurn instance open.
2. Save current LightBurn work. Choose a small downloaded Rasterizer `.lbrn2`
   project (maximum 1 MiB, ASCII filename without path separators).
3. On the staging connection-test page, select the file and click **Stage in
   extension**. This alone must not change LightBurn.
4. In the extension click **Review current project**. Unsaved projects are
   blocked. Read the current filename/device, check the replacement confirmation,
   then click **Open in LightBurn**. Avoid other imports or edits during this test.
5. Expect completion in the extension and **Check load status** on the website.
   Compare geometry, size, layers, power, speed, frequency, and pulse width with
   the downloaded project in LightBurn. Do not run the laser for this test.
6. Repeat in the other browser. Report browser, outcome, and any mismatch.

An unknown outcome means inspect LightBurn before staging again. No automatic
resend occurs. Opening consumes the staged payload once sending begins; reload
also clears it. Completion events have no file ID, so this POC requires exclusive
use during the test. Project checks cannot eliminate the API's compare/open race.
The website cannot confirm replacement; that action stays in the extension.

Automated checks: 35 focused Node tests, 25 web checks, and
`node tests/lightburn_extension_browser.mjs --import` in Edge and Chrome.
The import browser suite uses a synthetic API and never opens a real project.

### Import-time mapping update

Preview includes a Rasterizer swatch selector for every selected setting. Exact
swatch names are preselected; other settings begin Unassigned. Choose assignments
before Create palette; occupied swatches cannot be assigned twice. If the palette
is saved but mapping cannot be confirmed, review assignments in Vault rather than
creating a second palette. The creation result is shown beside the action button.
