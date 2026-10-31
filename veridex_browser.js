"use strict";

const fs = require("fs");
const http = require("http");
const path = require("path");
const { spawn } = require("child_process");

const repoRoot = __dirname;

function readEnvFile(fileName) {
  const values = {};
  const candidate = path.join(repoRoot, fileName);
  if (!fs.existsSync(candidate)) return values;
  for (const line of fs.readFileSync(candidate, "utf8").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const separator = trimmed.indexOf("=");
    if (separator < 1) continue;
    values[trimmed.slice(0, separator).trim()] = trimmed.slice(separator + 1).trim().replace(/^['"]|['"]$/g, "");
  }
  return values;
}

const localEnv = { ...readEnvFile(".env.local"), ...readEnvFile("local.env") };
const profileRoot = path.resolve(
  process.env.VERIDEX_BROWSER_PROFILE_DIR
    || localEnv.VERIDEX_BROWSER_PROFILE_DIR
    || process.env.VERIDEX_FACEBOOK_PROFILE_DIR
    || localEnv.VERIDEX_FACEBOOK_PROFILE_DIR
    || path.join(repoRoot, "data", "browser_profiles", "veridex_browser"),
);
const profileDirectory = String(
  process.env.VERIDEX_BROWSER_PROFILE_DIRECTORY
    || localEnv.VERIDEX_BROWSER_PROFILE_DIRECTORY
    || "Default",
).trim() || "Default";
const debugPort = Number(
  process.env.VERIDEX_BROWSER_DEBUG_PORT
    || localEnv.VERIDEX_BROWSER_DEBUG_PORT
    || process.env.VERIDEX_PP_CHROME_DEBUG_PORT
    || localEnv.VERIDEX_PP_CHROME_DEBUG_PORT
    || 9226,
);

function output(value, status = 0) {
  process.stdout.write(`${JSON.stringify(value)}\n`);
  process.exitCode = status;
}

function chromePath() {
  const candidates = [
    process.env.VERIDEX_CHROME_PATH,
    localEnv.VERIDEX_CHROME_PATH,
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    path.join(process.env.LOCALAPPDATA || "", "Google", "Chrome", "Application", "chrome.exe"),
  ].filter(Boolean);
  const found = candidates.find((candidate) => fs.existsSync(candidate));
  if (!found) throw new Error("Google Chrome was not found. Set VERIDEX_CHROME_PATH.");
  return found;
}

function getJson(route, method = "GET", allowText = false) {
  return new Promise((resolve, reject) => {
    const request = http.request(
      { host: "127.0.0.1", port: debugPort, path: route, method, timeout: 2500 },
      (response) => {
        let body = "";
        response.setEncoding("utf8");
        response.on("data", (chunk) => { body += chunk; });
        response.on("end", () => {
          if (response.statusCode < 200 || response.statusCode >= 300) return reject(new Error(`Chrome debugging endpoint returned ${response.statusCode}.`));
          try { resolve(JSON.parse(body)); } catch (error) {
            if (allowText) resolve(body);
            else reject(error);
          }
        });
      },
    );
    request.on("timeout", () => request.destroy(new Error("Chrome debugging endpoint timed out.")));
    request.on("error", reject);
    request.end();
  });
}

async function endpointReady() {
  try { return Boolean((await getJson("/json/version")).Browser); } catch (_) { return false; }
}

function launchChrome(startUrl) {
  fs.mkdirSync(profileRoot, { recursive: true });
  const child = spawn(chromePath(), [
    `--user-data-dir=${profileRoot}`,
    `--profile-directory=${profileDirectory}`,
    `--remote-debugging-port=${debugPort}`,
    "--remote-debugging-address=127.0.0.1",
    "--remote-allow-origins=*",
    "--no-first-run",
    "--no-default-browser-check",
    "--new-window",
    startUrl,
  ], { detached: true, stdio: "ignore", windowsHide: false });
  child.unref();
}

async function ensureBrowser(startUrl) {
  if (await endpointReady()) return false;
  launchChrome(startUrl);
  for (let attempt = 0; attempt < 60; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 250));
    if (await endpointReady()) return true;
  }
  throw new Error("The Veridex browser did not become available.");
}

async function openUrl(rawUrl) {
  const url = new URL(String(rawUrl || "http://127.0.0.1:8765/"));
  if (!/^https?:$/.test(url.protocol)) throw new Error("The Veridex browser accepts only HTTP or HTTPS URLs.");
  const launched = await ensureBrowser(url.href);
  if (!launched) {
    const targets = await getJson("/json/list");
    const canonical = url.href.replace(/\/$/, "");
    const existing = (Array.isArray(targets) ? targets : []).find((row) => row.type === "page" && String(row.url || "").replace(/\/$/, "") === canonical);
    if (existing) await getJson(`/json/activate/${encodeURIComponent(existing.id)}`, "GET", true);
    else await getJson(`/json/new?${encodeURIComponent(url.href)}`, "PUT");
  }
  return { ok: true, launched, url: url.href, profile_root: profileRoot, profile_directory: profileDirectory, debug_port: debugPort };
}

async function main() {
  const action = String(process.argv[2] || "status").toLowerCase();
  if (action === "status") return output({ ok: true, connected: await endpointReady(), profile_root: profileRoot, profile_directory: profileDirectory, debug_port: debugPort });
  if (action === "open") return output(await openUrl(process.argv[3]));
  throw new Error(`Unknown action: ${action}`);
}

if (require.main === module) main().catch((error) => output({ ok: false, error: error.message || String(error) }, 1));

module.exports = { openUrl };
