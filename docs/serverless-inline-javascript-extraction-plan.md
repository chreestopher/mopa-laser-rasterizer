# Serverless inline JavaScript extraction plan

## Outcome and scope

Move executable browser JavaScript used by the serverless site into tracked `.js` files without changing behavior, URLs, authentication, storage, rendering, or job payloads. This plan covers both the checked-in pages under `serverless_web/` and the generated pages uploaded by `dev_setup/deploy_serverless_staging_web.sh`; the production wrapper calls that same deployment script.

Non-executable data blocks are a separate concern. `type="application/json"` and SEO `type="application/ld+json"` blocks may remain inline when the page generator supplies their data, but they must never contain behavior. Before enforcing CSP, verify how target browsers and crawlers handle those blocks and document any deliberate exception.

## Baseline inventory

There is no `AGENTS.md` or existing repository-local skill in the staging baseline. OpenAI's published repository-skill convention is `.agents/skills/`, so this branch places the guidance there. `quick_validate.py` proves the package shape, not runtime discovery. This session started from a different worktree before the skill existed, so discovery cannot be demonstrated in-session; after merge, start a fresh Codex session rooted in this repository and confirm `serverless-frontend-javascript` appears in the available-skill catalog and activates for a representative serverless frontend request.

All eight `serverless_web/*.html` files contain executable inline JavaScript. There are ten blocks total and no inline `on*` HTML attributes:

| Source | Inline executable code | Existing external code | Ordering constraint |
| --- | --- | --- | --- |
| `admin.html` | shared 151-character pending-shell guard | `staging-shell.js` (defer), `admin.js` (module) | guard must run synchronously in `<head>` |
| `color-lab.html` | shared pending-shell guard | `staging-shell.js` (defer), `color-lab.js` (module) | same |
| `history.html` | shared pending-shell guard | `staging-shell.js` (defer), `history.js` (module) | same |
| `holographic.html` | shared pending-shell guard | `staging-shell.js` (defer), `holographic.js` (module) | same |
| `holographic-redirect.html` | 73-character redirect | none | keep the head redirect immediate and preserve query/hash |
| `index.html` | shared guard plus 446 lines / 138,077 characters of application code | `staging-shell.js` (defer) | application currently executes at the end of parsing, before deferred shell code is guaranteed to run |
| `release-story.html` | shared guard plus 48-line page enhancement IIFE | `staging-shell.js` (defer) | enhancement runs after its markup exists |
| `vault.html` | shared pending-shell guard | `staging-shell.js` (defer), `vault.js` (module) | guard must run synchronously in `<head>` |

Generated serverless output adds more inline code:

- `build_serverless_seo.py`, `build_serverless_depthmap.py`, `build_serverless_community.py`, `build_serverless_experimental.py`, and `build_serverless_docs.py` inject the same pending-shell guard.
- `templates/community_set.html` contains the Community Set client, which `build_serverless_community.py` rewrites for token/API behavior.
- The documentation hub in `templates/docs.html` contains search behavior and an injected search index.
- Landing and documentation templates contain JSON-LD; `templates/depthmap_generator.html` contains JSON data. These are data, not executable application code.
- Other Flask-only templates also contain inline JavaScript. They are outside the static serverless deployment boundary and should be handled in a follow-up inventory, not silently mixed into this migration.

The current CloudFront policy sends `Content-Security-Policy-Report-Only` with `script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval' https://cdn.jsdelivr.net`. Static HTML and JavaScript are uploaded with `Cache-Control: no-cache`, `config.json` uses `no-store`, and every deploy invalidates `/*`. JavaScript uploads are explicit, so every new entry point and imported module must be added to the deployment.

## Target boundaries

Keep small page entry points and organize the large Rasterizer client around ownership, not arbitrary file size:

```text
serverless_web/
  holographic-redirect.js          legacy URL redirect only
  release-story.js                 story progress/TOC/media behavior
  rasterizer.js                    temporary behavior-preserving entry point
  rasterizer/
    main.js                        composition, listeners, initial load
    state.js                       mutable session/UI state and explicit accessors
    dom.js                         selectors, escaping, display helpers
    auth-api.js                    token lifecycle, API and upload clients
    shape-assets.js                uploaded mask/SVG normalization and previews
    geometry-controls.js           preset definitions, routing, control serialization
    flow-painter.js                Fauxlogram flow editor/canvas behavior
    artwork-crop.js                crop selection and derived artwork file
    quantized-preview.js           color matching and preview rendering
    panel-tiling.js                tiling state, validation, and layout preview
    palette-resources.js           palettes, libraries, names, saved preferences
    jobs.js                        request assembly, submit, poll, and outputs
```

