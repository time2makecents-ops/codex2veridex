# Veridex Price Evaluation Roadmap

This file is the durable handoff for the price-evaluation project. Update it after each
slice with implemented behavior, verification evidence, open limitations, and the next
slice. Do not place runtime case data, URLs containing private tokens, or account details
in this file.

## Decisions

- Initial categories: art, antiques, and collectibles.
- Default match scope: exact, ordered as possible same physical item and then same
  model, edition, pattern, or catalog identity.
- Similar comparables require explicit user approval. “Find all likeness” will return
  exact results first and similar results second.
- Lawful public sources and explicitly authorized signed-in accounts are allowed.
- Primary output: expected resale value. Sold, asking, unsold, and estimate evidence
  remain separate.
- Weekly watches will be manual reminders. Price-only rechecks are the default; visual
  re-search requires separate consent.
- Search presets planned for Slice 2:
  - Fast: 90-second exact / 6-minute all-likeness budget.
  - Standard: 3-minute exact / 12-minute all-likeness budget.
  - Extended: 5-minute exact / 20-minute all-likeness budget.

## Slice Status

### Slice 1 — Evidence foundation

Status: completed and focused verification passed.

- Normalize source-bound comparable observations.
- Persist a deduplicated, append-only per-case observation ledger.
- Keep possible same-item, same-model/edition, similar, and rejected tiers distinct.
- Derive last sold and expected resale from supported exact sold evidence only.
- Keep active asking prices, estimates, unsupported records, and similar candidates out
  of the valuation.
- Show exact sold evidence before exact asking/estimate context in saved Antiques cases.
- Prompt for a similar-item search when no exact result exists.
- Preserve the existing research tool and HTTP response shapes by adding
  `latest_report.price_evaluation`.

### Slice 1B — Spreadsheet pricing bridge and engagement snapshots

Status: implemented; focused verification passed on 2026-09-20.

- Added a non-destructive XLSX updater that preserves inventory rows and embedded
  images, renames legacy estimates as prior provisional estimates, and adds the
  approved pricing-summary columns.
- Added a `Price Evidence` sheet with one row per observation and a versioned JSON
  sidecar option for reproducible regeneration.
- Structured search results are now listing-bound: an amount appearing in a different
  result on the same page cannot support the claimed listing or lot.
- Expected resale excludes low-confidence matches as well as unsupported, similar,
  active, unsold, estimate, wrong-currency, and incomparable-basis observations.
- Engagement snapshots support watchers, likes, favorites, saves, bids, unique bidders,
  views, and quantity sold. Explicit zero is preserved; unavailable remains blank.
  Engagement is displayed with its capture time and never affects valuation.
- The updater refuses to overwrite the source workbook and verifies the saved copy by
  reopening it, checking row count and nonzero size, and comparing embedded-image
  SHA-256 hashes.

### Slice 2 — Exact-first search controller

Status: implemented; focused verification passed on 2026-09-20.

- Exact-only is the default; all-likeness is a separate explicit scope that always runs
  exact before similar and displays exact results first.
- Fast, Standard, and Extended enforce the approved exact/all-likeness time budgets.
- Background jobs expose queued/running/completed/failed/canceled state, progress, and
  cooperative cancellation through HTTP, the Museum UI, and governed tools.
- A no-exact exact-only result asks for approval before similar search. Similar results
  remain excluded from exact valuation even after approval.
- Price-only rechecks use public text search and do not transmit case photographs.
- Completed, non-timeout evidence is saved as a new governed case revision; partial
  timeout results are reported but not silently persisted as complete.
- Spreadsheet subjects can be read from an Inventory sheet without changing the XLSX
  or XLSM source. Synthetic coverage passed, followed by read-only validation against
  the existing `table_inventory.xlsx` and `table2_inventory.xlsx` workbooks. The renamed
  `GS2` workbook is not required to continue this slice.

### Remaining slices

1. Safe remote candidate-image retrieval and visual verification.
2. Browser popup and secondary-window handling, especially for eBay Product Research,
   sign-in, consent, and rate-limit dialogs. Detect and track spawned tabs/windows,
   clearly request human action when needed, distinguish a user-closed window from a
   provider failure, and resume or fail truthfully without losing the search state.
3. Marketplace and auction-source adapters with explicit availability/auth status.
4. Historical sale timelines, currency normalization, and trend calculations.
5. Manual weekly watch reminders with Run, Snooze, and Disable.

## Verification Log

### 2026-09-21 five-item live-search retrospective

What worked:

- Exact-first behavior held. The system did not turn broad purple glass, unrelated
  Disney merchandise, different mechanical kits, or a three-item blowtorch lot into
  exact comparables.
- Active asking prices remained separate from sold prices. Item 1 recovered two
  plausible active Sport Chef listings, but expected resale stayed blank because no
  supported exact sold observation was found.
- User- and provider-suggested spelling variants remained retrieval hypotheses rather
  than identity proof. `Sport Chef` and `Sport Chek` were searched separately, and a
  later Google suggestion changed `TimeMachine` to `Time Machine` without lowering the
  exact-match standard.
- Every accepted eBay Product Research page verified the maximum available `Last 3
  years` setting. The output records that source limit and does not claim all-time
  history.
- The timeout path retained completed browser evidence instead of returning an empty
  phase. The formerly timing-out blowtorch item completed within its Standard budget.
- The final workbook and JSON evidence sidecar were non-destructive, image-preserving,
  nonzero, SHA-256 verified, and entered in the governed artifact ledger as artifacts
  6 and 7.

