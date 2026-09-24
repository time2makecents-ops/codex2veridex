import { randomBytes } from "node:crypto";
import { readFile, rename, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(scriptDirectory, "..", "..", "..");
const envPath = resolve(repositoryRoot, ".env.local");
const temporaryPath = `${envPath}.ebay-notifications.tmp`;

function parseEnvironment(text) {
  const values = new Map();
  for (const line of text.split(/\r?\n/)) {
    const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
    if (match) values.set(match[1], match[2].replace(/^['"]|['"]$/g, ""));
  }
  return values;
}

function replaceOrAppend(text, name, value) {
  const line = `${name}=${value}`;
  const pattern = new RegExp(`^\\s*${name}\\s*=.*$`, "m");
  if (pattern.test(text)) return text.replace(pattern, line);
  return `${text.replace(/\s*$/, "")}\n${line}\n`;
}

let existing = "";
try {
  existing = await readFile(envPath, "utf8");
} catch (error) {
  if (error.code !== "ENOENT") throw error;
}

const values = parseEnvironment(existing);
const verificationToken = values.get("EBAY_NOTIFICATION_VERIFICATION_TOKEN")
  || `veridex_${randomBytes(28).toString("base64url")}`;
const sharedSecret = values.get("VERIDEX_EBAY_WORKER_SHARED_SECRET")
  || randomBytes(48).toString("base64url");

let updated = replaceOrAppend(
  existing,
  "EBAY_NOTIFICATION_VERIFICATION_TOKEN",
  verificationToken,
);
updated = replaceOrAppend(
  updated,
  "VERIDEX_EBAY_WORKER_SHARED_SECRET",
  sharedSecret,
);
updated = replaceOrAppend(
  updated,
  "VERIDEX_EBAY_WORKER_URL",
  "https://veridex-ebay-notifications.veridex-ebay-notifications.workers.dev",
);

await writeFile(temporaryPath, updated, { encoding: "utf8", mode: 0o600 });
await rename(temporaryPath, envPath);
process.stdout.write("Generated notification secrets are stored in ignored .env.local.\n");
