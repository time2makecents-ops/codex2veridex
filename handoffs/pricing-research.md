# Pricing research system handoff

## Scope

Continue Veridex's exact-first price-evaluation system. This is system
development, not research for one specific item. Use
`PRICE_EVALUATION_ROADMAP.md` as the durable detailed record and read only the
section needed for the current slice.

## Implemented

- Slice 1: normalized, append-only comparable evidence with exact/similar tiers.
- Slice 1B: non-destructive XLSX pricing bridge, evidence sheet, JSON sidecar,
  engagement snapshots, and image-preservation verification.
- Slice 2: exact-first background controller, explicit all-likeness mode,
  progress, cancellation, time budgets, and price-only rechecks.
- Expected resale uses supported exact sold evidence only. Asking, unsold,
  estimate, low-confidence, wrong-currency, and similar records stay separate.
- Watchers, likes, favorites, saves, bids, bidders, views, and quantity sold are
  timestamped context and do not affect valuation.

## Next implementation slice

Add safe remote candidate-image retrieval and visual verification. Preserve the
source URL and image provenance, do not treat a thumbnail as exact evidence,
and require a confirmed visual comparison before promoting an uncertain
candidate to an exact tier.

After that, address browser popup/secondary-window recovery, explicit
marketplace adapters, historical sale timelines with currency normalization and
trend calculations, and manual weekly watch reminders.

## Required low-usage design

- Checkpoint each completed item and resume without rerunning valid results.
- Cache by normalized query, provider, marketplace, and source date range.
- Parse listing-bound facts locally and discard obvious mismatches before any
  model call.
- Skip synthesis when no plausible candidate exists.
- Use Google conditionally rather than for every eBay query variant.
- Send only a deduplicated structured shortlist to Sol/high for ambiguous exact
  matching, visual confirmation, or final valuation acceptance.
- Validate with fixtures, then one live item, then one five-item acceptance pass.
  Display the provider/model-call budget before a live batch.

## Known issues and truth constraints

- eBay Product Research may expose only `Last 3 years`; do not call that
  all-time history and do not impose an additional 30-day limit.
- Provider spelling suggestions are retrieval hypotheses, not identity proof.
- Google can return empty pages/timeouts; eBay can show warning text alongside
  results. Track provider health separately from a true no-result outcome.
- Preserve accepted evidence across popups, user actions, timeouts, and query
  corrections rather than restarting the item.
- Do not use video-derived crops or review records to test this work.

## Relevant files

- `PRICE_EVALUATION_ROADMAP.md`
- `price_search_controller.py`
- `antiques_department.py`
- `batch_inventory.py`
- `google_chrome_search.py`
- `test_price_search_controller.py`
- `test_antiques_department.py`
- `test_batch_inventory.py`
