# Current build and research checkpoint

## Verified repository state

- Workspace: `C:\codex2veridex`
- Branch: `codex/home-veridex-bridge-checkpoint`
- Current local commit: `1bc07ec` - `Add canonical research records and harden Google search`
- The branch is one commit ahead of its upstream. The commit has not been pushed.
- Full Python unittest discovery passed: 252/252 tests in 76.8 seconds.
- Python compilation, Google bridge JavaScript syntax, and Git diff-integrity checks passed.
- Standalone Veridex was running at `http://127.0.0.1:8765` with full computer access,
  but that process started before `1bc07ec`. Restart only after explicit user direction.

## What `1bc07ec` contains

- A pure `research_record.py` transformer for canonical, bounded Museum case records.
- Antiques cases retain identity fields across partial revisions and snapshot the
  canonical record in every revision.
- Existing cases without a canonical record are backfilled on their next saved revision.
- The record links identity, provenance summaries, correspondence references,
  attachments, derived artifacts, source references, and append-only price observations.
- Google Chrome search readiness distinguishes real results, delayed loading,
  interstitials, false-ready pages, blank tabs, and bounded timeout diagnostics.
- README, architecture, audit checkpoint, and focused tests were updated.

## Personal rules outside the repository

`C:\Users\Accordion to JR\.codex\config.toml` contains provisional personal rules that:

- announce optional plugin use and avoid unrelated plugin calls;
- describe approximate plugin-overhead measurement;
- require stating the model, reasoning level, phase, and switch requirement at the start
  of development tasks, then waiting for the user to say `continue`;
- use Sol/high for architecture, coding, diagnosis, and final acceptance; and
- use Luna/low for standalone full-suite routine execution.

This personal configuration is machine-specific and was not committed.

## Untracked user research and media

Preserve all untracked material. It was deliberately excluded from `1bc07ec` because
some research notes contain contact information and image/document metadata has not
been fully sanitized. Current categories include:

- `Artist research (1).docx`;
- new artist folders for Colleen Humphrey, Frank Nichols, Marcy Baker, Sandy Brown
  Jensen, SY Unknown, Toni Pennington, and Tyler Zefton;
- matching gallery artwork folders and photographs;
- `instagram/` design assets; and
- `tools/sheath_enhance.py`.

Do not clean, reset, stage, commit, move, or delete these files without reviewing the
exact scope with the user. They are visible to Git and not ignored, but remain
unprotected until they are sanitized and deliberately backed up or committed.

## Current artist and object research

- Sandy Brown Jensen directly confirmed that her photograph was made in August 2018 at
  Trönninge Church, Halmstad-Söndrum, Sweden, during a family trip. She also confirmed
  that the reverse label is consistent with framed prints prepared for gallery shows.
  Formal title, process/support, edition, exhibition history, and the ownership path to
  Goodwill remain unconfirmed. The sanitized artist and gallery notes are untracked.
- The Busch sign label identifies Deco-Sign Products item `1029534`, manufactured
  `11/04`, described as a NASCAR metal sign. A likely exact catalog record describes a
  2005 Busch NASCAR die-cut metal sign and marks it sold without a price. An active eBay
  listing asked $199.99 or best offer. No verified exact sold amount was found.
- Marcy Baker, Colleen Humphrey, Frank Nichols, Sister M. Cherubim Czahor, James
  Cloutier, Toni Pennington, Tyler Zefton, SY Unknown, and Sophie Wisocky remain at
  varying stages of identification, attribution, provenance, and valuation research.

## Architecture status and next recovery slices

The app is operational, but `veridex_server.py` and `web/app.js` remain oversized and
research state is still split between runtime cases, artist folders, gallery folders,
correspondence, and handoffs. The first recovery slice, the canonical case record, is
complete. Recommended next slices are:

1. Add an explicit migration/import path from sanitized artist and gallery notes into
   canonical Museum cases, preserving source references and originals.
2. Expose canonical record fields through the existing case API/UI without creating a
   second persistence system.
3. Extract backend controllers and the tool registry from `veridex_server.py`.
4. Split `web/app.js` into dependency-light feature modules.
5. Extract shared Chrome DevTools transport/readiness helpers from the Google,
   Instagram, and Facebook bridges.
6. Add API contract tests and a small real-browser smoke suite.

Documented feature gaps still needing verification or implementation include Google
Calendar, Conference Room meeting-state persistence and briefs, and Mailroom routing.

## Safe resume sequence

1. Confirm the required model route and wait for the user to say `continue`.
2. Run `git status -sb`; expect the branch to be ahead by one plus untracked research.
3. Do not push, restart Veridex, or include untracked research without explicit approval.
4. If the user wants the current code live, restart Veridex and verify the root endpoint
   and one Museum case save/backfill flow.
5. If continuing architecture work, begin with the bounded migration/import contract and
   run focused tests before another full-suite checkpoint.
