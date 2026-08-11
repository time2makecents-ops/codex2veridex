# Codex ↔ Veridex local bridge

This bridge adds a local MCP server that lets Codex use Veridex workspace and
room tools. It does not replace Codex's ChatGPT-authenticated model and does
not require an OpenAI API key.

## Configure

1. Choose an existing Veridex session ID from the Veridex UI.
2. Set the same random local token in `C:\Office-App\.env.local`:

```text
VERIDEX_CODEX_TOKEN=<random-local-secret>
```

3. Set these values in the environment used by Codex:

```text
VERIDEX_BASE_URL=http://127.0.0.1:8078
VERIDEX_CODEX_TOKEN=<same-random-local-secret>
VERIDEX_CODEX_SESSION_ID=<your-veridex-session-id>
VERIDEX_AUTOSTART=true
```

The token is a Veridex-local integration secret, not an OpenAI credential.
Keep it out of Git and do not expose the backend beyond localhost.

## Run manually

```powershell
python C:\codex2veridex\veridex_mcp.py
```

Codex should launch the bridge through its MCP server configuration. The
global Codex instruction recognizes “use Veridex model” as activation of the
Veridex MCP tools; the underlying Codex model remains unchanged.

## Install into Codex

The repository includes the portable Codex skill and configuration template:

- `codex/skills/veridex/SKILL.md`
- `codex/config-snippet.toml`

Copy the skill into your user-level Codex skills directory and add the MCP
block from the config snippet to your user-level `config.toml`. The current
machine already has these installed.

## Available tools

- `veridex_activate`
- `veridex_status`
- `veridex_request`
- `veridex_call`
- `veridex_list_tools`
- `veridex_deactivate`
