# Workspace development checkpoint

## Repository checkpoint

- Workspace: `C:\codex2veridex`
- Branch: `codex/home-veridex-bridge-checkpoint`
- Latest pushed commit when this handoff was written: `40e9e5b` — `Expand
  Veridex museum workflows and integrations`
- Local and remote hashes were verified equal after that push.

## Validation at the pushed checkpoint

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

Open PowerShell and run `veridex`. Personal rules and repository `AGENTS.md`
load automatically. Say `list handoffs` to choose a focused context instead of
loading every project area.

## First actions when resuming general development

1. Inspect `git status -sb` and the narrow relevant diff.
2. Read only the selected feature's README/architecture/policy sections.
3. Confirm the required model route once.
4. Continue the smallest unfinished slice and run narrow tests while iterating.
5. Run one batched full suite only at a completed cross-cutting checkpoint.
