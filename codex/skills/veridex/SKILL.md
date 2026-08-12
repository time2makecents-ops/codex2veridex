---
name: veridex
description: Activate the local governed Veridex workspace through the Veridex MCP bridge when the user says “use Veridex model”, “start Veridex”, or asks to work inside Veridex.
---

# Veridex mode

When the user explicitly says “use Veridex model”, “start Veridex”, or asks to
work inside Veridex, call `veridex_activate` before doing Veridex work.

Treat this as activating Veridex's governed workspace/tool environment. It
does not change Codex's underlying ChatGPT-authenticated model and must not be
described as a model replacement.

After activation:

- Use `veridex_request` for natural-language work that should follow room and
  workspace governance.
- Use `veridex_call` for explicit Veridex tools.
- Keep the active session and workspace IDs returned by activation.
- Never claim that a search, save, room change, or other operation happened
  unless Veridex returns evidence for it.
- Respect the access mode shown by `veridex_status`. Read-only mode can inspect
  readable files; full mode may search and work with computer files within the
  user's explicit request.
- If no session is configured, allow the standalone server to create and use
  its default local workspace and session automatically.

Use `veridex_deactivate` when the user says to stop using Veridex.

For full local file access, start the standalone server first with
`C:\codex2veridex\veridex.ps1 restart -FullAccess`.
