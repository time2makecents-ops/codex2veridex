# Standalone Codex + Veridex architecture

## Boundary

Everything required at runtime is rooted at `C:\codex2veridex`. The server binds
to `127.0.0.1` by default, serves its own static UI, writes only to its local
`data/` and `.runtime/` directories, and invokes the authenticated Codex CLI with
this repository as its working directory.

```text
Browser / Codex MCP
        |
        v
veridex_server.py :8765
        |
        +--> veridex_rooms.py --> room registry / explicit navigation
        |
        +--> veridex_governance.py --> Navigator preflight / postflight gates
        |       |
        |       +--> governance/navigator_governance_v1.0.0.json
        |
        +--> veridex_core.py --> data/workspaces/.../transcript.ndjson
        |
        +--> codex_gateway.py --> authenticated `codex exec`
```

There is one fixed local account. Workspaces contain sessions; each session owns
its transcript and one active room. New sessions start in `lobby` with the
Receptionist. This preserves the single-room
governance boundary without requiring onboarding or account discovery.

## Request lifecycle

1. The user submits a message in a workspace session.
2. The server saves the user message immediately.
3. The deterministic room router handles explicit navigation and room-directory
   requests without a model call.
4. Explicit Google requests run through the dedicated repository-local Chrome
   profile, inspect up to three top sources, and attach bounded Google/source
   evidence; failure returns locally and never substitutes another provider.
5. Other requests receive a deterministic task class.
6. The gateway maps that class to a Codex model and reasoning effort.
7. An ephemeral `codex exec` process receives the governed prompt, room registry,
   recent transcript context, and the launcher's configured access mode.
8. For generated media or documents, the server validates and imports staged outputs into the
   active session, then records path, size, SHA-256, and artifact number.
9. Navigator postflight rejects unsupported operational, file-creation,
   search-provider, and stale-upcoming claims.
10. The server saves the answer and exact route/artifact metadata to `transcript.ndjson`.
11. The UI shows the current route, route-change notice, and verified artifact previews.

## Room state

`veridex_rooms.py` is the standalone authoritative registry. The browser room
selector, `/api/rooms`, natural-language navigation, and local tool bridge all
use the same validated `VeridexStore.set_room` transition. Only commands with
explicit navigation intent can change the active room; mentioning another room
as a topic cannot move the session. The new room and its default persona are
written to that session's `session.json`.

## Navigator governance

The committed governance snapshot is the standalone runtime authority. Its
SHA-256 is calculated when loaded and returned through state, HTTP, and MCP
status surfaces. Office-App paths are provenance only and are never runtime
dependencies.

Navigator preflight handles governance questions, persistence scope, explicit
SAVE authorization, unsupported canon mutation, and governed model-route
validation before Codex runs. Postflight checks operational claims against
completed Codex evidence. File creation has a stronger evidence contract:
unrelated tool calls do not count, and completion requires a validated local
file, exact canonical path, nonzero size, SHA-256 checksum, and numbered ledger
entry. A violation suppresses the candidate response and saves a separate
Navigator hard-stop entry when the candidate falsely claimed completion.

Each workspace owns `governance_state.json`, `artifact_ledger.ndjson`, `governance_memos.ndjson`, and an
append-only `governance_incidents.ndjson`. A session may temporarily own
`pending_governance.json` while waiting for a gate resolution.

## File and computer access

Browser attachments are saved inside the active session directory, recorded in
`files.json`, and passed to Codex by verified local path. Image attachments also
use Codex's native `--image` input flag.

Generated files follow a separate output path. Before invocation, Veridex
creates `generated_staging/<message-id>/` inside the active session and gives
that exact directory to Codex. After invocation, Veridex accepts only valid
PNG, JPEG, GIF, WebP, PDF, DOCX, TXT, or Markdown files from that directory, imports them into canonical
session `files/`, hashes and ledgers them, and exposes them through a
session/file-ID-validated content endpoint. The transcript stores the canonical
path rather than relying on Codex's temporary generated-image location.

Resume Studio is a native HR Department subsystem. Workspace career profiles
and application projects are versioned under `resume_studio/` and persist only
after explicit UI/tool confirmation. The high-reasoning route returns a
normalized application document; deterministic renderers create DOCX, PDF, and
plain-text versions, reopen them, verify readable text and PDF page bounds, and
then register them as HR room artifacts. Suggested facts remain separate
unconfirmed claims and block export until the user resolves them.

