# Veridex issue and resolution log

Started 2026-11-01 from the visible user conversation and the current repository.
This is a working record, not a claim that the running app or external accounts
were tested. Earlier assistant replies and their test results were not available
in the visible conversation, so requests are not treated as completed merely
because a related implementation exists. Do not record passwords or tokens here.

## Resolved with recorded evidence

- **Estate Sales owner workspace (2026-11-02):** Implemented Boss's business
  and project workspace, linked Intake inventory, version-checked edits,
  approved pricing, quantities and online-stock guards, append-only operations,
  client-requested disposition, deterministic settlement and adjustments,
  atomic/idempotent CSV imports, local schedule and document exports. Individual
  receipts exclude other transactions; business totals separate currencies and
  disclose unset fees. Cached eBay review reads linked items without changing
  inventory or external listings. Reviewed specialist jobs retain project scope
  and selected references, reuse image production, and return verified draft
  artifacts without navigating the user session. Existing image behavior is
  covered by regression tests. Luna/low passed 505 tests with zero failures,
  errors, or skips in 110.8 seconds, plus five JavaScript syntax checks; the final
  focused Boss-chat guard test passed. The live API returned 11 workflows and
  the final assets, and whitespace checks passed. Chrome visual validation is
  pending: browser access was unavailable and native Computer Use stopped before
  opening Estate Sales when the current URL could not be reliably verified.
  No live specialist generation or external send/publish/payment/removal was
  performed. See [ESTATE_SALES_PLAN.md](ESTATE_SALES_PLAN.md) for acceptance and
  operator continuation notes.

- **Configured room scope missing from chat (2026-11-02):** Custom rooms stored
  their purpose and capabilities in the catalog, but normal chat omitted them
  from the active-room context and compacted the directory to names only.
  Include active-room purpose and capabilities in `context.current_room`.
  A controlled custom-room test verifies both reach the request and survive
  Codex context compaction without changing rooms. Luna/low passed 91 chat,
  gateway, and server tests with zero failures, errors, or skips. This describes
  assistant context, not implementation of specialized business tools.

- **Workspace and image-jobs commit checkpoint (2026-11-02):** Updated the
  README, architecture, and functionality guide for shared room workspaces,
  explicit chat model/reasoning choices, independent image jobs, friendly names,
  unified history, legacy-draft visibility, and type sorting. Corrected stale
  Back to media and Save as draft confirmation instructions. Final Luna/low
  discovery passed 477 tests with zero failures, errors, or skips in 81.879
  seconds. Syntax checks passed for `app.js`, `room_jobs.js`,
  `room_workspace.js`, and `video_room.js`; the staged diff passed whitespace
  checks. Latest Jobs layout browser validation and a live poster-edit run
  remain pending. Private runtime state is excluded from the commit.

- **Jobs sort by type (2026-11-02):** Added explicit Completed first, Draft
  first, and other lifecycle status choices under Sort by, plus Type A-Z.
  Preferred statuses move to the top without hiding other jobs. Two focused UI
  tests passed, including executed JavaScript checks for type ordering and
  newest-first ordering within drafts. JavaScript syntax and diff checks passed;
  the live server serves the updated script and cache version. Browser visual
  validation was not performed for this label and sorting change.

- **Legacy drafts missing from Jobs (2026-11-02):** The new unsaved-draft
  visibility default also hid older requests that lacked the visibility flag.
  Preserve visibility for legacy records while keeping explicitly unsaved new
  drafts hidden. Three focused tests passed. After backend restart, the scoped
  live Jobs API returned seven jobs: three completed and four drafts, with no
  active workspace jobs or production attempts on those drafts. No runtime
  request records were rewritten by this compatibility fix.

- **Plural and multiline image briefs (2026-11-02):** Image requests using plural
  nouns or line breaks could bypass draft preparation and reach ordinary chat.
  Updated the backend and frontend recognizers; controlled chat tests confirm
  these requests create drafts without model execution. Luna/low passed 112
  focused tests with no failures, errors, or skips; the frontend syntax check
  passed. Restarted the backend and refreshed Chrome with the corrected script.
  The open session was stored in eBay; tracked image creation remains limited
  to Visual Design. The user's exact refusal has not yet been identified, and
  live image production was not invoked for this correction.

