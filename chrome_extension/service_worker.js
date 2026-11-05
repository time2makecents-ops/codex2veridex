/* The native host owns credentials. No remote scripts, cookie access or eval. */
const HOST = "com.veridex.browser";
let port = null;
let selection = null;
let pending = new Map();
let rpcWaiters = new Map();
let busy = false;
let lastError = "Native host has not connected";
let bindingPending = false;

const originOf = (url) => {
  const value = new URL(url);
  if (!["http:", "https:"].includes(value.protocol) || value.username || value.password) {
    throw new Error("Open an HTTP/HTTPS page before choosing Use this tab. Chrome New Tab and settings pages cannot be selected.");
  }
  return value.origin;
};

async function currentSelection() {
  if (!selection) return null;
  try {
    const tab = await chrome.tabs.get(selection.tab_id);
    if (originOf(tab.url) !== selection.origin) return null;
    return {scope: selection.scope, tab_id: tab.id, url: tab.url};
  } catch { return null; }
}

function ingest(value) {
  if (Array.isArray(value.active_request_ids)) {
    const active = new Set(value.active_request_ids);
    for (const id of pending.keys()) if (!active.has(id)) pending.delete(id);
  }
  if (value.command) pending.set(value.command.request_id, value.command);
  void drainReads();
}

function connect() {
  if (port) return;
  try {
    port = chrome.runtime.connectNative(HOST);
    port.onMessage.addListener(message => {
      const waiter = rpcWaiters.get(message.rpc_id);
      if (waiter) { rpcWaiters.delete(message.rpc_id); clearTimeout(waiter.timer); message.error ? waiter.reject(new Error(message.error)) : waiter.resolve(message); }
      if (!message.error) { lastError = ""; ingest(message); }
    });
    port.onDisconnect.addListener(() => {
      lastError = chrome.runtime.lastError?.message || "Native host disconnected";
      port = null;
      pending.clear();
      for (const waiter of rpcWaiters.values()) { clearTimeout(waiter.timer); waiter.reject(new Error(lastError)); }
      rpcWaiters.clear();
    });
  } catch (error) { port = null; lastError = error.message; }
}

async function rpc(event, explicitSelection) {
  connect();
  if (!port) throw new Error(lastError);
  const selected = explicitSelection || await currentSelection();
  const rpcId = crypto.randomUUID();
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { rpcWaiters.delete(rpcId); reject(new Error("Native relay timed out; outcome must be checked before retrying")); }, 8000);
    rpcWaiters.set(rpcId, {resolve, reject, timer});
    try { port.postMessage({rpc_id: rpcId, selection: selected, ...(event ? {event} : {})}); }
    catch (error) { clearTimeout(timer); rpcWaiters.delete(rpcId); reject(error); }
  });
}

async function pageOperation(command, action = command.action) {
  const tab = await chrome.tabs.get(command.tab_id);
  if (!selection || tab.id !== selection.tab_id || originOf(tab.url) !== selection.origin) throw new Error("Selected tab or authorized origin changed");
  await chrome.scripting.executeScript({target: {tabId: tab.id}, files: ["page_operations.js"]});
  const results = await chrome.scripting.executeScript({target: {tabId: tab.id},
    func: (operation, args) => globalThis.__veridexPage.run(operation, args), args: [action, command]});
  if (!results[0]?.result) throw new Error("No top-level document observation returned");
  return results[0].result;
}