The Museum's Antiques cases keep revisioned reports beneath the workspace boundary and
append normalized price observations to a per-case NDJSON ledger. A deterministic
normalizer accepts only bounded records tied to source evidence captured in the same
research run, separates exact-item candidates from exact model/edition matches and
similar comparables, and prevents asking prices or estimates from affecting expected
resale. Case JSON stores the latest derived summary while the observation ledger remains
append-only and deduplicated by source listing, source URL, or a stable fallback
fingerprint.

`price_search_controller.py` is the provider-neutral scope and execution boundary for
saved-case price rechecks. It validates exact versus explicitly approved all-likeness
scope, owns Fast/Standard/Extended budgets, runs exact before similar, deduplicates and
orders candidates, and exposes cooperative background-job progress and cancellation.
`veridex_server.py` supplies the browser-search and evidence-classification adapters;
only completed, non-timeout source-bound observations are handed back to the Antiques
case/ledger abstraction. Price-only rechecks do not transmit case photographs.

Art Studio is a native Art Department subsystem. `art_studio.py` owns a small
provider registry, free-model allowlists, asynchronous job state, deterministic
finishing operations, and versioned project JSON. Cloudflare Workers AI is the
primary image provider; only transient or quota failures may fall through to
the allowlisted Pollinations free models. When Auto has no usable optional
provider, the server uses the same ChatGPT-authenticated Codex image route as
Art Department chat; that route requires Full computer access so the result can
enter Veridex's verified artifact handoff. Explicit provider choices, policy
rejection, malformed input, and cancellation never trigger provider substitution.

Provider bytes are not exposed directly to the browser. The server decodes and
reopens each image, applies byte and pixel limits, then saves it through the
same generated-image path used by governed chat. Artifact metadata records the
provider, model, operation, prompt, seed, dimensions, project, and parent image
IDs. Local finishing uses Pillow and optional rembg/Real-ESRGAN capability
adapters; every transformation produces a derived artifact rather than changing
its source.

The launcher has two explicit modes:

- Default: `--sandbox danger-full-access --ask-for-approval never`.
- `-ReadOnly`: `--sandbox read-only --ask-for-approval never`.

The legacy `-FullAccess` switch remains accepted as an explicit spelling of the
default mode.

The server reports the active mode to the UI. In full mode, the governed prompt
allows normal local shell inspection and file work within the user's requested
scope. It still requires tool evidence before the assistant claims a file was
found or changed.

## Browser search boundary

`google_chrome_search.js` launches Chrome with a dedicated user-data directory
under ignored Veridex `data/`, a loopback-only debugging endpoint, and no access
to the user's normal Chrome profile. Login is manual and remains in Chrome's
profile storage; Veridex source and environment configuration contain no Google
password. `google_chrome_search.py` detects explicit Google intent, extracts the
query, and returns bounded visible-result text and links to the server.

The server supplies that evidence to Codex as governed data and adds a completed
`google_browser_search` evidence record. Navigator's provider gate requires that
record for explicit Google requests and rejects generic `web_search` evidence as
a substitution. Search synthesis also receives the current local date; postflight
rejects past written, slash-formatted, or ISO dates inside an upcoming section.
For that specific failure, the request pipeline performs one bounded rewrite
using the same governed evidence. Navigator records a visible correction and
delivers the repaired answer when it passes; a second failure becomes a hard
stop only when no governed Google evidence can be preserved. For a completed
explicit Google search, a second date-classification failure returns bounded,
clearly unclassified source excerpts. Past events are evidence, not violations;
only falsely labeling them as upcoming violates the gate.

Google continuity is session-scoped and bounded to recent messages. An explicit
Google request establishes the provider and subject; `again`, `the results`, or
a search-oriented follow-up with matching subject tokens reuses that subject.
The query resolver appends only explicit refinements such as `upcoming shows`.
This prevents conversational filler from becoming a query and keeps related
follow-ups on the dedicated Google profile without making Google a global
default for unrelated searches.

