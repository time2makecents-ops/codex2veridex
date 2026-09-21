"use strict";

const fs = require("fs");
const http = require("http");
const path = require("path");
const { spawn } = require("child_process");

const repoRoot = __dirname;

function readLocalEnv() {
  const values = {};
  const candidate = path.join(repoRoot, ".env.local");
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

const localEnv = readLocalEnv();
const profileRoot = path.resolve(
  process.env.VERIDEX_INSTAGRAM_PROFILE_DIR
    || localEnv.VERIDEX_INSTAGRAM_PROFILE_DIR
    || path.join(repoRoot, "data", "browser_profiles", "veridex_instagram"),
);
const debugPort = Number(
  process.env.VERIDEX_INSTAGRAM_DEBUG_PORT || localEnv.VERIDEX_INSTAGRAM_DEBUG_PORT || 9224,
);
const configuredUsername = String(process.env.INSTAGRAM_USERNAME || localEnv.INSTAGRAM_USERNAME || "").trim();
const configuredPassword = String(process.env.INSTAGRAM_PASSWORD || localEnv.INSTAGRAM_PASSWORD || "");

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
  throw new Error("The dedicated Instagram Chrome profile did not become available.");
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
      this.socket.addEventListener("error", () => reject(new Error("Could not connect to the Instagram browser tab.")), { once: true });
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
    throw new Error(description || result.exceptionDetails.text || "Instagram page script failed.");
  }
  return result.result && result.result.value ? result.result.value : {};
}

async function withTab(url, callback, keepOpen = false) {
  await ensureChrome("https://www.instagram.com/");
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
    const text = String(document.body ? document.body.innerText : "").slice(0, 12000);
    const loginForm = Boolean(document.querySelector('input[name="username"], input[name="email"], input[name="password"], input[name="pass"]'));
    const nav = Boolean(document.querySelector('a[href="/direct/inbox/"], a[href^="/accounts/edit"], svg[aria-label="Home"]'));
    const ownProfileControls = /\\bedit profile\\b/i.test(text) && /\\bview archive\\b/i.test(text);
    const reserved = new Set(['accounts','direct','explore','reels','stories','about','developer','legal','web']);
    const profileLinks = Array.from(document.querySelectorAll('a[href]')).map((node) => {
      const match = String(node.getAttribute('href') || '').match(new RegExp('^/([A-Za-z0-9._]+)/?$'));
      if (!match || reserved.has(match[1].toLowerCase())) return '';
      const label = String(node.getAttribute('aria-label') || node.innerText || '').toLowerCase();
      const isProfile = /profile/.test(label) || node.querySelector('img[alt*="profile" i]');
      return isProfile ? match[1] : '';
    }).filter(Boolean);
    const pathHandle = String(location.pathname || '').match(new RegExp('^/([A-Za-z0-9._]+)/?$'));
    const activeUsername = profileLinks[0] || (ownProfileControls && pathHandle ? pathHandle[1] : '');
    return { title: document.title, url: location.href, text, login_form: loginForm, signed_in: (nav || ownProfileControls) && !loginForm, active_username: activeUsername };
  })()`);
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
  const statusUrl = configuredUsername
    ? `https://www.instagram.com/${encodeURIComponent(configuredUsername)}/`
    : "https://www.instagram.com/";
  const state = await withTab(statusUrl, (client) => pageState(client));
  return {
    ok: true,
    configured: Boolean(configuredUsername && configuredPassword),
    username: configuredUsername,
    profile_root: profileRoot,
    chrome_debugging: true,
    signed_in: Boolean(state.signed_in),
    active_username: state.active_username || "",
    account_matches: Boolean(state.signed_in && state.active_username && state.active_username.toLowerCase() === configuredUsername.toLowerCase()),
    page_url: state.url,
  };
}

