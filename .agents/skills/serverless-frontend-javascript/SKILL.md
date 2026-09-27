---
name: serverless-frontend-javascript
description: Maintain browser behavior for the MOPA Laser Rasterizer static serverless frontend. Use when adding or changing JavaScript in serverless_web or serverless page builders/templates; do not use for backend-only work.
---

# Serverless frontend JavaScript

Put executable browser behavior in external `.js` files. Do not add JavaScript inside HTML `<script>` bodies, Python-generated HTML strings, inline `on*` attributes, or `javascript:` URLs.

Before editing, identify whether the page is checked in under `serverless_web/` or rendered by a `dev_setup/build_serverless_*.py` builder. Include browser code deployed from both `serverless_web/` and `static/`; Depthmap entry points and their import graph are part of the serverless frontend even though their sources live under `static/`. Keep generated values as inert `application/json` data or ordinary `data-*` attributes and read them from external code. Treat JSON-LD as structured data, not an invitation to add behavior.

Preserve script timing deliberately:

- The current pending-shell guard runs synchronously before body paint. When extracting it, prefer a static class on `<html>` plus an external-CSS fail-open and let `staging-shell.js` remove the class; a parser-blocking external script adds a network stall before its timer can start. Do not change this path without normal, slow, failed-resource, JavaScript-disabled, and reduced-motion browser tests. Reduced-motion styling must not leave the page hidden.
- Page modules run after parsing; do not change a classic script to `type="module"` as part of an unrelated feature.
- `staging-shell.js` deliberately exposes `window.stagingShellSetAuthenticated` and `window.stagingShellBeginLogin`; avoid new globals.

When adding or renaming an asset, resolve direct references and static or literal dynamic imports across both source roots. Update the explicit uploads in `dev_setup/deploy_serverless_staging_web.sh`, use `application/javascript`, upload the complete dependency graph before dependent HTML, and revise the page's cache-busting query. A query revision and the final CloudFront invalidation are not atomic deployment; asset-first ordering is required. Production uses the same deployment path.

Keep markup assertions against HTML and behavior assertions against the owning JavaScript file. Run `python -m pytest tests/test_serverless_web_javascript.py -q` plus focused feature tests; this renders and scans all deployed serverless builders. Inline-debt inventories must preserve execution mode, order, and multiplicity so duplicated or reordered blocks cannot hide behind a set of hashes. Never expand or replace inline-script hashes or HTML-before-asset debt to land behavior; only remove entries while extracting legacy blocks. Preserve actual execution mode in syntax tests.

Before decomposing the Rasterizer, first move its block byte-for-byte to a classic end-of-body `rasterizer.js` in a dedicated change. Before that mechanical extraction, require deterministic browser smoke coverage for startup, signed-out behavior, restored settings, a representative quantized preview, panel tiling, and submission-payload equality. Build the comprehensive authentication, editing, job lifecycle, and feature characterization suite before module decomposition, then expand it around each boundary being moved. Keep CSP enforcement as a separate post-observation change.

This skill uses OpenAI's supported `.agents/skills/` repository convention. `quick_validate.py` checks structure only; after the skill is merged, verify discovery from a fresh Codex session rooted in the repository.

For the staged legacy extraction and module map, read [docs/serverless-inline-javascript-extraction-plan.md](../../../docs/serverless-inline-javascript-extraction-plan.md).