- **Visual Design room image jobs (2026-11-02):** Added durable numbered image
  drafts with original instructions, interpretation/assumptions, optional use,
  style, and caption questions, explicit send-versus-continue behavior, and
  version-checked refinement. Jobs are room/workspace-scoped across sessions,
  run independently of chat, and support progress, cancellation, retries,
  linked revisions, and return notices in the originating room/session.
  Controlled fixtures exercised asynchronous output, cancellation, restart
  interruption, and artifact verification. Browser checks in the dedicated
  Chrome profile verified draft creation and same-ID refinement; live image
  production was not invoked. One synthetic Draft #000001 remains in the live
  room. The full Luna/low regression passed 459 tests with zero failures,
  errors, or skips (~135 seconds) before the final focused changes. After the
  cancellation-review fix, the focused Luna/low run passed 110 tests with zero
  failures, errors, or skips, and all three JavaScript syntax checks passed.
  After the Video Production Jobs/media visibility correction, 35 UI tests
  passed with zero failures or errors, and both changed JavaScript syntax
  checks passed. Browser checks confirmed the draft survives restart, the
  narrow layout fits, the pre-creation banner and Return to normal chat work,
  and Video Production Jobs toggles back to media. No later full-discovery
  result is claimed. Semantic output quality and migration of legacy generation
  workflows were not verified.

- **Image request recovery and explicit draft controls (2026-11-02):** A local
  review found that a file-format image request had reached ordinary chat; the
  response offered a textual Send instruction but had created neither a tracked
  job nor draft controls. Updated recognition for PNG/JPEG/WebP creation and
  recovery of older untracked requests into numbered drafts without silently
  starting production. Documentation now describes actual **Send to room** and
  **Keep editing** choices, repeated after refinements; accepted requests report
  status without rerun. Submission carries request ID, reviewed version, and
  confirmation; stale controls and duplicate pending clicks are suppressed.
  The targeted 16 room-job tests and one Node-backed UI test passed. Full
  Luna/low discovery then passed 465 tests with zero failures, errors, or skips;
  Node syntax checks for `app.js` and `room_jobs.js` passed. In Chrome, recovery
  of an existing untracked brief created request #000002 and showed the actual
  Send to room/Keep editing buttons. Keep editing left it at zero attempts;
  actual Send accepted it and it progressed queued, running, completed with
  exactly one attempt. Normal chat remained usable and the stale draft controls
  disappeared after acceptance. The existing Codex media route produced a PNG;
  its nonzero size, SHA-256, and artifact-ledger entry were independently
  verified, and the image was viewed. The originating chat displayed its
  completion notice, and the room preview loaded. Final UI guards cover briefs
  edited in the workspace, reopening chat at its latest reply, and excluding
  deterministic job notices from the default model label. All 37 UI tests and
  the changed JavaScript syntax checks passed; Chrome confirmed latest-message
  positioning and the model label. Other follow-up controls or providers remain
  unverified live.
  Earlier checks in this entry and the original image-jobs entry remain dated
  historical evidence for their respective checkpoints.

- **Unified image history and Jobs controls (2026-11-02):** Implemented the
  modeless Jobs popup, sorting and keyboard/detail navigation, unsent-draft
  confirmation and save behavior, unified chat/Art Studio history, edit-draft
  source preservation, and friendly output renaming backed by metadata aliases.
  The new lifecycle, naming, and header/history tests plus the Node confirmation
  test passed. In the existing focused suite, 105 of 106 tests initially passed;
  the remaining old UI fixture was migrated and then passed. Three Art Studio
  completion tests initially exposed a read race; a terminal-publication fence
  corrected it and all three passed. Full Luna/low discovery passed 476 tests
  with zero failures, errors, or skips in 129.303 seconds. Syntax checks for
  `app.js`, `room_jobs.js`, and `room_workspace.js` passed. After runtime restart,
  the scoped live Jobs API returned three listed jobs, including one historical
  Art Studio output, no active workspace jobs, and the current-draft response
  field. Visual browser QA was not completed: the existing Chrome automation
  host was unavailable, and native computer use stopped when the current Chrome
  URL could not be reliably identified. Refresh Veridex to load the new JS/CSS.
  No live generation or poster edit was performed in this slice; cancellation,
  naming, confirmation, and job lifecycle behavior were checked with controlled
  fixtures. A prior live black-square generation remains evidence for its older
  checkpoint only. Current layout appearance remains unverified.