async function execute(command, approved) {
  if (busy || !pending.has(command.request_id)) throw new Error("Request is busy, stopped or expired");
  const initialSelection = await currentSelection();
  if (!initialSelection || JSON.stringify(initialSelection.scope) !== JSON.stringify(command.scope)) throw new Error("Selection scope changed");
  busy = true;
  let claimed = false;
  try {
    const claim = await rpc({type: "claim", request_id: command.request_id, approved_locally: approved});
    if (!claim.execute) throw new Error("Request was not authorized for execution");
    claimed = true;
    let result;
    if (command.action === "navigate") {
      const url = new URL(command.url).href;
      selection.origin = originOf(url);
      await chrome.tabs.update(command.tab_id, {url});
      const deadline = Date.now() + 15000;
      while (Date.now() < deadline) {
        const tab = await chrome.tabs.get(command.tab_id);
        if (tab.status === "complete" && tab.url === url) break;
        await new Promise(resolve => setTimeout(resolve, 100));
      }
      result = await pageOperation(command, "read");
      result.status = result.observation.url === url ? "completed" : "limited";
      result.effect_verified = result.status === "completed";
    } else result = await pageOperation(command);
    await rpc({type: "result", request_id: command.request_id, result}, await currentSelection() || initialSelection);
    pending.delete(command.request_id);
  } catch (error) {
    lastError = error.message;
    if (claimed) {
      try { await rpc({type: "result", request_id: command.request_id,
        result: {status: command.action === "read" ? "failed" : "limited", message: "Browser operation could not be verified; do not automatically retry", error: error.message}}, initialSelection); }
      catch { /* Broker expires uncertain work; never manufacture completion. */ }
    }
    pending.delete(command.request_id);
    throw error;
  } finally { busy = false; }
}

async function drainReads() {
  if (busy || bindingPending) return;
  const command = [...pending.values()].find(row => row.action === "read");
  if (command) { try { await execute(command, false); } catch { /* shown in status */ } }
}

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (sender.id !== chrome.runtime.id || sender.url !== chrome.runtime.getURL("popup.html")) return false;
  (async () => {
    if (message.type === "select") {
      const tabs = await chrome.tabs.query({active: true, currentWindow: true});
      const tab = tabs[0];
      const scope = {};
      for (const key of ["workspace_id", "session_id"]) {
        if (!/^[a-zA-Z0-9_-]{1,100}$/.test(message.scope?.[key] || "")) throw new Error(`Invalid ${key}`);
        scope[key] = message.scope[key];
      }
      if (busy) throw new Error("Wait for the active request before selecting a different tab");
      selection = {scope, tab_id: tab.id, origin: originOf(tab.url)};
      bindingPending = true;
      pending.clear();
      try {
        const reply = await rpc();
        const acknowledged = reply.selection;
        if (!acknowledged || acknowledged.tab_id !== selection.tab_id ||
            acknowledged.scope?.workspace_id !== scope.workspace_id || acknowledged.scope?.session_id !== scope.session_id ||
            !/^[a-zA-Z0-9_-]{1,100}$/.test(acknowledged.scope?.room || "")) {
          throw new Error("Veridex did not confirm the selected tab. Check the connection and try again.");
        }
        // Only this explicit selection can bind a newly detected room. Later
        // heartbeats cannot silently retarget an existing authorization.
        selection.scope = acknowledged.scope;
        await chrome.storage.session.set({selection});
        await chrome.storage.local.set({scopeDraft: selection.scope});
        bindingPending = false;
        void drainReads();
      } catch (error) {
        selection = null;
        bindingPending = false;
        await chrome.storage.session.remove("selection");
        throw error;
      }
    } else if (message.type === "approve") {
      const command = pending.get(message.request_id);
      if (!command || command.action === "read") throw new Error("Request is no longer awaiting approval");
      await execute(command, true);
    } else if (message.type === "reject") {
      await rpc({type: "reject", request_id: message.request_id});
      pending.delete(message.request_id);
    } else if (message.type !== "status") throw new Error("Unknown popup message");
    return {ok: true, selection: bindingPending ? null : await currentSelection(), pending: [...pending.values()], busy, error: lastError};
  })().then(respond, error => respond({ok: false, error: error.message}));
  return true;
});

chrome.storage.session.get("selection").then(value => { selection = value.selection || null; connect(); });
setInterval(() => { rpc().catch(error => { lastError = error.message; }); }, 2000);
