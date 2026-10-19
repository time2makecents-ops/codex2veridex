# Veridex eBay notification Worker

This Cloudflare Worker receives eBay HTTPS notifications for the
`provenancepending` workspace (`ws_598c81c638bb`). It verifies eBay's ECC signature before storing
an event in D1. Veridex reads events through a bearer-authenticated queue and
acknowledgement deletes the Cloudflare copy. A daily cleanup removes unclaimed
events after seven days.

Local Veridex consumes this queue through `ebay_notifications.py`. It requires an
exact workspace binding, durably stores each event before acknowledgement, and uses
the eBay notification ID as its idempotency key. Marketplace Account Deletion events
are reduced to non-identifying audit metadata and a payload digest before the remote
copy is deleted; their raw payload is not copied into the local database.

## Required Worker secrets

- `EBAY_VERIFICATION_TOKEN`: 32-80 alphanumeric, underscore, or hyphen characters.
- `EBAY_CLIENT_ID`: eBay Production App ID.
- `EBAY_CLIENT_SECRET`: eBay Production Cert ID.
- `VERIDEX_WORKER_SHARED_SECRET`: random bearer secret used only by local Veridex.

Never put these values in source or `wrangler.jsonc`.

## Deployment

From this directory:

```powershell
npm install
npx wrangler login
npx wrangler whoami
npx wrangler d1 create veridex-ebay-events
```

Replace `REPLACE_AFTER_D1_CREATE` in `wrangler.jsonc` with the returned database
ID, then run:

```powershell
npx wrangler d1 migrations apply veridex-ebay-events --remote
npx wrangler secret put EBAY_VERIFICATION_TOKEN
npx wrangler secret put EBAY_CLIENT_ID
npx wrangler secret put EBAY_CLIENT_SECRET
npx wrangler secret put VERIDEX_WORKER_SHARED_SECRET
npx wrangler deploy
```

The eBay destination is:

```text
https://veridex-ebay-notifications.veridex-ebay-notifications.workers.dev/ebay/notifications
```

Use the exact same verification-token value in eBay's developer portal.

For the Production RuName, configure these exact public URLs:

- Privacy policy: `https://time2makecents-ops.github.io/veridex-privacy/`
- Auth accepted URL: `https://veridex-ebay-notifications.veridex-ebay-notifications.workers.dev/ebay/oauth/accepted`
- Auth declined URL: `https://veridex-ebay-notifications.veridex-ebay-notifications.workers.dev/ebay/oauth/declined`

The accepted route preserves eBay's authorization query parameters and redirects
the browser to Veridex's loopback callback. The local OAuth listener still validates
the one-time state value before exchanging the code.

The Worker also serves `/privacy`, but eBay's Developer Portal rejected that
`workers.dev` privacy URL. The public GitHub Pages policy above is the registered
privacy URL; do not replace it with the Worker route.

## Production checkpoint (2026-09-24)

- The Worker and D1 database are deployed on Cloudflare Workers Free.
- The D1 migration and all four required Worker secrets have been applied remotely.
- The live `/health` and `/privacy` routes return HTTP 200, the OAuth accepted route
  returns the configured HTTP 302 loopback redirect, and the declined route returns
  HTTP 200. The notification route and signature-validation behavior pass the local
  Worker tests.
- The production eBay OAuth exchange completed for the workspace and authenticated
  seller reads succeeded.
- eBay Developer Portal topic registration and an end-to-end notification delivery
  are verified for Marketplace Account Deletion. Production user subscriptions for
  `ORDER_CONFIRMATION`, `BUYER_QUESTION`, and `NEW_MESSAGE` are enabled, and one
  eBay-generated test event for each completed Worker receipt, D1 queueing, local
  mapping, and acknowledgment on 2026-09-24. Real buyer-message and sold-item delivery
  remain to be observed before claiming real-world coverage.
- The local Veridex service automatically drains the workspace-bound D1 queue at startup
  and every 60 seconds by default. The manual Connected accounts check remains available
  for an immediate retry or operator verification.
