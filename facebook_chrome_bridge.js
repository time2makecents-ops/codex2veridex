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
    const key = trimmed.slice(0, separator).trim();
    let value = trimmed.slice(separator + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    values[key] = value;
  }
  return values;
}

const localEnv = { ...readEnvFile(".env.local"), ...readEnvFile("local.env") };
const profileRoot = path.resolve(
  process.env.VERIDEX_FACEBOOK_PROFILE_DIR
    || localEnv.VERIDEX_FACEBOOK_PROFILE_DIR
    || path.join(repoRoot, "data", "browser_profiles", "veridex_facebook"),
);
const debugPort = Number(
  process.env.VERIDEX_FACEBOOK_DEBUG_PORT || localEnv.VERIDEX_FACEBOOK_DEBUG_PORT || 9225,
);
const configuredUsername = String(
  process.env.FACEBOOK_USERNAME
    || process.env.FACEBOOK_EMAIL
    || localEnv.FACEBOOK_USERNAME
    || localEnv.FACEBOOK_EMAIL
    || "",
).trim();
const configuredPassword = String(process.env.FACEBOOK_PASSWORD || localEnv.FACEBOOK_PASSWORD || "");

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
  for (let attempt = 0; attempt < 60; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 250));
    if (await endpointReady()) return true;
  }
  throw new Error("The dedicated Facebook Chrome profile did not become available.");
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
      this.socket.addEventListener("error", () => reject(new Error("Could not connect to the Facebook browser tab.")), { once: true });
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

  close() { this.socket.close(); }
}

async function createTab(url) {
  return getJson(`/json/new?${encodeURIComponent(url)}`, "PUT");
}

async function waitForDocument(client) {
  await client.send("Runtime.enable");
  for (let attempt = 0; attempt < 60; attempt += 1) {
    const state = await client.send("Runtime.evaluate", { expression: "document.readyState", returnByValue: true });
    if (state.result && state.result.value === "complete") break;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  await new Promise((resolve) => setTimeout(resolve, 1400));
}

async function evaluate(client, expression) {
  const result = await client.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) {
    const description = result.exceptionDetails.exception && result.exceptionDetails.exception.description;
    throw new Error(description || result.exceptionDetails.text || "Facebook page script failed.");
  }
  return result.result && result.result.value !== undefined ? result.result.value : {};
}

async function withTab(url, callback, keepOpen = false) {
  await ensureChrome("https://www.facebook.com/");
  const target = await createTab(url);
  const client = new CdpClient(target.webSocketDebuggerUrl);
  try {
    await client.connect();
    await waitForDocument(client);
    return await callback(client, target);
  } finally {
    client.close();
    if (!keepOpen) {
      try { await getJson(`/json/close/${encodeURIComponent(target.id)}`); } catch (_) { /* best effort */ }
    }
  }
}

async function pageState(client) {
  return evaluate(client, `(() => {
    const text = String(document.body ? document.body.innerText : '').slice(0, 12000);
    const loginForm = Boolean(document.querySelector('#email, input[name="email"], #pass, input[name="pass"]'));
    const nav = Boolean(document.querySelector('a[aria-label="Home"], [aria-label^="Your profile" i], [aria-label="Account"], [aria-label="Facebook"]'));
    const checkpoint = /checkpoint|two_step_verification|login\\/identify/i.test(location.href)
      || /security code|check your notifications|confirm your identity|two-factor authentication/i.test(text);
    return {
      title: document.title,
      url: location.href,
      text,
      login_form: loginForm,
      checkpoint,
      signed_in: nav && !loginForm && !/\\/login\\/?/i.test(location.pathname),
    };
  })()`);
}

