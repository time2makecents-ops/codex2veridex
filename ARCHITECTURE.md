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
4. Other requests receive a deterministic task class.
5. The gateway maps that class to a Codex model and reasoning effort.
6. An ephemeral `codex exec` process receives the governed prompt, room registry,
   recent transcript context, and the launcher's configured access mode.
7. The server saves the answer and exact route metadata to `transcript.ndjson`.
8. The UI shows the current route and a persistent route-change notice.

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
captured Codex command evidence. A violation suppresses the candidate response
and saves a separate Navigator hard-stop entry.

Each workspace owns `governance_state.json`, `artifact_ledger.ndjson`, `governance_memos.ndjson`, and an
append-only `governance_incidents.ndjson`. A session may temporarily own
`pending_governance.json` while waiting for a gate resolution.

## File and computer access

Browser attachments are saved inside the active session directory, recorded in
`files.json`, and passed to Codex by verified local path. Image attachments also
use Codex's native `--image` input flag.

The launcher has two explicit modes:

- Default: `--sandbox read-only --ask-for-approval never`.
- `-FullAccess`: `--sandbox danger-full-access --ask-for-approval never`.

The server reports the active mode to the UI. In full mode, the governed prompt
allows normal local shell inspection and file work within the user's requested
scope. It still requires tool evidence before the assistant claims a file was
found or changed.

## Personal governance rules

The child Codex process ignores repository/user configuration to prevent MCP
recursion, so the gateway embeds the governing rules directly:

- one active room, with no implicit navigation;
- Veridex owns persistence, state, and authorization;
- no claims of searches, saves, edits, sends, or execution without evidence;
- no claims of durable memory without a saved transcript or governed path;
- direct answers with uncertainty stated instead of invented results.

The child process is ephemeral and cannot pause for approval. Its filesystem
mode is read-only by default and full only after the explicit `-FullAccess`
launch option. Veridex, not the Codex thread, owns conversation continuity.

## Billing and fallback

The primary provider is the locally authenticated Codex CLI, using the existing
ChatGPT/Codex subscription. This standalone app contains no API-provider fallback
and does not require OpenAI, Gemini, Groq, or OpenRouter API keys. A Codex failure
is shown to the user rather than silently switching to a paid API.