This is a dependency direction, not a requirement to create every file at once: `main.js` composes feature modules; feature modules may depend on `dom.js`, `state.js`, and `auth-api.js`; feature modules must not import `main.js` or communicate through accidental globals. Pass DOM nodes, callbacks, and state explicitly where that prevents circular imports.

Keep `staging-shell.js` a classic deferred script for the first migration. Its `window.stagingShellSetAuthenticated` and `window.stagingShellBeginLogin` functions are deliberate cross-entry integration points. Do not introduce additional `window` exports. Convert that contract to an imported module or `CustomEvent` only as a separately tested change.

## Phased migration

### Phase 0 — lock the baseline

1. Keep `tests/test_serverless_web_javascript.py` as the temporary debt inventory. It now builds Depthmap, Community Set, Experimental Labs, every documentation route, and every SEO route exactly as staging does. It fingerprints each allowed inline executable block and rejects new inline blocks, `on*` attributes, and `javascript:` URLs in both source and rendered output. Extraction only removes hashes.
2. Preserve each script's execution grammar in syntax checks. Classic scripts are checked as `.js`; only `type="module"` scripts are checked as `.mjs`. Every `serverless_web/**/*.js` file must be referenced in exactly one mode.
3. Keep the deployment-order debt inventory exact. Existing HTML-before-JavaScript pairs are grandfathered temporarily; do not add pairs. Every new extracted asset must have a matching upload and appear before its dependent HTML. Remove existing debt entries when touching those uploads.
4. Add a shared test helper that returns HTML plus referenced JavaScript. Twenty current test modules inspect `serverless_web/index.html`, and many assertions currently assume implementation code lives in the HTML. Move behavior assertions to the owning `.js` source as each block moves; keep markup assertions on HTML.
5. Before moving the Rasterizer block, establish a browser-level characterization suite against the current inline implementation. Serve the fully generated static site over HTTP and run a pinned headless browser. Use deterministic API/Cognito/upload fakes and capture DOM state plus outbound request payloads for: signed-out boot and fail-open shell reveal; Cognito callback/refresh/logout and cross-tab auth; guest/member resource loading; initial filter/geometry state; crop pointer flows; quantized preview; Fauxlogram painting; panel-tiling enablement and layout; palette selection; guest and member submission/upload; resumed polling and ordered downloads; release-story enhancement; docs search; and the legacy redirect with query/hash. Record the baseline on the inline client and require the same suite after extraction and after each module split. Unit/string assertions alone are not an adequate modularization gate.

### Phase 1 — extract low-risk shared and page scripts

1. Replace the pending-shell guard without adding a render-blocking JavaScript request. Prefer putting `staging-shell-pending` directly on the generated/static `<html>` element and moving the hide plus a three-second fail-open animation into an external stylesheet. `staging-shell.js` already removes the class after it renders. Browser-test normal load, slow CSS/JS, blocked shell JavaScript, and CSS failure before adopting this alternative. A synchronous external `shell-pending.js` is behaviorally closer to the inline code, but it blocks parsing on a new network request and its three-second timer cannot start until the file arrives; a stalled fetch can therefore delay the page instead of providing the intended fail-open. If the CSS alternative proves unsuitable, document and test that network tradeoff before using the external script.
2. Move the redirect verbatim to `holographic-redirect.js`, loaded synchronously in the head. Preserve the meta-refresh fallback, `location.replace`, query string, and hash.
3. Move the release-story IIFE verbatim to `release-story.js` at the current end-of-body position. Use a classic script initially.
4. Upload these assets before uploading HTML that references them. Keep the old object available for at least one release when renaming an asset.
5. Remove the corresponding hashes from the debt allowlist and add deploy/reference assertions.

### Phase 2 — extract the Rasterizer monolith without refactoring

1. Move the large `index.html` block byte-for-byte to `serverless_web/rasterizer.js` and use a classic end-of-body script. Do not combine extraction with renaming, formatting, event rewrites, or modules.
2. Preserve the current timing: DOM markup exists; `load()` starts immediately; the deferred shell might not have run; calls to the shell global remain optional.
3. Update behavior tests to read `rasterizer.js` and markup tests to read `index.html`. Syntax-check the external file and compare critical request payloads and generated DOM snapshots before/after.
4. Add the asset to the deploy script before switching the HTML reference. Bump the query revision used by the page even though origin metadata is `no-cache`.

