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
3. Deterministic text classification selects a task class.
4. The gateway maps that class to a Codex model and reasoning effort.
5. An ephemeral, read-only `codex exec` process receives the governed prompt and
   recent transcript context.
6. The server saves the answer and exact route metadata to `transcript.ndjson`.
7. The UI shows the current route and a persistent model-change notice.

## Personal governance rules

The child Codex process ignores repository/user configuration to prevent MCP
recursion, so the gateway embeds the governing rules directly:

- one active room, with no implicit navigation;
- Veridex owns persistence, state, and authorization;
- no claims of searches, saves, edits, sends, or execution without evidence;
- no claims of durable memory without a saved transcript or governed path;
- direct answers with uncertainty stated instead of invented results.

The child process is ephemeral, read-only, and cannot approve actions. Veridex,
not the Codex thread, owns conversation continuity.

## Billing and fallback

The primary provider is the locally authenticated Codex CLI, using the existing
ChatGPT/Codex subscription. This standalone app contains no API-provider fallback
and does not require OpenAI, Gemini, Groq, or OpenRouter API keys. A Codex failure
is shown to the user rather than silently switching to a paid API.
