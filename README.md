# Codex + Veridex standalone

This repository is a self-contained, single-user Veridex chat application that
uses the locally authenticated Codex CLI. It does not require an OpenAI API key
and does not read from or write to `C:\Office-App`.

## What is included

- A local web UI with no login screen.
- Automatic task routing to Codex models and reasoning levels.
- A visible status strip whenever the model is selected or changed.
- Multiple workspaces and sessions under one local account.
- Every new workspace and session starts in the Lobby with the Receptionist.
- A visible room selector and explicit natural-language room navigation.
- An always-visible Navigator monitor backed by deterministic hard gates.
- Durable NDJSON chat logs stored beneath `data/workspaces/`.
- Session-scoped file attachments saved beside each session transcript.
- A Codex MCP bridge for governed requests from an interactive Codex session.
- Independent start, stop, restart, and status commands.

No workspace data, chat logs, secrets, or user accounts are copied from another
application. The first launch creates a fresh local account and workspace.

## Run

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\codex2veridex\veridex.ps1 start
```

The browser opens at <http://127.0.0.1:8765>. Other commands are:

```powershell
.\veridex.ps1 status
.\veridex.ps1 restart
.\veridex.ps1 stop
```

To let Veridex use Codex's normal local shell tools across the computer, start
it explicitly in full-access mode:

```powershell
.\veridex.ps1 restart -FullAccess
```

The page always displays either `Read-only computer access` or
`Full computer access` beneath the current room. Full access uses Codex's
documented `danger-full-access` sandbox with approvals set to `never`. This lets
Codex actually search and work with local files; only enable it when you intend
to give the chat that authority. A normal `restart` returns to read-only mode.

Requirements: Python 3 and a working `codex` command authenticated through the
Codex desktop app/CLI. The runtime uses Python's standard library only.

## Storage

The application creates this local structure, which Git ignores:

```text
data/
  account.json
  workspaces/
    ws_.../
      workspace.json
      governance_state.json
      governance_incidents.ndjson
      artifact_ledger.ndjson
      governance_memos.ndjson
      sessions/
        sess_.../
          session.json
          transcript.ndjson
          files.json
          files/
```

Each assistant transcript entry records the provider, exact model, reasoning
effort, and task class used for that response.

Use the `+` button beside the composer to add files. Uploaded files are copied
into the active session's `files/` directory and selected for the next message.
They remain available in that session and can be selected again later.
Uploaded files enter the workspace's numbered artifact ledger before analysis.

## Navigator governance

Navigator is active in every room. The header badge opens a panel showing the
exact rule source, snapshot version and SHA-256 hash, provenance, active gates,
and latest incident. The standalone runtime reads its rules from:

```text
C:\codex2veridex\governance\navigator_governance_v1.0.0.json
```

The snapshot is self-contained; Veridex does not read or modify `C:\Office-App`
at runtime. Attempted hard-rule breaches are blocked with a separate Navigator
message and appended to the workspace's `governance_incidents.ndjson` when an
actual attempted breach needs debugging.

Persistent preferences use a two-step governed flow: choose `persistent`, then
reply exactly `SAVE`. Veridex records the approved text in the workspace's
`governance_memos.ndjson` and reports local GOV-SAVE separately from unverified
ChatGPT product memory.

See [DEVELOPMENT_MODEL_POLICY.md](DEVELOPMENT_MODEL_POLICY.md) for the separate
personal model-switch protocol used while coding Veridex in this Codex terminal.

## Rooms

Choose a room from the selector beneath the session title, or type an explicit
command such as `go to Art Department`. Commands such as `list rooms`, `list
room controls`, and `can you list available rooms?` return the authoritative
directory. Room navigation and directory requests are handled deterministically
by Veridex before Codex is called, and every session still has exactly one
active room.

## Model routing

| Task | Default model | Reasoning |
| --- | --- | --- |
| Coding, debugging | `gpt-5.6-sol` | high |
| Architecture, planning | `gpt-5.6-sol` | high |
| Image/video reasoning | `gpt-5.6-sol` | high |
| High-stakes topics | `gpt-5.6-sol` | xhigh |
| Search/general chat | `gpt-5.6-terra` | medium |
| UI checks and simple testing | `gpt-5.6-luna` | low |
| Greetings and trivial requests | `gpt-5.6-luna` | low |
| Room navigation and room directory | deterministic Veridex router | none |

Routing is automatic. Prompt text cannot directly select an arbitrary model.
Overrides are available in `.env.example`.

## Codex MCP bridge

The included config snippet points Codex at `veridex_mcp.py`. Calling
`veridex_activate` starts this standalone server when needed and automatically
uses the default local session if no session ID is configured.

## Test

```powershell
python -m unittest discover -v
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the governance and persistence
boundaries.
