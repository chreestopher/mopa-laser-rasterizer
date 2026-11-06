# LightBurn extension POC — approved development plan

Approved November 5, 2026. Worktree: `E:\Code\mopa-lightburn-rest`.
Branch: `feature/lightburn-rest-browser`, created from staging at `a5af8cc`.

## Working agreement

Develop one feature at a time: write tests, demonstrate failure, implement,
make tests pass, and verify the feature live where possible. Stop at a
reviewable feature for operator review and potential sign-off. Feature 1 makes
no deployments or project changes. Feature 2 permits the isolated staging
diagnostic page described below; no production deployment or project changes.

## Architecture

Plain JavaScript Manifest V3 Chrome/Edge extension, isolated under
`dev_setup/lightburn-extension-poc`. Following operator direction after Feature 4,
the background worker owns native file imports and SSE observation. Job History
owns the visible review/confirmation dialog. The extension tab remains for
pairing and diagnostics/library reads. No toolbar popup. No frameworks, native
companion, generic HTTP proxy, or backend API changes.

The in-page module creates controls only after a verified extension discovery
handshake. A narrowly scoped content script announces the public extension ID;
commands still pass through the exact-origin, top-frame external allowlist.
Disabled/absent extensions leave the existing downloads unchanged. Stage and
review are bound to the originating browser tab, and confirmation must include
its review identifier. A closed owner tab releases its pending/result ownership
without cancelling or replaying a send. Credentials stay in extension storage.
Session storage journals the staged file and operation intent. Worker recovery
marks an interrupted open unknown and never replays it.

Fixed API destination: `http://localhost:19520`. Enforce the port in code;
host permissions themselves cover localhost. Keep browser security enabled.
Add permissions only when the relevant feature needs them.

## Features and gates

1. **Transport:** sideloadable extension with a Check connection button.
   Extension-origin GET `/` must return readable 200 and GET `/api/status`
   with a deliberately invalid token must return readable 401. Distinguish
   reachability from successful pairing and machine-link status. Use bounded
   requests, reject redirects, and report failures honestly. Stop on a
   transport blocker before implementing authentication.
2. **Website bridge:** real button-driven HTTPS diagnostic page reaches the
   extension and receives the transport summary. Verify the actual Rasterizer
   staging origin through an existing preview, or an isolated diagnostic page
   deployed through the normal staging workflow. Exact origin and bounded
   command allowlists. DevTools execution is diagnostic, not acceptance.
3. **Authentication and library:** explicit pairing requests only `state`,
   `project`, `upload`; HMAC-SHA256 per Unix minute; secret in trusted extension
   local storage, never in website messages/logs. Forget removes local secret,
   not server-side authorization. Read status/project/units/library; prove
   reload persistence and minute rollover. Webpage receives real nonempty
   library and units; manually verify one MOPA entry and available sublayers.
4. **Native project:** webpage stages a <=1 MiB actual Rasterizer `.lbrn2`.
   Initially extension-tab confirmation (verified); now operator-approved
   in-page confirmation, saved/disposable target, reject
   modified project. Open SSE before POST `/api/file/open`; wait for stream
   readiness and completion event, then inspect project and actual layer
   settings/geometry. HTTP 202 is acceptance only. Test one instance without
   other clients/manual imports: completion events have no correlation ID.
5. **Failure evidence:** declined pairing, closed LightBurn, missing extension
   tab, disallowed origin, oversize payload, and interrupted post-send
   observation. Unknown outcome means check LightBurn, never automatic resend.

Use focused tests for transport, HMAC, bridge validation, SSE chunking, and
event-before-response/disconnect handling as each feature is implemented.
Maintain passed/failed/unproven evidence and record browser versions.

## Scope and reviewer decisions