### Phase 3 — externalize generated-route behavior

1. Extract Community Set behavior to an external client. Replace the builder's source-code string substitution with configuration/data passed through markup or an `application/json` block; do not generate JavaScript strings in Python.
2. Extract documentation search behavior to `docs-search.js`. Keep the generated search index in a JSON data block and parse it from the external module.
3. Rebuild SEO, depthmap, community, experimental, and documentation outputs in tests. Require zero inline executable scripts and zero inline event attributes. Keep JSON/JSON-LD explicitly classified as data.
4. For scripts shared by Flask templates and the serverless site, keep one source file under `static/` and explicitly upload/rewrite its public URL, or keep a serverless-only file under `serverless_web/`. Do not maintain copied implementations.

### Phase 4 — introduce native modules behind stable behavior

1. Do not start this phase until the Phase 0 browser characterization suite passes against both the original inline baseline and the byte-for-byte classic `rasterizer.js` extraction. Expand it for any feature whose boundary is about to move.
2. Convert `rasterizer.js` into a small `type="module"` entry and extract one cohesive boundary at a time following the target graph. Use explicit imports/exports and a state object rather than relying on top-level bindings becoming globals.
3. Attach listeners from `main.js` after module evaluation. Verify the changed timing against `staging-shell.js`, Cognito callback handling, resumed jobs, and initial control rendering.
4. Deploy the complete import graph with `application/javascript`. Prefer an explicit manifest or recursive module-directory upload plus a test that every relative import resolves and is published.

### Phase 5 — tighten delivery and CSP

1. Upload JavaScript before dependent HTML and invalidate only after all objects are present. A full invalidation does not prevent a transient HTML-new/JS-missing window during sequential uploads.
2. Keep HTML `no-cache`. During migration keep JavaScript `no-cache`; immutable long-lived caching is safe only after content-hashed filenames or an atomic release-prefix strategy exists. Query revisions alone do not prove atomicity.
3. Remove `'unsafe-inline'` from the report-only `script-src` after generated-output scans reach zero executable inline code. Exercise every route and third-party dependency, including WebAssembly/model loading.
4. Decide and test the JSON-LD policy before enforcement. If inline structured data needs CSP hashes, the shared CloudFront header must include all rendered hashes or delivery must change; do not drop SEO data merely to simplify CSP.
5. After a clean staging observation window, promote the CSP from report-only to enforced in a separate change with rollback instructions. Do not combine enforcement with extraction, modularization, or cache-policy changes.

## Verification and acceptance

For every phase:

- Run the focused JavaScript policy/syntax tests and the full Python suite. The focused test must parse classic and module scripts in their actual modes.
- Run all serverless builders and scan their rendered output, not only source templates.
- Validate deployment scripts (`bash -n` under the repository's existing Linux/CI path) and assert new assets are uploaded with the correct MIME type before dependent HTML.
- Test a local static origin over HTTP; ES modules cannot be validated reliably through `file://`.
- Run the deterministic browser characterization suite locally before and after each boundary change, then repeat its critical signed-out/signed-in flows in staging: Cognito callback/refresh/logout and cross-tab state, guest and member job submission, resume/poll/download, crop and quantized preview, geometry routing/Fauxlogram painter, panel tiling, Vault, History, Admin, Color Lab, Fauxlographic Lab, Depthmap Lab, Community Set, docs search, release story, and the legacy redirect with query/hash.
- Check the browser console/network panel for module 404s, MIME errors, CSP reports, duplicate listener execution, and flashes caused by the pending-shell guard.

Acceptance is: generated runtime pages contain no inline executable JavaScript or inline event attributes; data-only script blocks are documented and inert; all browser code is syntax-checked; every referenced/imported asset is deployed before its consumer; staging behavior matches the baseline; and CSP can remove `'unsafe-inline'` from `script-src` without runtime violations.

## Main cautions

- Extraction and modularization are different risk levels. The 138 KB Rasterizer block should first move unchanged, then be decomposed.
- Native module timing and scope differ from the current classic inline block. An immediate `type="module"` conversion can reorder startup and hide bindings that tests or other scripts implicitly use.
- Current tests are coupled to JavaScript text inside `index.html`; moving code without migrating those assertions will create false failures or, worse, lost coverage.
- The deploy is shared by staging and production and is not atomic. Validate on staging and preserve the staging-to-production promotion gate.
- CSP is currently report-only and allows inline scripts. Finishing file extraction does not itself authorize enforcement; generated routes, JSON-LD, CDN code, workers, and WebAssembly must be verified first.
