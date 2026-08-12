# Governed Codex and Veridex architecture

The integration has two deliberately separate directions.

## Codex to Veridex

`veridex_mcp.py` exposes Veridex's existing governed HTTP tools to an interactive
Codex session. Veridex remains authoritative for the selected workspace, room,
session, transcript, files, artifacts, and action permissions.

## Veridex to Codex

`codex_gateway.py` lets Veridex use the locally authenticated Codex CLI as its
primary reasoning provider. Each chat turn launches one ephemeral `codex exec`
process, sends the governed prompt through stdin, and reads the final agent
message from Codex's JSON event stream.

The child process:

- uses the user's existing Codex/ChatGPT sign-in instead of an OpenAI API key;
- is read-only and cannot approve actions;
- ignores user config, repository rules, and MCP registration to prevent a
  Veridex-to-Codex-to-Veridex recursion loop;
- does not persist its Codex thread; Veridex persists the conversation instead.

The gateway explicitly embeds the personal Veridex rules for one active room,
no implicit navigation, Navigator authority, tool-truth claims, and governed
persistence. These rules therefore still apply even though Codex user config is
disabled for the isolated child process.

## Model policy

| Task | Default model | Reasoning |
| --- | --- | --- |
| Coding, debugging | `gpt-5.6-sol` | high |
| Architecture, planning | `gpt-5.6-sol` | high |
| Image/video reasoning | `gpt-5.6-sol` | high |
| Legal, medical, financial, security risk | `gpt-5.6-sol` | xhigh |
| Search synthesis | `gpt-5.6-terra` | medium |
| General conversation | `gpt-5.6-terra` | medium |
| Greetings and trivial requests | `gpt-5.6-luna` | low |

The policy is deterministic and can be overridden only by administrator-owned
environment variables. User prompt text cannot directly choose an arbitrary
provider or model.

## Failure and billing behavior

Veridex uses `codex_cli` by default. If Codex is unavailable, times out, or
returns an error, the request fails visibly instead of silently using an
API-backed provider. Existing Gemini and Groq fallback can be enabled with
`VERIDEX_MODEL_ALLOW_EXTERNAL_FALLBACK=true`; OpenRouter remains separately
opt-in. The router records the provider, model, task type, attempts, and whether
a fallback was used.
