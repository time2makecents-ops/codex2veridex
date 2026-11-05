# Veridex Browser Companion 0.1.2

This is a locally loadable Manifest V3 prototype. It is not installed merely
because these files exist. Use only the dedicated Veridex Chrome profile.

It provides explicit tab selection, bounded page observations and reviewed
navigate/click/fill operations. Page text is untrusted evidence. Credentials,
payment and verification-code fields require manual entry. Cross-origin frames,
browser-internal pages and interactions requiring trusted CDP input are outside
this version. Keep the existing Lens and provider-specific CDP adapters.

## Prepare and review

From the Veridex checkout:

```powershell
.\.venv\Scripts\python.exe scripts\prepare_browser_extension.py
```

This creates ignored, machine-local native-host settings and a manifest under
`.runtime/browser-extension`. The token stays there, never in the extension,
source files, screenshots, command arguments or shared documentation. The
extension's fixed ID is `agigaaikljlfallmmpechfbfckbhagbe`; its manifest contains
only a public key. The private generation key was not retained.

Review the source package and native manifest. After explicit installation
approval, register the per-user native host:

```powershell
.\.venv\Scripts\python.exe scripts\prepare_browser_extension.py --register
```

The helper refuses to replace another registration or differing prepared files.
It uses the existing Veridex loopback service; no port is allocated. Restart the
backend only after approval so the new broker routes are available. A live
backend running older source will not have these tools yet.

The operator must open `chrome://extensions` in the dedicated profile, review
Developer mode and Load unpacked, then select this directory. Those steps grant
browser access and are deliberately not automated. Installation is local; no
Chrome Web Store publication or Google Cloud billing is needed.

## Select a tab and use it

1. On first setup, call `browser.status` in Veridex/Codex to obtain the workspace
   and session identifiers. Existing MCP clients use `veridex_call` with
   `tool: "browser.status"` and the active session context.
2. Open the intended HTTP(S) tab and the extension popup. Enter the workspace and
   session once, then choose **Use this tab**. The backend resolves and pins the
   session's current active room in response to this explicit selection; no room
   identifier needs typing and no Veridex room is changed. Internal Chrome New
   Tab/settings pages are unsupported. Chrome does not expose a trustworthy profile-name
   API here: the operator must verify the dedicated profile. The bridge does not
   claim automatic account/profile verification.
   Workspace/session preferences are remembered in this profile's local extension
   storage and prefilled after popup or browser restart. Connection settings
   collapse after setup; Use this tab stays visible. Saved preferences do not
   grant tab access or restore authorization after a browser restart. Change the
   saved workspace/session only when intentionally selecting a different context.
   If Veridex changes rooms, select the tab again to explicitly bind that room.
3. Call `browser.read` with an `intent` describing the authorized task. The
   response contains a request ID. Poll `browser.status` with that ID for the
   result; a queued request is not completed work.
4. Click/fill requests must reference the `document_id`, `snapshot_id` and
   `target_id` from the latest observation. Supply `text` for fill. For clicks,
   supply `expect_text` or `expect_url` to verify the intended outcome.
5. Every navigate/click/fill request appears in the popup with its intent,
   selected URL, scope, target description and any field text. Review and approve
   the exact action, or decline it. A destination-site permission is requested
   only from the user's approval click when navigating to a new origin.
6. Use `browser.stop` with the request ID to stop pending work. Already dispatched
   work cannot be undone: cancellation, disconnection or expiry after dispatch
   returns `outcome_unknown`. Never automatically repeat it.

Example arguments to `veridex_call` (use real IDs from your active session):

```json
{"tool":"browser.read","arguments":{"intent":"Read the selected page for my current task"}}
```

Public tools are `browser.status`, `browser.read`, `browser.navigate`,
`browser.click`, `browser.fill`, and `browser.stop`. They use existing `/call`
governance and the existing MCP envelope. The additive native relay endpoint is
`POST /api/browser-extension/relay`; it requires its separate local bearer token,
loopback peer and no browser Origin header.

Undelivered requests expire after two minutes. Once a mutation is offered for
local review, approval has a ten-minute window while the selected connection and
scope remain valid. Execution has a separate two-minute deadline after approval.
Expired work is not automatically retried. Missing heartbeats invalidate offered work
after twelve seconds. Reconnection never replays offered or running actions.
Unclaimed approval proposals can be shown again on the same connection after the
popup queue is cleared or a tab is reselected. This does not renew their deadline
or execute an action: only one locally approved claim can transition to running.
Results are bounded and held in memory; restart clears them. The append-only
browser audit records scope, request IDs, action, status and time, without page
text, URLs, target labels or filled values. Navigator runs before queueing and
again before execution, and checks returned evidence.

The DOM-based click is not trusted browser input. A click without observed
expected state is `limited`; it is not advertised as success. Chrome's existing
automation host, account sign-in, permission policies and screenshots are separate
systems and are not repaired by this extension.

## Verification boundaries

Python tests exercise scoped broker behavior, Navigator/access restrictions,
native message framing, HTTP relay authentication, and an actual MCP → HTTP →
native-host subprocess → broker round trip using a synthetic server.

The isolated Chrome test exercises DOM operations, stale observations, fixed
extension identity, worker scripting and popup accessibility. Its test-only
manifest grants only the synthetic `https://fixture.test/*` origin. Production
permissions are not changed. A mocked relay is used inside the browser test;
native stdio is independently tested by Python.

The browser test removes Native Messaging permission from its copied test-only
manifest so an isolated test cannot attach to an already registered production
host. Its mocked relay also checks automatic room acknowledgment; the real HTTP/
stdio test separately exercises both rejected legacy room IDs and successful
binding without a caller-supplied room.

Only one selected native connection owns the broker at a time. Idle connectors
cannot displace it or refresh its heartbeat. A competing selected connector gets
an actionable error; an expired connection's work is never replayed.

Live basic acceptance completed on 2026-11-05: the installed native connection
read the local fixture, displayed a fill proposal, and completed the fill only
after the operator approved it. The field value was independently observed in
Chrome; audit metadata recorded one execution claim and one completion. No form
was submitted. This verifies the existing client/HTTP/native-extension path for
read and approved fill. Live navigation/click, trusted-input workflows, real
account operations and automatic natural-language chat routing are separate
acceptance work; do not infer them from this local test.
