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
- Durable NDJSON chat logs stored beneath `data/workspaces/`.
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
      sessions/
        sess_.../
          session.json
          transcript.ndjson
```

Each assistant transcript entry records the provider, exact model, reasoning
effort, and task class used for that response.

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