function normalizeTarget(value) {
  const raw = String(value || "").trim();
  if (!raw) throw new Error("A Facebook profile URL or username is required.");
  let url;
  if (/^https?:\/\//i.test(raw)) {
    url = new URL(raw);
    if (!/(^|\.)facebook\.com$/i.test(url.hostname)) throw new Error("The target must be a facebook.com profile.");
  } else {
    const slug = raw.replace(/^@/, "").replace(/^\/+|\/+$/g, "");
    if (!/^[A-Za-z0-9._-]+$/.test(slug)) throw new Error("The Facebook username contains unsupported characters.");
    url = new URL(`https://www.facebook.com/${slug}`);
  }
  url.protocol = "https:";
  url.hostname = "www.facebook.com";
  const reserved = new Set(["login", "messages", "marketplace", "watch", "groups", "events", "settings", "help"]);
  const first = url.pathname.split("/").filter(Boolean)[0] || "";
  if (!first || reserved.has(first.toLowerCase())) throw new Error("The target must identify a Facebook profile.");
  if (first.toLowerCase() === "profile.php") {
    const id = url.searchParams.get("id");
    if (!id || !/^\d+$/.test(id)) throw new Error("The Facebook profile URL is missing a valid id.");
    return { profileUrl: `https://www.facebook.com/profile.php?id=${id}`, messageKey: id, label: id };
  }
  const slug = first.replace(/[^A-Za-z0-9._-]/g, "");
  if (!slug) throw new Error("The Facebook profile URL is invalid.");
  return { profileUrl: `https://www.facebook.com/${encodeURIComponent(slug)}`, messageKey: slug, label: slug };
}

async function status() {
  const chromeDebugging = await endpointReady();
  if (!chromeDebugging) {
    return {
      ok: true,
      configured: Boolean(configuredUsername && configuredPassword),
      username: configuredUsername,
      profile_root: profileRoot,
      chrome_debugging: false,
      signed_in: false,
    };
  }
  const state = await withTab("https://www.facebook.com/me", (client) => pageState(client));
  return {
    ok: true,
    configured: Boolean(configuredUsername && configuredPassword),
    username: configuredUsername,
    profile_root: profileRoot,
    chrome_debugging: true,
    signed_in: Boolean(state.signed_in),
    requires_interaction: Boolean(state.checkpoint),
    page_url: state.url,
  };
}

async function login() {
  if (!configuredUsername || !configuredPassword) {
    throw new Error("FACEBOOK_USERNAME (or FACEBOOK_EMAIL) and FACEBOOK_PASSWORD must be set in local.env or .env.local.");
  }
  return withTab("https://www.facebook.com/login/", async (client) => {
    const initial = await pageState(client);
    if (initial.signed_in) return { ok: true, signed_in: true, username: configuredUsername, already_signed_in: true };
    const prepared = await evaluate(client, `(() => {
      const consent = Array.from(document.querySelectorAll('button')).find((node) => /allow all cookies|only allow essential cookies|decline optional cookies/i.test(node.innerText || ''));
      if (consent) consent.click();
      const username = document.querySelector('#email, input[name="email"], input[autocomplete="username"]');
      const password = document.querySelector('#pass, input[name="pass"], input[autocomplete="current-password"], input[type="password"]');
      if (!username || !password) return { ready: false, page: String(document.body ? document.body.innerText : '').slice(0, 400) };
      const inputSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      inputSetter.call(username, ${JSON.stringify(configuredUsername)});
      username.dispatchEvent(new Event('input', { bubbles: true }));
      username.dispatchEvent(new Event('change', { bubbles: true }));
      inputSetter.call(password, ${JSON.stringify(configuredPassword)});
      password.dispatchEvent(new Event('input', { bubbles: true }));
      password.dispatchEvent(new Event('change', { bubbles: true }));
      const submit = document.querySelector('button[name="login"], button[type="submit"], input[type="submit"]');
      if (!submit) return { ready: false, page: 'Facebook login submit control was not found.' };
      submit.click();
      return { ready: true };
    })()`);
    if (!prepared.ready) throw new Error(`Facebook's login form was not ready. ${prepared.page || ""}`.trim());
    for (let attempt = 0; attempt < 60; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 500));
      const state = await pageState(client);
      if (state.signed_in) return { ok: true, signed_in: true, username: configuredUsername };
      if (state.checkpoint) {
        return {
          ok: true,
          signed_in: false,
          username: configuredUsername,
          requires_interaction: true,
          instruction: "Complete Facebook's security check in the visible Chrome window, then run facebook-status.",
        };
      }
    }
    return {
      ok: true,
      signed_in: false,
      username: configuredUsername,
      requires_interaction: true,
      instruction: "Facebook did not confirm sign-in. Review the visible Chrome window, then run facebook-status.",
    };
  }, true);
}

