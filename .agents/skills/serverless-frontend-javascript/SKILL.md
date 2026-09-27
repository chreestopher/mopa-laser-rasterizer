---
name: serverless-frontend-javascript
description: Maintain browser behavior for the MOPA Laser Rasterizer static serverless frontend. Use when adding or changing JavaScript in serverless_web or serverless page builders/templates; do not use for backend-only work.
---

# Serverless frontend JavaScript

Put executable browser behavior in external `.js` files. Do not add JavaScript inside HTML `<script>` bodies, Python-generated HTML strings, inline `on*` attributes, or `javascript:` URLs.

Before editing, identify whether the page is checked in under `serverless_web/` or rendered by a `dev_setup/build_serverless_*.py` builder. Keep generated values as inert `application/json` data or ordinary `data-*` attributes and read them from external code. Treat JSON-LD as structured data, not an invitation to add behavior.

Preserve script timing deliberately:

- The pending-shell guard must remain a synchronous head dependency so it runs before body paint.
- Page modules run after parsing; do not change a classic script to `type="module"` as part of an unrelated feature.
- `staging-shell.js` deliberately exposes `window.stagingShellSetAuthenticated` and `window.stagingShellBeginLogin`; avoid new globals.

When adding or renaming an asset, update the explicit uploads in `dev_setup/deploy_serverless_staging_web.sh`, use `application/javascript`, upload it before dependent HTML, and revise the page's cache-busting query. Production uses the same deployment path.

Keep markup assertions against HTML and behavior assertions against the owning JavaScript file. Run `python -m pytest tests/test_serverless_web_javascript.py -q` plus focused feature tests. Never expand or replace the inline-script hash allowlist to land behavior; only remove entries while extracting legacy blocks.

For the staged legacy extraction and module map, read [docs/serverless-inline-javascript-extraction-plan.md](../../../docs/serverless-inline-javascript-extraction-plan.md).
