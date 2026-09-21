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
    this.socket.addEventListener("close", () => {
      for (const { reject } of this.pending.values()) reject(new Error("Chrome closed the active automation tab."));
      this.pending.clear();
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

  sendDetached(method, params = {}) {
    const id = this.nextId;
    this.nextId += 1;
    this.socket.send(JSON.stringify({ id, method, params }));
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
        const suggestionLink = document.querySelector("a#fprsl")
          || document.querySelector('a[href*="spell=1"]')
          || Array.from(root.querySelectorAll("a[href]")).find((node) => {
            const nearby = clean(node.parentElement ? node.parentElement.innerText : "");
            return /did you mean|showing results for/i.test(nearby);
          });
        let spellingSuggestion = "";
        if (suggestionLink) {
          try {
            spellingSuggestion = clean(new URL(suggestionLink.href).searchParams.get("q"));
          } catch (_) {
            spellingSuggestion = "";
          }
          if (!spellingSuggestion) spellingSuggestion = clean(suggestionLink.innerText);
        }
        return {
          title: document.title,
          url: location.href,
          text: String(root.innerText || "").slice(0, 16000),
          links,
          spelling_suggestion: spellingSuggestion,
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
      spelling_suggestion: String(page.spelling_suggestion || ""),
      result_text: normalizedText,
      links: Array.isArray(page.links) ? page.links : [],
      opened_sources: openedSources,
    };
  } finally {
    client.close();
    await closeTab(target.id);
  }
}

async function waitForDocument(client) {
  await client.send("Runtime.enable");
  await client.send("DOM.enable");
  await client.send("Runtime.evaluate", { expression: 'window.name = "veridex-automation"' });
  for (let attempt = 0; attempt < 40; attempt += 1) {
    const state = await client.send("Runtime.evaluate", { expression: "document.readyState", returnByValue: true });
    if (state.result && state.result.value === "complete") return;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
}

async function pageEvidence(client, textLimit = 16000) {
  const evaluated = await client.send("Runtime.evaluate", {
    expression: `(() => {
      const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
      const root = document.querySelector("main") || document.body;
      return {
        title: document.title,
        url: location.href,
        text: String(root ? root.innerText : "").slice(0, ${Number(textLimit)}),
        links: Array.from((root || document).querySelectorAll("a[href]"))
          .map((node) => {
            const title = clean(node.innerText || node.getAttribute("aria-label"));
            const parentText = clean(node.parentElement && node.parentElement.innerText);
            return {
              title,
              url: node.href,
              snippet: parentText && parentText !== title ? parentText.slice(0, 600) : "",
            };
          })
          .filter((row) => row.title && /^https?:/i.test(row.url)).slice(0, 30),
      };
    })()`,
    returnByValue: true,
  });
  return evaluated.result && evaluated.result.value ? evaluated.result.value : {};
}

async function searchGoogleLens(filePath) {
  if (!fs.existsSync(filePath)) throw new Error("The selected Google Lens image does not exist.");
  const lensUrl = "https://www.google.com/imghp?hl=en";
  const browserStarted = await ensureChrome(lensUrl);
  const siteStatus = await siteAccountStatus();
  const priorTargets = await getJson("/json/list");
  const priorTargetIds = new Set(priorTargets.map((row) => row.id));
  const target = await createSearchTab(lensUrl);
  let evidenceTarget = target;
  let client = new CdpClient(target.webSocketDebuggerUrl);
  let phase = "connecting to the upload page";
  try {
    await client.connect();
    await waitForDocument(client);
    phase = "locating the image upload control";
    let document = await client.send("DOM.getDocument", { depth: -1, pierce: true });
    const lensInputSelector = 'input[jsname="wcaWdc"], input[name="encoded_image"], form[action*="searchbyimage"] input[type="file"], input[type="file"][accept*="tiff"], input[type="file"]';
    let found = await client.send("DOM.querySelector", { nodeId: document.root.nodeId, selector: lensInputSelector });
    if (!found.nodeId) {
      await client.send("Runtime.evaluate", {
        expression: `(() => {
          const button = document.querySelector('[aria-label="Search by image"], [aria-label*="Search by image"]');
          if (!button) return false;
          button.click();
          return true;
        })()`,
        returnByValue: true,
      });
      await new Promise((resolve) => setTimeout(resolve, 750));
      const modalTargets = await getJson("/json/list");
      const modalTarget = modalTargets.find((row) => (
        row.type === "page"
        && row.id !== target.id
        && !priorTargetIds.has(row.id)
        && (/google\.[^/]+\/\?olud/i.test(String(row.url || "")) || /search any image with google lens/i.test(String(row.title || "")))
      ));
      if (modalTarget) {
        const replacement = new CdpClient(modalTarget.webSocketDebuggerUrl);
        await replacement.connect();
        await waitForDocument(replacement);
        client.close();
        client = replacement;
        evidenceTarget = modalTarget;
      } else {
        await waitForDocument(client);
      }
      document = await client.send("DOM.getDocument", { depth: -1, pierce: true });
      found = await client.send("DOM.querySelector", { nodeId: document.root.nodeId, selector: lensInputSelector });
    }
    if (!found.nodeId) throw new Error("Google Lens did not expose an image upload control. Open Lens manually in the dedicated profile.");
    // Prefer the visible Lens drop-zone input and explicitly dispatch its
    // change event. Google currently exposes several hidden file inputs; the
    // older encoded_image control can lead to a generic Images feed instead.
    try {
      phase = "submitting the selected image";
      await client.send("DOM.setFileInputFiles", { nodeId: found.nodeId, files: [path.resolve(filePath)] });
      await client.send("Runtime.evaluate", {
        expression: `(() => {
          const input = document.querySelector(${JSON.stringify(lensInputSelector)});
          if (!input) return false;
          input.dispatchEvent(new Event("change", { bubbles: true }));
          return true;
        })()`,
        returnByValue: true,
      });
    } catch (error) {
      if (!/closed the active automation tab/i.test(String(error && error.message))) throw error;
    }
    phase = "waiting for visual-search results";
    let page = {};
    for (let attempt = 0; attempt < 30; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 500));
      const targets = await getJson("/json/list");
      const spawned = targets.find((row) => (
        row.type === "page"
        && row.id !== target.id
        && !priorTargetIds.has(row.id)
        && (/google\.[^/]+\/search/i.test(String(row.url || "")) || /Google Images|Ideas for you/i.test(String(row.title || "")))
      ));
      if (spawned && spawned.id !== evidenceTarget.id) {
        const replacement = new CdpClient(spawned.webSocketDebuggerUrl);
        try {
          await replacement.connect();
          await waitForDocument(replacement);
          client.close();
          client = replacement;
          evidenceTarget = spawned;
        } catch (_) {
          replacement.close();
          continue;
        }
      }
      try {
        page = await pageEvidence(client);
      } catch (_) {
        continue;
      }
      const pageUrl = String(page.url || "");
      const pageText = String(page.text || "");
      if (
        pageUrl.includes("lens.google.com/upload")
        || (/google\.[^/]+\/search/i.test(pageUrl) && (/visual matches|exact matches/i.test(pageText) || pageText.length > 500))
      ) break;
    }
    const text = String(page.text || "");
    const blocked = /unusual traffic|not a robot|recaptcha/i.test(text);
    const links = Array.isArray(page.links) ? page.links : [];
    return {
      ok: true,
      provider: "google_lens_chrome_profile",
      status: blocked ? "blocked" : (links.length ? "completed" : "limited"),
      searched_at: new Date().toISOString(),
      profile_email: expectedEmail,
      profile_root: profileRoot,
      site_signed_in: siteStatus.site_signed_in,
      browser_started: browserStarted,
      page_title: page.title || "Google Lens",
      page_url: page.url || "https://lens.google.com/",
      result_text: text,
      raw_result_text: text,
      links,
      opened_sources: [],
      error: blocked ? "Google presented an anti-automation challenge for Lens." : (!text.trim() ? "Google Lens returned no readable evidence." : ""),
    };
  } catch (error) {
    throw new Error(`Google Lens failed while ${phase}: ${error && error.message ? error.message : String(error)}`);
  } finally {
    client.close();
    await closeTab(evidenceTarget.id);
    if (evidenceTarget.id !== target.id) await closeTab(target.id);
  }
}