async function readProfile(target) {
  const normalized = normalizeTarget(target);
  return withTab(normalized.profileUrl, async (client) => {
    const state = await pageState(client);
    if (!state.signed_in) throw new Error("The dedicated Facebook profile is not signed in. Run facebook-login first.");
    const data = await evaluate(client, `(() => {
      const body = String(document.body ? document.body.innerText : '').replace(/\\s+/g, ' ').trim();
      const heading = Array.from(document.querySelectorAll('h1, h2')).map((node) => String(node.innerText || '').trim()).find(Boolean) || '';
      return { name: heading, text: body.slice(0, 6000), url: location.href, title: document.title };
    })()`);
    return { ok: true, provider: "facebook_chrome_profile", target: normalized.label, ...data };
  });
}

async function fillMessageComposer(client, body) {
  const prepared = await evaluate(client, `(() => {
    const visible = (node) => Boolean(node && (node.offsetWidth || node.offsetHeight || node.getClientRects().length));
    const candidates = Array.from(document.querySelectorAll('div[contenteditable="true"][role="textbox"], textarea[placeholder*="Message" i], textarea[aria-label*="Message" i]')).filter(visible);
    const box = candidates.find((node) => /message/i.test(String(node.getAttribute('aria-label') || node.getAttribute('data-lexical-editor') || node.getAttribute('placeholder') || ''))) || candidates[candidates.length - 1];
    if (!box) return {
      ready: false,
      page: String(document.body ? document.body.innerText : '').replace(/\\s+/g, ' ').trim().slice(0, 500),
      fields: Array.from(document.querySelectorAll('textarea, input, [contenteditable="true"]')).map((node) => ({
        tag: node.tagName, role: node.getAttribute('role') || '', aria: node.getAttribute('aria-label') || '',
        placeholder: node.getAttribute('placeholder') || '', contenteditable: node.getAttribute('contenteditable') || '',
      })).slice(0, 25),
    };
    const existing = String(box.value || box.innerText || box.textContent || '').replace(/\\s+/g, ' ').trim();
    const requested = ${JSON.stringify(body.replace(/\s+/g, " ").trim())};
    if (existing && existing !== requested) {
      return { ready: false, conflict: true, page: 'A different unsent Facebook draft is already present.' };
    }
    box.focus();
    if (!existing && box.tagName === 'TEXTAREA') {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
      setter.call(box, ${JSON.stringify(body)});
      box.dispatchEvent(new Event('input', { bubbles: true }));
      box.dispatchEvent(new Event('change', { bubbles: true }));
    }
    return { ready: true, tag: box.tagName, already_present: Boolean(existing) };
  })()`);
  if (!prepared.ready) return { composed: false, conflict: Boolean(prepared.conflict), page: prepared.page, fields: prepared.fields };
  if (!prepared.already_present && prepared.tag !== "TEXTAREA") await client.send("Input.insertText", { text: body });
  await new Promise((resolve) => setTimeout(resolve, 400));
  const draftText = await evaluate(client, `(() => {
    const visible = (node) => Boolean(node && (node.offsetWidth || node.offsetHeight || node.getClientRects().length));
    const candidates = Array.from(document.querySelectorAll('div[contenteditable="true"][role="textbox"], textarea[placeholder*="Message" i], textarea[aria-label*="Message" i]')).filter(visible);
    const box = candidates.find((node) => /message/i.test(String(node.getAttribute('aria-label') || node.getAttribute('data-lexical-editor') || node.getAttribute('placeholder') || ''))) || candidates[candidates.length - 1];
    return box ? String(box.value || box.innerText || box.textContent || '').trim() : '';
  })()`);
  return { composed: true, draft_text: String(draftText || "").trim() };
}