Prove the website bridge early; require native open, defer merge. Keep the
extension tab open during operations. Verify useful MOPA data, not only counts.
Defer Vault conversion/save, product controls, large files, background operation,
store packaging, Firefox, LAN, multiple instances, settings writes, and machine
commands. Re-estimate after transport/bridge and authenticated reads; the initial
2–4 day estimate is provisional, not a commitment.

## Review checkpoints

- Feature 1: implementation and live transport gate passed November 5, 2026;
  seven unit tests and browser UI checks pass. Live Chromium 153.0.8010.12:
  root 200, invalid-token status 401, exactly two GETs. Operator confirmed Edge
  success and signed off before Feature 2. See the extension README.
- Feature 2: tests-first bridge implemented; 13 unit tests and 25 existing
  serverless JavaScript checks pass. Deployed HTTPS staging page reached live
  LightBurn in installed Edge 156.0.4314.58 and Chrome 156.0.8078.80, without
  response substitution. Both reject unsupported commands and recover when the
  extension console closes. Three diagnostic assets published to staging only;
  no production or LightBurn project changes. Operator confirmed both Edge and
  Chrome and explicitly authorized Feature 3.
- Feature 3: tests-first pairing/library implementation; 24 unit tests and
  25 serverless JavaScript checks pass. Mocked browser auth tests pass in Edge
  and Chrome, including decline, saved pairing, units/sublayers, website handoff,
  empty library, unauthorized reads, and forgetting. Live Edge pairing, reload,
  minute rollover, and deployed website library handoff passed: `100w-fiber`,
  40 settings, mm/s and mm, device `JCZFiber 175X175`. Chrome 156.0.8078.80
  also passed real pairing, reload, minute rollover, and deployed handoff, with
  the same library and units (Edge 156.0.4314.58). One consent request per browser;
  all remaining operations were reads. The observed image setting included
  speed 4000, max power 90, MOPA pulse width 120 ns, and Stucki dithering.
  Operator confirmed library retrieval and individual setting selection in both
  Chrome and Edge and authorized continuing implementation.
- Feature 4: native open implemented in separate native-open/native-panel modules.
  Nine transport tests and two bridge tests were run red before implementation;
  all 35 focused tests and 25 serverless JavaScript checks now pass.
  Mock API browser tests pass in Edge and Chrome: website staging, no implicit
  upload, duplicate staging rejection, unsaved project block, explicit extension
  confirmation, event-before-202 completion, consumed payload, and status handoff.
  Files are limited to 1 MiB and native .lbrn2 XML. Open replaces the current
  project; it never merges or operates the machine. SSE is subscribed before
  POST, with reviewed metadata checked before and after readiness. A send with
  uncertain completion is never retried automatically. Pending files are memory
  only and cannot be silently replaced by another webpage request.
  Operator confirmed the live native-open workflow worked in both Chrome and
  Edge on November 5, 2026, accepting this review checkpoint. Detailed numerical
  geometry/settings comparisons were not separately reported.
  Only one LightBurn instance and one extension console
  should be open; no concurrent imports or project edits during the test. The API
  offers neither atomic compare-and-open nor correlated completion IDs, so these
  checks mitigate races but cannot establish exclusive ownership of LightBurn.
  Extension version 0.4.0 is ready for operator review. The three diagnostic
  staging assets were published and verified byte-for-byte over authenticated
  HTTPS (HTTP 200). Pairing/library regression and native import mock suites
  passed again in both installed browsers after integration. No live file open
  was performed during development; no production deployment occurred.
