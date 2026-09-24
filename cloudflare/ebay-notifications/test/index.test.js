import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";

import {
  challengeResponse,
  derEcdsaToRaw,
  handleRequest,
  parseSignatureHeader,
} from "../src/index.js";

const verificationToken = "veridex_test_token_1234567890_abcdef";

test("challenge response follows eBay's required concatenation order", async () => {
  const endpoint = "https://example.workers.dev/ebay/notifications";
  const challenge = "challenge-123";
  const expected = createHash("sha256")
    .update(challenge)
    .update(verificationToken)
    .update(endpoint)
    .digest("hex");
  assert.equal(await challengeResponse(challenge, verificationToken, endpoint), expected);
});

test("challenge endpoint uses the request URL without its query", async () => {
  const request = new Request(
    "https://example.workers.dev/ebay/notifications?challenge_code=abc123",
  );
  const response = await handleRequest(request, {
    EBAY_VERIFICATION_TOKEN: verificationToken,
  });
  assert.equal(response.status, 200);
  const payload = await response.json();
  assert.equal(
    payload.challengeResponse,
    await challengeResponse("abc123", verificationToken, "https://example.workers.dev/ebay/notifications"),
  );
});

test("signature header parser validates required fields", () => {
  const encoded = Buffer.from(JSON.stringify({ kid: "key-1", signature: "AA==" })).toString("base64");
  assert.deepEqual(parseSignatureHeader(encoded), { kid: "key-1", signature: "AA==" });
  assert.throws(() => parseSignatureHeader("not-base64"), /invalid/i);
});

test("DER ECDSA signatures are converted to fixed-width raw signatures", () => {
  const r = Buffer.alloc(32, 1);
  const s = Buffer.alloc(32, 2);
  const der = Buffer.concat([
    Buffer.from([0x30, 0x44, 0x02, 0x20]),
    r,
    Buffer.from([0x02, 0x20]),
    s,
  ]);
  const raw = derEcdsaToRaw(der);
  assert.equal(raw.length, 64);
  assert.deepEqual(Buffer.from(raw.slice(0, 32)), r);
  assert.deepEqual(Buffer.from(raw.slice(32)), s);
});

test("health endpoint does not expose configuration", async () => {
  const response = await handleRequest(new Request("https://example.test/health"), {});
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    status: "ok",
    service: "veridex-ebay-notifications",
  });
});

test("privacy policy is public and links the registered operator contact policy", async () => {
  const response = await handleRequest(new Request("https://example.test/privacy"), {});
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type"), /text\/html/);
  assert.match(
    await response.text(),
    /https:\/\/time2makecents-ops\.github\.io\/veridex-privacy\//,
  );
});

test("OAuth accept route forwards the authorization result to loopback Veridex", async () => {
  const response = await handleRequest(
    new Request("https://example.test/ebay/oauth/accepted?code=one-time-code&state=state-123"),
    {},
  );
  assert.equal(response.status, 302);
  assert.equal(
    response.headers.get("location"),
    "http://127.0.0.1:8079/integrations/ebay/callback?code=one-time-code&state=state-123",
  );
  assert.equal(response.headers.get("cache-control"), "no-store");
});

test("OAuth decline route discloses that no access was granted", async () => {
  const response = await handleRequest(
    new Request("https://example.test/ebay/oauth/declined"),
    {},
  );
  assert.equal(response.status, 200);
  assert.match(await response.text(), /No eBay access was granted/);
});

test("eBay-facing policy and callback URLs support HEAD validation", async () => {
  for (const path of ["/privacy", "/ebay/oauth/accepted", "/ebay/oauth/declined"]) {
    const response = await handleRequest(
      new Request(`https://example.test${path}`, { method: "HEAD" }),
      {},
    );
    assert.equal(response.status, 200, path);
    assert.match(response.headers.get("content-type"), /text\/html/, path);
    assert.equal(await response.text(), "", path);
  }
});

test("notification POST rejects unsigned payloads", async () => {
  const response = await handleRequest(
    new Request("https://example.test/ebay/notifications", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ notification: { notificationId: "n-1" } }),
    }),
    {},
  );
  assert.equal(response.status, 412);
});

test("Veridex queue rejects missing bearer authorization", async () => {
  const response = await handleRequest(
    new Request("https://example.test/veridex/events"),
    { VERIDEX_WORKER_SHARED_SECRET: "secret" },
  );
  assert.equal(response.status, 401);
});
