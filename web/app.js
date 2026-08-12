const state = {
  workspace: null,
  session: null,
  workspaces: [],
  sessions: [],
  messages: [],
  files: [],
  selectedFiles: new Set(),
  runtime: { access_mode: "read_only", access_label: "Read-only computer access" },
  route: null,
  sending: false,
  uploading: false,
};

const el = (id) => document.getElementById(id);
const api = async (path, options = {}) => {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || `Request failed (${response.status})`);
  return value;
};

function savedRoute(messages) {
  const row = [...(messages || [])].reverse().find((message) => message.role === "assistant" && message.model);
  if (!row) return null;
  return {
    provider: row.provider || "codex_cli",
    model: row.model,
    reasoning_effort: row.reasoning_effort || "default",
    task_type: row.task_type || "conversation",
    notice: "Last saved model route for this session.",
  };
}

function applyState(value, preserveRoute = false) {
  const sessionChanged = state.session?.session_id && state.session.session_id !== value.session?.session_id;
  state.workspace = value.workspace;
  state.session = value.session;
  state.workspaces = value.workspaces || [];
  state.sessions = value.sessions || [];
  state.messages = value.messages || [];
  state.files = value.files || [];
  state.runtime = value.runtime || state.runtime;
  if (sessionChanged) state.selectedFiles.clear();
  if (!preserveRoute) state.route = savedRoute(state.messages);
  if (value.account) el("account-name").textContent = value.account.display_name || "Local User";
  render();
}

function navButton(row, active, label, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `nav-item${active ? " active" : ""}`;
  button.textContent = label;
  button.title = label;
  button.addEventListener("click", onClick);
  return button;
}

function renderNavigation() {
  const workspaces = el("workspace-list");
  const sessions = el("session-list");
  workspaces.replaceChildren();
  sessions.replaceChildren();
  state.workspaces.forEach((row) => workspaces.append(navButton(
    row,
    row.workspace_id === state.workspace?.workspace_id,
    row.label,
    () => loadState(row.workspace_id),
  )));
  state.sessions.forEach((row) => sessions.append(navButton(
    row,
    row.session_id === state.session?.session_id,
    row.title,
    () => loadState(state.workspace.workspace_id, row.session_id),
  )));
}

function renderMessages() {
  const container = el("messages");
  container.replaceChildren();
  if (!state.messages.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.innerHTML = '<div class="empty-rule"></div><h2>Start where the work is.</h2><p>Coding and planning receive stronger reasoning. Simple checks use a lighter model. Every switch appears above.</p>';
    container.append(empty);
  } else {
    state.messages.forEach((row) => {
      const article = document.createElement("article");
      article.className = `message ${row.role === "user" ? "user" : "assistant"}`;
      const role = document.createElement("div");
      role.className = "message-role";
      role.textContent = row.role === "user" ? "You" : (row.speaker || "Veridex");
      const body = document.createElement("div");
      body.className = "message-body";
      body.textContent = row.text || "";
      article.append(role, body);
      if (Array.isArray(row.attachments) && row.attachments.length) {
        const attachments = document.createElement("div");
        attachments.className = "message-attachments";
        row.attachments.forEach((file) => {
          const chip = document.createElement("span");
          chip.textContent = `Attached: ${file.name}`;
          attachments.append(chip);
        });
        article.append(attachments);
      }
      if (row.model) {
        const route = document.createElement("div");
        route.className = "message-route";
        route.textContent = `${row.model} · ${row.reasoning_effort || "default"} reasoning · ${row.task_type || "conversation"}`;
        article.append(route);
      }
      container.append(article);
    });
  }
  if (state.sending) {
    const processing = document.createElement("article");
    processing.className = "message assistant processing";
    processing.textContent = "Veridex is working…";
    container.append(processing);
  }
  requestAnimationFrame(() => { container.scrollTop = container.scrollHeight; });
}

function formatBytes(size) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function renderFiles() {
  const tray = el("file-tray");
  tray.replaceChildren();
  if (!state.files.length && !state.uploading) {
    tray.hidden = true;
    return;
  }
  tray.hidden = false;
  if (state.uploading) {
    const uploading = document.createElement("span");
    uploading.className = "file-uploading";
    uploading.textContent = "Saving file…";
    tray.append(uploading);
  }
  state.files.forEach((file) => {
    const button = document.createElement("button");
    const selected = state.selectedFiles.has(file.file_id);
    button.type = "button";
    button.className = `file-chip${selected ? " selected" : ""}`;
    button.textContent = `${selected ? "✓ " : ""}${file.name} · ${formatBytes(file.size || 0)}`;
    button.title = selected ? "Included with the next message" : "Click to include with the next message";
    button.addEventListener("click", () => {
      if (selected) state.selectedFiles.delete(file.file_id);
      else state.selectedFiles.add(file.file_id);
      renderFiles();
    });
    tray.append(button);
  });
}

function renderRoute() {
  const status = el("route-status");
  if (state.sending) {
    status.className = "route-status checking";
    el("route-model").textContent = "Checking model route";
    el("route-meta").textContent = "Matching task, model, and reasoning level";
    el("route-notice").textContent = "";
    return;
  }
  status.className = "route-status ready";
  if (!state.route) {
    el("route-model").textContent = "Model routing ready";
    el("route-meta").textContent = "Codex selects the model automatically";
    el("route-notice").textContent = "";
    return;
  }
  el("route-model").textContent = `Codex CLI · ${state.route.model}`;
  el("route-meta").textContent = `${state.route.reasoning_effort} reasoning · ${state.route.task_type.replaceAll("_", " ")}`;
  el("route-notice").textContent = state.route.notice;
}