async function searchEbayProductResearch(query) {
  const url = `https://www.ebay.com/sh/research?marketplace=EBAY-US&keywords=${encodeURIComponent(query)}`;
  const browserStarted = await ensureChrome(url);
  const target = await createSearchTab(url);
  const client = new CdpClient(target.webSocketDebuggerUrl);
  try {
    await client.connect();
    await waitForDocument(client);
    await new Promise((resolve) => setTimeout(resolve, 2500));
    let initialRange = {};
    for (let attempt = 0; attempt < 20; attempt += 1) {
      const rangeButton = await client.send("Runtime.evaluate", {
        expression: `(() => {
          const buttons = [...document.querySelectorAll("button")];
          const button = buttons.find((element) => /^Last (?:7|30|90) days$|^Last (?:6 months|year|2 years|3 years)$/i.test((element.innerText || "").trim()));
          if (!button) return { found: false, current: "" };
          const current = (button.innerText || "").trim();
          if (current !== "Last 3 years") button.click();
          return { found: true, current };
        })()`,
        returnByValue: true,
      });
      initialRange = rangeButton.result && rangeButton.result.value ? rangeButton.result.value : {};
      if (initialRange.found) break;
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    if (!initialRange.found) throw new Error("eBay Product Research date-range control was unavailable.");
    if (initialRange.current !== "Last 3 years") {
      await new Promise((resolve) => setTimeout(resolve, 300));
      const selected = await client.send("Runtime.evaluate", {
        expression: `(() => {
          const option = [...document.querySelectorAll('[role="menuitemradio"]')]
            .find((element) => (element.innerText || "").trim() === "Last 3 years");
          if (!option) return false;
          option.click();
          return true;
        })()`,
        returnByValue: true,
      });
      if (!selected.result || selected.result.value !== true) {
        throw new Error("eBay Product Research could not select its maximum three-year date range.");
      }
      await new Promise((resolve) => setTimeout(resolve, 2500));
    }
    const verifiedRange = await client.send("Runtime.evaluate", {
      expression: `[...document.querySelectorAll("button")]
        .map((element) => (element.innerText || "").trim())
        .find((text) => text === "Last 3 years") || ""`,
      returnByValue: true,
    });
    const appliedRange = verifiedRange.result ? String(verifiedRange.result.value || "") : "";
    if (appliedRange !== "Last 3 years") {
      throw new Error("eBay Product Research did not retain the maximum three-year date range.");
    }
    const page = await pageEvidence(client, 18000);
    const text = String(page.text || "");
    if (/sign in|log in to continue|verify your identity|captcha/i.test(text) || /signin/i.test(String(page.url || ""))) {
      throw new Error("eBay Product Research requires sign-in in the dedicated Veridex Chrome profile.");
    }
    if (!text.trim()) throw new Error("eBay Product Research returned no readable evidence.");
    return {
      ok: true,
      provider: "ebay_product_research_chrome_profile",
      query,
      searched_at: new Date().toISOString(),
      browser_started: browserStarted,
      page_title: page.title || "eBay Product Research",
      page_url: page.url || url,
      date_range: {
        applied: true,
        label: appliedRange,
        maximum_available: true,
        history_limit: "eBay Product Research provides at most three years of sales data.",
      },
      result_text: text,
      links: Array.isArray(page.links) ? page.links : [],
      opened_sources: [],
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
  if (action === "lens") {
    const filePath = String(process.argv.slice(3).join(" ") || "").trim();
    if (!filePath) throw new Error("A Google Lens image path is required.");
    output(await searchGoogleLens(filePath));
    return;
  }
  if (action === "ebay") {
    const query = String(process.argv.slice(3).join(" ") || "").trim();
    if (!query) throw new Error("An eBay Product Research query is required.");
    output(await searchEbayProductResearch(query));
    return;
  }
  if (action === "cleanup") {
    output({ ok: true, closed_tabs: await cleanupAutomationTabs() });
    return;
  }
  throw new Error(`Unknown action: ${action}`);
}

main().catch((error) => {
  const action = String(process.argv[2] || "status").toLowerCase();
  if (action === "lens") {
    output({
      ok: true,
      provider: "google_lens_chrome_profile",
      status: "failed",
      searched_at: new Date().toISOString(),
      page_title: "Google Lens",
      page_url: "https://lens.google.com/",
      results: [],
      opened_sources: [],
      raw_result_text: "",
      error: error.message || String(error),
      ...profileStatus(),
    });
    return;
  }
  output({ ok: false, error: error.message || String(error), ...profileStatus() }, 1);
});
