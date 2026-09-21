# Veridex audit follow-ups

Source: local comparison of `codex2veridex` with `C:\Office-App` (Veridex v1.3), 2026-09-12.

These are implementation follow-ups, not claims that the work is complete.

## Priority gaps

## Artwork organization

- [ ] Copy the original artwork photographs and scans from `Desktop\\art` into the matching `gallery/<artist>_<title>/` folders, verify each assignment, and update each artwork record.

- [ ] Add a governed image-generation route compatible with the old Art Department contract (`office.image_generate`). Support Gemini image generation when `GEMINI_API_KEY` and quota are available, then Microsoft Designer/Bing Image Creator fallback. Preserve provider/error/quota telemetry and test fallback behavior.
- [ ] Port Google Calendar integration: read/list events plus confirmation-gated create, update, and cancel. Keep the existing Gmail confirmation flow and add end-to-end tests.
- [ ] Port Conference Room meeting-state persistence independent of Calendar: start meeting, agenda, decisions, action items, parking lot, show/close state, and workspace/session isolation.
- [ ] Add AI-polished meeting briefs generated from saved meeting state, with an explicit provenance and failure response.
- [ ] Port the Mailroom/memo contract (`mailroom.dispatch`): single-target cross-room routing, memo persistence, retrieval/listing, and request-pipeline routing for commands such as “ask Marketing to …” or “loop in Art.”
- [ ] Expand explicit persona modeling and behavior metadata for Nancy, Archivist, and the engineering persona (currently named R&D Director); preserve room restrictions and routing.

## Verification requirements

- [ ] Search all branches and compare the implementation against the sibling history before declaring a feature missing.
- [ ] Add unit and integration tests for confirmation gates, persistence, routing, provider fallback, and negative/error cases.
- [ ] Run the complete test suite and exercise the UI/API flows manually.
- [ ] Push the completed branch and verify the same files and behavior from the GitHub branch view.

## Audit caveat

The current branch has local commits ahead of its remote, and `.gitignore` excludes environment, runtime, workspace data, temporary, and output directories. Repeat the Git/GitHub visibility check after implementation.
