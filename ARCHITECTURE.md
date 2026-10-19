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

Video Production uses the same governed room and room-file abstractions. Beta's
room-specific prompt covers production planning and post-production while keeping
planned edits separate from execution-backed, artifact-verified renders or exports.

Animation Studio is a separate Beta-directed room so reusable animation assets and
voice-performance work do not blur into final editing and delivery. Its workspace
project records use atomic JSON replacement after an explicit SAVE. Local tool
availability is detected rather than assumed. Rhubarb consumes only a ledgered
session audio path; unsupported native inputs are copied through FFmpeg to an
ephemeral mono analysis WAV without modifying the source. The validated cue
artifact includes its recognizer, optional G/H/X shape set, and sanitized
character-rig binding, then follows the existing room-scoped file and
artifact-ledger path. Animation Studio exports one bounded Synfig shot package
with copied source media, placement metadata, audio timing, and lip-sync cues.
Imported Synfig renders are ledgered and linked to the storyboard shot only after
the user selects the render; final assembly remains in Video Production.

Animation project JSON stores references to ledgered source images and audio,
not duplicate binary payloads. Explicit project saves preserve the prior JSON
as a read-only version snapshot before atomically replacing the current project;
the UI can inspect or restore those snapshots without changing the canonical
project identity. Image placement, storyboard order and notes,
non-destructive audio-track settings, mouth-rig mappings, and bound lip-sync
takes and imported shot renders are versioned with the project. Mouth rigs persist independent jaw width,
vertical scale, position, and anchor percentages so a sprite can be pinned to its hinge
without changing its ledgered source image. They also carry reusable stage-placement X, Y,
width, and preset values; individual shots may override that starting position. A persisted placement-calibrated flag is reset
when the base, mouth mapping, or geometry changes, and cue generation is blocked until the
operator confirms the composite visually. Browser playback drives only the preview:
it selects the cue active at the audio element's current time and swaps the
referenced mouth image. GIMP and Audacity launches are allowlisted, path-bound
to a resolved session file, and require explicit confirmation; neither editor
is treated as completing or reimporting an artifact automatically. Synfig image
launches first create and ledger a valid `.sif` starter document that references
the source image, then open that document rather than passing the raster file as
an XML project.

Mouth rigs support an explicit limited-animation jaw-flap mode in addition to
phoneme-image swapping. Jaw-flap mode renders one registered closed-jaw artifact and
maps Rhubarb cues to bounded vertical opening amounts while preserving the master
hinge and placement. A persisted, bounded per-rig opening-strength percentage scales
only those amounts; it does not alter cue timing or invalidate calibrated geometry.
Existing projects may retain bounded `manual_jaw_corrections` and manual jaw-opening
segments for schema compatibility, but browser playback does not activate the waveform or
manual-performance layer. The operator-facing preview is deliberately limited to the native
audio control, the automatic cue track, and the calibrated character/jaw composite. This
keeps preview timing independent from waveform decoding and preserves the earlier Synfig
handoff workflow. A lightweight jaw follower reads the native audio element's current time;
it does not maintain an independent timeline or alter the audio. Both the bound dialogue
track preview and Voice Performance player can own that follower, with mutual exclusion so
only one audio element can drive the take at a time.

The iPhone media manager is intentionally a separate loopback-only utility rather
than a Veridex room or a bypass into workspace artifacts. Its SQLite manifest owns
source locators, user dispositions, resumable jobs, immutable archive hashes,
Google Drive verification evidence, transcript versions, and append-only events.
The Windows portable-device bridge is restricted to inventoried DCIM paths. Local
and remote copies are reverified before a short-lived deletion preview can be used;
unsupported device deletion is recorded as guided rather than completed. Optional
transcription consumes only already verified archive paths and cannot affect copy or
deletion eligibility.

