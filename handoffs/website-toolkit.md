# Website toolkit continuation

Updated 2026-11-04. Shared setup version 1.1.0.

## Resume checkpoint

Follow-up 2026-11-05: diagnosed the user's empty `Unknown session:` toast after
image Send. Room-only copies were being imported into generation-job history
without a producing session. `room_jobs.py` now excludes these from history
imports while keeping them in Images. Regression reproduced before the fix;
39 focused tests passed. Backend restarted; affected live Jobs request, image
listing and existing-copy content return 200. Full suite: 546 passed, zero
failures/errors/skips; visual toast acceptance pending in the dedicated window
the user just opened. The user authorized committing and pushing this fix;
identify its revision from this checkout's Git history. Preserve the other terminal's
browser-extension changes and the user's untracked screenshot. After this fix,
resume the website toolkit below; the user's side-chat plan is not available
in this main chat and still needs to be supplied before executing that plan.

The OpenAI resource-installation work is complete locally. Canonical setup
commit: **`413d865`** on `main` (`codex-personal-setup`) remains unpublished.
Publishing the Veridex fix and handoff does not publish that separate setup
repository. Do not claim cross-computer availability of the setup installation
before its publication. codexxx stops on unpublished source divergence;
do not bypass its guard. Preserve the Google terminal's independent changes.

Next concrete action: reload/resume Codex, open `/mcp`, and check that
`openaiDeveloperDocs` is connected. Ask it to find the official frontend prompt
instructions and retrieve the page. Standalone service search/fetch already
passed; tools were not exposed in the previous running chat. The local kit is
at `<CODEX_HOME>/tools/openai-resources/README.md`; canonical source is
`shared/tools/openai-resources/` in the setup repository.

Continue with: **Continue from handoff 10; verify the OpenAI Docs MCP connection.**

## Current decisions

The selected toolkit has a **zero OpenAI API-credit budget**. Use public guides,
prompt examples and the existing Codex workflow. Docs MCP is configured with
standalone search/fetch verified. Client tool exposure still needs configuration
reload. API-backed sample execution and model-based evaluations are outside this
toolkit's scope.

Portable selections and installed/pending status belong in the canonical setup
repository's `WEBSITE_RESOURCES.md`. Project research is in
[OPENAI_TOOLKIT_REVIEW.md](../OPENAI_TOOLKIT_REVIEW.md) and
[WEBSITE_TOOLKIT.md](../WEBSITE_TOOLKIT.md). Keep Veridex's Python and vanilla
frontend architecture; a toolkit choice does not authorize a framework migration.

## Completed and verified

- OpenAI resource kit installed locally: eight official Python source examples
  plus MIT LICENSE, pinned revision `23e9996ac146109bdcd9b871e3564f70dc13aae1`,
  manifest sizes/hashes verified; three original reusable prompts and a public
  docs check included. No SDK examples executed or API credits used.
- Managed OpenAI Docs MCP URL added; standalone initialization, discovery of five
  tools, search and page retrieval passed. Full setup suite now **83 passed**;
  525 managed files applied, follow-up preview clean, other config entries and
  verified 45% hook state preserved. Reload current client to expose its tools.
- A separate terminal owns Google Cloud resources. OpenAI bundle application is
  finished, so that terminal can now update the shared installer/lock for its own
  work while preserving OpenAI entries. Keep commits scoped to owned files.

- Earlier 45% checkpoint/pause helper and startup verification implemented;
  its then-current setup suite passed **80 tests** (now 83), zero failures/errors/skips. Fourteen
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
- Earlier bundle applied 509 managed files (now 525). Follow-up preview had no
  changes/profile edits; fresh global/workspace CLI prompt checks passed.
- Official OpenAI resource review completed. Agent Builder, reusable prompt
  objects and hosted Evals are scheduled to close November 30, 2026; the
  dataset-backed optimizer is part of that transition. New work should keep
  prompts in code and review old sample dependencies.

## Remaining work

1. Reload the current Codex client and inspect `/mcp` for its connection to the
   configured public Docs MCP; standalone service checks already passed.
2. Decide/configure DevTools MCP with an isolated QA browser; disable usage
   statistics/CrUX URL transmission and verify a real handshake/browser check.
3. Use the three installed prompt starters on the first selected website task;
   do not recreate them. Adapt to the app's existing conventions. Keep personal
   policies in the canonical setup source, not a parallel project copy.
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
alone do not. Publication of the separate setup installation slice remains
pending explicit push authorization for that repository.
