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

## Production eBay checkpoint (2026-09-24)

- The `provenancepending` workspace has a production OAuth connection. Authorization
  is pinned by ignored local configuration to its dedicated Chrome profile, and the
  reusable access and refresh tokens are encrypted in that workspace.
- The granted scopes cover the base API, seller account, inventory, fulfillment,
  finances, marketing, and commerce messages. Live production reads succeeded for
  connection status, inventory, orders, transactions, and business policies.
- The seller account is opted into Business Policies and has one payment, shipping,
  and return policy for `EBAY_US`. An enabled warehouse inventory location exists;
  its private address details are intentionally not recorded here.
- The Cloudflare notification/OAuth relay is deployed at
  `https://veridex-ebay-notifications.veridex-ebay-notifications.workers.dev` with D1,
  the required secrets, signature verification, acknowledgment deletion, and
  seven-day cleanup. The public privacy policy is
  `https://time2makecents-ops.github.io/veridex-privacy/` because eBay rejected the
  Worker's `/privacy` URL in the RuName form.
- No live listing was published during setup. The Developer Portal's manual token
  generator and noninteractive consent preview are not required after the real
  Veridex authorization flow succeeds.

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
- Repair `ebay.offers`: eBay's production `getOffers` endpoint requires a SKU,
  but the current route sends only pagination parameters and returns HTTP 400.
- Complete and record eBay Developer Portal notification-topic registration, then
  validate a signed event through Worker receipt, local retrieval, and acknowledgment.
- Implement or verify the governed buyer-message read path and the sold-item alert
  path. OAuth scope and ordinary eBay email do not by themselves prove either path.
- Exercise a complete listing preview with real item data. Keep publication behind
  the existing explicit confirmation gate and record the returned eBay identifiers.

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