What needs correction or further work:

- The run was far too expensive in model allowance. Browser navigation itself does not
  consume model tokens, but each item ended with a separate `search_deep` Sol/high
  synthesis over a large evidence prompt. Repeated partial restarts during development
  multiplied those calls. This was the primary avoidable usage pattern.
- The completed five-item pass took about 697 seconds of wall time, but wall time does
  not explain depletion of a five-hour model allowance. The expensive portion was the
  number, reasoning level, and evidence size of model invocations across the final and
  discarded attempts.
- Completed items were not checkpointed during the ad-hoc batch runner. A correction
  to one query forced restarts instead of resuming from the first unfinished or invalid
  item.
- The model was invoked even when provider evidence was empty, errored, or obviously
  unrelated. Those cases should end deterministically as `no exact candidate` without
  a high-reasoning synthesis.
- Up to five query variants and two providers per item can produce a large prompt. Raw
  4,000-character page excerpts should be replaced by locally extracted, listing-bound
  fields before any model call.
- Google frequently returned an empty page or timed out. eBay often displayed both a
  server-response warning and result/no-result content. Provider health and coverage
  need explicit scoring so a failure is not mistaken for a true negative.
- Text-only matching cannot prove exact likeness for poorly described items. Remote
  candidate-image retrieval and visual verification remain necessary before promoting
  uncertain listings.
- One completed blowtorch run contained a redundant `blowlamp / blowlamp` retrieval
  variant. The generator was fixed after that item completed, and focused regression
  coverage was added, but the historical evidence sidecar truthfully retains what that
  run attempted.

Required low-usage redesign before another multi-item live pass:

1. Add durable per-item checkpoints and resume support. Never rerun completed items
   unless their query, source range, image, or matching rules changed.
2. Cache browser results by normalized query, provider, marketplace, and date range.
   Reclassification must reuse cached evidence without reopening the provider.
3. Make discovery deterministic and model-free. Parse titles, amounts, sale state,
   dates, identifiers, links, and engagement locally, then discard obvious mismatches.
4. Skip synthesis when there are no candidates. Use Luna/low for bounded extraction or
   first-pass triage where a model is genuinely needed; reserve Sol/high for ambiguous
   exact-match promotion, visual comparison, and final valuation acceptance.
5. Send only a small deduplicated shortlist of structured candidates to the model,
   with source snippets limited to the text that supports identity and price.
6. Search eBay once per useful normalized variant and call Google conditionally—for a
   spelling correction, missing identity evidence, or cross-site confirmation—not as
   an unconditional second provider for every variant.
7. Validate new logic with fixtures first, then one live item, then one five-item
   acceptance pass. Do not use repeated full live batches as an inner development loop.
8. Before starting a live batch, display the planned item count, maximum provider
   calls, expected model-call count, model/reasoning route, and an explicit approval
   checkpoint.

- 2026-09-20: `.venv\Scripts\python.exe -m unittest -v test_antiques_department test_batch_inventory`
  passed 16/16, including listing-bound evidence, engagement independence, blank-versus-zero
  counts, source immutability, and embedded-image preservation.
- 2026-09-20: the previously failing document-export artifact classification was fixed by
  recognizing the router's `resume_generation`, `search_synthesis`, and `search_deep`
  task labels. The Museum timing race was fixed with a bounded job-manager wait primitive.
- 2026-09-20: full unittest discovery passed 225/225 after both repairs and the video
  inventory slice.
- 2026-09-20: `.venv\Scripts\python.exe -m unittest test_price_search_controller
  test_veridex_server test_web_ui -v` passed 63/63. `node --check web/app.js` and
  Python compilation also passed. Tests used only synthetic fixtures, not video-derived
  crops or review records.
- 2026-09-20: final `.venv\Scripts\python.exe -m unittest discover -v` passed
  238/238 after the controller, server, governed-tool, and Museum UI integration.
- 2026-09-20: real-workbook controller smoke test extracted 41 subjects (23 and 18)
  from the two existing table inventories. Exact-only made zero similar-adapter calls
  across all 41 queries; an explicit all-likeness run executed exact then similar and
  returned exact before similar. File size, modification time, and SHA-256 were
  unchanged for both source workbooks.
- 2026-09-20: a live Fast exact-only run exposed provider starvation when eBay consumed
  the entire phase budget. Provider calls now receive bounded shares with time reserved
  for evidence synthesis, and callback deadline exceptions terminate and clean up the
  Node bridge. Focused tests passed 18/18 and final discovery passed 239/239. Live eBay
  acceptance remains pending human sign-in to the visible Provenance account; no eBay
  OAuth assignment or stored repository credential was present.

- 2026-09-19: `.venv\Scripts\python.exe -m unittest -v test_antiques_department test_web_ui`
  passed 24/24.
- 2026-09-19: `node --check web/app.js` passed.
- 2026-09-19: full discovery ran 217 tests and retained two unrelated failures:
  `test_museum_visual_job_saves_evidence_and_case_revision` exceeded its one-second
  polling window while the background job still held its temporary ledger, and
  `test_document_export_request_requires_file_artifact` failed its existing governance
  classification assertion.
- Browser layout validation remains unperformed because the local Veridex service was
  not running; no service was restarted.

## Next Slice

Implement safe remote candidate-image retrieval and visual verification. Preserve source
provenance, avoid treating thumbnails as exact evidence, and require a confirmed visual
comparison before promoting a candidate to an exact tier.
