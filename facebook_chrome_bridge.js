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
const veridexBrowserRoot = String(
  process.env.VERIDEX_BROWSER_PROFILE_DIR
    || localEnv.VERIDEX_BROWSER_PROFILE_DIR
    || "",
).trim();
const sharedUserDataDir = String(
  process.env.VERIDEX_PP_CHROME_USER_DATA_DIR
    || localEnv.VERIDEX_PP_CHROME_USER_DATA_DIR
    || "",
).trim();
const useSharedProfile = /^(?:1|true|yes)$/i.test(String(
  process.env.VERIDEX_FACEBOOK_USE_SHARED_PP_PROFILE
    || localEnv.VERIDEX_FACEBOOK_USE_SHARED_PP_PROFILE
    || "false",
).trim());
const profileDirectory = String(
  process.env.VERIDEX_BROWSER_PROFILE_DIRECTORY
    || localEnv.VERIDEX_BROWSER_PROFILE_DIRECTORY
    || process.env.VERIDEX_FACEBOOK_PROFILE_DIRECTORY
    || localEnv.VERIDEX_FACEBOOK_PROFILE_DIRECTORY
    || (useSharedProfile ? (
      process.env.VERIDEX_PP_CHROME_PROFILE_DIRECTORY
        || localEnv.VERIDEX_PP_CHROME_PROFILE_DIRECTORY
        || localEnv.VERIDEX_EBAY_CHROME_PROFILE_DIRECTORY
    ) : "")
    || "Default",
).trim() || "Default";
const profileRoot = path.resolve(
  veridexBrowserRoot
    || process.env.VERIDEX_FACEBOOK_PROFILE_DIR
    || localEnv.VERIDEX_FACEBOOK_PROFILE_DIR
    || (useSharedProfile ? sharedUserDataDir : "")
    || path.join(repoRoot, "data", "browser_profiles", "veridex_browser"),
);
const debugPort = Number(
  process.env.VERIDEX_BROWSER_DEBUG_PORT
    || localEnv.VERIDEX_BROWSER_DEBUG_PORT
    || process.env.VERIDEX_PP_CHROME_DEBUG_PORT
    || localEnv.VERIDEX_PP_CHROME_DEBUG_PORT
    || process.env.VERIDEX_FACEBOOK_DEBUG_PORT
    || localEnv.VERIDEX_FACEBOOK_DEBUG_PORT
    || 9225,
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
      `--profile-directory=${profileDirectory}`,
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
  if (useSharedProfile && sharedUserDataDir) return "profile_opened_without_debugging";
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

function classifyFacebookCookies(cookies) {
  const names = new Set((Array.isArray(cookies) ? cookies : [])
    .filter((cookie) => /(^|\.)facebook\.com$/i.test(String(cookie && cookie.domain || "").replace(/^\./, "")))
    .map((cookie) => String(cookie && cookie.name || "")));
  const signedIn = names.has("c_user") && names.has("xs");
  return { signed_in: signedIn, evidence: signedIn ? "authenticated_cookie" : "login_cookie_absent" };
}

async function passiveFacebookSession() {
  const version = await getJson("/json/version");
  const targets = await getJson("/json/list");
  const target = (Array.isArray(targets) ? targets : []).find((row) => {
    if (row.type !== "page" || !row.webSocketDebuggerUrl) return false;
    try { return /(^|\.)facebook\.com$/i.test(new URL(String(row.url || "")).hostname); } catch (_) { return false; }
  });
  let page = null;
  if (target) {
    const client = new CdpClient(target.webSocketDebuggerUrl);
    try {
      await client.connect();
      page = await pageState(client);
    } finally {
      client.close();
    }
  }
  let cookieSession = { signed_in: false, evidence: "cookie_check_unavailable" };
  if (version && version.webSocketDebuggerUrl) {
    const client = new CdpClient(version.webSocketDebuggerUrl);
    try {
      await client.connect();
      const result = await client.send("Storage.getCookies");
      cookieSession = classifyFacebookCookies(result.cookies);
    } finally {
      client.close();
    }
  }
  const signedIn = Boolean(cookieSession.signed_in || (page && page.signed_in));
  return {
    signed_in: signedIn,
    session_evidence: page && page.signed_in ? page.session_evidence : cookieSession.evidence,
    requires_interaction: Boolean(!signedIn && page && page.checkpoint),
    page_url: page ? String(page.url || "") : "",
    passive: true,
  };
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

function classifyFacebookSession(state) {
  const value = state && typeof state === "object" ? state : {};
  let current;
  try { current = new URL(String(value.url || "")); } catch (_) { return { signed_in: false, evidence: "invalid_url" }; }
  const facebookHost = /(^|\.)facebook\.com$/i.test(current.hostname);
  const loginRoute = /^\/(?:login(?:\.php)?|recover|checkpoint|two_step_verification)(?:\/|$)/i.test(current.pathname);
  if (!facebookHost || value.checkpoint || value.login_form || loginRoute) {
    return { signed_in: false, evidence: value.checkpoint ? "checkpoint" : value.login_form || loginRoute ? "login" : "not_facebook" };
  }
  if (value.navigation_shell) return { signed_in: true, evidence: "authenticated_navigation" };
  if (/^\/(?:home\.php|me)(?:\/|$)/i.test(current.pathname)) {
    return { signed_in: true, evidence: "authenticated_route" };
  }
  return { signed_in: false, evidence: "inconclusive" };
}

async function withTab(url, callback, keepOpen = false) {
  await ensureChrome("https://www.facebook.com/");
  if (!(await endpointReady())) {
    throw new Error("The Provenance Pending Chrome profile is open, but its debugging endpoint is unavailable. Complete the visible browser step, then retry after starting Veridex with the configured PP debug port.");
  }
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

async function withExistingFacebookTab(url, callback) {
  if (!(await endpointReady())) {
    throw new Error("The PP Facebook browser is not connected to Veridex. Keep an existing Facebook tab open in the PP profile and start it with the configured debugging port; fetch will not open a new window.");
  }
  const targets = await getJson("/json/list");
  const target = (Array.isArray(targets) ? targets : []).find((row) => {
    if (row.type !== "page" || !row.webSocketDebuggerUrl) return false;
    try { return /(^|\.)facebook\.com$/i.test(new URL(String(row.url || "")).hostname); } catch (_) { return false; }
  });
  if (!target) throw new Error("No existing Facebook tab was found in the PP profile. Open Facebook there first; fetch will not open a new window.");
  const client = new CdpClient(target.webSocketDebuggerUrl);
  try {
    await client.connect();
    await client.send("Page.navigate", { url });
    await waitForDocument(client);
    return await callback(client, target);
  } finally {
    client.close();
  }
}

async function withBackgroundTab(url, callback) {
  if (!(await endpointReady())) {
    throw new Error("The Veridex browser is not connected. Start Veridex, then retry the Facebook group fetch.");
  }
  const version = await getJson("/json/version");
  if (!version || !version.webSocketDebuggerUrl) {
    throw new Error("The Veridex browser debugging connection is unavailable.");
  }
  // Do not borrow one of the user's New Tab pages as a scratch document.
  // That both interrupted their browsing and taught Chrome's New Tab page to
  // surface Facebook more often in its automatically generated site tiles.
  let target = null;
  const browser = new CdpClient(version.webSocketDebuggerUrl);
  let targetId = "";
  let createdTarget = false;
  let client = null;
  try {
    await browser.connect();
    const created = await browser.send("Target.createTarget", { url: "about:blank", background: true });
    targetId = String(created.targetId || "");
    createdTarget = true;
    if (!targetId) throw new Error("Chrome did not create a background Facebook page.");
    for (let attempt = 0; attempt < 20; attempt += 1) {
      const currentTargets = await getJson("/json/list");
      target = (Array.isArray(currentTargets) ? currentTargets : []).find((row) => row.id === targetId && row.webSocketDebuggerUrl);
      if (target) break;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    if (!target) throw new Error("The background Facebook page did not become available.");
    targetId = String(target.id || targetId);
    client = new CdpClient(target.webSocketDebuggerUrl);
    await client.connect();
    await client.send("Page.navigate", { url });
    await waitForDocument(client);
    return await callback(client, target);
  } finally {
    if (client) client.close();
    if (createdTarget && targetId) {
      try { await browser.send("Target.closeTarget", { targetId }); } catch (_) { /* best effort */ }
    }
    browser.close();
  }
}

async function pageState(client) {
  const state = await evaluate(client, `(() => {
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
      navigation_shell: nav,
    };
  })()`);
  const session = classifyFacebookSession(state);
  return { ...state, signed_in: session.signed_in, session_evidence: session.evidence };
}

async function waitForLoginState(client) {
  let state = await pageState(client);
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (state.signed_in || state.checkpoint || state.login_form) return state;
    await new Promise((resolve) => setTimeout(resolve, 250));
    state = await pageState(client);
  }
  return state;
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
      profile_directory: profileDirectory,
      shared_profile: Boolean(useSharedProfile && sharedUserDataDir),
      chrome_debugging: false,
      signed_in: false,
    };
  }
  const state = await passiveFacebookSession();
  return {
    ok: true,
    configured: Boolean(configuredUsername && configuredPassword),
    username: configuredUsername,
    profile_root: profileRoot,
    profile_directory: profileDirectory,
    shared_profile: Boolean(useSharedProfile && sharedUserDataDir),
    chrome_debugging: true,
    signed_in: Boolean(state.signed_in),
    session_evidence: String(state.session_evidence || "inconclusive"),
    requires_interaction: Boolean(state.checkpoint),
    page_url: state.url,
  };
}

async function login() {
  if (!configuredUsername || !configuredPassword) {
    throw new Error("FACEBOOK_USERNAME (or FACEBOOK_EMAIL) and FACEBOOK_PASSWORD must be set in local.env or .env.local.");
  }
  const launched = await ensureChrome("https://www.facebook.com/login/");
  if (!(await endpointReady())) {
    return {
      ok: true,
      signed_in: false,
      username: configuredUsername,
      launched,
      requires_interaction: true,
      profile_root: profileRoot,
      profile_directory: profileDirectory,
      shared_profile: Boolean(useSharedProfile && sharedUserDataDir),
      instruction: "Sign in or review Facebook in the visible Provenance Pending Chrome window, then refresh status.",
    };
  }
  return withTab("https://www.facebook.com/login/", async (client) => {
    const initial = await waitForLoginState(client);
    if (initial.signed_in) return { ok: true, signed_in: true, username: configuredUsername, already_signed_in: true };
    if (initial.checkpoint) {
      return {
        ok: true,
        signed_in: false,
        username: configuredUsername,
        requires_interaction: true,
        instruction: "Complete Facebook's security check in the visible Chrome window, then run facebook-status.",
      };
    }
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

function parseFacebookGroupSections(text) {
  const source = String(text || "");
  const lines = source.split(/\r?\n/).map((value) => value.replace(/\s+/g, " ").trim()).filter(Boolean);
  const unique = lines.filter((value, index) => index === 0 || value !== lines[index - 1]);
  const rulesStart = unique.findIndex((value) => /^(?:group\s+)?rules(?:\s+from\s+the\s+admins)?$/i.test(value));
  const aboutHeading = unique.findIndex((value) => /^about\s+this\s+group$/i.test(value));
  const aboutStart = aboutHeading >= 0 ? aboutHeading : unique.findIndex((value) => /^about$/i.test(value));
  const sectionEnd = (start, fallback) => {
    if (start < 0) return -1;
    const index = unique.findIndex((value, position) => position > start && position >= start + 2
      && /^(?:about|activity|members|media|events|featured|discussion|files|guides|photos|people)$/i.test(value));
    return index < 0 ? fallback : index;
  };
  const rulesEnd = sectionEnd(rulesStart, unique.length);
  const aboutFallback = rulesStart > aboutStart ? rulesStart : unique.length;
  const aboutEnd = sectionEnd(aboutStart, aboutFallback);
  const aboutLines = aboutStart >= 0 ? unique.slice(aboutStart + 1, aboutEnd) : [];
  const detailLabel = /^(?:Private|Public|Visible|Hidden|History|Tags|Location)$/i;
  const firstDetail = aboutLines.findIndex((value) => detailLabel.test(value));
  const lineAbout = aboutLines.slice(0, firstDetail < 0 ? aboutLines.length : firstDetail).join("\n");
  const lineRules = rulesStart >= 0 ? unique.slice(rulesStart + 1, rulesEnd).join("\n") : "";
  const compact = source.replace(/\s+/g, " ").trim();
  const inlineSection = (startPattern, endPattern) => {
    const start = compact.match(startPattern);
    if (!start || start.index == null) return "";
    const remainder = compact.slice(start.index + start[0].length).trim();
    const end = remainder.match(endPattern);
    return (end && end.index != null ? remainder.slice(0, end.index) : remainder).trim();
  };
  const inlineAbout = inlineSection(
    /\bAbout this group\b/i,
    /\b(?:Public\s+Anyone can see|Private\s+Only members can see|Visible\s+Anyone can find|Hidden\s+Only members can find|History\s+Group created|Group activity)\b/i,
  );
  const inlineRules = inlineSection(
    /\bGroup\s+rules(?:\s+from\s+the\s+admins)?\b/i,
    /\b(?:About|Activity|Members|Media|Events|Featured|Discussion|Files|Guides|Photos|People|History|Group activity)\b/i,
  );
  const narrativeAbout = [lineAbout, inlineAbout].sort((left, right) => right.length - left.length)[0] || "";
  const detailBlocks = new Map();
  const setDetailBlock = (key, block) => {
    const cleaned = String(block || "").split(/\r?\n/)
      .map((value) => value.replace(/\s+See (?:more|less)\s*$/i, "").trim())
      .filter((value) => value && !/^See more(?: group history)?$/i.test(value) && !/^See less$/i.test(value)).join("\n");
    if (!cleaned || cleaned.length > 600) return;
    const validators = {
      private: /Only members can see/i,
      public: /Anyone can see/i,
      visible: /Anyone can find/i,
      hidden: /Only members can find|can't find|cannot find/i,
      history: /Group created/i,
    };
    if (validators[key] && !validators[key].test(cleaned)) return;
    const existing = String(detailBlocks.get(key) || "");
    if (!existing || cleaned.length < existing.length) detailBlocks.set(key, cleaned);
  };
  for (let index = 0; index < unique.length; index += 1) {
    const label = unique[index];
    if (!detailLabel.test(label)) continue;
    const values = [];
    for (let position = index + 1; position < unique.length && values.length < 10; position += 1) {
      const value = unique[position];
      if (detailLabel.test(value) || /^(?:group\s+)?rules(?:\s+from\s+the\s+admins)?$|^(?:activity|members|media|events|featured|discussion|files|guides|photos|people)$/i.test(value)) break;
      const cleaned = value.replace(/\s+See (?:more|less)\s*$/i, "").trim();
      if (!/^See (?:more|less)$/i.test(cleaned) && cleaned) values.push(cleaned);
    }
    const key = label.toLowerCase();
    const locationIndex = values.findIndex((value) => /^[A-Za-z .'-]+,\s*[A-Za-z .'-]+$/.test(value) && !/^(?:account, your profile|facebook,|messenger,|notifications,)/i.test(value));
    if ((key === "history" || key === "tags") && locationIndex >= 0) {
      setDetailBlock("location", `Location\n${values[locationIndex]}`);
      values.splice(locationIndex, 1);
    }
    const block = [label, ...values].join("\n");
    setDetailBlock(key, block);
  }
  for (const segment of lines) {
    const inlineDetails = [
      ["private", segment.match(/\bPrivate\s+(.+?)(?=\s+(?:Visible|Hidden|History|Tags|Location)\b|$)/i)],
      ["public", segment.match(/\bPublic\s+(.+?)(?=\s+(?:Visible|Hidden|History|Tags|Location)\b|$)/i)],
      ["visible", segment.match(/\bVisible\s+(.+?)(?=\s+(?:Private|Public|History|Tags|Location)\b|$)/i)],
      ["hidden", segment.match(/\bHidden\s+(.+?)(?=\s+(?:Private|Public|History|Tags|Location)\b|$)/i)],
      ["history", segment.match(/\bHistory\s+(.+?)(?=\s+(?:Tags|Location)\b|$)/i)],
      ["tags", segment.match(/\bTags\s+(.+?)(?=\s+Location\b|$)/i)],
      ["location", segment.match(/\bLocation\s+(.+)$/i)],
    ];
    for (const [key, match] of inlineDetails) {
      if (!match) continue;
      const label = key.charAt(0).toUpperCase() + key.slice(1);
      const value = match[1].replace(/\s+See (?:more|less)\s*$/i, "").replace(/\s*[•·]\s*/g, "\n").trim();
      setDetailBlock(key, `${label}\n${value}`);
    }
  }
  const profile = {
    privacy: ["private", "public"].map((key) => detailBlocks.get(key)).filter(Boolean).join("\n"),
    visibility: ["visible", "hidden"].map((key) => detailBlocks.get(key)).filter(Boolean).join("\n"),
    history: String(detailBlocks.get("history") || ""),
    tags: String(detailBlocks.get("tags") || ""),
    location: String(detailBlocks.get("location") || ""),
  };
  const details = ["private", "public", "visible", "hidden", "history", "tags", "location"]
    .map((key) => detailBlocks.get(key)).filter(Boolean).join("\n");
  const about = [narrativeAbout, details ? `Group details\n${details}` : ""].filter(Boolean).join("\n\n");
  const rules = [lineRules, inlineRules].sort((left, right) => right.length - left.length)[0] || "";
  return {
    about: about.slice(0, 4000),
    narrative_about: narrativeAbout.slice(0, 4000),
    details_text: details.slice(0, 2000),
    rules_text: rules.slice(0, 6000),
    profile,
  };
}

function isCollapsedFacebookSection(value) {
  return /(?:^|\s)see more\s*$/i.test(String(value || "").trim());
}

function classifyFacebookGroupAccess(controlLabels) {
  const labels = Array.isArray(controlLabels) ? controlLabels.map((value) => String(value || "").trim().toLowerCase()) : [];
  const has = (pattern) => labels.some((value) => pattern.test(value));
  if (has(/^(?:cancel request|membership pending|pending)$/)) return { status: "pending", detail: "Facebook shows a pending membership request." };
  if (has(/^joined$/)) return { status: "joined", detail: "Facebook shows the account as joined." };
  if (has(/^join(?: group)?$/)) return { status: "not_joined", detail: "Facebook shows a Join control." };
  return { status: "unknown", detail: "Facebook did not expose a clear membership control." };
}

async function expandFacebookSeeMore(client, section = "all") {
  let expanded = 0;
  for (let pass = 0; pass < 4; pass += 1) {
    const clicked = Number(await evaluate(client, `(() => {
      const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
      const requestedSection = ${JSON.stringify(section)};
      const raw = Array.from(document.querySelectorAll('button, [role="button"], span'));
      const controls = [];
      for (const node of raw) {
        const label = clean(node.innerText || node.textContent || node.getAttribute('aria-label'));
        if (!/^see more$/i.test(label)) continue;
        const control = node.matches('button, [role="button"]') ? node : node.closest('button, [role="button"]');
        if (control && !controls.includes(control)) controls.push(control);
      }
      let count = 0;
      for (const control of controls) {
        let controlContext = control;
        let surroundingText = '';
        for (let depth = 0; controlContext && depth < 10; depth += 1, controlContext = controlContext.parentElement) {
          const value = clean(controlContext.innerText || controlContext.textContent);
          if (value.length > surroundingText.length && value.length < 1200) surroundingText = value;
        }
        if (requestedSection !== 'about' && /\\bHistory\\b.*\\bGroup created\\b/i.test(surroundingText)) continue;
        if (requestedSection === 'about') {
          let context = control;
          let belongsToAbout = false;
          for (let depth = 0; context && depth < 12; depth += 1, context = context.parentElement) {
            const text = clean(context.innerText || context.textContent);
            if (/\\babout this group\\b/i.test(text)) {
              belongsToAbout = true;
              break;
            }
          }
          // Facebook sometimes renders the description control outside the About heading's DOM subtree.
          // History controls are excluded above, so the remaining See more control is the description.
          void belongsToAbout;
        }
        control.click();
        count += 1;
        if (requestedSection === 'about') break;
      }
      return count;
    })()`)) || 0;
    expanded += clicked;
    if (!clicked) break;
    await new Promise((resolve) => setTimeout(resolve, 600));
  }
  return expanded;
}

async function facebookAccessibilityText(client) {
  try {
    await client.send("Accessibility.enable");
    const tree = await client.send("Accessibility.getFullAXTree");
    const values = [];
    for (const node of Array.isArray(tree.nodes) ? tree.nodes : []) {
      const role = String(node.role && node.role.value || "").toLowerCase();
      if (!/^(?:heading|statictext|link|button|listitem|paragraph|genericcontainer)$/.test(role)) continue;
      const value = String(node.name && node.name.value || "").replace(/\s+/g, " ").trim();
      if (value && values[values.length - 1] !== value) values.push(value);
    }
    return values.join("\n").slice(0, 16000);
  } catch (_) {
    return "";
  }
}

async function scrollFacebookAbout(client, position = "bottom") {
  await evaluate(client, `(() => {
    const direction = ${JSON.stringify(position)};
    const candidates = [document.scrollingElement, ...document.querySelectorAll('div')].filter(Boolean);
    for (const node of candidates) {
      if (node.scrollHeight <= node.clientHeight + 200) continue;
      node.scrollTop = direction === 'top' ? 0 : node.scrollHeight;
    }
    window.scrollTo(0, direction === 'top' ? 0 : Math.max(document.body?.scrollHeight || 0, document.documentElement?.scrollHeight || 0));
    return true;
  })()`);
  await new Promise((resolve) => setTimeout(resolve, 700));
}

async function readFacebookYourItems(client) {
  const locate = async () => evaluate(client, `(() => {
    const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
    const link = Array.from(document.querySelectorAll('a[href]')).find((node) => /^your items$/i.test(clean(node.innerText || node.textContent)));
    return link ? new URL(link.getAttribute('href'), location.origin).href : '';
  })()`);
  let href = await locate();
  if (!href) {
    await evaluate(client, `(() => {
      const node = Array.from(document.querySelectorAll('button,[role="button"]')).find((entry) => /^more$/i.test(String(entry.innerText || entry.textContent || '').trim()));
      if (node) node.click();
      return Boolean(node);
    })()`);
    await new Promise((resolve) => setTimeout(resolve, 400));
    href = await locate();
  }
  if (!href) return { available: false, count: 0, items: [], detail: "Facebook did not expose a Your items link for this group." };
  await client.send("Page.navigate", { url: href });
  await waitForDocument(client);
  return evaluate(client, `(() => {
    const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
    const articles = Array.from(document.querySelectorAll('[role="article"]')).map((node) => clean(node.innerText || node.textContent)).filter((value) => value && value.length > 8);
    const items = Array.from(new Set(articles)).slice(0, 20).map((value) => value.slice(0, 500));
    return { available: true, count: items.length, items, page_url: location.href, detail: items.length ? 'Visible Your items entries were sampled from Facebook and saved for reconciliation.' : 'Facebook opened Your items but showed no visible item cards.' };
  })()`);
}

async function readGroup(target) {
  const raw = String(target || "").trim();
  let url;
  if (!raw) throw new Error("Paste a Facebook group URL first.");
  try {
    url = new URL(raw);
  } catch (_) {
    throw new Error("The group URL is not valid. Use a full https://www.facebook.com/groups/... URL.");
  }
  if (!/(^|\.)facebook\.com$/i.test(url.hostname) || !/\/groups\//i.test(url.pathname)) throw new Error("The target must be a facebook.com group URL.");
  url.protocol = "https:"; url.hostname = "www.facebook.com";
  const groupPath = url.pathname.match(/^\/groups\/[^/]+/i)?.[0];
  if (!groupPath) throw new Error("The Facebook group URL does not include a group name or ID.");
  const groupUrl = new URL(`https://www.facebook.com${groupPath}/`);
  const aboutUrl = new URL(`${groupUrl.href}about`);
  return withBackgroundTab(aboutUrl.href, async (client) => {
    const state = await pageState(client);
    if (!state.signed_in) throw new Error("The dedicated Facebook profile is not signed in.");
    await new Promise((resolve) => setTimeout(resolve, 3000));
    let expanded_count = await expandFacebookSeeMore(client, "about");
    let bestData = {};
    let bestCombined = "";
    let bestNarrative = "";
    let bestCollapsedNarrative = "";
    let bestDetails = "";
    let bestRules = "";
    let bestScore = 0;
    let stableSamples = 0;
    for (let attempt = 0; attempt < 16; attempt += 1) {
      const data = await evaluate(client, `(() => {
        const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
        const cleanLines = (value) => String(value || '').split(/\\r?\\n/).map(clean).filter(Boolean).join('\\n');
        const titleName = clean(document.title).replace(/^\\(\\d+\\)\\s*/, '').replace(/\\s*\\|\\s*Facebook.*$/i, '');
        const heading = titleName || Array.from(document.querySelectorAll('h1, h2')).map((node) => clean(node.innerText || node.textContent)).find(Boolean);
        const membership_controls = Array.from(document.querySelectorAll('button, [role="button"]')).map((node) => clean(node.innerText || node.textContent || node.getAttribute('aria-label')))
          .filter((value) => /^(?:Joined|Join(?: group)?|Cancel request|Membership pending|Pending|Manage)$/i.test(value));
        const body = clean(document.body ? (document.body.innerText || document.body.textContent) : '').slice(0, 8000);
        const description = clean(document.querySelector('meta[name="description"], meta[property="og:description"]')?.content);
        let about_context = '';
        for (const node of Array.from(document.querySelectorAll('button, [role="button"], span'))) {
          if (!/^see more$/i.test(clean(node.innerText || node.textContent || node.getAttribute('aria-label')))) continue;
          const control = node.matches('button, [role="button"]') ? node : node.closest('button, [role="button"]');
          let current = control;
          for (let depth = 0; current && depth < 10; depth += 1, current = current.parentElement) {
            const raw = cleanLines(current.innerText || current.textContent);
            const compact = clean(raw);
            if (/\\b(?:Private|Public)\\b.*\\b(?:Visible|Hidden)\\b.*\\bHistory\\b/i.test(compact) && raw.length > about_context.length && raw.length < 4000) about_context = raw;
          }
        }
        const text = [description, about_context, body].filter(Boolean).filter((value, index, values) => values.indexOf(value) === index).join('\\n').slice(0, 10000);
        return { name: heading, text, about_context, membership_controls, url: location.href, title: document.title };
      })()`);
      const accessibility_text = await facebookAccessibilityText(client);
      const combined = [String(data.text || ""), accessibility_text].filter(Boolean).join("\n");
      const sections = parseFacebookGroupSections(combined);
      const access = classifyFacebookGroupAccess(data.membership_controls);
      const aboutCollapsed = isCollapsedFacebookSection(sections.narrative_about);
      if (aboutCollapsed) {
        if (sections.narrative_about.length > bestCollapsedNarrative.length) bestCollapsedNarrative = sections.narrative_about;
      } else if (sections.narrative_about.length > bestNarrative.length) {
        bestNarrative = sections.narrative_about;
      }
      if (sections.details_text.length > bestDetails.length) bestDetails = sections.details_text;
      if (sections.rules_text.length > bestRules.length) bestRules = sections.rules_text;
      const score = bestNarrative.length + bestDetails.length + bestRules.length;
      if (combined.length > bestCombined.length) bestCombined = combined;
      if (!bestData.name || score > bestScore) bestData = { ...data, facebook_access: access };
      else if (access.status !== "unknown" && bestData.facebook_access?.status === "unknown") bestData.facebook_access = access;
      stableSamples = bestNarrative && bestRules && Math.abs(score - bestScore) < 40 ? stableSamples + 1 : 0;
      bestScore = Math.max(bestScore, score);
      if (attempt >= 3 && stableSamples >= 2) break;
      if (attempt === 0) {
        await scrollFacebookAbout(client, "bottom");
        expanded_count += await expandFacebookSeeMore(client);
      }
      if (aboutCollapsed && attempt < 8) expanded_count += await expandFacebookSeeMore(client, "about");
      if (attempt === 1 || (attempt === 3 && score < 500)) expanded_count += await expandFacebookSeeMore(client);
      if (attempt === 2) {
        await scrollFacebookAbout(client, "top");
        expanded_count += await expandFacebookSeeMore(client, "about");
      }
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    const data = bestData;
    const narrative = bestNarrative || bestCollapsedNarrative;
    const profile = parseFacebookGroupSections(bestCombined).profile;
    const your_items = await readFacebookYourItems(client);
    const about = [narrative, bestDetails ? `Group details\n${bestDetails}` : ""].filter(Boolean).join("\n\n");
    const about_complete = Boolean(bestNarrative) && !isCollapsedFacebookSection(bestNarrative);
    return {
      ok: true,
      provider: "facebook_chrome_profile",
      target: groupUrl.href,
      ...data,
      url: groupUrl.href,
      page_url: String(data.url || aboutUrl.href),
      text: bestCombined.slice(0, 12000),
      about,
      about_complete,
      details_text: bestDetails,
      group_profile: profile,
      your_items,
      facebook_access: data.facebook_access || classifyFacebookGroupAccess(data.membership_controls),
      rules_text: bestRules,
      expanded_count,
    };
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

function readPayload() {
  return new Promise((resolve, reject) => {
    let body = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => { body += chunk; });
    process.stdin.on("end", () => {
      try { resolve(body.trim() ? JSON.parse(body) : {}); }
      catch (error) { reject(new Error("Facebook bridge payload was not valid JSON.")); }
    });
    process.stdin.on("error", reject);
  });
}

async function setFileInputFiles(client, files) {
  if (!Array.isArray(files) || !files.length) throw new Error("At least one verified image path is required.");
  await client.send("DOM.enable");
  const documentNode = await client.send("DOM.getDocument", { depth: -1, pierce: true });
  const found = await client.send("DOM.querySelector", {
    nodeId: documentNode.root.nodeId,
    selector: 'input[type="file"]',
  });
  if (!found.nodeId) throw new Error("Facebook's Marketplace photo control was not found.");
  await client.send("DOM.setFileInputFiles", { nodeId: found.nodeId, files });
  await new Promise((resolve) => setTimeout(resolve, 1800));
}

async function fillMarketplaceFields(client, draft) {
  const fields = {
    title: String(draft.title || ""),
    price: String(draft.price ?? ""),
    category: String(draft.category || ""),
    condition: String(draft.condition || "good").replaceAll("_", " "),
    description: String(draft.description || ""),
  };
  return evaluate(client, `(() => {
    const requested = ${JSON.stringify(fields)};
    const visible = (node) => Boolean(node && (node.offsetWidth || node.offsetHeight || node.getClientRects().length));
    const label = (node) => String(node && (node.getAttribute('aria-label') || node.getAttribute('placeholder') || node.innerText || node.textContent) || '').replace(/\\s+/g, ' ').trim();
    const controls = Array.from(document.querySelectorAll('input, textarea, [contenteditable="true"][role="textbox"]')).filter(visible);
    const setValue = (node, value) => {
      node.focus();
      if (node.tagName === 'INPUT') {
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
        setter.call(node, value);
      } else if (node.tagName === 'TEXTAREA') {
        const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
        setter.call(node, value);
      } else {
        node.textContent = value;
      }
      node.dispatchEvent(new Event('input', { bubbles: true }));
      node.dispatchEvent(new Event('change', { bubbles: true }));
      node.dispatchEvent(new Event('blur', { bubbles: true }));
    };
    const find = (patterns) => controls.find((node) => patterns.some((pattern) => pattern.test(label(node))));
    const title = find([/^title$/i, /listing title/i]);
    const price = find([/^price$/i, /asking price/i]);
    const description = find([/^description$/i, /describe.*item/i]);
    if (title) setValue(title, requested.title);
    if (price) setValue(price, requested.price);
    if (description) setValue(description, requested.description);
    const clickChoice = (fieldPattern, requestedValue) => {
      const buttons = Array.from(document.querySelectorAll('[role="button"], [role="combobox"], button')).filter(visible);
      const control = buttons.find((node) => fieldPattern.test(label(node)));
      if (!control) return false;
      control.click();
      return true;
    };
    return {
      title: Boolean(title),
      price: Boolean(price),
      description: Boolean(description),
      category_opened: clickChoice(/category/i, requested.category),
      condition_opened: false,
      requested_category: requested.category,
      requested_condition: requested.condition,
      page_url: location.href,
    };
  })()`);
}

async function chooseOpenMarketplaceOption(client, requestedValue) {
  const chosen = await evaluate(client, `(() => {
    const requested = ${JSON.stringify(String(requestedValue || ""))}.toLowerCase().replace(/[_-]+/g, ' ').replace(/\\s+/g, ' ').trim();
    if (!requested) return false;
    const visible = (node) => Boolean(node && (node.offsetWidth || node.offsetHeight || node.getClientRects().length));
    const text = (node) => String(node.innerText || node.textContent || node.getAttribute('aria-label') || '').toLowerCase().replace(/[_-]+/g, ' ').replace(/\\s+/g, ' ').trim();
    const candidates = Array.from(document.querySelectorAll('[role="option"], [role="menuitem"], [role="radio"], div[tabindex="0"]')).filter(visible);
    const exact = candidates.find((node) => text(node) === requested);
    const partial = candidates.find((node) => text(node).includes(requested) || requested.includes(text(node)));
    const match = exact || partial;
    if (!match) return false;
    match.click();
    return true;
  })()`);
  if (chosen) await new Promise((resolve) => setTimeout(resolve, 700));
  return Boolean(chosen);
}

async function openMarketplaceChoice(client, pattern) {
  const opened = await evaluate(client, `(() => {
    const pattern = new RegExp(${JSON.stringify(pattern)}, 'i');
    const visible = (node) => Boolean(node && (node.offsetWidth || node.offsetHeight || node.getClientRects().length));
    const label = (node) => String(node.getAttribute('aria-label') || node.innerText || node.textContent || '').replace(/\\s+/g, ' ').trim();
    const candidates = Array.from(document.querySelectorAll('[role="button"], [role="combobox"], button')).filter(visible);
    const control = candidates.find((node) => pattern.test(label(node)));
    if (!control) return false;
    control.click();
    return true;
  })()`);
  if (opened) await new Promise((resolve) => setTimeout(resolve, 700));
  return Boolean(opened);
}

async function prepareMarketplace(payload) {
  const draft = payload && payload.draft && typeof payload.draft === "object" ? payload.draft : {};
  const imagePaths = Array.isArray(payload.image_paths) ? payload.image_paths.map(String) : [];
  if (!String(draft.title || "").trim()) throw new Error("Marketplace draft title is required.");
  return withTab("https://www.facebook.com/marketplace/create/item", async (client) => {
    const initial = await pageState(client);
    if (initial.checkpoint) {
      return { ok: true, status: "human_action_required", page_url: initial.url, instruction: "Complete Facebook's security check in the visible Chrome window, then retry preparation." };
    }
    if (!initial.signed_in) throw new Error("The dedicated Facebook profile is not signed in. Run facebook-login first.");
    await setFileInputFiles(client, imagePaths);
    const fields = await fillMarketplaceFields(client, draft);
    if (fields.category_opened) await chooseOpenMarketplaceOption(client, draft.category);
    const conditionOpened = await openMarketplaceChoice(client, "condition");
    const conditionSelected = conditionOpened ? await chooseOpenMarketplaceOption(client, String(draft.condition || "good").replaceAll("_", " ")) : false;
    const finalState = await pageState(client);
    if (finalState.checkpoint) {
      return { ok: true, status: "human_action_required", page_url: finalState.url, instruction: "Complete Facebook's security check in the visible Chrome window, then retry preparation." };
    }
    if (!fields.title || !fields.price || !fields.description) {
      return {
        ok: true,
        status: "human_action_required",
        page_url: finalState.url,
        fields,
        instruction: "Facebook changed or withheld one or more Marketplace fields. Finish the visible form manually; Veridex did not click Next or Publish.",
      };
    }
    return {
      ok: true,
      status: "facebook_prepared",
      page_url: finalState.url,
      fields: { ...fields, condition_selected: conditionSelected },
      publish_clicked: false,
      instruction: "Review every visible field in Facebook, choose any account-specific options, then click Next and Publish yourself.",
    };
  }, true);
}

async function resumeMarketplace(payload) {
  const draft = payload && payload.draft && typeof payload.draft === "object" ? payload.draft : {};
  const title = String(draft.title || "").replace(/\s+/g, " ").trim();
  if (!title) throw new Error("Marketplace draft title is required.");
  return withTab("https://www.facebook.com/marketplace/you/selling", async (client) => {
    const state = await pageState(client);
    if (state.checkpoint) return { ok: true, status: "human_action_required", page_url: state.url, instruction: "Complete Facebook's security check, then resume again." };
    if (!state.signed_in) throw new Error("The dedicated Facebook profile is not signed in. Run facebook-login first.");
    const evidence = await evaluate(client, `(() => {
      const expected = ${JSON.stringify(title)}.toLowerCase();
      const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
      const anchors = Array.from(document.querySelectorAll('a[href*="/marketplace/item/"]'));
      const cardText = (node) => {
        let current = node;
        for (let depth = 0; current && depth < 6; depth += 1, current = current.parentElement) {
          const value = clean(current.innerText || current.textContent);
          if (value.length <= 1200 && value.toLowerCase().includes(expected)) return value;
        }
        return '';
      };
      const match = anchors.find((node) => clean(node.innerText || node.textContent).toLowerCase().includes(expected))
        || anchors.find((node) => Boolean(cardText(node)));
      if (!match) return { matched: false, visible_text: clean(document.body && document.body.innerText).slice(0, 1200) };
      return { matched: true, listing_url: new URL(match.getAttribute('href'), location.origin).href, visible_title: clean(match.innerText || match.textContent) || cardText(match), page_url: location.href };
    })()`);
    if (!evidence.matched || !evidence.listing_url) {
      return {
        ok: true,
        status: "human_action_required",
        page_url: state.url,
        instruction: "No matching published listing is visibly available yet. Publish it in Facebook, then resume again.",
      };
    }
    return { ok: true, status: "published_observed", listing_url: evidence.listing_url, page_url: evidence.page_url, visible_title: evidence.visible_title };
  });
}

async function prepareGroupShare(payload) {
  const draft = payload && payload.draft && typeof payload.draft === "object" ? payload.draft : {};
  const group = payload && payload.group && typeof payload.group === "object" ? payload.group : {};
  const listingUrl = String(draft.listing_url || "").trim();
  const groupUrl = String(group.url || "").trim();
  if (!/^https:\/\/www\.facebook\.com\/marketplace\/item\//i.test(listingUrl)) throw new Error("A verified Facebook Marketplace listing URL is required.");
  if (!/^https:\/\/www\.facebook\.com\/groups\/[A-Za-z0-9._-]+$/i.test(groupUrl)) throw new Error("An approved Facebook group URL is required.");
  const postText = `${String(draft.title || "").trim()}\n${listingUrl}`;
  return withTab(groupUrl, async (client) => {
    const state = await pageState(client);
    if (state.checkpoint) return { ok: true, status: "human_action_required", group_id: group.group_id, page_url: state.url, instruction: "Complete Facebook's security check, then retry the group preparation." };
    if (!state.signed_in) throw new Error("The dedicated Facebook profile is not signed in. Run facebook-login first.");
    const opened = await evaluate(client, `(() => {
      const visible = (node) => Boolean(node && (node.offsetWidth || node.offsetHeight || node.getClientRects().length));
      const text = (node) => String(node.innerText || node.textContent || node.getAttribute('aria-label') || '').replace(/\\s+/g, ' ').trim();
      const candidates = Array.from(document.querySelectorAll('[role="button"], button')).filter(visible);
      const control = candidates.find((node) => /write something|create (?:a )?post|what(?:'s| is) on your mind/i.test(text(node)));
      if (!control) return false;
      control.click();
      return true;
    })()`);
    if (opened) await new Promise((resolve) => setTimeout(resolve, 1200));
    const composed = await evaluate(client, `(() => {
      const requested = ${JSON.stringify(postText)};
      const visible = (node) => Boolean(node && (node.offsetWidth || node.offsetHeight || node.getClientRects().length));
      const boxes = Array.from(document.querySelectorAll('div[contenteditable="true"][role="textbox"], textarea')).filter(visible);
      const box = boxes[boxes.length - 1];
      if (!box) return { ready: false };
      const existing = String(box.value || box.innerText || box.textContent || '').replace(/\\s+/g, ' ').trim();
      if (existing && existing !== requested.replace(/\\s+/g, ' ').trim()) return { ready: false, conflict: true };
      box.focus();
      if (!existing && box.tagName === 'TEXTAREA') {
        const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
        setter.call(box, requested);
        box.dispatchEvent(new Event('input', { bubbles: true }));
      }
      return { ready: true, tag: box.tagName, existing: Boolean(existing) };
    })()`);
    if (!composed.ready) {
      return { ok: true, status: "human_action_required", group_id: group.group_id, page_url: state.url, instruction: composed.conflict ? "A different unsent group post is already present. Review it manually." : "Facebook's group composer was not found. Open it manually and paste the verified listing URL." };
    }
    if (!composed.existing && composed.tag !== "TEXTAREA") await client.send("Input.insertText", { text: postText });
    return {
      ok: true,
      status: "group_share_prepared",
      group_id: String(group.group_id || ""),
      page_url: groupUrl,
      post_clicked: false,
      instruction: "Review the visible group post and click Post yourself.",
    };
  }, true);
}

async function main() {
  const action = String(process.argv[2] || "status").toLowerCase();
  if (action === "status") return output(await status());
  if (action === "setup") {
    const launched = await ensureChrome("https://www.facebook.com/login/");
    if (!(await endpointReady())) {
      throw new Error("Chrome opened the PP profile, but it is already owned by another Chrome process and is not debugging. Close all Chrome windows, then run the PP Facebook profile setup once; after that, Fetch will reuse the existing tab and will not open another window.");
    }
    return output({
      ok: true,
      launched,
      profile_root: profileRoot,
      profile_directory: profileDirectory,
      shared_profile: Boolean(useSharedProfile && sharedUserDataDir),
      username: configuredUsername,
      instruction: "Use facebook-login or sign in manually in the opened Chrome window.",
    });
  }
  if (action === "login") return output(await login());
  if (action === "profile") return output(await readProfile(process.argv[3]));
  if (action === "group-info") return output(await readGroup(process.argv[3]));
  if (action === "draft-message" || action === "send-message") {
    const target = process.argv[3];
    const message = process.argv.slice(4).join(" ");
    return output(await composeMessage(target, message, action === "send-message"));
  }
  if (action === "marketplace-prepare") return output(await prepareMarketplace(await readPayload()));
  if (action === "marketplace-resume") return output(await resumeMarketplace(await readPayload()));
  if (action === "group-share-prepare") return output(await prepareGroupShare(await readPayload()));
  throw new Error(`Unknown action: ${action}`);
}

if (require.main === module) {
  main().catch((error) => output({
    ok: false,
    error: error.message || String(error),
    username: configuredUsername,
    profile_root: profileRoot,
  }, 1));
}

module.exports = { classifyFacebookCookies, classifyFacebookSession, classifyFacebookGroupAccess, isCollapsedFacebookSection, parseFacebookGroupSections };
