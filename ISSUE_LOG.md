# Veridex issue and resolution log

Started 2026-11-01 from the visible user conversation and the current repository.
This is a working record, not a claim that the running app or external accounts
were tested. Earlier assistant replies and their test results were not available
in the visible conversation, so requests are not treated as completed merely
because a related implementation exists. Do not record passwords or tokens here.

## Resolved with recorded evidence

- **Animation revision ordering on rapid saves (2026-11-02):** Release checks
  exposed older revisions appearing before the latest project when save times
  were identical. Project lists now break timestamp ties by numeric version.
  The existing versioned-save test freezes the clock and verifies latest-first
  ordering, preserved notes and the earlier snapshot; the focused test passed.
  Final repository release verification passed all 439 discovered tests with
  no failures, errors or skips. JavaScript syntax and staged whitespace checks
  also passed. Live browser validation remains blocked as recorded below.

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

- **Chrome access to local Veridex remains blocked (2026-11-02):** Normal
  Browser Use requests for `http://127.0.0.1:8765` are rejected by the origin
  approval gate as a saved user permission or managed-policy denial. The local
  Codex configuration now explicitly allows that origin, so the saved setting
  and effective browser authorization disagree. Stale session state or another
  policy override is possible; the cause is not established. Restarting ChatGPT
  Desktop and testing in a fresh coding chat is the next diagnostic step.
  Veridex itself restarted successfully and returned `ok: true` from `/health`;
  restarting the backend did not clear the browser denial. Live UI validation
  remains blocked. No alternate browser route was used to bypass the denial.

## Changes present; live verification still needed

- **Video room media workspace (2026-11-01):** Added gallery/list and media filters,
  browser source playback, room intake from the top toolbar, and floating Beta
  chat with attachments beside the input. Room and chat intake have separate
  scopes. Uploads use bounded streaming and reject room changes before save;
  media serving supports HTTP seeking. Focused core/server/UI checks passed,
  including HTTP 201 intake, 200/206 playback, 416 invalid ranges and ledger/scope
  checks. The final UI/media target passed 38 tests; earlier server/UI/media and
  core targets passed 100 and 19 respectively. Live visual behavior is unverified
  because browser access was declined earlier; full discovery was not repeated
  after the prior routine agent hit its usage limit. Editing/timeline remains the
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
  executable detections were checked. Live browser validation remains blocked by
  the earlier browser-origin approval denial. OBS recording/scenes and Audacity
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
