const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
};

const MAX_BODY_BYTES = 1_000_000;
const DEFAULT_PAGE_SIZE = 25;
const MAX_PAGE_SIZE = 100;
const LOCAL_OAUTH_CALLBACK = "http://127.0.0.1:8079/integrations/ebay/callback";

let cachedApplicationToken = null;
const cachedPublicKeys = new Map();

function jsonResponse(value, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: JSON_HEADERS });
}

function htmlResponse(body, status = 200) {
  return new Response(body, {
    status,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "public, max-age=300",
      "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
      "referrer-policy": "no-referrer",
      "x-content-type-options": "nosniff",
    },
  });
}

function page(title, content) {
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${title}</title>
  <style>
    :root { color-scheme: light; font-family: system-ui, sans-serif; line-height: 1.55; }
    body { margin: 0; background: #f4f1eb; color: #20201d; }
    main { max-width: 760px; margin: 0 auto; padding: 64px 24px 80px; }
    h1, h2 { line-height: 1.15; }
    h1 { font-size: clamp(2rem, 6vw, 3.5rem); margin: 0 0 32px; }
    h2 { margin-top: 36px; }
    p, li { max-width: 70ch; }
    a { color: #174f45; }
    .eyebrow { color: #766b58; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }
  </style>
</head>
<body><main>${content}</main></body>
</html>`;
}

function privacyPolicy() {
  return page("Veridex Privacy Policy", `
    <p class="eyebrow">Veridex</p>
    <h1>Privacy Policy</h1>
    <p>Effective September 24, 2026</p>
    <p>Veridex is a privately operated workspace assistant. This policy describes how its eBay integration handles information when an eBay seller authorizes Veridex to act on that seller's behalf.</p>
    <h2>Information handled</h2>
    <p>Veridex may process the seller's eBay account identifier, OAuth access and refresh tokens, listings, inventory, offers, orders, financial transactions, fulfillment details, buyer communications, and notification identifiers needed to provide requested seller tools.</p>
    <h2>How information is used</h2>
    <p>The information is used only to authenticate the authorized seller, search and manage that seller's eBay activity, display buyer messages and sale events, and perform actions the seller explicitly requests. Veridex does not sell eBay user information or use it for advertising.</p>
    <h2>Storage and service providers</h2>
    <p>Reusable seller tokens are encrypted in the seller's local Veridex workspace. Cloudflare operates the public notification endpoint and temporarily queues verified eBay events for delivery to that workspace. Acknowledged queue entries are deleted, and unclaimed entries expire after no more than seven days. Information is otherwise shared only with eBay and infrastructure providers as necessary to operate the integration or when required by law.</p>
    <h2>Retention and deletion</h2>
    <p>Seller credentials are retained until the seller disconnects the integration or the credentials are revoked. Veridex processes eBay marketplace-account-deletion notifications and deletes affected eBay user data unless retention is required by a specific legal obligation. Sellers may request deletion or disconnect eBay at any time.</p>
    <h2>Security</h2>
    <p>Veridex uses workspace isolation, encrypted token storage, HTTPS notification delivery, signature verification, short-lived queue retention, and confirmation gates for consequential seller actions.</p>
    <h2>Contact</h2>
    <p>Questions and deletion-request contact details are available in the
    <a href="https://time2makecents-ops.github.io/veridex-privacy/">registered privacy policy</a>.</p>
  `);
}

function oauthAccepted(request) {
  const source = new URL(request.url);
  const destination = new URL(LOCAL_OAUTH_CALLBACK);
  for (const [name, value] of source.searchParams) destination.searchParams.append(name, value);
  return new Response(null, {
    status: 302,
    headers: {
      location: destination.toString(),
      "cache-control": "no-store",
      "referrer-policy": "no-referrer",
    },
  });
}

function base64Bytes(value) {
  const normalized = String(value || "").replace(/-/g, "+").replace(/_/g, "/");
  const padding = normalized.length % 4 ? "=".repeat(4 - (normalized.length % 4)) : "";
  const decoded = atob(normalized + padding);
  return Uint8Array.from(decoded, (character) => character.charCodeAt(0));
}

function bytesToBase64(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function pemToDer(pem) {
  const body = String(pem || "")
    .replace(/-----BEGIN PUBLIC KEY-----/g, "")
    .replace(/-----END PUBLIC KEY-----/g, "")
    .replace(/\s+/g, "");
  if (!body) throw new Error("eBay returned an empty public key.");
  return base64Bytes(body);
}

function integerBytes(bytes, width) {
  let offset = 0;
  while (offset < bytes.length - 1 && bytes[offset] === 0) offset += 1;
  const value = bytes.slice(offset);
  if (value.length > width) throw new Error("ECDSA integer is too large.");
  const output = new Uint8Array(width);
  output.set(value, width - value.length);
  return output;
}

export function derEcdsaToRaw(signature, width = 32) {
  const bytes = signature instanceof Uint8Array ? signature : new Uint8Array(signature);
  if (bytes.length === width * 2) return bytes;
  let offset = 0;
  if (bytes[offset++] !== 0x30) throw new Error("Invalid ECDSA signature sequence.");
  let sequenceLength = bytes[offset++];
  if (sequenceLength & 0x80) {
    const lengthBytes = sequenceLength & 0x7f;
    sequenceLength = 0;
    for (let index = 0; index < lengthBytes; index += 1) {
      sequenceLength = (sequenceLength << 8) | bytes[offset++];
    }
  }
  if (offset + sequenceLength !== bytes.length || bytes[offset++] !== 0x02) {
    throw new Error("Invalid ECDSA signature length.");
  }
  const rLength = bytes[offset++];
  const r = bytes.slice(offset, offset + rLength);
  offset += rLength;
  if (bytes[offset++] !== 0x02) throw new Error("Invalid ECDSA signature value.");
  const sLength = bytes[offset++];
  const s = bytes.slice(offset, offset + sLength);
  if (offset + sLength !== bytes.length) throw new Error("Invalid ECDSA signature value length.");
  const raw = new Uint8Array(width * 2);
  raw.set(integerBytes(r, width), 0);
  raw.set(integerBytes(s, width), width);
  return raw;
}

export function parseSignatureHeader(value) {
  let decoded;
  try {
    decoded = JSON.parse(new TextDecoder().decode(base64Bytes(value)));
  } catch {
    throw new Error("The X-EBAY-SIGNATURE header is invalid.");
  }
  if (!decoded || typeof decoded !== "object" || !decoded.kid || !decoded.signature) {
    throw new Error("The X-EBAY-SIGNATURE header is incomplete.");
  }
  return decoded;
}

export async function challengeResponse(challengeCode, verificationToken, endpoint) {
  if (!/^[A-Za-z0-9_-]{32,80}$/.test(String(verificationToken || ""))) {
    throw new Error("EBAY_VERIFICATION_TOKEN must contain 32-80 allowed characters.");
  }
  const bytes = new TextEncoder().encode(`${challengeCode}${verificationToken}${endpoint}`);
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  return Array.from(digest, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function environmentRoot(env) {
  return String(env.EBAY_ENVIRONMENT || "production").toLowerCase() === "sandbox"
    ? "https://api.sandbox.ebay.com"
    : "https://api.ebay.com";
}

async function applicationToken(env) {
  const now = Date.now();
  if (cachedApplicationToken && cachedApplicationToken.expiresAt > now + 60_000) {
    return cachedApplicationToken.value;
  }
  if (!env.EBAY_CLIENT_ID || !env.EBAY_CLIENT_SECRET) {
    throw new Error("eBay application credentials are not configured.");
  }
  const credentials = bytesToBase64(
    new TextEncoder().encode(`${env.EBAY_CLIENT_ID}:${env.EBAY_CLIENT_SECRET}`),
  );
  const response = await fetch(`${environmentRoot(env)}/identity/v1/oauth2/token`, {
    method: "POST",
    headers: {
      authorization: `Basic ${credentials}`,
      "content-type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({
      grant_type: "client_credentials",
      scope: "https://api.ebay.com/oauth/api_scope",
    }),
  });
  if (!response.ok) throw new Error(`eBay application token request failed (${response.status}).`);
  const payload = await response.json();
  if (!payload.access_token) throw new Error("eBay did not return an application token.");
  cachedApplicationToken = {
    value: payload.access_token,
    expiresAt: now + Number(payload.expires_in || 7200) * 1000,
  };
  return cachedApplicationToken.value;
}

async function ebayPublicKey(kid, env) {
  const cached = cachedPublicKeys.get(kid);
  if (cached && cached.expiresAt > Date.now()) return cached.key;
  const token = await applicationToken(env);
  const response = await fetch(
    `${environmentRoot(env)}/commerce/notification/v1/public_key/${encodeURIComponent(kid)}`,
    { headers: { authorization: `Bearer ${token}`, accept: "application/json" } },
  );
  if (!response.ok) throw new Error(`eBay public-key request failed (${response.status}).`);
  const payload = await response.json();
  if (!payload.key) throw new Error("eBay did not return a public key.");
  const key = await crypto.subtle.importKey(
    "spki",
    pemToDer(payload.key),
    { name: "ECDSA", namedCurve: "P-256" },
    false,
    ["verify"],
  );
  cachedPublicKeys.set(kid, { key, expiresAt: Date.now() + 6 * 60 * 60 * 1000 });
  return key;
}

async function verifyBytes(key, signature, content) {
  for (const hash of ["SHA-1", "SHA-256"]) {
    try {
      if (await crypto.subtle.verify({ name: "ECDSA", hash }, key, signature, content)) return true;
    } catch {
      // Try the next supported digest.
    }
  }
  return false;
}

export async function verifyNotificationSignature(rawBody, parsedBody, signatureHeader, env) {
  const signatureMetadata = parseSignatureHeader(signatureHeader);
  const key = await ebayPublicKey(String(signatureMetadata.kid), env);
  const encodedSignature = base64Bytes(signatureMetadata.signature);
  const signatures = [encodedSignature];
  try {
    const rawSignature = derEcdsaToRaw(encodedSignature);
    if (rawSignature !== encodedSignature) signatures.push(rawSignature);
  } catch {
    // Some runtimes accept DER directly, so retain the original signature.
  }
  const payloads = [new TextEncoder().encode(rawBody)];
  const canonical = JSON.stringify(parsedBody);
  if (canonical !== rawBody) payloads.push(new TextEncoder().encode(canonical));
  for (const signature of signatures) {
    for (const payload of payloads) {
      if (await verifyBytes(key, signature, payload)) return true;
    }
  }
  return false;
}

async function authorized(request, expectedSecret) {
  const supplied = request.headers.get("authorization") || "";
  const expected = expectedSecret ? `Bearer ${expectedSecret}` : "";
  if (!expected || supplied.length !== expected.length) return false;
  const encoder = new TextEncoder();
  const [left, right] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(supplied)),
    crypto.subtle.digest("SHA-256", encoder.encode(expected)),
  ]);
  const a = new Uint8Array(left);
  const b = new Uint8Array(right);
  let difference = 0;
  for (let index = 0; index < a.length; index += 1) difference |= a[index] ^ b[index];
  return difference === 0;
}

function endpointFromRequest(request) {
  const endpoint = new URL(request.url);
  endpoint.search = "";
  endpoint.hash = "";
  return endpoint.toString();
}

function eventIdentity(payload) {
  const metadata = payload?.metadata && typeof payload.metadata === "object" ? payload.metadata : {};
  const notification = payload?.notification && typeof payload.notification === "object" ? payload.notification : {};
  const topic = String(metadata.topic || payload?.topic || "UNKNOWN").trim().toUpperCase();
  const notificationId = String(notification.notificationId || payload?.notificationId || "").trim();
  const eventDate = String(notification.eventDate || payload?.eventDate || "").trim();
  if (!notificationId) throw new Error("Notification payload has no notificationId.");
  return { topic, notificationId, eventDate };
}

async function receiveNotification(request, env, verifier) {
  const signature = request.headers.get("x-ebay-signature");
  if (!signature) return jsonResponse({ error: "Missing X-EBAY-SIGNATURE." }, 412);
  const rawBody = await request.text();
  if (!rawBody || new TextEncoder().encode(rawBody).byteLength > MAX_BODY_BYTES) {
    return jsonResponse({ error: "Notification body is empty or too large." }, 413);
  }
  let payload;
  try {
    payload = JSON.parse(rawBody);
  } catch {
    return jsonResponse({ error: "Notification body is not valid JSON." }, 400);
  }
  let valid = false;
  try {
    valid = await verifier(rawBody, payload, signature, env);
  } catch (error) {
    console.error("eBay signature validation could not complete:", error?.message || error);
  }
  if (!valid) return jsonResponse({ error: "Notification signature validation failed." }, 412);
  let identity;
  try {
    identity = eventIdentity(payload);
  } catch (error) {
    return jsonResponse({ error: error.message }, 400);
  }
  try {
    await env.EVENTS_DB.prepare(
      `INSERT INTO ebay_notification_events
       (notification_id, topic, workspace_id, event_date, payload_json, received_at)
       VALUES (?, ?, ?, ?, ?, ?)`,
    )
      .bind(
        identity.notificationId,
        identity.topic,
        String(env.VERIDEX_WORKSPACE_ID || "provenancepending"),
        identity.eventDate,
        JSON.stringify(payload),
        new Date().toISOString(),
      )
      .run();
  } catch (error) {
    if (!String(error?.message || error).toLowerCase().includes("unique")) throw error;
  }
  return new Response(null, { status: 204 });
}

async function listEvents(request, env) {
  if (!(await authorized(request, env.VERIDEX_WORKER_SHARED_SECRET))) {
    return jsonResponse({ error: "Unauthorized." }, 401);
  }
  const url = new URL(request.url);
  const requestedWorkspace = String(url.searchParams.get("workspace_id") || "").trim();
  const workspace = String(env.VERIDEX_WORKSPACE_ID || "provenancepending");
  if (requestedWorkspace && requestedWorkspace !== workspace) {
    return jsonResponse({ error: "Workspace is not authorized for this endpoint." }, 403);
  }
  const limit = Math.max(1, Math.min(MAX_PAGE_SIZE, Number(url.searchParams.get("limit")) || DEFAULT_PAGE_SIZE));
  const result = await env.EVENTS_DB.prepare(
    `SELECT id, notification_id, topic, workspace_id, event_date, payload_json, received_at, delivery_count
     FROM ebay_notification_events
     WHERE workspace_id = ?
     ORDER BY id ASC
     LIMIT ?`,
  ).bind(workspace, limit).all();
  const rows = Array.isArray(result.results) ? result.results : [];
  if (rows.length) {
    const now = new Date().toISOString();
    await env.EVENTS_DB.batch(
      rows.map((row) => env.EVENTS_DB.prepare(
        "UPDATE ebay_notification_events SET delivery_count = delivery_count + 1, last_delivered_at = ? WHERE id = ?",
      ).bind(now, row.id)),
    );
  }
  return jsonResponse({
    workspace_id: workspace,
    events: rows.map((row) => ({
      ...row,
      payload: JSON.parse(row.payload_json),
      payload_json: undefined,
    })),
  });
}

async function acknowledgeEvent(request, env, id) {
  if (!(await authorized(request, env.VERIDEX_WORKER_SHARED_SECRET))) {
    return jsonResponse({ error: "Unauthorized." }, 401);
  }
  if (!/^\d+$/.test(id)) return jsonResponse({ error: "Invalid event ID." }, 400);
  const workspace = String(env.VERIDEX_WORKSPACE_ID || "provenancepending");
  const result = await env.EVENTS_DB.prepare(
    "DELETE FROM ebay_notification_events WHERE id = ? AND workspace_id = ?",
  ).bind(Number(id), workspace).run();
  return jsonResponse({ acknowledged: Number(result.meta?.changes || 0) === 1, id: Number(id) });
}

export async function handleRequest(
  request,
  env,
  ctx,
  dependencies = { verifyNotificationSignature },
) {
  const url = new URL(request.url);
  if (
    request.method === "HEAD"
    && ["/privacy", "/ebay/oauth/accepted", "/ebay/oauth/declined"].includes(url.pathname)
  ) {
    return new Response(null, {
      status: 200,
      headers: {
        "content-type": "text/html; charset=utf-8",
        "cache-control": "public, max-age=300",
        "content-security-policy": "default-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        "referrer-policy": "no-referrer",
        "x-content-type-options": "nosniff",
      },
    });
  }
  if (request.method === "GET" && url.pathname === "/health") {
    return jsonResponse({ status: "ok", service: "veridex-ebay-notifications" });
  }
  if (request.method === "GET" && url.pathname === "/privacy") {
    return htmlResponse(privacyPolicy());
  }
  if (request.method === "GET" && url.pathname === "/ebay/oauth/accepted") {
    return oauthAccepted(request);
  }
  if (request.method === "GET" && url.pathname === "/ebay/oauth/declined") {
    return htmlResponse(page(
      "eBay authorization declined",
      '<p class="eyebrow">Veridex</p><h1>Authorization was not completed.</h1><p>No eBay access was granted. You may close this page and return to Veridex.</p>',
    ));
  }
  if (request.method === "GET" && url.pathname === "/ebay/notifications") {
    const challengeCode = url.searchParams.get("challenge_code");
    if (!challengeCode) return jsonResponse({ error: "Missing challenge_code." }, 400);
    try {
      const response = await challengeResponse(
        challengeCode,
        env.EBAY_VERIFICATION_TOKEN,
        endpointFromRequest(request),
      );
      return jsonResponse({ challengeResponse: response });
    } catch (error) {
      console.error("eBay endpoint challenge failed:", error?.message || error);
      return jsonResponse({ error: "Endpoint challenge is not configured." }, 503);
    }
  }
  if (request.method === "POST" && url.pathname === "/ebay/notifications") {
    return receiveNotification(request, env, dependencies.verifyNotificationSignature);
  }
  if (request.method === "GET" && url.pathname === "/veridex/events") {
    return listEvents(request, env);
  }
  const acknowledgement = url.pathname.match(/^\/veridex\/events\/(\d+)\/ack$/);
  if (request.method === "POST" && acknowledgement) {
    return acknowledgeEvent(request, env, acknowledgement[1]);
  }
  return jsonResponse({ error: "Not found." }, 404);
}

export default {
  fetch(request, env, ctx) {
    return handleRequest(request, env, ctx);
  },
  async scheduled(_controller, env, _ctx) {
    const retention = Math.max(1, Math.min(30, Number(env.EVENT_RETENTION_DAYS) || 7));
    const cutoff = new Date(Date.now() - retention * 86_400_000).toISOString();
    await env.EVENTS_DB.prepare(
      "DELETE FROM ebay_notification_events WHERE received_at < ?",
    ).bind(cutoff).run();
  },
};
