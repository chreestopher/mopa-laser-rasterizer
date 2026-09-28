---
name: serverless-frontend-javascript
description: Maintain browser behavior for the MOPA Laser Rasterizer deployed serverless frontend. Use when adding or changing JavaScript in serverless_web, deployed static modules, or serverless builders/templates; do not use for backend-only work.
---

# Serverless frontend JavaScript

Put executable browser behavior in external `.js` files. Do not add JavaScript to HTML `<script>` bodies, Python-generated source strings, inline `on*` attributes, or `javascript:` URLs. Keep generated values in inert `application/json` blocks or ordinary `data-*` attributes and read them from external code; JSON-LD is data, not behavior.

Before editing, trace the deployed artifact from `dev_setup/deploy_serverless_staging_web.sh`. Cover checked-in `serverless_web/`, all invoked `build_serverless_*.py` output, and browser code deployed from `static/`. Depthmap's bootstrap and transitive imports are in scope even though the feature spans both roots.

Preserve execution semantics:

- Do not change classic scripts to modules incidentally. Syntax-check classic code as classic and modules, including transitive imports, as modules.
- Keep script order and startup timing. `staging-shell.js` intentionally exports `window.stagingShellSetAuthenticated` and `window.stagingShellBeginLogin`. Depthmap currently sets `window.serverlessDepthResources` and `window.serverlessDepthGuest` before dynamically importing its generator; do not break those contracts without characterization.
- For pending-shell behavior, prefer the existing Mandala/SpiralGraph pattern: static class plus external-CSS fail-open, removed by the shell. A synchronous external guard blocks parsing and cannot start its timer until the network responds. Test normal, slow, failed CSS/JS, JavaScript-disabled, and reduced-motion cases before changing it.

When adding or renaming an asset, resolve direct references plus static and literal dynamic imports across both roots. Update the explicit deployment uploads, use `application/javascript`, and upload the complete JavaScript/CSS dependency graph before dependent HTML. Bump the page query revision, but remember query revisions and CloudFront invalidation are not atomic deployment. Keep old names through the rollback window when renaming.

Keep HTML assertions about markup and JavaScript assertions against the owning source. Run `python -m pytest tests/test_serverless_web_javascript.py -q`, relevant feature tests, every serverless builder scan, import resolution, and `bash -n` in the supported Linux/CI path. The debt inventory must preserve block execution mode, order, and multiplicity, cover every artifact the deployment publishes, reject obfuscated handlers and `javascript:` URLs, and list zero-debt routes explicitly. Never accept a new/replacement hash or HTML-before-asset exception merely to land behavior; investigate source intent and only remove debt during extraction.

Before decomposing any large client, establish deterministic HTTP-served browser characterization for its owned behavior, payloads, previews, auth/storage, mobile layout, resume/poll, and downloads. In particular:

- Extract the Rasterizer block byte-for-byte to a classic end-of-body `rasterizer.js` in its own passing change before modularizing it. Cover Processing Palettes, geometry/flow, crop/quantized preview, panel tiling, submission, and lifecycle.
- Cover SpiralGraph palette routing, per-drawing controls, custom SVG, colored and hardware previews, keyboard/touch interaction, mobile overflow, exact payload, and SVG/LightBurn outputs before splitting `spiralgraph.js`.
- Cover Layered Mandala palette roles, layer order/reset/randomize, motif/bridge/openwork controls, custom SVG, previews, payload, and per-layer/combined exports before splitting `mandala.js`.
- Cover Depthmap bootstrap order, edit controls, color-guided palettes, 8/16-bit PNG, Depthmap LightBurn, Parallax PNG/SVG, and Layered Relief LightBurn before changing its module graph.

Keep CSP enforcement separate. First reach zero inline executable code, deploy without enforcement changes, and observe report-only violations for CDN/model, API/Cognito, WebAssembly, workers, blob/data previews/downloads, JSON-LD, and dynamic styles. Enforce only in a later reversible header change.

This uses the supported `.agents/skills/` project convention. `quick_validate.py` checks structure only; after merge, confirm automatic discovery from a fresh Codex session rooted in this repository.

For the inventory, boundaries, migration order, characterization matrix, and rollback process, read [the extraction plan](../../../docs/serverless-inline-javascript-extraction-plan.md).