Item Intake is a separate browser surface served by the Veridex host at
`/item-intake`, so it inherits the same loopback default and remote-session
authorization. The optional `lan` launcher mode binds the same host to private local
network adapters, still requires a one-time pairing URL, and opens Windows Firewall only
for TCP 8765 on Private networks. Its pairing cookie is intentionally allowed over
private-LAN HTTP, so Tailscale HTTPS remains the recommended remote path. Its local
SQLite catalog under `data/seller_intake/` is authoritative for batches, item records,
assets, source-linked evidence notes, and handoffs. Each item also has an atomically
written `item.json` snapshot and contained source folders inside its batch. Uploads
are stored unchanged and are not analyzed automatically. A handoff explicitly copies
the selected files and a source-linked brief into a Veridex session through the normal
artifact-ledger path; it cannot imply research, marketplace preparation, or publish.
An item may retain validated `https://chatgpt.com/share/...` and
`https://g.co/gemini/share/...` thread links as local references. The URLs are included
in its SQLite row, item snapshot, batch export, and controlled handoff brief. A
user-triggered PC Inbox preview may read a public shared thread through the dedicated
Chrome boundary; a second reviewed action saves only its visible text and available
visible images. The backend never imports automatically or gains ChatGPT credentials.

The Capture Companion is a separate lightweight LAN service on port 8775 that shares
the same catalog but exposes only raw phone capture: title, notes, image uploads, and
shared-thread references. Reference IDs and other catalog fields remain in the PC's
collapsed Advanced details area. It accepts the same paired-device cookie as Veridex on the
same host, so no ChatGPT, Gemini, or Veridex credentials leave the PC. Phone-side removal
archives an item instead of destroying its catalog record or original files. A separate
typed-confirmation delete route permanently removes one item, its catalog rows, and its
contained source folder; the full
Veridex application on port 8765 retains workspace/session management and PC review.
Both browser surfaces request the rear camera only on an explicit Camera or Close-up
tap. They turn the resulting frame into a JPEG in the browser and use the existing
photo-upload route; Close-up applies a camera zoom constraint only if that capability
is exposed by the browser and otherwise reports the limitation without claiming macro
control. A plain private-LAN HTTP phone session can fall back to the native
`capture="environment"` file-input flow when browser live-camera access is unavailable.
The PC Item Intake photo editor keeps originals immutable: manual crop, local automatic
edge-contrast crop, and local automatic adjustment each create a separate JPEG under
the item's `derivatives` folder. The catalog records the source asset ID and a bounded
transformation record, and refuses to delete a source while derivative photos remain.
Its AI touch-up requires an explicit confirmation immediately before transmitting the
chosen source photo and prompt to the user-selected Codex image-tools or configured
Cloudflare reference-edit provider; there is no provider fallback. AI output follows
the same derived-photo lineage path.

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

Connected services have two explicit scopes. Instagram, eBay, and optional
workspace Gmail assignments remain isolated beneath one workspace. The Veridex
corporate Gmail token store beneath `data/integrations/` is shared across all
workspaces and is selected only by a corporate/shared account request or as the
fallback when the active workspace has no assigned Gmail. Gmail results and
confirmed sends retain the selected scope and account identity in evidence.
Gmail OAuth authorization opens in the same dedicated Veridex Google Chrome
profile used by the browser-search boundary; it never relies on the user's
ordinary default Chrome profile, and the callback still validates OAuth state
and the configured account identity before storing tokens.
This shared-services boundary is the extension point for future corporate
services such as Google Drive; no unavailable service is inferred from a Google
login alone.

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

The Museum multi-item selector submits one authorized source attachment plus bounded,
normalized rectangular regions. The server revalidates the regions against the
EXIF-corrected source dimensions, creates each crop through the normal generated-file
artifact path, and records source file ID, batch/selection IDs, normalized and pixel
bounds, size, and SHA-256. Batch research runs sequentially through the shared browser
profile and creates one case per crop. Google Lens receives only the sanitized crop;
the original remains a local case attachment. Consent is evaluated once before the
batch unless Museum shopping mode is active, while partial failures and cancellation
retain truthful per-item outcomes and any cases already completed.

Each case JSON also contains a versioned `research_record`: the canonical bounded view
of item identity, provenance summaries, correspondence references, attachments, derived
evidence artifacts, source references, and linked price-observation IDs. Each case
revision snapshots that record. Partial research or price-only revisions merge new
nonempty facts into the prior record so omitted identity fields are not silently lost.
The record stores correspondence summaries and source references, not email bodies or
credentials. Artist and gallery folders are supporting human-readable research views;
they are not a second runtime authority.

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