- **Connected reasoning selector (2026-11-02):** Replaced the native model list
  with a two-panel picker: models on the left, governed reasoning choices on the
  right. Explicit Codex requests carry a validated `chat_reasoning` value through
  the server and gateway; Default and Gemini reject arbitrary reasoning overrides.
  Browser checks verified selecting Luna/High, closing the picker, preserving
  the pair across chat close/reopen, and returning to automatic defaults. The
  focused Luna/low run passed 147 tests; final discovery passed all 447 tests
  with no failures/errors/skips and both JavaScript syntax checks passed. Live AI
  generation was not used to validate reasoning; gateway invocation and rejection
  behavior are covered by tests.

- **Floating chat model selection and window controls (2026-11-02):** Added a
  centered title, minimize/maximize/restore/close controls and a model dropdown.
  Default keeps automatic routing; explicit Codex choices use a governed
  allowlist and cannot silently fall back. Configured Gemini supports text
  conversation across rooms, with unsupported tasks rejected. Its configuration
  is now local to Veridex rather than the sibling app. Older runtime snapshots
  without the new allowlist inherit the committed additive policy; an explicit
  empty allowlist still disables choices. Browser checks verified the default
  label, manual selection, minimize/maximize/restore, and choice preservation on
  close/reopen. The local catalog reports Gemini not configured, so live Gemini
  generation remains unverified. No live AI generation was used for acceptance.
  Luna/low ran the final suite: 446 passed, zero failures/errors/skips, with both
  changed JavaScript syntax checks passing. Configuration secrecy, invalid
  choices, Gemini task/attachment limits, legacy policy handling, and explicit
  failure without fallback have focused coverage. Choices are page-memory only;
  structured tool workflows continue using their own routing.

- **Shared room workspaces (2026-11-02):** Added a common room header, full-height
  workspace, and one floating session chat using the existing transcript and
  composer. All 22 configured rooms were checked in Chrome: workspace dimensions
  matched at the same viewport, each desktop header measured 82 pixels, and only
  one transcript/composer was present. Narrow checks covered My Office, Control,
  Infrastructure, Conference, and Video Production: all headers measured 132
  pixels without horizontal document overflow. Chat close/reopen preserved an
  unsent draft; Control Room's logs and My Office's email/compose/address-book
  controls opened. Video preview loaded its 213.2-second duration without a media
  error. The existing focused UI/media/tools suite passed 44 tests; the final
  Luna/low validation passed all 439 discovered tests with no failures, errors,
  or skips, plus syntax checks for all three changed JavaScript modules. Calendar
  remains an explicitly labeled disabled placeholder. New room dashboards and
  video timeline editing are not implemented; runtime model routing was not
  changed. Live attachment upload, native-editor execution, and session-switch
  draft behavior were not exercised in this slice.

- **Documentation model routing (2026-11-02):** Added Luna/low for routine
  documentation-only edits and focused review using established facts. The
  policy emphasizes bounded context and avoiding repeated work to minimize
  token use, without claiming that model choice guarantees fewer tokens.
  Technical decisions, diagnosis, and policy design remain on Sol/high; small
  documentation follow-ups may finish on an already-active Sol/high route.

- **Chrome extension connection and Video Production playback (2026-11-02):**
  Read-only installation checks found ChatGPT in ordinary Chrome's `Default`
  profile but absent from Veridex's dedicated `Profile 2`. After the user
  installed the extension in the dedicated profile, Chrome became discoverable
  and the local Veridex page could be read. One interaction reported a detached
  debugger; a later reconnect, startup-notice dismissal, and updated page read
  succeeded. Video Production navigation, the media workspace, and Production
  tools panel were then observed in Chrome. The selected video displayed a
  duration of 213.2 seconds, and the user confirmed that it plays. This verifies
  user-reported browser playback, not agent-observed playback or seeking.
  The focused media/tools/UI checks passed 44 tests with no failures, errors,
  or skips; both video JavaScript syntax checks passed. Upload interaction,
  floating-chat behavior, native-app launch, and live export/import remain
  unverified. Audacity and OBS report that automation setup is needed.

- **Animation revision ordering on rapid saves (2026-11-02):** Release checks
  exposed older revisions appearing before the latest project when save times
  were identical. Project lists now break timestamp ties by numeric version.
  The existing versioned-save test freezes the clock and verifies latest-first
  ordering, preserved notes and the earlier snapshot; the focused test passed.
  Final repository release verification passed all 439 discovered tests with
  no failures, errors or skips. JavaScript syntax and staged whitespace checks
  also passed. Browser validation was blocked at that checkpoint; later Video
  Production checks are recorded above. Animation's live checks remain pending.

