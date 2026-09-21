# Single-item sale handoff

## Objective

Help the user identify, research, price, and prepare one item for sale. Keep the
session focused on that item. Do not load unrelated inventory, video-review, art
catalog, or prior-item runtime data unless the user explicitly requests it.

## Start here

1. Ask for or locate the item's photographs. Prefer front, back, underside,
   maker's marks, labels, signatures, damage, accessories, packaging, and one
   scale or measurement view.
2. Record only user-provided facts and directly visible evidence. Separate
   observations from inferences and unresolved questions.
3. Establish the exact identity before pricing. Distinguish a possible repeat
   appearance of the same physical item from the same model, edition, pattern,
   or catalog identity.
4. If no exact match is found, ask before expanding to similar items. If the
   user asks for all likeness, show exact results first and similar results in a
   separate section.

## Efficient research sequence

1. Reuse cached evidence first. Search the exact identity on the core sources
   before using broad or deep research.
2. Treat spelling corrections and provider suggestions as search hypotheses,
   not proof of identity. Verify them against images, markings, and dimensions.
3. Extract listing-bound fields locally before model synthesis: title, URL,
   status, sold date, price, shipping, currency, condition, venue, image URL,
   engagement, and capture time.
4. Do not invoke deep synthesis when provider evidence is empty, errored, or
   plainly unrelated. Report `no exact candidate` and the coverage limitation.
5. Checkpoint accepted evidence after each provider so a popup, timeout, or
   corrected query does not force a restart.

The current controller supports exact-first searches, explicit all-likeness,
background progress/cancellation, and price-only rechecks. Its durable status
and remaining work are in `PRICE_EVALUATION_ROADMAP.md`. Read only the relevant
section when implementation details are needed.

## Price evidence rules

- Keep sold, active asking, unsold, estimate, and similar evidence separate.
- Calculate expected resale from supported exact sold evidence only.
- Record the last sold price and a chronological sale history when available.
- Preserve venue, sale date, currency, condition, shipping, and source URL.
- Capture likes, watchers, favorites, saves, bids, views, and quantity sold when
  visible, with a timestamp. Engagement does not determine value.
- Do not impose an arbitrary recent-date filter. Disclose a marketplace's own
  history limit; eBay Product Research may expose at most `Last 3 years`.
- Never promote a text-only candidate to exact when visual evidence is needed.

## Browser and account handling

- Explicit Google work uses the dedicated Veridex Chrome profile and must not
  silently fall back to another provider.
- eBay, sign-in, consent, rate-limit, and secondary-window popups may require the
  user's action. Preserve progress, explain the needed click, and resume from
  the checkpoint rather than restarting the item.
- Credentials, cookies, OAuth tokens, browser profiles, and account details stay
  in ignored local storage and never enter this handoff or a commit.
- Research and listing previews are read-only. Publishing, revising,
  withdrawing, sending offers, fulfillment, refunds, purchases, and bids require
  the app's explicit confirmation path and matching execution evidence.

## Sale preparation

Prepare a concise package containing:

- Best-supported identity and confidence, with remaining uncertainty.
- Exact sold-comparable table followed by exact active listings.
- Separate similar-item context only when approved.
- Expected resale range, suggested list price, quick-sale price, and maximum
  acquisition price when relevant, with the evidence behind each figure.
- Marketplace recommendation and a search-friendly listing title.
- Factual description, item specifics, measurements, included pieces, condition
  notes, defects, and provenance claims that are actually supported.
- Photo checklist, shipping/packing questions, and any authentication or testing
  needed before listing.

Do not publish the listing until the user has reviewed the exact title,
description, price, shipping terms, photographs, and confirmation prompt.

## Definition of done

The task is complete only when the user has a reviewable identity assessment,
source-linked price evidence, valuation with limitations, and a listing draft or
clear next evidence request. State what remains unverified. A live listing is a
separate, explicitly confirmed action.

## Relevant files — open only if needed

- `PRICE_EVALUATION_ROADMAP.md`
- `price_search_controller.py`
- `antiques_department.py`
- `google_chrome_search.py`
- `ebay_gateway.py`
- `visual_evidence.py`
