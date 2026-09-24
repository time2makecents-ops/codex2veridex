# Veridex audit follow-ups

Source: local comparison of `codex2veridex` with `C:\Office-App` (Veridex v1.3), 2026-09-12.

These are implementation follow-ups, not claims that the work is complete.

## Current checkpoint (2026-09-23)

- The app is running locally at `http://127.0.0.1:8765` with full computer access.
- Branch `codex/home-veridex-bridge-checkpoint` matches its upstream branch (`0` ahead, `0` behind).
- Google search readiness changes in `google_chrome_search.js` and their tests are modified but uncommitted.
- Artist, gallery, Instagram, tools, and imported research files are visible to Git but remain untracked. Do not clean, reset, or switch branches over them without preserving them.
- Antiques cases now derive a canonical, revision-snapshotted `research_record` from the existing case and evidence abstractions.

## Priority gaps

## eBay integration

- [ ] Make `ebay.offers` SKU-aware. The current production request calls eBay's
  `getOffers` operation with pagination only, and eBay rejects it because a SKU is
  required.
- [ ] Confirm the production notification topic/destination in eBay's Developer
  Portal and capture end-to-end evidence for Worker verification, D1 queueing, local
  retrieval, acknowledgment, and deletion.
- [ ] Implement or verify buyer-message retrieval and sold-item alerting. Granted
  OAuth scope, a deployed receiver, and expected eBay emails are not delivery proof.
- [ ] Run a real listing preview using the configured policies and warehouse location;
  publish only after a separate explicit confirmation.

## Operator-state reporting

- [ ] Fix the model/reasoning status report that identified the terminal route as
  high when it was actually medium. Status text must come from observed host state and
  must not claim a model or reasoning level that was not verified.

## Artwork organization

- [ ] Copy the original artwork photographs and scans from `Desktop\\art` into the matching `gallery/<artist>_<title>/` folders, verify each assignment, and update each artwork record.

- [x] Replace the old image-generation gap with the governed Art Studio: authenticated Codex generation, Cloudflare Workers AI, allowlisted Pollinations fallback, verified artifacts, provider telemetry, and tested failure boundaries. The earlier Gemini/Designer proposal was superseded.
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

The branch currently matches its remote, but the working tree contains important modified and untracked work. `.gitignore` excludes environment, runtime, workspace data, temporary, and output directories. Repeat the Git/GitHub visibility check before any commit, cleanup, branch switch, or release checkpoint.
