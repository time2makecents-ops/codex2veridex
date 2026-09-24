import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const environmentText = readFileSync(resolve(scriptDirectory, "..", "..", "..", ".env.local"), "utf8");

function environmentValue(name) {
  const match = environmentText.match(new RegExp(`^\\s*${name}\\s*=\\s*(.*)\\s*$`, "m"));
  return (match?.[1] || "").trim().replace(/^['"]|['"]$/g, "");
}

const clientId = environmentValue("EBAY_CLIENT_ID");
const clientSecret = environmentValue("EBAY_CLIENT_SECRET");
if (!clientId || !clientSecret) throw new Error("eBay application credentials are missing.");

const authorization = Buffer.from(`${clientId}:${clientSecret}`).toString("base64");
const response = await fetch("https://api.ebay.com/identity/v1/oauth2/token", {
  method: "POST",
  headers: {
    authorization: `Basic ${authorization}`,
    "content-type": "application/x-www-form-urlencoded",
  },
  body: new URLSearchParams({
    grant_type: "client_credentials",
    scope: "https://api.ebay.com/oauth/api_scope",
  }),
});
let payload = {};
try {
  payload = await response.json();
} catch {
  // Status-only output is intentional so no remote response can expose secrets.
}
process.stdout.write(`ebay_app_auth_status=${response.status}\n`);
process.stdout.write(`ebay_app_token_received=${Boolean(payload.access_token)}\n`);
if (!response.ok || !payload.access_token) process.exit(1);