async function openConversation(client, normalized) {
  const opened = await evaluate(client, `(() => {
    const label = (node) => String(node.innerText || node.textContent || node.getAttribute('aria-label') || '').trim();
    const button = Array.from(document.querySelectorAll('button, div[role="button"], a[role="button"]')).find((node) => /^message$/i.test(label(node)));
    if (!button) return false;
    button.click();
    return true;
  })()`);
  if (opened) {
    await new Promise((resolve) => setTimeout(resolve, 2500));
    return true;
  }
  await client.send("Page.navigate", { url: `https://www.facebook.com/messages/t/${encodeURIComponent(normalized.messageKey)}` });
  await waitForDocument(client);
  await new Promise((resolve) => setTimeout(resolve, 1800));
  return false;
}

async function composeMessage(target, message, confirmed) {
  const normalized = normalizeTarget(target);
  const body = String(message || "").trim();
  if (!body) throw new Error("A message is required.");
  return withTab(normalized.profileUrl, async (client) => {
    const state = await pageState(client);
    if (!state.signed_in) throw new Error("The dedicated Facebook profile is not signed in. Run facebook-login first.");
    await openConversation(client, normalized);
    const composed = await fillMessageComposer(client, body);
    if (!composed.composed) {
      if (composed.conflict) throw new Error(String(composed.page || "A different unsent Facebook draft is already present."));
      const page = String(composed.page || "").replace(/\s+/g, " ").trim().slice(0, 300);
      throw new Error(`Facebook's message composer was not found.${page ? ` Page says: ${page}` : ""} Fields: ${JSON.stringify(composed.fields || [])}`);
    }
    const draftedText = String(composed.draft_text || "").replace(/\s+/g, " ").trim();
    const requestedText = body.replace(/\s+/g, " ").trim();
    if (draftedText !== requestedText) {
      throw new Error(`Facebook's message draft did not match the requested text, so it was not sent. Current draft: ${draftedText.slice(0, 1000)}`);
    }
    if (!confirmed) {
      return {
        ok: true,
        target: normalized.label,
        status: "drafted",
        sent: false,
        draft_text: composed.draft_text,
        instruction: "Review the visible Facebook message in Chrome before sending.",
      };
    }
    const sent = await evaluate(client, `(() => {
      const visible = (node) => Boolean(node && (node.offsetWidth || node.offsetHeight || node.getClientRects().length));
      const label = (node) => String(node.innerText || node.textContent || node.getAttribute('aria-label') || '').trim();
      const candidates = Array.from(document.querySelectorAll('button, div[role="button"]')).filter(visible);
      const button = candidates.find((node) => /^send(?: message)?$/i.test(label(node)) || /^send$/i.test(String(node.getAttribute('aria-label') || '')));
      if (!button) return false;
      button.click();
      return true;
    })()`);
    if (!sent) throw new Error("Facebook's Send control was not found; the message remains composed for review.");
    return { ok: true, target: normalized.label, status: "sent", sent: true };
  }, true);
}

async function main() {
  const action = String(process.argv[2] || "status").toLowerCase();
  if (action === "status") return output(await status());
  if (action === "setup") {
    const launched = await ensureChrome("https://www.facebook.com/login/");
    return output({
      ok: true,
      launched,
      profile_root: profileRoot,
      username: configuredUsername,
      instruction: "Use facebook-login or sign in manually in the opened Chrome window.",
    });
  }
  if (action === "login") return output(await login());
  if (action === "profile") return output(await readProfile(process.argv[3]));
  if (action === "draft-message" || action === "send-message") {
    const target = process.argv[3];
    const message = process.argv.slice(4).join(" ");
    return output(await composeMessage(target, message, action === "send-message"));
  }
  throw new Error(`Unknown action: ${action}`);
}

main().catch((error) => output({
  ok: false,
  error: error.message || String(error),
  username: configuredUsername,
  profile_root: profileRoot,
}, 1));
