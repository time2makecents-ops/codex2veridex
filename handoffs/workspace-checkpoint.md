# All-encompassing workspace checkpoint

## Scope

This is the broad/default Veridex handoff. Use it when a new session may need
repository-wide development state, operator setup, safety boundaries, tooling,
or notes spanning more than one focused workflow. The other numbered handoffs
remain the token-efficient choice for work confined to a single subject.

## Current status (2026-11-03)

- PRE-COMMIT baseline: branch `codex/home-veridex-bridge-checkpoint`, HEAD `2410055` (`Point workstation startup to shared Codex setup repository`). The current Veridex changes are intended for a new commit; its hash and push status are not yet recorded here. Remote freshness for the baseline has not been checked.
- Shared personal setup is version 1.1.0 at `C:\Users\kgwamadmin\codex-personal-setup`. The `codexxx` launcher checks and updates shared rules at startup.
- That setup source currently has only `bundle-lock.json` and `shared/ports.json` dirty. HTTPS 9228 is local and unpublished; publication requires explicit authorization and the dirty-source guard still applies. HTTP 9227 was published in `f32bed7`. Do not claim a global reservation for 9228.
- Device Transfer is a separate app/source folder outside this repository and has no Git repository/remote; edits to its standalone handoff do not travel in the Veridex commit. See [standalone handoff](<../../Users/kgwamadmin/Documents/Device Transfer/HANDOFF.md>). Destination is `C:\Users\kgwamadmin\Documents\Device Transfers`; eight files were size/SHA-256 verified, with eight download links, three paired devices, and HTTPS health verified. Android HTTPS connection is user-confirmed; PWA installation and Gallery sharing remain unconfirmed.
- Estate Sales is implemented. The earlier 505-test result and 11 live workflows are historical; the latest 517-test full discovery passed and includes Estate Sales regression coverage. The long-box project layout follow-up is deferred. Full visual QA and live specialist acceptance remain pending; see [handoff 8](chrome-bridge-estate-sales.md).
- Shared image preview/editing includes local background removal in session View files, room Files, and Visual Design Images. Full discovery passed 517 tests; background-removal coverage includes 11 backend tests, one Web UI test, and six Node scenarios. The U2NET model is MD5-verified and inference passed on a synthetic fixture here. Live restart/health/asset checks passed. Real user-photo and desktop/narrow visual QA remain unverified. The earlier 515-test result is historical; see [handoff 9](README.md) and [IMAGE_PREVIEW_PLAN.md](../IMAGE_PREVIEW_PLAN.md).

## Remaining work

| Area | Open checklist | Evidence and boundary |
| --- | --- | --- |
| Image preview | See [image plan](../IMAGE_PREVIEW_PLAN.md): real-photo checks in all three surfaces on desktop and narrow browser; review Touch up/Revert, background remove/restore, manual editor, Save copy/Send across workspaces, destination files, and original preservation; prepare dependencies/model on other machines. | 517-test suite, focused tests, synthetic U2NET inference, and live health/assets passed. User-photo and visual QA remain open. Generative AI/Sunburst is explicitly deferred. |
| Device Transfer | See the local `Documents\Device Transfer\HANDOFF.md`: confirm PWA install and Gallery share of two photos, remove one and send one; verify settings, receipts, multifile, recipients, timestamps, and Documents path on Android, iPhone, and PC. | HTTPS connection is user-confirmed; file transfer to the paired work PC is not independently verified. Device Transfer source has no Git remote and is outside the Veridex commit. Large/video files and real pause/resume/cancel are optional; Veridex room integration is deferred. |
| Estate Sales | See [Estate Sales plan](../ESTATE_SALES_PLAN.md): operator visual QA and one explicitly confirmed live specialist task; create the first real project only after the user supplies missing business values. | Long-box layout is deferred per user acceptance. 505 tests and 11 live workflows are historical; latest 517 regression passed. Desktop browser host remains unavailable; CLI bridge does not prove account sign-in or visual acceptance. |
| Shared setup | See [CODEX_SETUP.md](../CODEX_SETUP.md): resolve explicit publication authorization for only `shared/ports.json` and `bundle-lock.json` (9228); then verify `codexxx -Check` here and diagnostics/sign-in/role on the other workstation. | 9228 is unpublished and not globally reserved. This is separate from committing/pushing Veridex. Setup's 51 tests are historical. |

## Historical repository checkpoint

