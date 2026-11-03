# Codex working workflow

## Start and finish a task

Keep the task record with the code. State the outcome, constraints, acceptance
checks, current state, and next action in the selected plan or handoff. Use
ISSUE_LOG.md for problems and evidence-backed fixes; APP_FUNCTIONALITY.md is the
user-facing capability outline. Link existing records rather than duplicating them.

Plan significant or ambiguous changes first. Small clear fixes can proceed in an
execution mode. Plan mode itself never permits implementation. After planning,
switch to execution, implement, run focused checks, and update the issue record
and handoff with results actually observed. A source change alone does not prove
that a live account or browser workflow succeeds.

For sustained work, explicitly request `/goal` with the outcome, constraints,
and measurable completion criteria. No goal, budget, or recurring schedule is
created automatically. Keep related work in one conversation; use a concise
handoff when changing computers or starting an unrelated task.

## Usage and delegation

Use DEVELOPMENT_MODEL_POLICY.md for model routing. Keep one main agent and use
Luna/low for routine documentation-only edits from established evidence, with
the policy's small-follow-up exception and escalation rules. Minimize relevant
context, output, and repeated checks; model choice alone does not establish
token savings. Do not start a separate agent for a trivial documentation edit.
For substantial independent routine exploration or completed tests, use up to
two Luna/low routine agents. Give them only the bounded task context and ask for
paths and findings or counts/errors. Return failures to Sol/high for diagnosis. Instructions
to avoid edits are not a separate read-only sandbox; host permissions still apply.

Batch independent reads, keep output short, reuse evidence, and load only relevant
skills and references. Review important changes once after a meaningful slice,
especially accounts, routing, persistence, and governance. Subagents generally
increase total tokens even when they reduce elapsed time. There is no promised
universal token-saving mode. Use usage measurements when the client exposes them.

## Move between computers

Start with [CODEX_SETUP.md](CODEX_SETUP.md) for the shared GitHub setup repository,
the portable `codexxx` PowerShell command, and first-time workstation installation.
Personal policies, reusable commands, and port assignments belong in that shared
repository; this Veridex checkout points to it rather than maintaining copies.

The personal setup source is a separate `codex-personal-setup` repository, normally
at `~/codex-personal-setup`. Its setup tool installs global guidance, custom skills,
and routine agent definitions while preserving unrelated configuration. Run:

```text
python ~/codex-personal-setup/setup.py diagnose --workspace <Veridex-path> --verify-prompt --check-remote
```

PowerShell users can use `$HOME\codex-personal-setup\setup.py` as the script path.
The CLI diagnostic reports file presence separately from inclusion in a fresh
prompt. Desktop loading requires checking a new desktop chat as well.

Before switching machines, record unpublished local changes and the next action
in a selected handoff. Adding a handoff requires updating handoffs/README.md with
stable numbering. Commit/push and private-repository publication require explicit
authorization. No local work is considered synchronized merely because it exists.

Sign in separately on each computer. Do not synchronize `.codex` wholesale,
Veridex runtime data, browser profiles, passwords, tokens, or private transcripts.
The portable setup includes instructions and scripts, not installed tool binaries.
Windows, macOS, and Linux checks must be recorded separately; Windows-only helpers
remain platform-specific.
