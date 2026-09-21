# Veridex Workspace Instructions

These instructions apply to the entire repository.

## Sources of truth

- Read only the relevant sections of `README.md` for supported behavior, setup, and operator commands.
- Read the relevant sections of `ARCHITECTURE.md` before changing request flow, persistence, routing, rooms, governance, browser bridges, or artifact handling.
- Follow `DEVELOPMENT_MODEL_POLICY.md` before development begins. State the configured and required model/reasoning once; repeat only if the route changes or mismatches, and pause on a mismatch.
- Do not reread an unchanged instruction or reference file during the same task.
- Treat `governance/navigator_governance_v1.0.0.json` as the committed runtime governance authority. Do not casually duplicate or weaken it elsewhere.

## Handoff selection

- When the user says `list handoffs` or clearly asks to list available handoffs, read only `handoffs/README.md`. Return its numbered names and short descriptions, then ask which number to use. Do not load any handoff yet.
- If the immediately following user message is a bare valid number, or says `use <number>`, map it through `handoffs/README.md`, read only that handoff, state which one was loaded, and continue from its scope.
- If the number is invalid, show the valid range and ask again. Do not interpret a bare number as a handoff choice unless a handoff selection is pending.
- Never load all handoffs automatically. Keep their numbering stable by updating `handoffs/README.md` whenever a handoff is added, removed, or renamed.

## Repository boundaries

- Preserve unrelated user changes; the worktree may already be dirty.
- Keep changes limited to the requested behavior. Avoid opportunistic refactors.
- Treat `data/`, `.runtime/`, `tmp/`, `output/`, browser profiles, transcripts, ledgers, and `.env.local` as private runtime state. Do not inspect or modify them unless the task explicitly requires it.
- Never place credentials, cookies, tokens, personal data, or transcript contents in source, fixtures, logs, or commits.
- Do not modify generated runtime records or weaken assertions merely to make a test pass.

## Application invariants

- Exactly one room is active per session; room changes require explicit navigation.
- Navigator remains present and authoritative for governance decisions.
- Searches, saves, edits, sends, execution, and provider use may be claimed only when matching evidence exists.
- A generated file is complete only after path, nonzero size, SHA-256, and artifact-ledger verification. User artifacts must be ledgered before analysis, and derived outputs must not overwrite originals.
- Explicit Google requests must use the dedicated Veridex Chrome profile and must not silently fall back to another provider.
- Persistence requires the governed scope and SAVE flow. Local governance persistence must not be presented as verified product-memory persistence.
- Cancellation must stop cancellable work and record a truthful stopped state, never false completion.
- External follows, messages, email sends, billing changes, and other consequential actions require the app's explicit confirmation path.

## Implementation guidance

- Keep the Python backend and dependency-light, vanilla HTML/CSS/JavaScript frontend consistent with the existing architecture.
- Preserve public API shapes, append-only audit semantics, atomic JSON replacement, and path-bound authorization unless the requested change explicitly migrates them.
- Prefer extending the existing governed request, room, artifact, and provider abstractions over creating parallel state or bypass paths.
- For price evaluation, reuse cached evidence and search the exact identity on the core source set first. Escalate to broader or thorough searches only after exact-match failure or an explicit user request, and batch independent item searches when practical.
- Do not add paid-provider routing, silent fallbacks, or dependencies on `C:\Office-App`.

## Validation

- Run the narrowest relevant `unittest` target while iterating.
- Run `.venv\Scripts\python.exe -m unittest discover -v` once per completed cross-cutting slice or final checkpoint when appropriate, rather than after every small edit.
- Use Luna/low subagents only for bounded, substantial routine execution. Prefer no conversation fork, return counts and errors only, and avoid agent startup for trivial commands.
- For UI changes, include the relevant `test_web_ui.py` coverage and perform browser validation when behavior or layout cannot be proven statically.
- Treat failed, flaky, or ambiguous tests as diagnosis work and return to the model/reasoning required by `DEVELOPMENT_MODEL_POLICY.md` before investigating.
- Do not claim success without reporting what was actually verified and any remaining unverified behavior.

## Operations and version control

- Ask before cleanup or deletion of generated, temporary, cache, build, or analysis artifacts.
- Do not restart services, open login flows, or perform external sends unless the request requires it and the scope is clear.
- Never create a commit or push a branch without explicit authorization for that specific action.
