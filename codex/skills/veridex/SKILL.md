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
- Use `office.room_list` to inspect the authoritative room directory and
  `office.room_set` for an explicit room transition. Natural-language commands
  such as `go to Art Department` are handled by the same governed transition.
- Use `office.governance_status` to inspect Navigator's exact rule source and
  active gates, `office.governance_incident_list` for blocked-breach evidence,
  and `office.compliance_check` for the current pending-gate state.
- Keep the active session and workspace IDs returned by activation.
- Never claim that a search, save, room change, or other operation happened
  unless Veridex returns evidence for it.
- Respect the access mode shown by `veridex_status`. Read-only mode can inspect
  readable files; full mode may search and work with computer files within the
  user's explicit request.
- If no session is configured, allow the standalone server to create and use
  its default local workspace and session automatically.

Use `veridex_deactivate` when the user says to stop using Veridex.

The standalone server starts with full local file access by default. Use
`C:\codex2veridex\veridex.ps1 restart -ReadOnly` only when the user explicitly
requests a read-only run.
