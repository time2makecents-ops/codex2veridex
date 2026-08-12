"use strict";

const fs = require("fs");
const http = require("http");
const path = require("path");
const { spawn } = require("child_process");

const repoRoot = __dirname;
const profileRoot = path.resolve(
  process.env.VERIDEX_GOOGLE_PROFILE_DIR || path.join(repoRoot, "data", "browser_profiles", "veridex_google"),
);
const expectedEmail = String(process.env.VERIDEX_GOOGLE_ACCOUNT || "veridexcorp@gmail.com").trim().toLowerCase();
const debugPort = Number(process.env.VERIDEX_GOOGLE_DEBUG_PORT || 9223);

function output(value, status = 0) {
  process.stdout.write(`${JSON.stringify(value)}\n`);
  process.exitCode = status;
}

function chromePath() {
  const candidates = [
    process.env.VERIDEX_CHROME_PATH,
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    path.join(process.env.LOCALAPPDATA || "", "Google", "Chrome", "Application", "chrome.exe"),
  ].filter(Boolean);
  const found = candidates.find((candidate) => fs.existsSync(candidate));
  if (!found) throw new Error("Google Chrome was not found. Set VERIDEX_CHROME_PATH.");
  return found;
}

function profileStatus() {
  const preferencesPath = path.join(profileRoot, "Default", "Preferences");
  let preferences = {};
  try {
    preferences = JSON.parse(fs.readFileSync(preferencesPath, "utf8"));
  } catch (_) {
    // A missing profile is an expected setup state.
  }
  const accounts = Array.isArray(preferences.account_info) ? preferences.account_info : [];
  const emails = accounts.map((row) => String(row.email || "").trim().toLowerCase()).filter(Boolean);
  return {
    profile_root: profileRoot,
    expected_email: expectedEmail,
    profile_created: fs.existsSync(preferencesPath),
    signed_in: emails.includes(expectedEmail),
    signed_in_email: emails.includes(expectedEmail) ? expectedEmail : "",
  };
}

function getJson(route, method = "GET") {
  return new Promise((resolve, reject) => {
    const request = http.request(
      { host: "127.0.0.1", port: debugPort, path: route, method, timeout: 2500 },
      (response) => {
        let body = "";
        response.setEncoding("utf8");
        response.on("data", (chunk) => { body += chunk; });
        response.on("end", () => {
          if (response.statusCode < 200 || response.statusCode >= 300) {
            reject(new Error(`Chrome debugging endpoint returned ${response.statusCode}.`));
            return;
          }
          try { resolve(JSON.parse(body)); } catch (error) { reject(error); }
        });
      },
    );
    request.on("timeout", () => request.destroy(new Error("Chrome debugging endpoint timed out.")));
    request.on("error", reject);
    request.end();
  });
}

async function endpointReady() {
  try {
    const value = await getJson("/json/version");
    return Boolean(value && value.Browser);
  } catch (_) {
    return false;
  }
}

function launchChrome(startUrl) {
  fs.mkdirSync(profileRoot, { recursive: true });
  const child = spawn(
    chromePath(),
    [
      `--user-data-dir=${profileRoot}`,
      "--profile-directory=Default",
      `--remote-debugging-port=${debugPort}`,
      "--remote-debugging-address=127.0.0.1",
      "--remote-allow-origins=*",
      "--no-first-run",
      "--no-default-browser-check",
      "--new-window",
      startUrl,
    ],
    { detached: true, stdio: "ignore", windowsHide: false },
  );
  child.unref();
}

async function ensureChrome(startUrl) {
  if (await endpointReady()) return false;
  launchChrome(startUrl);
  for (let attempt = 0; attempt < 40; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 250));
    if (await endpointReady()) return true;
  }
  throw new Error("The dedicated Veridex Chrome profile did not become available.");
}

class CdpClient {
  constructor(url) {
    this.nextId = 1;
    this.pending = new Map();
    this.socket = new WebSocket(url);
  }

  async connect() {
    await new Promise((resolve, reject) => {
      this.socket.addEventListener("open", resolve, { once: true });
      this.socket.addEventListener("error", () => reject(new Error("Could not connect to the Chrome tab.")), { once: true });
    });
    this.socket.addEventListener("message", (event) => {
      const message = JSON.parse(String(event.data));
      if (!message.id || !this.pending.has(message.id)) return;
      const { resolve, reject } = this.pending.get(message.id);
      this.pending.delete(message.id);
      if (message.error) reject(new Error(message.error.message || "Chrome command failed."));
      else resolve(message.result || {});
    });
  }