function render() {
  el("workspace-name").textContent = state.workspace?.label || "Workspace";
  el("session-title").textContent = state.session?.title || "New session";
  const room = (state.session?.active_room || "lobby").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
  el("room-location").textContent = `${room} · ${state.session?.active_persona || "Receptionist"}`;
  const fullAccess = state.runtime.access_mode === "full";
  el("access-status").className = `access-status ${fullAccess ? "full" : "read-only"}`;
  el("access-label").textContent = state.runtime.access_label || (fullAccess ? "Full computer access" : "Read-only computer access");
  el("composer-note").textContent = fullAccess
    ? "Full computer access · Codex can search and work with local files · transcripts stay here"
    : "Read-only computer access · attach files or restart with -FullAccess · transcripts stay here";
  el("send-button").disabled = state.sending || state.uploading;
  el("message-input").disabled = state.sending || state.uploading;
  el("attach-button").disabled = state.sending || state.uploading;
  renderNavigation();
  renderMessages();
  renderFiles();
  renderRoute();
}

async function loadState(workspaceId = "", sessionId = "", preserveRoute = false) {
  const query = new URLSearchParams();
  if (workspaceId) query.set("workspace_id", workspaceId);
  if (sessionId) query.set("session_id", sessionId);
  applyState(await api(`/api/state?${query}`), preserveRoute);
}

function routeNotice(next) {
  if (!state.route) return `Model selected: ${next.model} · ${next.reasoning_effort} reasoning.`;
  if (state.route.model !== next.model || state.route.reasoning_effort !== next.reasoning_effort) {
    return `Model changed: ${state.route.model} → ${next.model} · ${next.reasoning_effort} reasoning.`;
  }
  if (state.route.task_type !== next.task_type) {
    return `Task route changed: ${state.route.task_type.replaceAll("_", " ")} → ${next.task_type.replaceAll("_", " ")}.`;
  }
  return `Continuing with ${next.model} · ${next.reasoning_effort} reasoning.`;
}

async function sendMessage(text) {
  const selectedAttachments = state.files.filter((file) => state.selectedFiles.has(file.file_id));
  state.sending = true;
  state.messages.push({
    role: "user",
    text: text || "Review the attached file or files and summarize what is important.",
    speaker: "You",
    attachments: selectedAttachments,
  });
  render();
  try {
    const result = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        workspace_id: state.workspace.workspace_id,
        session_id: state.session.session_id,
        text,
        attachment_ids: selectedAttachments.map((file) => file.file_id),
      }),
    });
    const nextRoute = {
      provider: result.provider,
      model: result.model,
      reasoning_effort: result.reasoning_effort,
      task_type: result.task_type,
    };
    nextRoute.notice = routeNotice(nextRoute);
    state.route = nextRoute;
    state.selectedFiles.clear();
    await loadState(state.workspace.workspace_id, state.session.session_id, true);
  } catch (error) {
    showError(error.message || String(error));
    await loadState(state.workspace.workspace_id, state.session.session_id, true);
  } finally {
    state.sending = false;
    render();
    el("message-input").focus();
  }
}

function showError(message) {
  const toast = el("toast");
  toast.textContent = message;
  toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 7000);
}

el("composer").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = el("message-input");
  const text = input.value.trim();
  if ((!text && !state.selectedFiles.size) || state.sending || state.uploading) return;
  input.value = "";
  input.style.height = "auto";
  await sendMessage(text);
});

async function uploadFiles(fileList) {
  if (!state.workspace || !state.session) return;
  state.uploading = true;
  render();
  try {
    for (const file of fileList) {
      const query = new URLSearchParams({
        workspace_id: state.workspace.workspace_id,
        session_id: state.session.session_id,
        name: file.name,
      });
      const result = await api(`/api/files?${query}`, {
        method: "POST",
        headers: { "Content-Type": file.type || "application/octet-stream" },
        body: file,
      });
      state.files = result.files || state.files;
      if (result.file?.file_id) state.selectedFiles.add(result.file.file_id);
    }
  } catch (error) {
    showError(error.message || String(error));
  } finally {
    state.uploading = false;
    el("file-input").value = "";
    render();
  }
}

el("attach-button").addEventListener("click", () => el("file-input").click());
el("file-input").addEventListener("change", (event) => uploadFiles([...event.target.files]));

el("message-input").addEventListener("input", (event) => {
  event.target.style.height = "auto";
  event.target.style.height = `${Math.min(event.target.scrollHeight, 180)}px`;
});

el("message-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    el("composer").requestSubmit();
  }
});

el("new-workspace").addEventListener("click", async () => {
  const label = window.prompt("Workspace name", "New workspace")?.trim();
  if (!label) return;
  try {
    applyState(await api("/api/workspaces", { method: "POST", body: JSON.stringify({ label }) }));
    state.route = null;
    renderRoute();
  } catch (error) { showError(error.message || String(error)); }
});

el("new-session").addEventListener("click", async () => {
  const title = window.prompt("Session name", "New session")?.trim();
  if (!title) return;
  try {
    applyState(await api("/api/sessions", {
      method: "POST",
      body: JSON.stringify({ workspace_id: state.workspace.workspace_id, title }),
    }));
    state.route = null;
    renderRoute();
  } catch (error) { showError(error.message || String(error)); }
});

api("/api/bootstrap").then(applyState).catch((error) => showError(error.message || String(error)));