- Job History integration (operator-authorized scope update): implemented as
  separate lightburn-integration JS/CSS modules and import-controller worker
  module. Native-only Load in LightBurn buttons, review, confirmation, and progress
  stay on the existing page. Diagnostics remain optional for file loading.
  No new controls or dialog exist when the extension is absent; active controls
  are removed when the extension stops responding to its heartbeat.
  Tests-first controller/protocol/download cases passed red then green. All 43
  focused tests and 40 web/production-deployment regression checks pass. Real
  History rendering with synthetic LightBurn passed in Edge and Chrome, including
  closing/reopening the dialog during import, reload recovery, exactly one send,
  and no controls after extension removal or on a fresh extension-free page.
  Pairing/library browser regression also passed in both browsers.
  Staging artifacts now permit GET CORS only from the staging origin; existing
  POST rules and signed URL access controls are preserved. Infrastructure and
  deployment definitions retain that rule. Both browsers passed real signed
  artifact reads from the actual HTTPS staging origin.
  Six web assets deployed to staging and verified byte-for-byte over HTTPS.
  Extension version 0.5.0 is ready for manual review. No production deployment or
  live file replacement was performed for this change. Live in-page acceptance
  in both browsers remains the operator checkpoint.

## November 6 update: staging failure recovery and 100 MiB files

Operator reported an empty/idle dialog and identified the original 1 MiB cap as
the likely trigger. Browser regression reproduced the defect: idle status polling
erased the useful oversize error. The regression failed before the fix. Errors
now stay visible, the selected filename remains visible, and Stage selected file
provides recovery. Polling is limited to observing an active open.

Operator explicitly requested a 100 MiB limit. Version 0.6.0 replaces the normal
page's single base64 message with bounded 256 KiB chunk requests. IndexedDB owns
the binary data; the session journal stores only its reference. Exact upload IDs,
offsets, tab ownership, and cumulative byte limits are validated. Completion
validates native UTF-8 content; the byte upload remains a single explicit POST
only after review and confirmation. File bytes are cleared on completion/discard
and orphaned bytes on startup without a matching session. Legacy small-message
diagnostic validation remains bounded to 1 MiB, but the normal page uses the
100 MiB path. Limits are application limits, not claimed LightBurn API limits.

Tests cover exactly 100 MiB, one byte over, bounded messages, data preservation,
incomplete transfer cleanup, and file-reference-only journaling. Browser tests
stream the full 100 MiB inside the renderer (avoiding a giant DevTools fixture
message), through actual external messaging and IndexedDB, to synthetic LightBurn.
Real large-project import behavior still requires operator review.

Verification: 47 focused tests and 25 web checks pass. Exact 100 MiB browser
transfers passed in Edge and Chrome, including reload of the staged file, a
session journal under 4 KiB, explicit confirmation, and exactly one byte-count-
verified synthetic POST. The initial idle/error regression failed before its
fix and passes in both browsers. The updated page module was published only to
staging and verified byte-for-byte over authenticated HTTPS. Reload extension
0.6.0 and refresh Job History before manual review; older extensions receive an
explicit upgrade message rather than attempting an unsupported large transfer.

Operator acceptance, November 6, 2026: user confirmed the updated in-page
native loading workflow works in both Edge and Chrome. This review checkpoint
is passed. The actual operator-tested file size was not reported; exact 100 MiB
coverage remains the automated browser evidence described above.

## November 6 failure-handling checkpoint — version 0.6.1

The operator authorized the planned failure-handling work. New tests reproduced
two gaps before implementation: raw/unhelpful offline review errors, and a page
that kept displaying a successful old review after a failed second review had
revoked its backend confirmation identifier. The page now reconciles extension
state after errors, clears the confirmation checkbox, and preserves the useful
failure message. Missing/expired pairing and unreachable/timed-out LightBurn have
actionable messages. Authentication rejection at SSE setup or file POST gives
pairing recovery instructions without repeating the request.

| Failure | Verified behavior |
| --- | --- |
| Download interrupted | Partial upload cleared; message remains; explicit retry works |
| Partial upload cleanup fails | Message directs the user to Discard / clear result |
| Missing pairing / 401 / closed LightBurn | Review cannot confirm; staged file remains available for recovery |
| A later review fails | Earlier confirmation is revoked in the UI and extension |
| Request timeout | Bounded wait, request aborted, recovery message |
| Completion stream disappears after POST | Unknown result persists across page reload; no automatic resend |
| Worker interrupted during staging/open | Explicit discard for partial staging; unknown for interrupted open; no replay |
| Extension removed or absent | Integration controls disappear; ordinary downloads remain |
| Declined consent / negative import / disallowed origin / oversize | Existing focused regressions remain passing |

