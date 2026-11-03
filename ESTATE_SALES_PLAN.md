# Estate Sales implementation record

Outcome: an owner-operated estate-sale workspace for business setup, client
projects, linked Intake inventory, approved specialist briefs, external-payment
records, settlement, and client-requested cleanup. Preserve existing chat model
selection, image jobs, room navigation, artifact verification, and unrelated edits.

Build sequence: project/business persistence; inventory and operations ledger;
reports; reviewed cross-room jobs; shared workspace UI; controlled workflow tests
and Chrome verification. No paid services, staff/client accounts, card processing,
automatic publishing, or assumed tax/commission settings.

Acceptance: a sample project can reach closeout, money/quantity calculations are
deterministic, client/project records remain isolated, duplicate imports and stale
saves are rejected safely, specialist work requires confirmation and leaves the
user's room unchanged, and exported results pass artifact checks.

State: the owner-operated workflow is implemented. Existing uncommitted
room-context changes were preserved. The workspace has business/project forms,
linked inventory, specialist brief review, operations, cleanup, settlement,
reports, individual receipts, cached eBay observations, and business summaries.

Historical Estate Sales verification (2026-11-02): Luna/low passed all 505 tests
with no failures, errors, or skips in 110.8 seconds; all five JavaScript syntax
checks passed. Later full discovery passed 517 tests and includes Estate Sales
regression coverage; the 11 Estate Sales live workflows below were not rerun.
A final focused Boss-chat check also passed after tightening advice-versus-work
recognition. The live server exposes 11 workflows and serves the final assets.
Controlled fixtures verify specialist/image dispatch, artifact handoffs, exact
money and stock calculations, duplicate/atomic imports, client-requested removal,
receipt isolation, source preservation, stale edits, and project boundaries.

At the 2026-11-02 checkpoint, Chrome layout validation remained pending because
the browser bridge was unavailable and native Computer Use stopped before opening
Estate Sales. Follow-up on 2026-11-03 verified the dedicated Chrome bridge and
served assets, but its CLI cannot inspect layout. The user saw projects as long
boxes rather than individual boxes, accepted "fine for now," and deferred that
layout follow-up. No full visual QA or live specialist/provider task is claimed.
No external sale, send, payment, publishing, or removal action was performed.

Earlier bridge-only diagnostic (2026-11-03; Estate Sales tests/live workflows not rerun): the user is using Codex in PowerShell, with
the desktop app closed. After opening the dedicated profile with
`.\veridex.ps1 google-profile`, Veridex's bridge reported connected to
`veridex_corporate`, `Profile 2`, on loopback port 9226. The live page,
`estate_sales.js`, and `estate_sales.css` returned HTTP 200 and matched the
repository files by SHA-256. Desktop Computer Use still reported a missing
browser host and native pipe. The existing bridge CLI supports `status` and
`open`, not layout inspection, so this does not complete Chrome visual QA or
verify live specialist/provider work. No client records or source files were
changed during these checks; the application test suite was not rerun.

## Remaining operator checklist

- [ ] Complete operator visual QA after refreshing Estate Sales; the user saw long project boxes, said "fine for now," and explicitly deferred that layout follow-up. It is not fixed or accepted as complete visual QA.
- [ ] Run one live specialist task through its explicit confirmation path and verify the resulting draft; no live specialist task has been confirmed.
- [ ] When the user supplies service area, fee rates, or external business-app choices, save the business profile and create the first real project. Do not assume these values or create a sample client/project record automatically.

Existing publishing/email flows stay separate and confirmed. Specialist text deliverables are drafts, not sent posts or messages. The room remains for the owner only; staff/client accounts and live POS/calendar integrations remain deferred as planned.
