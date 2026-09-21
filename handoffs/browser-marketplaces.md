# Browser and marketplace integrations handoff

## Scope

Continue dedicated-browser and connected-account work for Google, eBay,
Facebook, Instagram, and related governed actions. Do not inspect credentials,
cookies, browser profiles, tokens, or private runtime records unless the user
explicitly places that runtime state in scope.

## Current behavior

- Explicit Google requests use the dedicated Veridex Chrome profile and cannot
  silently fall back to another provider.
- Facebook and Instagram use separate repository-local Chrome profiles. Reads
  are bounded; composing and sending/following are separate steps.
- eBay uses OAuth and encrypted workspace-local tokens, defaults new connections
  to Sandbox, and exposes seller tools through governed APIs.
- Marketplace mutations require `confirm=true` through the app's explicit
  confirmation path. Read-only research or preview does not authorize a write.

## Next work

Implement robust popup and secondary-window handling, especially for eBay
Product Research, sign-in, consent, security checks, and rate-limit dialogs:

- Detect and track spawned tabs/windows rather than assuming one page.
- Distinguish a user-closed popup from provider failure or no results.
- Pause with a precise human-action request when a security or consent step
  cannot be automated.
- Resume from preserved search state after the user acts; do not bounce between
  items or restart completed searches.
- Record truthful provider availability, coverage limits, errors, and evidence.

## Safety constraints

- Never place account details or secrets in source, tests, logs, handoffs, or
  commits.
- Publishing/revising/withdrawing listings, sending offers/messages, following,
  fulfillment, refunds, purchases, and bids require explicit confirmation and
  matching execution evidence.
- Do not restart services or open login flows unless the current request needs
  them and the scope is clear.

## Relevant files

- `connected_accounts.py`
- `google_chrome_search.py` and `google_chrome_search.js`
- `facebook_chrome_bridge.py` and `facebook_chrome_bridge.js`
- `instagram_chrome_bridge.py` and `instagram_chrome_bridge.js`
- `ebay_oauth.py`
- `ebay_gateway.py`
- Corresponding `test_*` modules