  send(method, params = {}) {
    const id = this.nextId;
    this.nextId += 1;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  close() {
    this.socket.close();
  }
}

async function createSearchTab(url) {
  return getJson(`/json/new?${encodeURIComponent(url)}`, "PUT");
}

async function closeTab(targetId) {
  try { await getJson(`/json/close/${encodeURIComponent(targetId)}`); } catch (_) { /* best effort */ }
}

async function evaluatePage(url, expression, settleMilliseconds = 500) {
  const target = await createSearchTab(url);
  const client = new CdpClient(target.webSocketDebuggerUrl);
  try {
    await client.connect();
    await client.send("Runtime.enable");
    await client.send("Runtime.evaluate", { expression: 'window.name = "veridex-automation"' });
    for (let attempt = 0; attempt < 40; attempt += 1) {
      const state = await client.send("Runtime.evaluate", {
        expression: "document.readyState",
        returnByValue: true,
      });
      if (state.result && state.result.value === "complete") break;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    await new Promise((resolve) => setTimeout(resolve, settleMilliseconds));
    const evaluated = await client.send("Runtime.evaluate", { expression, returnByValue: true });
    return evaluated.result && evaluated.result.value ? evaluated.result.value : {};
  } finally {
    client.close();
    await closeTab(target.id);
  }
}

async function siteAccountStatus() {
  if (!(await endpointReady())) return { site_signed_in: false };
  const accountPage = await evaluatePage(
    "https://accounts.google.com/ListAccounts?gpsia=1&source=ChromiumBrowser&json=standard",
    `(() => ({ text: String(document.body ? document.body.innerText : "").slice(0, 12000) }))()`,
  );
  const normalized = String(accountPage.text || "").toLowerCase();
  return { site_signed_in: normalized.includes(expectedEmail) };
}

async function cleanupAutomationTabs() {
  let targets = [];
  try { targets = await getJson("/json/list"); } catch (_) { return 0; }
  let closed = 0;
  for (const target of targets) {
    if (target.type !== "page" || !target.webSocketDebuggerUrl) continue;
    const client = new CdpClient(target.webSocketDebuggerUrl);
    try {
      await client.connect();
      const value = await client.send("Runtime.evaluate", { expression: "window.name", returnByValue: true });
      if (value.result && value.result.value === "veridex-automation") {
        client.close();
        await closeTab(target.id);
        closed += 1;
        continue;
      }
    } catch (_) { /* Best-effort cleanup. */ }
    client.close();
  }
  return closed;
}

function sourceCandidates(links, limit = 3) {
  const selected = [];
  const seen = new Set();
  const hostCounts = new Map();
  for (const row of Array.isArray(links) ? links : []) {
    try {
      const url = new URL(String(row.url || ""));
      if (!/^https?:$/.test(url.protocol)) continue;
      const host = url.hostname.replace(/^www\./, "").toLowerCase();
      if (!host || host.endsWith("google.com")) continue;
      url.hash = "";
      const canonical = url.toString();
      if (seen.has(canonical) || (hostCounts.get(host) || 0) >= 2) continue;
      seen.add(canonical);
      hostCounts.set(host, (hostCounts.get(host) || 0) + 1);
      selected.push({ title: String(row.title || "").slice(0, 500), url: canonical, host });
      if (selected.length >= limit) break;
    } catch (_) { /* Ignore malformed result URLs. */ }
  }
  return selected;
}

async function openSource(row) {
  try {
    const page = await evaluatePage(
      row.url,
      `(() => {
        const root = document.querySelector("article") || document.querySelector("main") || document.body;
        return {
          title: document.title,
          url: location.href,
          text: String(root ? root.innerText : "").replace(/\\n{3,}/g, "\\n\\n").trim().slice(0, 4500),
        };
      })()`,
      1200,
    );
    const text = String(page.text || "");
    const limited = text.length < 160 || /sign in|log in|access denied|verify you are human|enable javascript/i.test(text);
    return {
      title: row.title,
      url: page.url || row.url,
      page_title: page.title || row.title,
      status: limited ? "limited" : "completed",
      text,
    };
  } catch (error) {
    return { title: row.title, url: row.url, status: "failed", error: error.message || String(error), text: "" };
  }
}

async function searchGoogle(query) {
  const status = profileStatus();
  const browserStarted = await ensureChrome("https://www.google.com/");
  const siteStatus = await siteAccountStatus();
  if (!status.signed_in && !siteStatus.site_signed_in) {
    throw new Error(
      `The dedicated Chrome profile is not signed in as ${expectedEmail}. Run .\\veridex.ps1 google-profile first.`,
    );
  }
  const searchUrl = `https://www.google.com/search?q=${encodeURIComponent(query)}&hl=en`;
  const target = await createSearchTab(searchUrl);
  const client = new CdpClient(target.webSocketDebuggerUrl);
  try {
    await client.connect();
    await client.send("Runtime.enable");
    await client.send("Runtime.evaluate", { expression: 'window.name = "veridex-automation"' });
    for (let attempt = 0; attempt < 40; attempt += 1) {
      const state = await client.send("Runtime.evaluate", {
        expression: "document.readyState",
        returnByValue: true,
      });
      if (state.result && state.result.value === "complete") break;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    await new Promise((resolve) => setTimeout(resolve, 1800));
    const evaluated = await client.send("Runtime.evaluate", {
      expression: `(() => {
        const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
        const root = document.querySelector("#search") || document.querySelector("main") || document.body;
        const links = Array.from(root.querySelectorAll("a[href]"))
          .map((node) => ({ title: clean(node.innerText), url: node.href }))
          .filter((row) => row.title && /^https?:/i.test(row.url))
          .filter((row) => {
            try {
              const host = new URL(row.url).hostname.replace(/^www\\./, "");
              return !host.endsWith("google.com") || row.url.includes("/url?");
            } catch (_) { return false; }
          })
          .slice(0, 20);
        return {
          title: document.title,
          url: location.href,
          text: String(root.innerText || "").slice(0, 16000),
          links,
        };
      })()`,
      returnByValue: true,
    });
    const page = evaluated.result && evaluated.result.value ? evaluated.result.value : {};
    const normalizedText = String(page.text || "");
    if (/unusual traffic|not a robot|recaptcha/i.test(normalizedText)) {
      throw new Error("Google presented an anti-automation challenge in the dedicated Chrome profile.");
    }
    if (!normalizedText.trim()) throw new Error("Google returned an empty search page.");
    const openedSources = [];
    for (const candidate of sourceCandidates(page.links, 3)) {
      openedSources.push(await openSource(candidate));
    }
    return {
      ok: true,
      provider: "google_chrome_profile",
      query,
      searched_at: new Date().toISOString(),
      profile_email: expectedEmail,
      profile_root: profileRoot,
      site_signed_in: siteStatus.site_signed_in,
      browser_started: browserStarted,
      page_title: page.title || "Google Search",
      page_url: page.url || searchUrl,
      result_text: normalizedText,
      links: Array.isArray(page.links) ? page.links : [],
      opened_sources: openedSources,
    };
  } finally {
    client.close();
    await closeTab(target.id);
  }
}

async function main() {
  const action = String(process.argv[2] || "status").toLowerCase();
  if (action === "status") {
    const chromeDebugging = await endpointReady();
    const siteStatus = chromeDebugging ? await siteAccountStatus() : { site_signed_in: false };
    const status = profileStatus();
    output({
      ok: true,
      ...status,
      ...siteStatus,
      signed_in: status.signed_in || siteStatus.site_signed_in,
      signed_in_email: status.signed_in || siteStatus.site_signed_in ? expectedEmail : "",
      chrome_debugging: chromeDebugging,
    });
    return;
  }
  if (action === "setup") {
    const started = await ensureChrome(
      `https://accounts.google.com/ServiceLogin?continue=${encodeURIComponent("https://www.google.com/")}`,
    );
    output({ ok: true, launched: started, ...profileStatus(), instruction: `Sign into Chrome as ${expectedEmail}.` });
    return;
  }
  if (action === "search") {
    const query = String(process.argv.slice(3).join(" ") || "").trim();
    if (!query) throw new Error("A Google search query is required.");
    output(await searchGoogle(query));
    return;
  }
  if (action === "cleanup") {
    output({ ok: true, closed_tabs: await cleanupAutomationTabs() });
    return;
  }
  throw new Error(`Unknown action: ${action}`);
}

main().catch((error) => output({ ok: false, error: error.message || String(error), ...profileStatus() }, 1));
