# Veridex audit follow-ups

Source: local comparison of `codex2veridex` with `C:\Office-App` (Veridex v1.3), 2026-09-12.

These are implementation follow-ups, not claims that the work is complete.

## Current checkpoint (2026-09-23)

- The app is running locally at `http://127.0.0.1:8765` with full computer access.
- Branch `codex/home-veridex-bridge-checkpoint` is one commit ahead of its upstream branch.
- Google search readiness changes and canonical research records are included in local commit `1bc07ec`; that commit has not been pushed.
- Artist, gallery, Instagram, tools, and imported research files are visible to Git but remain untracked. Do not clean, reset, or switch branches over them without preserving them.
- Antiques cases derive a canonical, revision-snapshotted `research_record` from the existing case and evidence abstractions.

## Priority gaps

## eBay integration

- [ ] Make `ebay.offers` SKU-aware. The current production request calls eBay's
  `getOffers` operation with pagination only, and eBay rejects it because a SKU is
  required.
- [x] Confirm the Production Marketplace Account Deletion destination and capture
  end-to-end evidence for Worker signature verification, D1 queueing, workspace-bound
  local retrieval, payload minimization, acknowledgment, and remote deletion. A
  five-event live canary completed without processing errors on 2026-09-24.
- [x] Register and verify the user subscriptions for `ORDER_CONFIRMATION`,
  `BUYER_QUESTION`, and `NEW_MESSAGE`. All three are enabled and their eBay-generated
  test events traversed the Worker, D1 queue, local consumer, topic mapping, and remote
  acknowledgment on 2026-09-24.
- [x] Start automatic workspace-scoped notification polling with Veridex. The poller
  checks immediately at startup and every 60 seconds by default, preserves the existing
  persist-before-ack boundary, serializes manual and background checks, and stops cleanly
  with the service. Connected accounts provides a persisted per-workspace on/off control;
  re-enabling requests an immediate check and manual checks remain available while off.
- [ ] Implement or verify buyer-message retrieval and sold-item alerting. Granted
  OAuth scope and test events prove the notification pipeline, but a real buyer message
  and completed order still need observed delivery evidence.
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

The branch is one commit ahead of its remote, and the working tree contains important untracked research and media. `.gitignore` excludes environment, runtime, workspace data, temporary, and output directories. Repeat the Git/GitHub visibility check before any commit, cleanup, branch switch, push, or release checkpoint.
