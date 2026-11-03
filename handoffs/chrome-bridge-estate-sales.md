# Chrome bridge and Estate Sales continuation

## Session context

- Date: 2026-11-03. Workspace: `C:\codex2veridex` (PowerShell).
- Personal setup: 1.1.0. Main diagnosis, coding, and review route: `gpt-6.1-sol/high`; use `Luna/low` for routine documentation and bounded tests. The user prefers useful, low-cost subagents within repository policy.
- Pre-image-controls baseline: `2410055` ("Point workstation startup to shared Codex setup repository") on `codex/home-veridex-bridge-checkpoint`; local and fetched remote matched before preparing this checkpoint. Historical verified pushes include `e3261ca` (Estate Sales) and `8c10969` (shared rooms/image/chat).
- Use `git log -1` and `git status` for the current revision and publication state. This handoff and related status documents are included in the image-controls checkpoint; see [the image implementation record](../IMAGE_PREVIEW_PLAN.md). Preserve unrelated changes and distinguish the separate setup repository and Device Transfer folder.

## Current connection state and next task

The user clarified on 2026-11-03 that this session is **Codex in PowerShell** and the desktop app is not running. Do not treat it as a desktop-app session or require a desktop restart for Veridex CLI bridge work. Desktop Computer Use still reports no apps/browsers, `The browser access host is unavailable`, and a missing native pipe (`os error 2`). This does not establish a fault in Veridex's separate Chrome bridge. The earlier stale-daemon explanation remains a hypothesis, not a proven cause.

Windows PowerShell initially blocked the startup profile. With user authorization, `CurrentUser` execution policy was set to `RemoteSigned`. A fresh PowerShell process without the tool session's inherited `Bypass` reported `RemoteSigned`, loaded the profile without errors, and exited 0; the user confirmed the fix. No machine-wide policy was changed.

Ordinary Chrome was initially open without Veridex's dedicated profile/debugging flags. The user opened a separate PowerShell window and ran:

```powershell
cd C:\codex2veridex
.\veridex.ps1 google-profile
```

Afterward, `node veridex_browser.js status` reported `connected: true`, profile root `C:\codex2veridex\data\browser_profiles\veridex_corporate`, `Profile 2`, and loopback port `9226`. This verifies bridge connectivity, not account sign-in. The live `/`, `/estate_sales.js`, and `/estate_sales.css` each returned HTTP 200 and matched repository files by SHA-256. No client data was created or modified, and no application tests were rerun for this diagnosis.

The next remaining task is Estate Sales visual validation. The existing `veridex_browser.js` CLI exposes only `status` and `open`; it cannot inspect layout. Continue supported bridge/API checks from the CLI as needed, but do not label them visual QA. For agent-controlled desktop validation, first open the desktop app, load the Computer Use skill, and verify inventory/access in that context. User-operated visual review is also still pending. Do not bypass URL verification, alter guards, copy authentication values, change profiles/accounts, weaken permissions, or force-kill the active app/server daemon. No service restart unless necessary; avoid interrupting production work.

On 2026-11-02, CUA repeatedly reported no browsers and “The browser access host is unavailable,” including after a clean `js_reset`. The installed browser runtime’s error path indicates it fails before connecting to Chrome when an authenticated host pipe or verification identity is missing (environment key names: `BROWSER_USE_ACCESS_PIPE_PATH` and `BROWSER_USE_ACCESS_VERIFYING_IDENTITY`; no values recorded). A long-lived app-server daemon predating the current desktop process makes stale desktop/daemon connection a hypothesis, not a proven cause. The native fallback was stopped because its URL could not be reliably verified. No installed runtime, registry, profile, or security edits were made.

Official recovery guidance: [Chrome extension troubleshooting](https://learn.chatgpt.com/docs/chrome-extension#troubleshooting) recommends a fresh chat/desktop restart and checking the correct profile, Manage connection, browser restart, and reinstall only if needed. The native URL-policy block and missing browser host are distinct observations; do not infer that the extension is broken or that restarting Veridex fixes the host.

Separately, the Veridex Chrome DevTools bridge was verified on 2026-11-02: `node veridex_browser.js status` reported connected to the correct dedicated repository-local corporate Chrome profile (`Profile 2`, port `9226`), and `http://127.0.0.1:9226/json/version` responded with Chrome 156 / protocol 1.3. The profile had the ChatGPT extension enabled with no disable reasons, and the native messaging registry, manifest, and executable existed; the native host ran under the dedicated Chrome. These facts do not establish desktop browser-access host availability.

## Estate Sales implementation checkpoint

The owner-operated Estate Sales slice is implemented. On 2026-11-03, the user saw projects displayed as long boxes rather than individual boxes, said ?fine for now,? and moved on. Treat the visual layout follow-up as explicitly deferred; do not claim full visual QA. Read `ESTATE_SALES_PLAN.md`, the Estate Sales section of `README.md`, `ARCHITECTURE.md`, and `ISSUE_LOG.md` for the project details; avoid duplicating the full specification here. The Estate Sales Room owner is Boss. The slice covers business/client projects, linked Intake catalog and photos, approved pricing and stock guards, operations/receipts, deterministic money/settlement, client-requested cleanup, report exports, and shared reviewed specialist jobs/metadata. Specialist text outputs are draft artifacts, not sent emails or published listings. Staff/client portals, live POS/calendar, paid providers, and assumed locations/fees/apps are out of scope.

Historical Estate Sales validation (2026-11-02): 505 tests, 0 failures/errors/skips, 110.8 seconds; five JS syntax checks passed; final focused Boss-chat guard passed; 11 live API workflows and final assets verified. The later 515-test full discovery passed and includes Estate Sales regression coverage; the 11 live workflows were not rerun. Visual browser QA and a live specialist/provider task remain unverified. No sample client projects were created in the live workspace (last checked: 0 projects).

Relevant source files: `estate_sales.py`, `estate_reports.py`, `web/estate_sales.js`, `web/estate_sales.css`, `room_jobs.py`, `veridex_server.py`. The room-context purpose/capability fix is included in the commit.

## Working constraints and tools

- Veridex URL: `http://127.0.0.1:8765`.
- Python: `.venv\Scripts\python.exe`; Node is available. Git is not on `PATH`; use `C:\Program Files\Git\cmd\git.exe`.
- Do not rerun the 505-test suite for documentation-only work or browser-host diagnosis. Ask before cleanup/deletion. Do not commit or push without explicit authorization for that action.
- Account/scope checks remain necessary. No external sends, publishing, or payments.
