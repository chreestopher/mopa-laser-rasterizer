# Serverless inline JavaScript extraction plan

## Outcome and scope

Move executable browser JavaScript used by the deployed serverless site into tracked `.js` files without changing URLs, authentication, storage, rendering, payloads, exports, or mobile behavior. This covers checked-in pages under `serverless_web/`, browser modules deployed from `static/`, and every HTML artifact produced by the builders called from `dev_setup/deploy_serverless_staging_web.sh`. Production wraps the same web deployment path.

This is not permission to refactor while extracting. Preserve classic versus module execution, DOM-ready timing, script order, globals, and cache revisions. Non-executable `application/json` and `application/ld+json` blocks may remain inline when they contain data only; inventory them separately before CSP enforcement. Serialize embedded JSON with an HTML-safe encoder that prevents a value such as `</script>` from terminating the element; never concatenate user-controlled text into a script-data block.

## Active extraction checkpoint and promotion boundary

- Rollback commit: `aa911ea2bad3e3d86c92be7839bcd5fb87730940` (`origin/staging` after PR #123).
- Extraction branch: `feature/inline-js-phase-1`, created directly from that commit.
- Until extraction acceptance is complete, keep this branch and subsequent staging changes limited to extraction, its tests, deployment ordering, and directly required documentation. Do not mix feature work into this sequence.
- Staging is the only permitted deployment target during extraction validation. Do not create a production PR, merge to `main`, manually dispatch the production workflow, or deploy production until the owner explicitly requests the production PR after acceptance testing.
- Production deployment is currently isolated by workflow configuration: staging deploys only from `staging`; production deploys only from `main` or an explicit production workflow dispatch; production PRs are required to originate from `staging`.

## Current staging inventory

The inventory below is from `origin/staging` at `aa911ea`. There are 11 checked-in `serverless_web/*.html` files. Eight contain executable inline JavaScript: ten blocks total, with no inline `on*` attributes or `javascript:` URLs currently detected.

| Source | Inline executable code | Existing external code and mode | Ordering/coupling |
| --- | --- | --- | --- |
| `admin.html` | pending-shell guard | `staging-shell.js` classic/defer; `admin.js` module | guard is synchronous in `<head>` |
| `color-lab.html` | pending-shell guard | shell classic/defer; `color-lab.js` module | same |
| `history.html` | pending-shell guard | shell classic/defer; `history.js` module | same |
| `holographic.html` | pending-shell guard | shell classic/defer; `holographic.js` module | same |
| `holographic-redirect.html` | redirect script | none | synchronous head redirect preserves query/hash; meta refresh is fallback |
| `index.html` | guard plus 446-line, approximately 138 KB Rasterizer client | shell classic/defer | large block runs at end of body; optional shell globals may not exist yet |
| `mandala.html` | none | shell classic/defer; `mandala.js` module | static `staging-shell-pending` class; module owns startup |
| `release-story.html` | guard plus 48-line enhancement IIFE | shell classic/defer | IIFE runs after its markup |
| `spiralgrap.html` | none | none | misspelled legacy route uses meta refresh only |
| `spiralgraph.html` | none | shell classic/defer; `spiralgraph.js` module | static pending class; module owns startup |
| `vault.html` | pending-shell guard | shell classic/defer; `vault.js` module | guard is synchronous in `<head>` |

Other deployed external browser sources are `blank-palette.js` (classic), `depthmap_bootstrap.js` (module), and the Depthmap module graph under `static/`: `depthmap_generator.js`, `depthmap_parallax.js`, `depthmap_parallax_svg.js`, `depthmap_layered_relief.js`, and `depthmap_lightburn.js`. `depthmap_bootstrap.js` establishes `window.serverlessDepthResources` and `window.serverlessDepthGuest`, updates the JSON data block, then dynamically imports `depthmap_generator.js`; that bootstrap-before-generator contract must survive until an explicit configuration API replaces it.

The builders add or copy more inline debt into deployed artifacts:

- `build_serverless_seo.py` copies the Rasterizer home, Fauxlographic, Color Lab, Mandala, SpiralGraph, and `spiralgrap` pages and renders the SEO landing routes. Copied pages retain their source behavior: Mandala, SpiralGraph, and `spiralgrap` have no inline executable code; copied home has the guard and Rasterizer client; Fauxlographic and Color Lab have the guard. Landing pages receive the guard.
- `build_serverless_depthmap.py` produces `depthmap.html`, inserts the guard, and points at the Depthmap bootstrap module.
- `build_serverless_community.py` produces `community-set` with the guard plus a rewritten inline client from `templates/community_set.html`.
- `build_serverless_experimental.py` produces `experimental-laboratories` with the guard.
- `build_serverless_docs.py` renders the docs index and every documentation route. All receive the guard; the index also contains generated search behavior and search-index data.

Phase 0 is not green on this staging revision. `tests/test_serverless_web_javascript.py` builds the right route families, but its rendered-debt expectation is stale: it expects shell guards on newly copied Mandala/SpiralGraph/`spiralgrap` SEO pages that intentionally use the newer static-class/no-script pattern, and its docs-search fingerprint predates the current source. Reconcile this from reviewed source intent and retain ordered, multiplicity-aware debt records. Do not blindly replace hashes to make the test pass.

The deploy currently uploads several consumers before dependencies, including Mandala HTML before `mandala.js`/CSS, SpiralGraph HTML before `spiralgraph.js`/CSS, Depthmap HTML before its full module graph, and older page HTML before page modules. This is a real partial-deploy hazard. `Cache-Control: no-cache`, query revisions, and the final CloudFront `/*` invalidation do not make sequential S3 writes atomic.

## Runtime boundaries and dependency direction

Keep the already external lab entry points stable during legacy extraction. Before splitting any monolith, add browser characterization. Proposed boundaries are ownership seams, not a mandate to create every file at once.

```text
serverless_web/
  holographic-redirect.js          legacy redirect only (classic, synchronous)
  release-story.js                 story progress/TOC/media behavior (classic first)
  rasterizer.js                    byte-for-byte classic extraction first
  rasterizer/
    main.js                        composition, listeners, startup
    state.js                       session/UI state and explicit accessors
    dom.js                         selectors, escaping, display helpers
    auth-api.js                    token lifecycle, API, uploads
    shape-assets.js                mask/SVG normalization and previews
    geometry-controls.js           presets, routing, serialization
    flow-painter.js                Fauxlogram editor/canvas behavior
    artwork-crop.js                crop selection and derived file
    quantized-preview.js           matching and preview rendering
    panel-tiling.js                tiling controls, validation, aspect/layout preview
    palette-resources.js           processing/color palettes, roles, preferences
    jobs.js                        payload, submit, poll, outputs
  spiralgraph.js                   current stable module entry
  spiralgraph/
    main.js                        startup and event composition
    state.js                       drawings, active drawing, dimension constraints
    palette-routing.js             processing/color palettes, swatches, line/fill roles
    geometry.js                    built-in/custom tracks and rolling-curve math
    hardware-preview.js            track/gear/assembled SVG and pen-hole interaction
    canvas-preview.js              selected/stacked previews and frame scheduling
    drawing-editor.js              per-drawing controls, order, duplicate/remove
    auth-jobs.js                   auth/resources, payload, submit/poll/download
  mandala.js                       current stable module entry
  mandala/
    main.js                        startup and event composition
    state-randomize.js             physical layers, defaults, reset/randomization/order
    palette-routing.js             processing palette/material/Cut role
    geometry.js                    motifs, radial composition, bridges/openwork
    canvas-preview.js              selected/stacked preview scheduling
    layer-editor.js                per-layer controls and custom SVG
    auth-jobs.js                   auth/resources, payload, submit/poll/download
```

Keep Depthmap sources under `static/` unless a separate move is justified. Its later seams are bootstrap/auth configuration; depth generation and paint/canvas state; color-guided palette controls; 8/16-bit PNG export; Depthmap LightBurn export; Parallax PNG/SVG; and Layered Relief planning/preview/LightBurn. Preserve its existing relative imports and query revisions during extraction work.

`main.js` composes feature modules. Features may depend on shared state, DOM helpers, and an injected API client; they must not import `main.js` or communicate through new accidental globals. Keep `staging-shell.js` classic initially. Its `window.stagingShellSetAuthenticated` and `window.stagingShellBeginLogin` functions, plus the temporary Depthmap globals above, are the only reviewed cross-entry globals; remove them only in separately characterized changes.

## Phased migration

### Phase 0 - make the baseline trustworthy

1. Repair `tests/test_serverless_web_javascript.py` against the current generated artifacts. Represent inline blocks as ordered `(execution mode, digest)` lists per route, not digest sets, so duplicates and reordering are visible. Add the new no-inline SEO copies to an explicit zero-debt expectation. Keep scans for inline bodies, case/character-reference-obfuscated `on*` attributes, and whitespace/character-reference-obfuscated `javascript:` URLs.
2. Enumerate deployment inputs from the actual deploy script and run every invoked builder: SEO, Depthmap, Community Set, Experimental Labs, and all docs. Fail if a deployed HTML artifact is not scanned or a generated artifact appears unexpectedly. Source-only `serverless_web/*.html` scanning is insufficient.
3. Check scripts in their real modes. Parse classic scripts as `.js`; parse `type="module"` sources and every transitive static/literal dynamic import as modules. Assert each entry is referenced in one mode, all imports resolve, and all deployed sources have an upload. Include Mandala and SpiralGraph in the module allowlist and the complete Depthmap graph under `static/`.
4. Replace the current hand-maintained HTML-first exceptions with exact temporary debt covering all deployed page/asset pairs, including CSS where the static pending-shell behavior depends on it. New or touched assets must upload before all dependent HTML; only delete debt.
5. Add a helper that returns HTML plus its referenced/imported scripts. Move the many `index.html` text assertions to the owning `.js` file as extraction proceeds; markup assertions stay on HTML.
6. Establish a pinned browser characterization suite served over HTTP with deterministic Cognito, API, upload, image, and timer fakes. Capture DOM/accessibility state, canvas/SVG checkpoints, console/network failures, storage changes, and exact outbound payloads. Run it against the inline baseline before moving the Rasterizer block.

### Phase 1 - remove low-risk inline code

1. Prefer the Mandala/SpiralGraph pattern for the pending shell: a static `staging-shell-pending` class on `<html>`, an external stylesheet fail-open, and `staging-shell.js` removing the class. Test normal, slow, blocked CSS/JS, JavaScript-disabled, and reduced-motion cases. A synchronous external guard is closer to current timing, but its network request blocks parsing and its timer cannot start until the file arrives; use it only if the CSS approach fails characterized requirements.
2. Move the redirect verbatim to `holographic-redirect.js`, synchronously in the head. Preserve `location.replace`, query/hash, and meta fallback. Do not add script to the `spiralgrap` meta-only alias without a demonstrated need.
3. Move the release-story IIFE verbatim to a classic `release-story.js` at the current end-of-body position.
4. Upload each new asset before switching dependent HTML and remove only its reviewed inline-debt records.

### Phase 2 - mechanical Rasterizer extraction

1. In a dedicated change, move the large `index.html` block byte-for-byte into `serverless_web/rasterizer.js`. Load it as a classic end-of-body script. Do not format, rename, deduplicate, change event registration, or convert it to a module.
2. Preserve current startup timing: markup exists, `load()` starts immediately, and the deferred shell may not yet have run.
3. Prove byte equality after accounting only for the surrounding `<script>` tags/newline, run classic syntax checks, and compare stored characterization results and payloads.
4. Publish the extracted client under an immutable, content-versioned name, upload it first, verify it, and only then update HTML to reference it. Keep the previous asset available through at least the rollback window. Query revisions may remain as diagnostics, but they are not the release boundary.

### Phase 3 - externalize generated-route behavior

1. Move Community Set behavior to an external client. Replace Python source-code substitution with inert JSON/data attributes consumed by that file.
2. Move docs search behavior to `docs-search.js`; keep the generated search index in an inert JSON block.
3. Rebuild and scan every output. The executable-inline allowlist should reach zero; JSON and JSON-LD remain explicitly classified data.
4. For shared Flask/serverless behavior, keep one source under `static/` and upload/rewrite its public path, or use a serverless-only source under `serverless_web/`. Do not fork copies.

### Phase 4 - modularize only behind characterization

1. Do not split Rasterizer, SpiralGraph, Mandala, or Depthmap until the browser baseline covers the boundary being moved. The classic `rasterizer.js` extraction must remain its own passing checkpoint before Rasterizer becomes a module.
2. Split one ownership seam at a time with explicit imports/exports. Preserve exact payload types/order, layer order, preview scheduling, storage, URL `?task=` resume, and error/status text unless a separately approved behavior change says otherwise.
3. SpiralGraph coverage must precede splitting palette routing, drawing state, geometry, hardware SVG, canvas preview, or job code. Mandala coverage must precede splitting randomization, motif/bridge geometry, previews, or job code. Depthmap coverage must precede changing its bootstrap globals or dynamic import.
4. Publish the complete import graph through an explicit manifest or tested recursive upload. All modules must exist before the entry HTML is uploaded.

### Phase 5 - observe, then tighten CSP separately

1. Reach zero executable inline code and deploy to staging without changing CSP enforcement.
2. Observe report-only violations across every route and feature. Account for jsDelivr/model loading, API/Cognito connections, WebAssembly, workers, blob-backed SVG/image previews and downloads, and `data:` image use. Dynamic style attributes/custom properties in Rasterizer and the labs affect `style-src`, not the `script-src` extraction goal.
3. Decide how JSON-LD is treated before enforcement; do not remove SEO data merely to simplify policy.
4. Remove `'unsafe-inline'` from report-only `script-src`, observe again, then enforce CSP in a later isolated change with a header-only rollback. Do not combine enforcement with extraction, modularization, or cache changes.

## Characterization and regression matrix

The browser suite is the main behavior contract; string tests are supporting guardrails.

- Shared shell/auth: signed-out reveal and fail-open; sign-in callback, refresh, logout, cross-tab state; registered-only labs; config failure; no duplicate listeners.
- Rasterizer: guest/member resource loading; Processing Palette and color mapping; restored preferences; crop and transparent-shape paths; quantized preview; geometry-by-swatch and Fauxlogram flow painter; panel tiling enable/disable, dimensions, gaps/inset, row/column/serpentine order, aspect fit/fill, padding/border swatches, layout preview and payload; guest/member uploads; submit, resume, poll, logs, ordered downloads.
- SpiralGraph: Processing Palette fallback roles versus Color Palette swatch routing; automatic line/fill mode; add/duplicate/reorder/remove drawings; every per-drawing track, gear, pen-hole, side, start, direction, rotation, track inclusion, ribbon thickness, and custom SVG path; selected/stacked colored canvas previews; hardware track/gear/assembled SVG; pointer and keyboard/radio pen-hole selection; slider/card active-drawing sync; payload equality; `/spiralgraph/jobs`, resume/poll, SVG/LightBurn/manifest downloads. Test narrow mobile widths for no horizontal page/control-card overflow, readable previews, and usable touch/keyboard targets.
- Layered Mandala: Processing Palette material/Cut-role selection; add/duplicate/reorder/remove (up to 12); reset and bounded randomize; built-in and sanitized custom SVG motifs; ornament/composition, construction, repetitions/rings, transforms, rim/openwork and automatic-bridge controls; selected/stacked previews; dimension constraints; exact payload; `/mandala/jobs`, resume/poll, combined and per-layer LightBurn/SVG/preview/manifest downloads; mobile layout and control accessibility.
- Depthmap: guest/member bootstrap and palette data; photo inference versus existing depthmap; clip/gamma/invert, resize/border/perimeter, paint/clear; color-guided Depth Palette influence; 8/16-bit PNG; 3D-Slice Processing Palette roles, cleanup and LightBurn export; Parallax strength/background/appearance and PNG/SVG; Layered Relief construction, grouping, smoothing, thresholds, palette roles, surface engraving, scoring, registration, previews, and LightBurn export. Verify the bootstrap runs before the generator exactly once.
- Other routes: Vault, History, Admin, Color Lab, Fauxlographic Lab, Community Set, docs search/index data, release-story media/TOC/progress, SEO copies, and both legacy redirects.

At desktop and representative mobile viewports, assert no unexpected horizontal overflow and snapshot key accessible names/states. For canvas output use deterministic dimensions/data checkpoints rather than fragile pixel-perfect full screenshots; use stable SVG/DOM snapshots for hardware/vector previews.

## Delivery and rollback

Every phase is a separate commit and staging release. Deployment order is always: publish every new/revised JavaScript, CSS, and transitive module dependency under immutable content-versioned names; verify object existence/content type; upload dependent HTML last; then invalidate CloudFront. Query-string revisions improve cache revalidation but are not an atomic release mechanism. Do not overwrite an asset in place when old cached HTML and new HTML require different behavior.

Keep old asset names for at least one release when renaming because cached HTML may still request them. Record the source commit and deployed asset manifest. If a stage fails, stop promotion, revert the phase commit, and redeploy the last known-good repository revision using the same asset-first ordering; do not repair production by manually mixing object generations. Verify root plus affected routes, console/network, auth, one representative payload, and download links after rollback. If CSP later fails, roll back only the security-header change to the prior report-only policy and leave known-good external assets in place.

## Acceptance

For each phase, run the focused JavaScript policy/syntax suite, relevant feature tests, all builders/scans, import resolution, and `bash -n` in the supported Linux/CI path. Serve locally over HTTP; do not use `file://` for module validation. Run the characterization suite before/after each boundary, then repeat critical signed-out/signed-in and job/download flows on staging.

Each extraction PR must pass a minimum gate: the JavaScript policy/inventory suite, syntax and import-resolution checks for every touched entry, the focused route characterization tests, a shared shell/auth smoke suite, generated-artifact scans, and deployment-script syntax validation. The full browser matrix remains the staging promotion gate rather than making every small PR rerun unrelated workflows.

Final acceptance requires: no executable inline script bodies, `on*` attributes, or `javascript:` URLs in any deployed output; data blocks documented, inert, and safely serialized for HTML; scripts checked in their actual mode; every direct and imported asset uploaded before every consumer; baseline-equivalent desktop/mobile behavior; clean staging console/network; and a report-only CSP observation showing `script-src` can drop `'unsafe-inline'`. CSP enforcement remains a later decision.

## Project skill

The repository-local guidance lives at `.agents/skills/serverless-frontend-javascript/SKILL.md`, following the supported project convention. `quick_validate.py` validates its structure but not runtime discovery. Because this session began in the primary worktree while the skill exists only on this isolated branch, fresh-session discovery cannot be proven here; after merge, start a new Codex session rooted in the repository and confirm the skill appears and activates for a representative serverless frontend change.
