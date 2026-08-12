# Codex and Veridex local bridge

This repository connects Codex and Veridex in both directions without adding
an OpenAI API key:

- `veridex_mcp.py`: lets an interactive Codex session use governed Veridex tools.
- `codex_gateway.py`: lets Veridex AI chats use the locally authenticated Codex CLI.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the governance boundary, recursion
barrier, model-routing policy, and fallback behavior.

## Configure Codex to Veridex

Choose an existing Veridex session ID and set the same random local token in
`C:\Office-App\.env.local` and `C:\codex2veridex\.env.local`:

```text
VERIDEX_BASE_URL=http://127.0.0.1:8078
VERIDEX_CODEX_TOKEN=<random-local-secret>
VERIDEX_CODEX_SESSION_ID=<your-veridex-session-id>
VERIDEX_AUTOSTART=true
```

The token is a local Veridex integration secret, not an OpenAI credential. Keep
it out of Git and do not expose the backend beyond localhost.

## Configure Veridex to Codex

Add the following to `C:\Office-App\.env.local`:

```text
VERIDEX_CODEX_ENABLED=true
VERIDEX_CODEX_GATEWAY=C:\codex2veridex\codex_gateway.py
VERIDEX_CODEX_WORKDIR=C:\Office-App
VERIDEX_CODEX_TIMEOUT_SECONDS=240
```

The optional per-task model variables are listed in `.env.example`. The defaults
select Sol for coding and planning, Terra for ordinary chat, and Luna for simple
requests.

## Install the MCP side into Codex

The portable skill and MCP configuration template are included at:

- `codex/skills/veridex/SKILL.md`
- `codex/config-snippet.toml`

The current machine already has these installed.

## Test

```powershell
python -m unittest discover -v
```