Explicit Google requests use the `search_deep` route (`gpt-5.6-sol`, high). The
Chrome bridge records bounded result text, links, and up to three opened-source
records with `completed`, `limited`, or `failed` status. Opened page text has
higher evidentiary weight than snippets; unavailable pages do not erase useful
indexed snippets.

### Instagram browser bridge

`instagram_chrome_bridge.js` uses the same loopback-only CDP boundary with a
different ignored Chrome profile and debugging port. Its Python wrapper is an
importable program interface for status checks, bounded profile reads,
confirmation-gated follows, visible message composition, and explicit sends.
`.env.local` supplies credentials
without placing them in command arguments or repository files. Instagram
security and 2FA prompts remain visible for the user to complete. The
`office.instagram_message_send` tool does not invoke the send action unless
`confirm=true`; drafting and sending are separate bridge operations.

### Facebook browser bridge

`facebook_chrome_bridge.js` owns a separate repository-local Chrome profile and
loopback-only debugging port. It reads credentials from ignored `local.env` or
`.env.local` without putting them in command arguments or source. Its Python
wrapper exposes status, bounded profile inspection, visible message composition,
and confirmation-gated sends. Facebook security and two-factor prompts remain in
the visible Chrome window for the user to complete. Drafting never sends, and
`office.facebook_message_send` requires `confirm=true` before invoking the bridge's
send action.

### eBay seller boundary

`ebay_gateway.py` uses eBay's official OAuth and Sell APIs. Each workspace has an
independent encrypted token database beneath `integrations/` and a non-secret account
assignment in `connected_accounts.json`. Client credentials remain in ignored local
configuration; neither tokens nor secrets enter source, transcripts, tool responses,
or command arguments.

Status, inventory, offers, policies, orders, and transaction reads are non-mutating.
Listing preview performs local validation only and accepts fixed-price Inventory API
listings; auction creation is outside this integration. Publishing or withdrawing a listing,
recording shipment fulfillment, issuing a refund, or sending a seller-initiated offer
requires `confirm=true` at the gateway boundary. Successful mutation responses carry
the matching eBay identifiers; partial listing creation stops and reports the last
verified offer or listing boundary instead of claiming completion. Buyer purchases
and bids are outside this integration.

## Active request cancellation

The browser creates a unique request ID before posting a chat message. The HTTP
request registers a thread-safe cancellation event for that request and passes
it into both the Chrome bridge wrapper and Codex gateway. `/api/chat/cancel`
sets only that event. A cancellable subprocess is terminated, the active request
is unregistered in `finally`, and the transcript receives a deterministic
`Stopped by you.` entry. The UI keeps the original chat request open until this
acknowledgment arrives, so cancellation persistence is not a client-only visual.

## Personal governance rules

The child Codex process ignores repository/user configuration to prevent MCP
recursion, so the gateway embeds the governing rules directly:

- one active room, with no implicit navigation;
- Veridex owns persistence, state, and authorization;
- no claims of searches, saves, edits, sends, or execution without evidence;
- no file-creation claim without a verified path, size, checksum, and artifact number;
- no claims of durable memory without a saved transcript or governed path;
- direct answers with uncertainty stated instead of invented results.

The child process is ephemeral and cannot pause for approval. Its filesystem
mode is full by default; `-ReadOnly` opts a launcher run into read-only access.
Veridex, not the Codex thread, owns conversation continuity.

## Administrative control plane

`veridex_admin.py` owns a global versioned room catalog, active governance
snapshot, proposal records, backups, and an append-only audit log. Infrastructure
creates room and path-bounded program proposals; Navigator validates and owns
rule and gate proposals. Applying a proposal requires its ID, preview version,
and explicit confirmation. Governance amendments or disables require a second
one-time confirmation token.

Room and governance applications use atomic JSON replacement with prior-version
backups. Program proposals record a repository fingerprint, become stale when
source changes before approval, and preserve approved-path backups for rollback.
Activation and application restart remain separate explicit operations.

## Billing and fallback

The primary provider is the locally authenticated Codex CLI, using the existing
ChatGPT/Codex subscription. This standalone app contains no API-provider fallback
and does not require OpenAI, Gemini, Groq, or OpenRouter API keys. A Codex failure
is shown to the user rather than silently switching to a paid API.