52 focused Node tests and 25 serverless web checks pass. The expanded browser
failure suite passed in Edge and Chrome using actual page/extension messaging
with synthetic download and LightBurn faults. Run:
`node tests/lightburn_extension_browser.mjs --inline --failures`.
No live LightBurn process was stopped, pairing revoked, or project replaced.
Manual recovery review remains the operator checkpoint. Full browser restart
or extension reload clears session state; inspect LightBurn before deliberately
restaging a file if either happened during an open operation.

The updated integration module was deployed to staging only and verified
byte-for-byte over authenticated HTTPS. Reload extension 0.6.1 and refresh
Job History for operator review. Production was not deployed.

Operator review, November 6, 2026: user reported the failure-handling update
seems to be working well. This checkpoint is accepted; individual manual fault
cases and browser coverage were not separately specified in that feedback.

## November 6: Material Library to new swatch palette — version 0.7.0

Approved sequence:
1. Import one or more selected LightBurn Material Library settings into a new swatch palette (this checkpoint).
2. Add a "+" button on each existing palette to start Import Swatch from LightBurn. Do not introduce a standalone destination picker.
3. Processing palette builder: assign a material setting to each processing operation type.

The first workflow is implemented as isolated page bridge, conversion model, and
Vault dialog modules. Controls appear only after an enabled compatible extension
is detected. The extension reads the selected library directly using its stored
pairing; the diagnostics tab can remain closed. No LightBurn writes are made.

Select 1–100 entries across materials, name the palette, preview, then explicitly
create it using the existing account import/upload/finalize API. Entries become
one palette material group with unique descriptions. Source material names and
the sanitized API snapshot are retained as provenance in the CLB. Speed and
distance units convert independently to mm/s and mm; frequency stays Hz and pulse
width stays ns. Supported settings and sublayers are mapped; unsupported fields
are listed and require acknowledgment, and remain reference data only. This is
not a lossless clone of all LightBurn settings. Thickness is normalized to the
palette's -1 sentinel; original thickness remains in source provenance. Colors
are assigned afterward through the existing Vault swatch controls, never guessed.

Tests were written first. 55 focused Node tests and 26 Python web/parser checks
pass. The new browser scenario passes in both Edge and Chrome with actual
extension messaging and synthetic LightBurn/account services. It covers selected
entries only, preview acknowledgment, upload/finalize, empty and unauthorized
libraries, uncertain save without retry, and disappearing controls without the
extension. Generated XML also passes the actual backend material parser checks.
Run `node tests/lightburn_extension_browser.mjs --palette` for browser coverage.

Manual review remains pending: reload extension 0.7.0, refresh staging Vault,
import selected live settings, inspect the saved palette, and repeat in both
browsers. Only this first feature is included; the per-palette + and processing
builder remain deferred until this checkpoint is reviewed.

Staging publication: the six new/updated Vault assets were deployed and verified byte-for-byte over authenticated HTTPS. Production was not deployed. Operator review is pending.

### Save feedback follow-up

Operator confirmed live palette creation works, but completion feedback was not
visible. A browser regression with expanded setting details reproduced the
success message being above the dialog's scroll viewport. Progress/results now
move beside the Create action; confirmed saves show Palette created and Done,
and the result receives focus and scrolls into view. Success is announced before
the Vault refresh completes. The regression and existing palette scenarios pass
in Edge and Chrome. Staging upload was attempted but blocked by expired AWS SSO;
this follow-up is local only until credentials are refreshed and upload succeeds.

### Import-time swatch assignments