- **Personal Codex instruction loading and startup reporting (2026-11-01):**
  Installed global working agreements and corrected rule-loader discovery to
  use global/project instruction files rather than treating config.toml as the
  personal rules. The launcher now reports the setup version and uses a local
  fresh-prompt diagnostic. Both instruction files were verified; seven startup
  tests passed. This verifies this computer's CLI, not every other computer.
- **Development model policy drift (2026-11-01):** Updated the required main
  route to Sol/high and routine route to Luna/low with current explicit model IDs.
  Added the shared workflow and bounded agent definitions. Cross-computer
  publication and per-machine acceptance remain pending.

The following eBay entries are earlier project fixes documented in [AUDIT_FOLLOWUPS.md](AUDIT_FOLLOWUPS.md),
not necessarily fixes requested in this conversation.

- **eBay notification delivery test (2026-09-24):** The audit records a five-event
  canary covering signature verification, queueing, local retrieval, minimized
  storage, and acknowledgment. It also records provider-generated tests for
  order, buyer-question, and message topics. Real buyer messages and completed
  orders still need observed delivery evidence.
- **Automatic eBay notification checks:** The audit records a startup poller with
  serialized manual/background checks and a Connected Accounts toggle. Current
  operation was not checked for this document.

## Open operational issues

- **Earlier Chrome origin denial; cause unconfirmed (2026-11-02):** Normal
  Browser Use requests for `http://127.0.0.1:8765` were rejected by the origin
  approval gate as a saved user permission or managed-policy denial. The local
  Codex configuration now explicitly allows that origin, so the saved setting
  and effective browser authorization disagree. Stale session state or another
  policy override is possible; the cause is not established. Restarting ChatGPT
  Desktop and testing in a fresh coding chat was the proposed diagnostic step.
  Veridex itself restarted successfully and returned `ok: true` from `/health`;
  restarting the backend did not clear the browser denial. Live UI validation
  was blocked at that checkpoint. Later local-page access and interaction
  succeeded after installing the extension in the dedicated profile, as recorded
  above. The origin denial's original cause is not established; no permission
  bypass or recurrence check across fresh desktop sessions was performed.

## Changes present; live verification still needed

- **Video room media workspace (2026-11-01):** Added gallery/list and media filters,
  browser source playback, room intake from the top toolbar, and floating Beta
  chat with attachments beside the input. Room and chat intake have separate
  scopes. Uploads use bounded streaming and reject room changes before save;
  media serving supports HTTP seeking. Focused core/server/UI checks passed,
  including HTTP 201 intake, 200/206 playback, 416 invalid ranges and ledger/scope
  checks. The final UI/media target passed 38 tests; earlier server/UI/media and
  core targets passed 100 and 19 respectively. On 2026-11-02, the room and source
  preview loaded in Chrome and the user confirmed browser playback; see the
  resolved verification entry above for checks and remaining live coverage.
  Full discovery was not repeated for this verification. Editing/timeline remains the
  next slice, and video thumbnails/proxy generation are not yet implemented.

- **Video Production app integration (2026-11-01):** Added the Production tools
  panel and shared `video.action` gateway for six detected apps: Kdenlive,
  Shotcut, Audacity, HandBrake, OBS and VLC. Official HandBrakeCLI was installed
  after verifying its published SHA-256. Sample HandBrake conversion and both
  bundled MLT renderers produced probe-verified playable files. New scope,
  integrity, XML-resource, OBS-authentication and cancellation tests passed;
  40 focused tests passed after the final adjustments (112 existing tests passed
  earlier in the slice). The full-suite subagent hit a usage limit and did not
  return a result. Backend restart, health, static script delivery and all six
  executable detections were checked. On 2026-11-02, the Production tools panel
  loaded in Chrome with all six apps detected; native-app launches and live job
  controls were not exercised. OBS recording/scenes and Audacity
  scripting require local setup and remain unverified live; no streaming or
  automatic synchronization of arbitrary native-editor projects is claimed.

- **VLC playback integration (2026-11-01):** Detected the installed VLC media
  player and added **Open in VLC** for local audio/video in room Files libraries.
  The confirmed launch requires full access, an active-room file, and matching
  artifact-ledger path, size, and SHA-256. Animation Studio uses the same guarded
  VLC route. All 429 regression tests passed; a subsequent guard adjustment passed
  its focused test. The backend was restarted without opening a browser and its
  health and invalid-request rejection checked. Real media decoding/playback and
  the live browser button remain unverified; no claim of remote playback control
  or video editing is made.

