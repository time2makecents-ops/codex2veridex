# Google resources and Chrome companion continuation

Updated 2026-11-05. Shared personal setup version 1.1.0.

## Development checkout

Continue extension development on `codex/chrome-companion`, a separate worktree
based on `6600f1b`. Use `git worktree list` to find its machine-local path. Only
the extension and supporting browser-tooling changes were copied; unrelated room
definition edits, the other terminal's website-toolkit notes and its screenshot
were excluded. The copied tracked patch and new-file hashes were verified, and
all 39 focused extension/MCP checks passed from this worktree.

The running backend, registered native host and unpacked Chrome extension still
use the original checkout. Its extension changes were deliberately retained to
keep that installation working. Do not start a second backend, copy credentials,
or remove those live originals without an intentional installation migration.
Use Git history/status for the feature commit state. The original live copy
still has its working changes. No push was requested or performed.

## Outcome and accepted decisions

User requested useful free Google resources for Full Circle first, a later
toolkit shortlist, investigation of repeated agent-to-Chrome connection failures,
and a Veridex extension supporting page reading and approved actions for both
Veridex and Codex. The user approved implementing the proposed plan.

Website remains on existing IONOS hosting. No paid provider, API-credit usage,
billing change, new service port or automatic account/profile switching.
Another terminal owns the OpenAI resource work; its files/commit were preserved.

## Implemented

- `browser_extension.py`, `chrome_native_host.py`, `chrome_extension/`: scoped,
  bounded broker, native relay, tab-selection popup and approved DOM actions.
- Additive server tool catalog/dispatch and authenticated relay route; existing
  MCP `veridex_call` is unchanged. Navigator checks and audit metadata are explicit.
- Preparation, resource download/extraction, diagnostics, packaging and isolated
  QA scripts under `scripts/`. Prepared native settings are ignored/local only;
  no secrets appear in the extension or shared notes. Host registration was later
  explicitly approved and completed; Chrome loading remains manual/pending.
- Google resources and manifests in the operator's Documents/FullCircle/resources/
  google folder. WebP 1.6.0, Chrome for Testing 157.0.8103.38 and pinned official
  troubleshooting references downloaded and verified. See
  [GOOGLE_BROWSER_RESOURCES.md](../GOOGLE_BROWSER_RESOURCES.md).

## Verified

- Latest live acceptance (2026-11-05): selected-page read and user-approved fill
  completed through the installed client/HTTP/native-extension path. The local
  Test note contained the synthetic test value, independently confirmed through
  Chrome's accessibility state. The result reported completed/effect_verified;
  audit metadata recorded exactly one running claim and one completion. Nothing
  was submitted or persisted by the fixture. Basic live acceptance is complete.

- Live read succeeded on the selected local fixture through the normal client/
  HTTP/native extension path. The first fill approval expired unexecuted after
  two minutes. Approval proposals now have ten minutes after delivery while
  heartbeat and scope remain valid; delivery/execution remain separately bounded.
  A regression reproduced missing re-delivery after popup queue loss. The broker
  now repeats unclaimed mutation proposals only to the same connection/scope/tab,
  without extending expiry or allowing duplicate execution claims. Latest focused
  checks: 39 passed. Full 550-test result below precedes these narrow corrections.
  During acceptance the session moved from Lobby to Marketing and the backend
  process restarted, invalidating the old scoped/in-memory request. Audit metadata
  for that request showed queued/offered only, not execution. Queue fix deployed
  by supported backend restart; no extension reload is needed for this correction.

- Latest correction (2026-11-05): a manually entered `Art_Room` did not match the
  actual active-room ID, and the old native host hid the rejection behind a generic
  message. Companion 0.1.2 now remembers workspace/session preferences and gets
  the current room from the backend only on explicit Use this tab. No room typing,
  navigation or automatic permission grant. Scope/room/ownership errors are fixed
  sanitized messages, and invalid/idle connections cannot replace a selected one.
  Verified 36 focused Python tests and 19 browser checks, zero axe violations;
  latest full suite passed 550 tests with zero failures/errors/skips. The actual
  stdio/HTTP regression also rejects the old wrong-room value before successfully
  binding a selection without a room argument. Backend restart completed.
  User must reload the extension in the dedicated profile to load this correction.

- Live loading follow-up (2026-11-05): operator reported the extension loaded.
  Actual production `browser.status` returned `connected`, with healthy backend
  and native registration present. No tab was authorized yet. Opened the benign
  local companion fixture through the existing dedicated-profile bridge; manual
  popup scope selection is pending. No live page read or mutation is claimed yet.
  Subsequent inspection found the popup over Chrome's internal New Tab page and
  the actual native-host Chrome ancestry outside the dedicated Veridex browser.
  The dedicated CDP target list had the local fixture but no companion target.
  A connected native transport therefore does not establish correct-profile
  installation. Correct the operator's profile selection before live acceptance.

- Focused Python checks: 32 passed. They include a real MCP → HTTP → native-host
  subprocess → broker/evidence round trip with synthetic state, no registration.
- Full `.venv\Scripts\python.exe -m unittest discover -v`: **545 tests**,
  zero failures, errors or skips; 98.156 seconds. Reported by bounded Luna validation.
- Isolated Chrome integration: **13 checks passed**, zero axe violations. Chrome
  157.0.8103.38 loaded the extension, checked DOM operations and stale rejection,
  fixed ID, worker scripting and popup rendering. Test-only fixture permission
  and mocked relay; native stdio is independently tested in Python.
- Installed DevTools MCP 1.12.0: real initialization/list-tools/list-pages passed,
  32 tools, isolated Chrome, statistics/CrUX/update checks disabled. No global
  client configuration was changed.
- Existing dedicated CDP bridge reported connected; the current client browser
  host/capture failures therefore are not the same as a disconnected CDP bridge.
- Python/JavaScript syntax and whitespace checks passed. Review package and
  resource manifests record actual nonzero sizes and SHA-256 hashes.
- A follow-up preparation check found CRLF/LF differences in this task's own
  generated manifest. Preparation now accepts identical text with either line
  ending without overwriting it; the 32 focused checks and actual preparation
  rerun passed after this narrow installer correction.

## Limits and next action

User explicitly approved native-host registration and backend restart after the
review. Both completed: the registry key exists, live backend health is true, all
six browser tools are exposed, and unauthorized relay access returns HTTP 401.
The operator loaded the extension and selected the local fixture. Live native
connection, selected-page read and an explicitly approved fill are verified.
Browser internal pages, cross-origin frames, trusted-input
workflows and real account operations are not verified by the prototype. Profile
identity is operator-verified, not automatically established by the extension.
The client-owned browser-host problem is not claimed fixed; exact onset and
cause remain unestablished.

Next: report the verified local read/approved-fill result. No further installation
or setup approval is pending for that path. Extend acceptance to live navigation,
click and other provider flows only when requested. Internal Chrome pages remain
unsupported. Room/session changes require an explicit new tab selection; never
retry uncertain dispatched actions. See the latest live result above rather than
the superseded pending steps preserved in the historical verification bullets.
See [installation instructions](../chrome_extension/README.md).

Extension development belongs on `codex/chrome-companion`; use Git history/status
for its commit state. No push, Cloud deployment, sign-in or shared personal policy
change was performed. Context usage is not
reported by this session; no threshold firing or armed-hook claim is made here.