The Lens adapter opens Google's search-by-image panel with a trusted CDP mouse event;
Google's current control ignores a page-script `click()`. A Lens result is admissible
only when the bridge reports `completed`; `limited`, `blocked`, and `failed` responses
are errors rather than source evidence. Museum quick research then either uses the Lens
candidates and one bounded synthesis call, or stops after one bounded visual fallback
with a limited result. It does not fan out to broader searches or valuation after a
Lens failure.

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
send action. The Connected accounts surface exposes status and login controls for
this repository-local profile without returning its password. Session detection waits
through Facebook redirects and accepts either authenticated navigation UI or the
authenticated home route while continuing to reject login and checkpoint pages.

`facebook_marketplace.py` stores atomic workspace-scoped listing drafts and approved
group URLs beneath the workspace integration directory, with append-only transition
audit records. Draft photos are artifact-ledger IDs; the server rechecks workspace
containment, nonzero size, and SHA-256 before every browser handoff. The bridge may
upload those verified files and fill Marketplace or group-composer fields, but it has
no route that activates Marketplace Next/Publish or a group Post control. A draft can
become `published_observed` only when the dedicated profile exposes a matching listing
URL on the seller's visible listings page. Group preparation requires that evidence and
an allowlisted group selected on the draft. Local pickup uses Facebook's existing
location rather than persisting an address in Veridex.

### eBay seller boundary

`ebay_gateway.py` uses eBay's official OAuth and Sell APIs. Each workspace has an
independent encrypted token database beneath `integrations/` and a non-secret account
assignment in `connected_accounts.json`. Client credentials remain in ignored local
configuration; neither tokens nor secrets enter source, transcripts, tool responses,
or command arguments.

OAuth opens in the explicitly configured Chrome profile for the assigned workspace.
For production, the eBay RuName accepted route terminates at the Cloudflare Worker,
which preserves the one-time authorization response and forwards it to the local
loopback listener. The listener still validates the OAuth state before exchanging the
code, so the public relay does not replace the local anti-forgery boundary.

Status, inventory, offers, policies, orders, and transaction reads are non-mutating.
Listing preview performs local validation only and accepts fixed-price Inventory API
listings; auction creation is outside this integration. Publishing or withdrawing a listing,
recording shipment fulfillment, issuing a refund, or sending a seller-initiated offer
requires `confirm=true` at the gateway boundary. Successful mutation responses carry
the matching eBay identifiers; partial listing creation stops and reports the last
verified offer or listing boundary instead of claiming completion. Buyer purchases
and bids are outside this integration.

The production notification Worker verifies eBay ECC signatures before placing events
in a workspace-bound D1 queue. `ebay_notifications.py` consumes that queue with a
separate bearer secret and requires the Worker's configured workspace identifier to
match the active Veridex workspace exactly. Each notification is committed to the
workspace-local `integrations/ebay_notifications.db` before the remote acknowledgement
is sent; notification IDs make a crash between those steps safe to replay. The Worker
deletes acknowledged copies and its scheduled cleanup expires unclaimed copies after
seven days.

`EbayNotificationPoller` starts and stops with the standalone server. It discovers only
workspaces with an explicit eBay assignment, runs an immediate check at startup, then
checks at the configured interval. A process-wide lock keyed by the workspace notification
database serializes background and operator-triggered syncs. One workspace failure is
recorded in poller status without stopping checks for other workspaces.
The workspace's connected-account record stores its automatic-check preference. Disabled
workspaces are omitted from poller discovery but retain manual queue access; enabling a
workspace wakes the running poller without a service restart.

Marketplace Account Deletion payloads are minimized at ingestion: local storage keeps
the notification ID, topic, timestamps, payload digest, and non-identifying processing
disposition, but not the raw deletion payload. Other verified seller events retain a
bounded display summary and payload digest rather than the raw webhook body.
`ORDER_CONFIRMATION` is mapped to a sold alert, while `BUYER_QUESTION` and `NEW_MESSAGE`
are mapped to message alerts.
A working consumer is not evidence that those seller topics are subscribed; topic
registration and an observed delivery remain separate provider evidence.

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