- Workspace: `C:\codex2veridex`
- Branch: `codex/home-veridex-bridge-checkpoint`
- Latest pushed commit when this handoff was written: `40e9e5b` — `Expand
  Veridex museum workflows and integrations`
- Local and remote hashes were verified equal after that push.

## Historical validation at the pushed checkpoint

- Python unittest discovery: 245/245 passed.
- JavaScript syntax checks: 5/5 passed.
- Secret-signature, conflict-marker, whitespace, and staged private-media checks
  passed before the commit.

## Work added after the checkpoint

- Token-efficient personal/workspace rule refinements.
- Reduced repeated model announcements, documentation rereads, agent handoffs,
  and full-suite execution.
- `start_codex.ps1` plus the current-user PowerShell `veridex` command.
- The launcher uses `danger-full-access` and approval mode `never` and prints a
  warning on every start.
- Topic-specific handoffs and numbered handoff selection.

These later repository changes were uncommitted when this handoff was created.
Inspect `git status` and `git diff` before staging. Personal configuration and
the PowerShell profile live outside the repository and must not be committed.

## Repository boundaries

- Preserve the user's untracked personal art, gallery, document, Instagram, and
  other media content. Do not stage it as part of a source checkpoint.
- Keep `.env.local`, runtime data, browser profiles, transcripts, ledgers,
  generated output, and credentials out of commits.
- Do not commit or push without explicit authorization for that exact action.

## Starting a session

Open PowerShell and run `codexxx` so the launcher can check/update the canonical
shared setup and load current rules. If offline, report the last verified setup
freshness honestly. Do not infer current remote synchronization from historical
push evidence. Say `list handoffs` to choose a focused context instead of
loading every project area.

## Codex plugin and integration note (2026-09-24)

- The AI Psychiatry plugin was contributing a large always-on skill (roughly
  1,754 tokens by a simple character estimate) to task context.
- Its `SessionStart` hook invokes `sh` and points at
  `${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh`. No `sh` executable was present
  on the Windows PATH, producing `SessionStart hook failed (exit code 1)`.
- If the hook can run, `session-start.sh` prints the plugin's full
  `always-on.md` contract, which is undesirable for token-efficient sessions.
- The AI Psychiatry plugin was removed with the supported Codex plugin command.
  A fresh plugin listing no longer reports it as installed. Its old
  `[hooks.state]` trust record may remain in the personal Codex configuration;
  that record does not reinstall or enable the plugin.
- A chat that was already running can still display the earlier hook failure or
  retain its startup context. Fully quit and relaunch Codex before starting a
  clean chat; `/new` alone may reuse the running process's loaded plugin state.
- The direct Gmail plugin remains installed but is disabled in the personal
  Codex configuration. The governed, workspace-scoped Veridex Gmail connections
  do not depend on that plugin and remain connected.
- The token audit found that direct Gmail attachment calls had previously put
  very large base64 payloads into tool arguments. Do not use that route for
  Veridex attachments; retain session attachment IDs and the governed Gmail
  path required by repository policy.
- The two Gmail accounts are assigned to their intended, separate workspaces.
  Do not move or merge those assignments without an explicit request.
- eBay production OAuth is now connected for the `provenancepending` workspace.
  Tokens are encrypted in that workspace, OAuth is pinned to its dedicated Chrome
  profile through ignored local configuration, and authenticated inventory, order,
  finance, and policy reads succeeded.
- The seller account is opted into Business Policies and has payment, shipping, and
  return policies plus an enabled Inventory API warehouse location. No live listing
  was published during setup.
- The production Cloudflare notification/OAuth relay and D1 queue are deployed. The
  RuName uses Worker accepted/declined routes and the public GitHub Pages privacy
  policy because eBay rejected the Worker's privacy URL.
- Remaining eBay work is explicit: repair SKU-aware offer retrieval, verify the
  Developer Portal notification subscription end to end, verify buyer-message and
  sold-item alert delivery, and run a real listing preview before any separately
  confirmed publication.
- Existing art-research artifacts remain in the Randolfini workspace. A new
  research session exists in the provenance workspace, but no artifact-ledger
  migration has been performed.

## First actions when resuming general development

1. Inspect `git status -sb` and the narrow relevant diff.
2. Read only the selected feature's README/architecture/policy sections.
3. Confirm the required model route once.
4. Continue the smallest unfinished slice and run narrow tests while iterating.
5. Run one batched full suite only at a completed cross-cutting checkpoint.
