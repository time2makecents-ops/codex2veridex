const send = message => chrome.runtime.sendMessage(message);
const status = document.getElementById("status");
let displayed = new Map();
let renderedSignature = "";
let scopeRestored = false;
let scopeEdited = false;
const fields = {workspace_id: document.getElementById("workspace"), session_id: document.getElementById("session"), room: document.getElementById("room")};
const readScope = () => Object.fromEntries(Object.entries(fields).map(([key, field]) => [key, field.value.trim()]));
async function rememberScope() {
  // UI preference only: no tab identity, authorization, page text or form content.
  await chrome.storage.local.set({scopeDraft: readScope()});
}
for (const field of Object.values(fields)) {
  field.addEventListener("input", () => {
    scopeEdited = true;
    rememberScope().catch(error => { status.textContent = error.message; });
  });
}
async function restoreScope() {
  const stored = await chrome.storage.local.get("scopeDraft");
  const value = await send({type: "status"});
  const scope = stored.scopeDraft && typeof stored.scopeDraft === "object" ? stored.scopeDraft : value.selection?.scope;
  if (scope && !scopeEdited) {
    for (const [key, field] of Object.entries(fields)) {
      if (key !== "room" && typeof scope[key] === "string") field.value = scope[key];
    }
    if ([fields.workspace_id.value, fields.session_id.value].every(value => /^[a-zA-Z0-9_-]{1,100}$/.test(value))) {
      document.getElementById("connection-settings").open = false;
      document.getElementById("saved-connection").textContent = "Saved connection details are filled in. Your current room is detected when you choose Use this tab.";
    }
  }
  scopeRestored = true;
}
async function refresh() {
  if (!scopeRestored) return;
  const value = await send({type: "status"});
  if (!value.ok) { status.textContent = value.error; return; }
  const selectedScope = value.selection?.scope;
  fields.room.value = selectedScope?.workspace_id === fields.workspace_id.value.trim() &&
    selectedScope?.session_id === fields.session_id.value.trim() ? selectedScope.room || "" : "";
  status.textContent = value.error || (value.selection ? `Selected: ${value.selection.url}` : "No authorized tab selected");
  const signature = JSON.stringify([value.pending, value.busy]);
  if (signature === renderedSignature) return;
  renderedSignature = signature;
  const container = document.getElementById("requests");
  container.replaceChildren();
  displayed = new Map((value.pending || []).filter(row => row.action !== "read").map(row => [row.request_id, row]));
  if (!displayed.size) container.textContent = "No actions awaiting approval.";
  for (const command of displayed.values()) {
    const article = document.createElement("article");
    const title = document.createElement("strong"); title.textContent = command.action;
    const preview = document.createElement("pre");
    preview.textContent = JSON.stringify({intent: command.intent, tab: command.selected_url, scope: command.scope,
      target: command.target_preview || command.target_id, destination: command.url, field_text: command.text,
      expect_text: command.expect_text, expect_url: command.expect_url}, null, 2);
    const approve = document.createElement("button"); approve.textContent = "Approve this action"; approve.disabled = value.busy;
    approve.addEventListener("click", async () => {
      approve.disabled = true;
      try {
        // The optional permission prompt is reached only from this explicit user click.
        if (command.action === "navigate") {
          const origin = new URL(command.url).origin;
          if (!await chrome.permissions.request({origins: [`${origin}/*`]})) throw new Error("Destination permission was not granted");
        }
        const result = await send({type: "approve", request_id: command.request_id});
        if (!result.ok) throw new Error(result.error);
        await refresh();
      } catch (error) { status.textContent = error.message; approve.disabled = false; }
    });
    const reject = document.createElement("button"); reject.className = "reject"; reject.textContent = "Decline";
    reject.addEventListener("click", async () => { await send({type: "reject", request_id: command.request_id}); await refresh(); });
    article.append(title, preview, approve, reject); container.append(article);
  }
}
document.getElementById("selection").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    await rememberScope();
    const scope = readScope();
    const result = await send({type: "select", scope: {workspace_id: scope.workspace_id, session_id: scope.session_id}});
    if (!result.ok) status.textContent = result.error;
    else {
      if (result.selection?.scope?.room) fields.room.value = result.selection.scope.room;
      await refresh();
    }
  } catch (error) { status.textContent = error.message; }
});
restoreScope().then(refresh).catch(error => { status.textContent = error.message; });
setInterval(() => refresh().catch(error => { status.textContent = error.message; }), 2500);
