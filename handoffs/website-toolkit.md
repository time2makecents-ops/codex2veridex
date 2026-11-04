# Website toolkit continuation

Updated 2026-11-04. Shared setup version 1.1.0.

## Current decisions

The selected toolkit has a **zero OpenAI API-credit budget**. Use public guides,
prompt examples and the existing Codex workflow. Docs MCP is the next selected
connection to configure. API-backed sample execution and model-based evaluations
are outside this toolkit's scope.

Portable selections and installed/pending status belong in the canonical setup
repository's `WEBSITE_RESOURCES.md`. Project research is in
[OPENAI_TOOLKIT_REVIEW.md](../OPENAI_TOOLKIT_REVIEW.md) and
[WEBSITE_TOOLKIT.md](../WEBSITE_TOOLKIT.md). Keep Veridex's Python and vanilla
frontend architecture; a toolkit choice does not authorize a framework migration.

## Completed and verified

- Shared 45% checkpoint/pause helper and startup verification implemented;
  full setup suite passed **80 tests**, zero failures/errors/skips. Fourteen
  checkpoint tests include real Windows PowerShell pause/block/manual-reset,
  quoted paths and changed-script refusal. Real app-server hook inventory and
  untrusted/disabled rejection were exercised.
- User completed the required hook review on the implementation workstation.
  Actual installed `--arm` and separate `--status` both verified the three trusted
  hooks and target 45 for the CLI workspace. Config loading requires a fresh
  session; no real 45% event or desktop behavior has yet been observed.
- This target is checked after completed final responses and can overshoot
  during a long turn. The hook saves a repository snapshot pointing to maintained
  notes, not a conversation summary. Compaction remains manual. See the canonical
  setup repository's `CONTEXT_PAUSE.md`; trust/configuration are machine-local.
- Local npm toolkit installed: Chrome DevTools MCP 1.12.0, Playwright CLI 0.1.23,
  Lighthouse 13.5.0, axe Playwright 4.14.0, Prettier 3.9.10, SVGO 4.1.0.
  Final installation audit: zero vulnerabilities across 147 packages. CLI
  versions/imports/help were checked; no live website audit was performed.
- Google upstream a11y-debugging and debug-optimize-lcp skills included in the
  managed bundle with Apache license and pinned provenance. Source revision
  `af2834411a564d366f9cab63efb046d9084f4dba` matches npm 1.12.0 gitHead.
- Bundle lock refreshed and 509 managed files applied. Follow-up preview had no
  changes/profile edits; fresh global/workspace CLI prompt checks passed.
- Official OpenAI resource review completed. Agent Builder, reusable prompt
  objects and hosted Evals are scheduled to close November 30, 2026; the
  dataset-backed optimizer is part of that transition. New work should keep
  prompts in code and review old sample dependencies.

## Remaining work

1. Configure and verify the selected public read-only OpenAI Docs MCP connection.
2. Decide/configure DevTools MCP with an isolated QA browser; disable usage
   statistics/CrUX URL transmission and verify a real handshake/browser check.
3. Adapt concise website and debugging prompts to the existing skills. Keep
   personal policies in the canonical setup source, not a parallel project copy.
4. Confirm which website is first and the relevant Google Developer membership
   tier. Do not assume paid Google API/Cloud access or a framework preference.
5. Finish broad website-tool research synthesis. The Google report and canonical
   resources guide preserve findings. Figma/Paper/Excalidraw remain optional;
   Figma connection was offered but not confirmed. Do not repeat the suggestion
   unless requested or the suggestion cooldown has passed.
6. Observe a real 45% pause after fresh-session activation. Maintain decisions,
   changes, checks, limitations and next action at meaningful task boundaries.
   Verify desktop/cloud and other workstations separately.

No OpenAI model API calls, new billing, sign-ins, hosting deployments or service
port allocations were performed for these resource reviews. App code is
unchanged; no Veridex application tests were needed. The setup publication
checks and repository commit history establish synchronization; local files
alone do not. The user has now authorized committing and pushing this work.