async function login() {
  if (!configuredUsername || !configuredPassword) {
    throw new Error("INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD must be set in .env.local.");
  }
  return withTab("https://www.instagram.com/accounts/login/", async (client) => {
    const initial = await pageState(client);
    if (initial.signed_in) return { ok: true, signed_in: true, username: configuredUsername, already_signed_in: true };
    let readiness = { ready: false, page: "" };
    for (let attempt = 0; attempt < 40; attempt += 1) {
      readiness = await evaluate(client, `(() => {
        const consent = Array.from(document.querySelectorAll('button')).find((node) => /allow all cookies|only allow essential cookies|decline optional cookies/i.test(node.innerText || ''));
        if (consent) consent.click();
        const username = document.querySelector('input[name="username"], input[name="email"], input[autocomplete^="username"], input[aria-label*="Phone number" i], input[aria-label*="Mobile number" i], input[aria-label*="username" i]');
        const password = document.querySelector('input[name="password"], input[name="pass"], input[autocomplete="current-password"], input[type="password"]');
        return {
          ready: Boolean(username && password),
          page: String(document.body ? document.body.innerText : '').slice(0, 300),
          fields: Array.from(document.querySelectorAll('input')).map((node) => ({
            name: node.name || '', type: node.type || '', aria: node.getAttribute('aria-label') || '',
            autocomplete: node.autocomplete || '', placeholder: node.placeholder || '',
          })).slice(0, 10),
        };
      })()`);
      if (readiness.ready) break;
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    const result = await evaluate(client, `(() => {
      const username = document.querySelector('input[name="username"], input[name="email"], input[autocomplete^="username"], input[aria-label*="Phone number" i], input[aria-label*="Mobile number" i], input[aria-label*="username" i]');
      const password = document.querySelector('input[name="password"], input[name="pass"], input[autocomplete="current-password"], input[type="password"]');
      if (!username || !password) return { submitted: false, reason: "login_form_missing" };
      const setValue = (node, value) => {
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
        setter.call(node, value);
        node.dispatchEvent(new Event("input", { bubbles: true }));
        node.dispatchEvent(new Event("change", { bubbles: true }));
      };
      setValue(username, ${JSON.stringify(configuredUsername)});
      setValue(password, ${JSON.stringify(configuredPassword)});
      const button = Array.from(document.querySelectorAll('button, div[role="button"], input[type="submit"]')).find((node) => /^log in$/i.test(String(node.innerText || node.value || node.getAttribute('aria-label') || '').trim()));
      if (!button) return { submitted: false, reason: "login_button_missing" };
      button.click();
      return { submitted: true };
    })()`);
    if (!result.submitted) {
      const page = String(readiness.page || "").replace(/\s+/g, " ").trim().slice(0, 240);
      const fields = JSON.stringify(readiness.fields || []);
      throw new Error(`Instagram login could not be submitted: ${result.reason || "unknown"}.${page ? ` Page says: ${page}` : ""} Fields: ${fields}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 5000));
    const finalState = await pageState(client);
    const challenge = /challenge|two.factor|security|checkpoint/i.test(String(finalState.url || ""))
      || /enter.*code|confirm.*identity|suspicious login/i.test(String(finalState.text || ""));
    return {
      ok: true,
      username: configuredUsername,
      signed_in: Boolean(finalState.signed_in),
      active_username: finalState.active_username || "",
      account_matches: Boolean(finalState.signed_in && finalState.active_username && finalState.active_username.toLowerCase() === configuredUsername.toLowerCase()),
      requires_interaction: challenge || !finalState.signed_in,
      page_url: finalState.url,
      instruction: challenge || !finalState.signed_in ? "Complete the visible Instagram security or 2FA prompt in Chrome." : "Instagram login succeeded.",
    };
  }, true);
}

function normalizeHandle(value) {
  const handle = String(value || "").trim().replace(/^@/, "");
  if (!/^[A-Za-z0-9._]{1,30}$/.test(handle)) throw new Error("A valid Instagram handle is required.");
  return handle;
}

async function readProfile(handle) {
  const normalized = normalizeHandle(handle);
  return withTab(`https://www.instagram.com/${encodeURIComponent(normalized)}/`, async (client) => {
    const state = await pageState(client);
    if (!state.signed_in) throw new Error("The dedicated Instagram profile is not signed in. Run instagram-login first.");
    const data = await evaluate(client, `(() => {
      const root = document.querySelector('main') || document.body;
      return {
        title: document.title,
        url: location.href,
        text: String(root ? root.innerText : "").slice(0, 12000),
        links: Array.from((root || document).querySelectorAll('a[href]')).map((a) => ({ title: String(a.innerText || a.getAttribute('aria-label') || '').trim(), url: a.href })).filter((x) => x.title).slice(0, 40),
      };
    })()`);
    return { ok: true, provider: "instagram_chrome_profile", handle: normalized, ...data };
  });
}

async function followAccount(handle) {
  const normalized = normalizeHandle(handle);
  return withTab(`https://www.instagram.com/${encodeURIComponent(normalized)}/`, async (client) => {
    const state = await pageState(client);
    if (!state.signed_in) throw new Error("The dedicated Instagram profile is not signed in. Run instagram-login first.");
    const result = await evaluate(client, `(() => {
      const labels = (node) => String(node.innerText || node.textContent || node.getAttribute('aria-label') || '').trim();
      const controls = Array.from(document.querySelectorAll('button, div[role="button"]'));
      const current = controls.find((node) => /^(following|requested)$/i.test(labels(node)));
      if (current) return { clicked: false, status: labels(current).toLowerCase() };
      const follow = controls.find((node) => /^follow$/i.test(labels(node)));
      if (!follow) return { clicked: false, status: 'follow_control_missing' };
      follow.click();
      return { clicked: true, status: 'clicked' };
    })()`);
    if (result.status === "follow_control_missing") throw new Error("Instagram did not expose a Follow control for this profile.");
    if (!result.clicked) {
      return { ok: true, handle: normalized, status: result.status, followed: result.status === "following", already_active: true };
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
    const finalStatus = await evaluate(client, `(() => {
      const labels = (node) => String(node.innerText || node.textContent || node.getAttribute('aria-label') || '').trim();
      const control = Array.from(document.querySelectorAll('button, div[role="button"]')).find((node) => /^(following|requested)$/i.test(labels(node)));
      return control ? labels(control).toLowerCase() : 'unverified';
    })()`);
    if (!['following', 'requested'].includes(finalStatus)) {
      throw new Error("Instagram did not confirm the follow action; no retry was attempted.");
    }
    return { ok: true, handle: normalized, status: finalStatus, followed: finalStatus === "following", requested: finalStatus === "requested" };
  }, true);
}

async function createPost(imageFile, caption) {
  const imagePath = path.resolve(String(imageFile || ""));
  const body = String(caption || "").trim();
  if (!fs.existsSync(imagePath) || !fs.statSync(imagePath).isFile()) throw new Error("The Instagram post image was not found.");
  if (!/\.(?:jpe?g|png|webp)$/i.test(imagePath)) throw new Error("Instagram post images must be JPEG, PNG, or WebP files.");
  if (!body) throw new Error("An Instagram post caption is required.");
  return withTab("https://www.instagram.com/", async (client) => {
    const state = await pageState(client);
    if (!state.signed_in) throw new Error("The dedicated Instagram profile is not signed in. Run instagram-login first.");
    const opened = await evaluate(client, `(() => {
      const label = (node) => String(node.innerText || node.textContent || node.getAttribute('aria-label') || '').trim();
      const icon = document.querySelector('svg[aria-label="New post"], svg[aria-label="Create"], [aria-label="New post"], [aria-label="Create"]');
      const candidate = (icon && icon.closest('a, button, div[role="button"]'))
        || Array.from(document.querySelectorAll('a, button, div[role="button"]')).find((node) => /^create$/i.test(label(node)) || /^new post$/i.test(String(node.getAttribute('aria-label') || '').trim()));
      if (!candidate) return false;
      candidate.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
      candidate.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
      candidate.click();
      return true;
    })()`);
    if (!opened) throw new Error("Instagram did not expose its Create control.");
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await client.send("DOM.enable");
    let inputNodeId = 0;
    for (let attempt = 0; attempt < 30; attempt += 1) {
      const document = await client.send("DOM.getDocument", { depth: -1, pierce: true });
      const query = await client.send("DOM.querySelector", { nodeId: document.root.nodeId, selector: 'input[type="file"]' });
      inputNodeId = Number(query.nodeId || 0);
      if (inputNodeId) break;
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    if (!inputNodeId) {
      const diagnostic = await evaluate(client, `(() => ({
        page: String(document.body ? document.body.innerText : '').replace(/\\s+/g, ' ').trim().slice(0, 500),
        inputs: Array.from(document.querySelectorAll('input')).map((node) => ({ type: node.type || '', accept: node.accept || '', aria: node.getAttribute('aria-label') || '' })).slice(0, 20),
      }))()`);
      throw new Error(`Instagram's image upload control was not found. Page says: ${diagnostic.page || ''} Inputs: ${JSON.stringify(diagnostic.inputs || [])}`);
    }
    await client.send("DOM.setFileInputFiles", { nodeId: inputNodeId, files: [imagePath] });
    await new Promise((resolve) => setTimeout(resolve, 3500));
    for (let step = 0; step < 2; step += 1) {
      const advanced = await evaluate(client, `(() => {
        const label = (node) => String(node.innerText || node.textContent || node.getAttribute('aria-label') || '').trim();
        const root = document.querySelector('div[role="dialog"]') || document;
        const button = Array.from(root.querySelectorAll('button, div[role="button"]')).find((node) => /^next$/i.test(label(node)));
        if (!button) return false;
        button.click();
        return true;
      })()`);
      if (!advanced) throw new Error(`Instagram's post editor did not expose Next step ${step + 1}.`);
      await new Promise((resolve) => setTimeout(resolve, 2500));
    }
    let prepared = { ready: false };
    for (let attempt = 0; attempt < 30; attempt += 1) {
      prepared = await evaluate(client, `(() => {
        const root = document.querySelector('div[role="dialog"]') || document;
        const box = root.querySelector('textarea[aria-label*="caption" i], textarea[placeholder*="caption" i], div[contenteditable="true"][aria-label*="caption" i]');
        if (!box) return { ready: false };
        box.focus();
        if (box.tagName === 'TEXTAREA') {
          const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
          setter.call(box, ${JSON.stringify(body)});
          box.dispatchEvent(new Event('input', { bubbles: true }));
          box.dispatchEvent(new Event('change', { bubbles: true }));
        }
        return { ready: true, tag: box.tagName };
      })()`);
      if (prepared.ready) break;
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    if (!prepared.ready) {
      const diagnostic = await evaluate(client, `(() => ({
        page: String(document.body ? document.body.innerText : '').replace(/\\s+/g, ' ').trim().slice(0, 700),
        fields: Array.from(document.querySelectorAll('textarea, input, [contenteditable]')).map((node) => ({
          tag: node.tagName, type: node.type || '', role: node.getAttribute('role') || '',
          aria: node.getAttribute('aria-label') || '', placeholder: node.getAttribute('placeholder') || '',
          contenteditable: node.getAttribute('contenteditable') || '',
        })).slice(0, 30),
      }))()`);
      throw new Error(`Instagram's caption editor was not found. Page says: ${diagnostic.page || ''} Fields: ${JSON.stringify(diagnostic.fields || [])}`);
    }
    if (prepared.tag !== "TEXTAREA") await client.send("Input.insertText", { text: body });
    await new Promise((resolve) => setTimeout(resolve, 400));
    const entered = await evaluate(client, `(() => {
      const root = document.querySelector('div[role="dialog"]') || document;
      const box = root.querySelector('textarea[aria-label*="caption" i], textarea[placeholder*="caption" i], div[contenteditable="true"][aria-label*="caption" i]');
      return box ? String(box.value || box.innerText || box.textContent || '').trim() : '';
    })()`);
    if (String(entered || '').replace(/\s+/g, ' ').trim() !== body.replace(/\s+/g, ' ').trim()) {
      throw new Error("Instagram's caption did not match the reviewed caption, so the post was not submitted.");
    }
    // Instagram requires disclosure for realistic AI-generated imagery. Enable
    // the disclosure when the current editor exposes the Add AI label control.
    const aiLabel = await evaluate(client, `(() => {
      const label = (node) => String(node.innerText || node.textContent || node.getAttribute('aria-label') || '').trim();
      const root = document.querySelector('div[role="dialog"]') || document;
      const candidates = Array.from(root.querySelectorAll('button, div[role="button"], label, input[role="switch"]'));
      const control = candidates.find((node) => /add ai label/i.test(label(node)) || /add ai label/i.test(String(node.getAttribute('aria-label') || '')));
      if (!control) return { found: false, enabled: false };
      const checkbox = control.matches('input[role="switch"]') ? control : control.querySelector('input[role="switch"], input[type="checkbox"]');
      const checked = checkbox && (checkbox.checked || checkbox.getAttribute('aria-checked') === 'true');
      if (!checked) (checkbox || control).click();
      return { found: true, enabled: !checked };
    })()`);
    if (aiLabel.found) await new Promise((resolve) => setTimeout(resolve, 400));
    const shared = await evaluate(client, `(() => {
      const label = (node) => String(node.innerText || node.textContent || node.getAttribute('aria-label') || '').trim();
      const root = document.querySelector('div[role="dialog"]') || document;
      const button = Array.from(root.querySelectorAll('button, div[role="button"]')).find((node) => /^share$/i.test(label(node)));
      if (!button) return false;
      button.click();
      return true;
    })()`);
    if (!shared) throw new Error("Instagram's Share control was not found; the post remains in the editor.");
    for (let attempt = 0; attempt < 40; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 500));
      const outcome = await evaluate(client, `(() => {
        const text = String(document.body ? document.body.innerText : '');
        if (/your post has been shared|post shared/i.test(text)) return 'posted';
        if (/something went wrong|couldn't post|could not post/i.test(text)) return 'failed';
        return 'pending';
      })()`);
      if (outcome === "posted") return { ok: true, status: "posted", posted: true, image_path: imagePath };
      if (outcome === "failed") throw new Error("Instagram reported that the post could not be shared.");
    }
    throw new Error("Instagram did not confirm whether the post was shared; no retry was attempted.");
  }, true);
}

async function inspectCreateDialog() {
  if (!(await endpointReady())) throw new Error("The dedicated Instagram Chrome profile is not running.");
  const targets = await getJson("/json/list");
  const target = targets.find((item) => item.type === "page" && /create new post/i.test(String(item.title || "")));
  if (!target) throw new Error("No open Instagram Create post dialog was found.");
  const client = new CdpClient(target.webSocketDebuggerUrl);
  try {
    await client.connect();
    const diagnostic = await evaluate(client, `(() => ({
      page: String(document.body ? document.body.innerText : '').replace(/\\s+/g, ' ').trim().slice(0, 1000),
      dialog_text: String(document.querySelector('div[role="dialog"]') ? document.querySelector('div[role="dialog"]').innerText : '').replace(/\\s+/g, ' ').trim().slice(0, 2000),
      dialog_controls: Array.from((document.querySelector('div[role="dialog"]') || document).querySelectorAll('button, div[role="button"]')).map((node) => String(node.innerText || node.textContent || node.getAttribute('aria-label') || '').trim()).filter(Boolean).slice(0, 50),
      caption: (() => { const root = document.querySelector('div[role="dialog"]') || document; const box = root.querySelector('textarea[aria-label*="caption" i], textarea[placeholder*="caption" i], div[contenteditable="true"][aria-label*="caption" i]'); return box ? String(box.value || box.innerText || box.textContent || '').trim() : ''; })(),
      fields: Array.from(document.querySelectorAll('textarea, input, [contenteditable]')).map((node) => ({
        tag: node.tagName, type: node.type || '', role: node.getAttribute('role') || '',
        aria: node.getAttribute('aria-label') || '', placeholder: node.getAttribute('placeholder') || '',
        contenteditable: node.getAttribute('contenteditable') || '',
      })).slice(0, 40),
    }))()`);
    return { ok: true, ...diagnostic };
  } finally {
    client.close();
  }
}

async function inspectProfilePage(handle) {
  if (!(await endpointReady())) throw new Error("The dedicated Instagram Chrome profile is not running.");
  const targets = await getJson("/json/list");
  const target = targets.find((item) => item.type === "page" && /instagram\.com/i.test(String(item.url || "")));
  if (!target) throw new Error("No Instagram page is open in the dedicated profile.");
  const client = new CdpClient(target.webSocketDebuggerUrl);
  try {
    await client.connect();
    await client.send("Page.navigate", { url: `https://www.instagram.com/${encodeURIComponent(normalizeHandle(handle))}/` });
    await waitForDocument(client);
    await new Promise((resolve) => setTimeout(resolve, 2500));
    return await evaluate(client, `(() => ({
      url: location.href,
      body: String(document.body ? document.body.innerText : '').replace(/\\s+/g, ' ').trim().slice(0, 2500),
      posts: Array.from(document.querySelectorAll('a[href*="/p/"], a[href*="/reel/"]')).slice(0, 5).map((a) => ({ href: a.href, text: String(a.innerText || a.getAttribute('aria-label') || '').trim() })),
    }))()`);
  } finally { client.close(); }
}

async function inspectPostPage(url) {
  if (!(await endpointReady())) throw new Error("The dedicated Instagram Chrome profile is not running.");
  const targets = await getJson("/json/list");
  const target = targets.find((item) => item.type === "page" && /instagram\.com/i.test(String(item.url || "")));
  if (!target) throw new Error("No Instagram page is open in the dedicated profile.");
  const client = new CdpClient(target.webSocketDebuggerUrl);
  try {
    await client.connect();
    await client.send("Page.navigate", { url: String(url) });
    await waitForDocument(client);
    await new Promise((resolve) => setTimeout(resolve, 2500));
    return await evaluate(client, `(() => ({
      url: location.href,
      body: String(document.body ? document.body.innerText : '').replace(/\\s+/g, ' ').trim().slice(0, 4000),
      captions: Array.from(document.querySelectorAll('article, [role="dialog"]')).map((n) => String(n.innerText || '').replace(/\\s+/g, ' ').trim()).filter(Boolean).slice(0, 5),
      metadata: Array.from(document.querySelectorAll('meta')).map((n) => ({ property: n.getAttribute('property') || '', name: n.getAttribute('name') || '', content: n.getAttribute('content') || '' })).filter((n) => /description|caption|og:/i.test(String(n.property || '') + ' ' + String(n.name || ''))),
      controls: Array.from(document.querySelectorAll('button, [role="button"]')).slice(0, 80).map((n) => ({ text: String(n.innerText || '').trim(), aria: n.getAttribute('aria-label') || '', title: n.getAttribute('title') || '', html: n.outerHTML.slice(0, 300) })),
      svgs: Array.from(document.querySelectorAll('svg')).map((n) => n.getAttribute('aria-label') || n.getAttribute('data-testid') || '').filter(Boolean).slice(0, 80),
    }))()`);
  } finally { client.close(); }
}

async function openPostMenu(url) {
  if (!(await endpointReady())) throw new Error("The dedicated Instagram Chrome profile is not running.");
  const targets = await getJson("/json/list");
  const target = targets.find((item) => item.type === "page" && /instagram\.com/i.test(String(item.url || "")));
  if (!target) throw new Error("No Instagram page is open in the dedicated profile.");
  const client = new CdpClient(target.webSocketDebuggerUrl);
  try {
    await client.connect();
    await client.send("Page.navigate", { url: String(url) }); await waitForDocument(client); await new Promise((r) => setTimeout(r, 2200));
    const opened = await evaluate(client, `(() => { const xs = Array.from(document.querySelectorAll('[aria-haspopup="dialog"]')); const x = xs[xs.length - 1]; if (!x) return false; x.click(); return true; })()`);
    await new Promise((r) => setTimeout(r, 500));
    return { opened, body: await evaluate(client, `String(document.body ? document.body.innerText : '').replace(/\\s+/g, ' ').trim().slice(-1800)`) };
  } finally { client.close(); }
}

async function editPostCaption(url, caption) {
  if (!(await endpointReady())) throw new Error("The dedicated Instagram Chrome profile is not running.");
  const targets = await getJson("/json/list"); const target = targets.find((item) => item.type === "page" && String(item.url || "").includes("instagram.com"));
  if (!target) throw new Error("No Instagram page is open in the dedicated profile.");
  const client = new CdpClient(target.webSocketDebuggerUrl);
  const body = String(caption || "").trim();
  try {
    await client.connect(); await client.send("Page.navigate", { url: String(url) }); await waitForDocument(client); await new Promise((r) => setTimeout(r, 2200));
    const opened = await evaluate(client, `(() => { const s = document.querySelector('svg[aria-label="More options"]'); const x = s && s.closest('button, div[role="button"], div[tabindex="0"]'); if (!x) return false; x.click(); return true; })()`);
    if (!opened) throw new Error("Post options control was not found.");
    await new Promise((r) => setTimeout(r, 500));
    const edited = await evaluate(client, `(() => { const x = Array.from(document.querySelectorAll('div[role="dialog"] button, div[role="dialog"] div[role="button"], button, div[role="button"]')).find((n) => /^edit$/i.test(String(n.innerText || '').trim())); if (!x) return false; x.click(); return true; })()`);
    if (!edited) throw new Error("Instagram's Edit option was not found.");
    await new Promise((r) => setTimeout(r, 700));
    const filled = await evaluate(client, `(() => { const root = document.querySelector('div[role="dialog"]') || document; const b = root.querySelector('textarea, div[contenteditable="true"]'); if (!b) return false; b.focus(); if (b.tagName === 'TEXTAREA') { const s = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set; s.call(b, ${JSON.stringify(body)}); b.dispatchEvent(new Event('input', {bubbles:true})); b.dispatchEvent(new Event('change', {bubbles:true})); } return true; })()`);
    if (!filled) throw new Error("Instagram's caption editor was not found.");
    if (!(await evaluate(client, `(() => { const x = Array.from((document.querySelector('div[role="dialog"]') || document).querySelectorAll('button, div[role="button"]')).find((n) => /^(done|save)$/i.test(String(n.innerText || '').trim())); if (!x) return false; x.click(); return true; })()`))) throw new Error("Instagram's Save control was not found.");
    await new Promise((r) => setTimeout(r, 1200)); return { ok: true, status: "caption_updated", updated: true };
  } finally { client.close(); }
}

async function fillMessageComposer(client, body) {
  const prepared = await evaluate(client, `(() => {
    const box = document.querySelector('textarea[placeholder*="Message" i], textarea[aria-label*="Message" i], div[contenteditable="true"][role="textbox"], div[contenteditable="true"][aria-label*="Message" i]');
    if (!box) return {
      ready: false,
      page: String(document.body ? document.body.innerText : '').slice(0, 500),
      fields: Array.from(document.querySelectorAll('textarea, input, [contenteditable="true"]')).map((node) => ({
        tag: node.tagName, role: node.getAttribute('role') || '', aria: node.getAttribute('aria-label') || '',
        placeholder: node.getAttribute('placeholder') || '', contenteditable: node.getAttribute('contenteditable') || '',
      })).slice(0, 20),
    };
    box.focus();
    if (box.tagName === 'TEXTAREA') {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
      setter.call(box, ${JSON.stringify(body)});
      box.dispatchEvent(new Event('input', { bubbles: true }));
      box.dispatchEvent(new Event('change', { bubbles: true }));
    }
    return { ready: true, tag: box.tagName };
  })()`);
  if (!prepared.ready) return { composed: false, page: prepared.page, fields: prepared.fields };
  if (prepared.tag !== "TEXTAREA") {
    await client.send("Input.dispatchKeyEvent", {
      type: "keyDown", modifiers: 2, key: "a", code: "KeyA", windowsVirtualKeyCode: 65,
    });
    await client.send("Input.dispatchKeyEvent", {
      type: "keyUp", modifiers: 2, key: "a", code: "KeyA", windowsVirtualKeyCode: 65,
    });
    await client.send("Input.insertText", { text: body });
  }
  await new Promise((resolve) => setTimeout(resolve, 300));
  const draftText = await evaluate(client, `(() => {
    const box = document.querySelector('textarea[placeholder*="Message" i], textarea[aria-label*="Message" i], div[contenteditable="true"][role="textbox"], div[contenteditable="true"][aria-label*="Message" i]');
    return box ? String(box.value || box.innerText || box.textContent || '').trim() : '';
  })()`);
  return { composed: true, draft_text: String(draftText || "").trim() };
}

async function openDirectConversation(client, handle) {
  await client.send("Page.navigate", { url: "https://www.instagram.com/direct/new/" });
  await waitForDocument(client);
  let searchReady = false;
  for (let attempt = 0; attempt < 30; attempt += 1) {
    searchReady = await evaluate(client, `(() => {
      const input = document.querySelector('input[placeholder*="Search" i], input[aria-label*="Search" i], input[name="queryBox"]');
      if (!input) return false;
      input.focus();
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      setter.call(input, ${JSON.stringify(handle)});
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    })()`);
    if (searchReady) break;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  if (!searchReady) return false;
  await new Promise((resolve) => setTimeout(resolve, 2500));
  const selected = await evaluate(client, `(() => {
    const handle = ${JSON.stringify(handle.toLowerCase())};
    const candidates = Array.from(document.querySelectorAll('span, div, button, label'));
    const exact = candidates.find((node) => String(node.innerText || node.getAttribute('aria-label') || '').trim().toLowerCase() === handle);
    if (!exact) return false;
    const row = exact.closest('button, label, div[role="button"], [tabindex="0"]') || exact.parentElement || exact;
    row.click();
    return true;
  })()`);
  if (!selected) return false;
  await new Promise((resolve) => setTimeout(resolve, 750));
  const advanced = await evaluate(client, `(() => {
    const button = Array.from(document.querySelectorAll('button, div[role="button"]')).find((node) => /^(chat|next)$/i.test(String(node.innerText || node.getAttribute('aria-label') || '').trim()));
    if (!button) return false;
    button.click();
    return true;
  })()`);
  if (!advanced) return false;
  await new Promise((resolve) => setTimeout(resolve, 3000));
  return true;
}

async function composeMessage(handle, message, confirmed) {
  const normalized = normalizeHandle(handle);
  const body = String(message || "").trim();
  if (!body) throw new Error("A message is required.");
  return withTab(`https://www.instagram.com/${encodeURIComponent(normalized)}/`, async (client) => {
    const state = await pageState(client);
    if (!state.signed_in) throw new Error("The dedicated Instagram profile is not signed in. Run instagram-login first.");
    const opened = await evaluate(client, `(() => {
      const button = Array.from(document.querySelectorAll('button, div[role="button"]')).find((node) => /^message$/i.test(String(node.innerText || node.getAttribute('aria-label') || '').trim()));
      if (!button) return false;
      button.click();
      return true;
    })()`);
    if (opened) await new Promise((resolve) => setTimeout(resolve, 2500));
    let composed = await fillMessageComposer(client, body);
    if (!composed.composed) {
      await openDirectConversation(client, normalized);
      composed = await fillMessageComposer(client, body);
    }
    if (!composed.composed) {
      const page = String(composed.page || '').replace(/\s+/g, ' ').trim().slice(0, 300);
      throw new Error(`Instagram's message composer was not found.${page ? ` Page says: ${page}` : ''} Fields: ${JSON.stringify(composed.fields || [])}`);
    }
    const draftedText = String(composed.draft_text || '').replace(/\s+/g, ' ').trim();
    const requestedText = body.replace(/\s+/g, ' ').trim();
    if (draftedText !== requestedText) {
      throw new Error(`Instagram's message draft did not match the requested text, so it was not sent. Current draft: ${draftedText.slice(0, 1000)}`);
    }
    if (!confirmed) {
      return { ok: true, handle: normalized, status: "drafted", sent: false, draft_text: composed.draft_text, instruction: "Review the visible message in Chrome before sending." };
    }
    const sent = await evaluate(client, `(() => {
      const button = Array.from(document.querySelectorAll('button, div[role="button"]')).find((node) => /^send$/i.test(String(node.innerText || node.getAttribute('aria-label') || '').trim()));
      if (!button) return false;
      button.click();
      return true;
    })()`);
    if (!sent) throw new Error("Instagram's Send button was not found; the message remains composed for review.");
    return { ok: true, handle: normalized, status: "sent", sent: true };
  }, true);
}

async function main() {
  const action = String(process.argv[2] || "status").toLowerCase();
  if (action === "status") return output(await status());
  if (action === "setup") {
    const launched = await ensureChrome("https://www.instagram.com/accounts/login/");
    return output({ ok: true, launched, profile_root: profileRoot, username: configuredUsername, instruction: "Use instagram-login or sign in manually in the opened Chrome window." });
  }
  if (action === "login") return output(await login());
  if (action === "profile") return output(await readProfile(process.argv[3]));
  if (action === "follow") return output(await followAccount(process.argv[3]));
  if (action === "post") return output(await createPost(process.argv[3], process.argv.slice(4).join(" ")));
  if (action === "inspect-create") return output(await inspectCreateDialog());
  if (action === "inspect-profile") return output(await inspectProfilePage(process.argv[3]));
  if (action === "inspect-post") return output(await inspectPostPage(process.argv[3]));
  if (action === "open-post-menu") return output(await openPostMenu(process.argv[3]));
  if (action === "edit-post-caption") return output(await editPostCaption(process.argv[3], process.argv.slice(4).join(" ")));
  if (action === "draft-message" || action === "send-message") {
    const handle = process.argv[3];
    const message = process.argv.slice(4).join(" ");
    return output(await composeMessage(handle, message, action === "send-message"));
  }
  throw new Error(`Unknown action: ${action}`);
}

main().catch((error) => output({ ok: false, error: error.message || String(error), username: configuredUsername, profile_root: profileRoot }, 1));
