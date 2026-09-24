import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const workerRoot = resolve(scriptDirectory, "..");
const repositoryRoot = resolve(workerRoot, "..", "..");
const envText = readFileSync(resolve(repositoryRoot, ".env.local"), "utf8");

function environmentValue(name) {
  const match = envText.match(new RegExp(`^\\s*${name}\\s*=\\s*(.*)\\s*$`, "m"));
  const value = match?.[1]?.trim().replace(/^['"]|['"]$/g, "") || "";
  if (!value) throw new Error(`${name} is missing from .env.local.`);
  return value;
}

const secrets = new Map([
  ["EBAY_VERIFICATION_TOKEN", environmentValue("EBAY_NOTIFICATION_VERIFICATION_TOKEN")],
  ["EBAY_CLIENT_ID", environmentValue("EBAY_CLIENT_ID")],
  ["EBAY_CLIENT_SECRET", environmentValue("EBAY_CLIENT_SECRET")],
  ["VERIDEX_WORKER_SHARED_SECRET", environmentValue("VERIDEX_EBAY_WORKER_SHARED_SECRET")],
]);

for (const [name, value] of secrets) {
  const executable = process.platform === "win32" ? process.env.ComSpec : "npx";
  const argumentsForProcess = process.platform === "win32"
    ? ["/d", "/s", "/c", `npx wrangler secret put ${name}`]
    : ["wrangler", "secret", "put", name];
  const result = spawnSync(executable, argumentsForProcess, {
    cwd: workerRoot,
    input: `${value}\n`,
    encoding: "utf8",
    shell: false,
  });
  if (result.status !== 0) {
    process.stderr.write(
      result.error?.message
      || result.stderr
      || result.stdout
      || `Failed to upload ${name}.\n`,
    );
    process.stderr.write("\n");
    process.exit(result.status || 1);
  }
  process.stdout.write(`Uploaded ${name}.\n`);
}