The following have source or documentation evidence, but no verified end-to-end
result in the visible conversation. They should remain in this section until
the actual user workflow is checked.

- **Shared accounts and workspace confusion:** The user requested the same
  accounts in every workspace after navigation kept returning to a different
  workspace. `connected_accounts.py` supports a designated shared owner and
  `README.md` describes the opt-in setting. Confirm the setting is active, each
  intended account is accessible from each workspace, and navigation stays in
  the selected workspace. Account sharing and workspace navigation are separate.
- **Connected Accounts access:** `web/index.html` and `web/app.js` contain a
  top-toolbar button. Confirm it opens the correct panel in the running app.
- **Corporate Gmail reconnect:** The panel includes a connect/reconnect control;
  the README says valid grants refresh automatically. Verify reconnect and later
  refresh with the intended account, including any Google consent prompts.
- **Sidebar fit and identity:** The user reported the lower menu was cut off and
  asked to remove the obstructing Local User label. `web/styles.css` provides
  scrolling for the rail; the UI tests describe removal of the sidebar identity.
  `web/veridex_actions.js` still contains Local User in an action menu, so verify
  the intended surfaces and window sizes before calling the request complete.
  Follow-up on 2026-11-01: added independently bounded workspace/session lists
  with left-side scrollbar tracks and left-side scrolling for the enclosing menu
  in both sidebar implementations. Navigation text remains left-to-right. All
  34 `test_web_ui` checks and the global navigation JavaScript syntax check passed.
  Live visual verification remains pending because the browser approval gate
  declined access to the local app; no alternate browser route was attempted.
- **Betting photos and screenshots:** The UI provides file selection, image
  drag-and-drop, and Ctrl+V paste, and `test_web_ui.py` contains relevant coverage.
  Check actual attachment, preview, send, and session-switch behavior in the
  running Betting room with both a photo and a screenshot.
- **Dedicated browser profile:** The launcher and bridges are documented to use
  a unified Veridex Chrome profile. Verify startup opens the intended signed-in
  profile and that service tabs use the intended identities; a Chrome profile
  alone does not prove Gmail, eBay, or Facebook is signed in.

## Open or unresolved observations

- **Cross-computer Codex setup:** The portable personal setup is implemented
  locally with preview, backup, restore, diagnostics, and shared skills. Private
  GitHub publication requires specific commit/push approval. Other machines and
  browser password behavior are unverified. See WORKFLOW.md and the separate
  personal setup guide; do not copy browser profiles or authentication state.
- **Todoist CLI authorization:** A fresh CLI acceptance reported authentication
  required even though the plugin is installed. Reauthorize in that client before
  depending on task operations. Repository documents remain the task authority.

- **Google's unverified-app warning:** The user saw a warning that the OAuth app
  is being tested and asked whether Google could trust the app on this computer.
  No resolution or verification of the Google project's publishing status is
  visible. Determine the project's consent-screen/testing configuration and the
  applicable Google requirements before proposing a permanent fix.
- **Gmail and eBay sign-in:** The user reported repeated sign-in and a saved
  password that did not autofill on the password screen; they identified an
  incorrect saved password. The visible thread does not confirm that it was
  corrected or that subsequent sign-ins persist. Do not store credentials here.
- **Facebook sign-in:** The user reported Facebook did not log in. No successful
  login or diagnosis is visible; check the dedicated profile and provider status.
- **Two other errors:** The user asked to fix two errors, but their contents are
  not present in the visible thread. Identify them from the user or current UI
  before recording a diagnosis or marking them fixed.
- **Codex usage reset:** The user reported that the expected five-hour Codex
  reset did not occur around the fall daylight-saving clock change. This is a
  Codex service/account question, not an established Veridex defect; no reset
  time or cause was verified in the visible thread.

## Other existing project follow-ups

[AUDIT_FOLLOWUPS.md](AUDIT_FOLLOWUPS.md) also tracks eBay offer lookup, live seller
verification, model status reporting, and other older project work. Its checkpoint
is dated and should be revalidated before relying on its current-state claims.

When an issue is fixed, record the observed result, a short description of the
fix, the date, and the relevant test or other evidence. Preserve unresolved
provider or manual-verification limitations alongside the fix.