User requested swatch assignment during import. Preview now provides an official
Rasterizer swatch selector for each selected entry. Exact description/name matches
(case-insensitive, trimmed) default to that swatch when available; unmatched or
conflicting entries remain Unassigned. All assignments can be changed, and a
swatch cannot be used by two settings. Source descriptions are preserved.

After creating the new palette, the page reads current account preferences and
saves its mapping through the existing preferences API, preserving mappings for
other palettes. Explicitly unassigned entries remain unassigned. This is a
separate save step: if it fails, feedback says the palette exists, directs the
user to review assignments in Vault, and never retries palette creation.

Tests-first: new defaults/uniqueness validation and browser selector regression
failed before implementation. Four model tests pass; Edge and Chrome palette
scenarios pass including saved mapping, existing mapping preservation, and partial
mapping-save failure. Live acceptance and staging publication remain pending.


## Existing Color palette imports

The operator accepted the latest new-palette flow and requested an **Import
LightBurn Swatches** button on each existing palette, replacing the earlier +
label. Implemented on branch `feature/lightburn-existing-palette`.

Only Color palettes accept these imported swatches. The button is injected by
the isolated extension integration when the extension is detected and is restored
after Vault refreshes. No controls appear without the extension. The same dialog
selects settings, previews conversions and unsupported fields, and assigns
available Rasterizer swatches. The destination is fixed to the clicked palette.
Existing assignments are reserved; duplicate descriptions receive unique names.
Users should save pending Vault edits before importing.

The existing upload/finalize API now accepts an owned Color palette target. It
appends XML entries without recreating the palette or changing existing settings,
metadata, provenance, or mappings. Duplicate descriptions and size overflow are
rejected before writing. Conditional S3 writes reject intervening object edits;
no automatic retry occurs. Settings and mapping saves are separate steps, as in
the new-palette flow. A partial/unknown result directs the user to inspect the
Vault before another import.

Tests-first coverage includes name collisions, inferred and explicit existing
mappings, reserved swatches, backend ownership/type checks, source preservation,
combined size limits, conditional write failure, and targeted finalization with
session cleanup. Browser coverage checks new-palette and existing-palette flows,
retained assignments, destination identity, and extension-free UI.

Live operator review is pending after the staging PR merges and deploys. The
extension itself is unchanged; refresh Vault after deployment. Processing palette
builder integration remains a separate future feature.

## Processing palette import: role-first review checkpoint

Operator accepted the existing Color palette append feature. The next authorized
feature creates a new Processing palette from LightBurn with one searchable
setting selector per existing Vault role: Cut, Score, Photo, Fill, Shovel,
Cleaning, and 3D-Slice. All start Unassigned. At least one role is required;
multiple roles may share an entry, which is imported once. Source material,
setting name, and operation type identify each choice. The destination is one
new palette material group; original source metadata stays in provenance.

Implemented in separate processing import UI/model modules. The role list is
supplied by Vault rather than duplicated. Existing library conversion and
unsupported-field acknowledgment are reused. Changing a role/name invalidates
the preview and consent. Saving uses the existing material upload/finalize API
with processing_palette intent, then saves material-scoped roles using server
entry references and explicit blanks, preserving other palettes' mappings.
Partial/unknown completion is reported beside the action with no automatic retry.
Only extension-enabled staging pages expose this workflow. No extension or
backend API change is required. The coordinated visual styling pass remains
explicitly deferred until the palette import workflows are complete.

Validation: model tests first failed before implementation. 60 focused Node tests
and 35 Python web/parser/processing checks pass. Compatibility coverage resolves
multiple source materials and duplicate names against the actual backend parser.
Browser coverage includes role-first selection, search, shared entry import,
preview invalidation, unsupported-field acknowledgment, role persistence,
existing-mapping preservation, missing/empty library handling, partial saves,
and extension-free UI. Live operator acceptance follows staging deployment.
