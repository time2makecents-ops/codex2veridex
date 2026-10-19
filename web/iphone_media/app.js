const state = {
  status: null,
  sources: [],
  items: [],
  total: 0,
  selected: new Set(),
  jobs: [],
  deletionPreview: null,
};

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {"Content-Type": "application/json", ...(options.headers || {})},
  });
  const value = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(value.error || `${response.status} ${response.statusText}`);
  return value;
}

let toastTimer;
function toast(message, error = false) {
  clearTimeout(toastTimer);
  const element = $("#toast");
  element.textContent = message;
  element.className = `toast visible${error ? " error" : ""}`;
  toastTimer = setTimeout(() => element.className = "toast", 3500);
}

function formatBytes(bytes) {
  const value = Number(bytes || 0);
  if (!value) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const power = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / (1024 ** power)).toFixed(power > 1 ? 1 : 0)} ${units[power]}`;
}

function formatDate(value) {
  if (!value) return "Unknown date";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleDateString(undefined, {year: "numeric", month: "short", day: "numeric"});
}

function currentSelection() {
  return state.items.filter(item => state.selected.has(item.item_id));
}

function showView(name) {
  const titles = {inventory: "Inventory", sources: "Sources", transfers: "Transfers", cleanup: "Cleanup", audio: "Audio library", deletion: "Deletion review", settings: "Settings", guide: "How to use"};
  $$(".nav-item").forEach(button => button.classList.toggle("active", button.dataset.view === name));
  $$(".view").forEach(view => view.classList.toggle("active", view.id === `${name}-view`));
  $("#view-title").textContent = titles[name];
  if (name === "transfers") loadJobs();
  if (name === "cleanup") loadDuplicates();
  if (name === "deletion") renderSelection();
  window.scrollTo({top: 0, behavior: "smooth"});
}

function updateSourcePathControls() {
  const usesUsb = $("#source-kind").value === "iphone_usb";
  $("#source-path-wrap").hidden = usesUsb;
  $("#pick-source").hidden = usesUsb;
}

function renderStatus() {
  const status = state.status;
  const local = status.counts.local_verified;
  const drive = status.counts.second_copy_verified;
  const dot = $("#copy-state-dot");
  dot.className = local > 0 && drive === local ? "good" : "warn";
  $("#copy-state-label").textContent = local > 0 && drive === local ? "Two copies verified" : "Archive safety check";
  $("#copy-state-detail").textContent = `${local} primary · ${drive} second-copy verified`;
  if (status.destination) {
    $("#destination-path").value = status.destination.path || "";
    $("#destination-detail").textContent = status.destination.writable
      ? `${formatBytes(status.destination.free_bytes)} available on selected drive.`
      : status.destination.error || "Destination unavailable.";
  }
  if (status.secondary_destination) {
    $("#secondary-destination-path").value = status.secondary_destination.path || "";
    $("#secondary-destination-detail").textContent = status.secondary_destination.writable
      ? `${formatBytes(status.secondary_destination.free_bytes)} available on an independent destination.`
      : status.secondary_destination.error || "Second-copy destination unavailable.";
  }
  const limits = status.limits || {};
  $("#batch-limit").value = limits.batch_bytes ? (limits.batch_bytes / 1024 ** 3).toFixed(2) : "";
  $("#file-limit").value = limits.file_bytes ? (limits.file_bytes / 1024 ** 3).toFixed(2) : "";
  $("#transcription-state").textContent = status.transcription_available ? "Local transcription is ready" : "Local transcription is not installed";
  $("#transcription-detail").textContent = status.transcription_available
    ? "It runs only when you select archived audio and start a transcription job."
    : "Downloading and cleanup still work normally. Install requirements-transcription.txt only when you want this feature.";
  const google = status.google || {};
  $("#google-detail").textContent = google.connected ? `Connected as ${google.email || google.name || "Google user"}.` : `Not connected${google.reason ? ` — ${google.reason}` : "."}`;
}

async function loadStatus() {
  state.status = await api("/api/status");
  renderStatus();
}

function dispositionLabel(value) {
  return ({keep_on_phone: "Leave on phone", download_keep: "Download + keep", download_delete: "Download + delete"})[value] || value;
}

function itemTemplate(item) {
  const selected = state.selected.has(item.item_id);
  const showPreview = item.media_kind === "photo";
  const copyText = item.second_copy_verified ? "2 copies" : item.local_verified ? "Primary only" : "Not downloaded";
  const copyClass = item.second_copy_verified ? " verified" : "";
  const planClass = item.disposition === "download_delete" ? " delete" : "";
  return `<article class="media-row${selected ? " selected" : ""}" data-id="${item.item_id}">
    <div class="media-main">
      <input class="media-check" type="checkbox" aria-label="Select ${escapeHtml(item.filename)}" ${selected ? "checked" : ""}>
      <div class="media-thumb">${showPreview ? `<img src="${item.preview_url}" alt="" loading="lazy" onerror="this.replaceWith(document.createTextNode('PHOTO'))">` : escapeHtml(item.media_kind)}</div>
      <div class="media-name"><strong title="${escapeHtml(item.filename)}">${escapeHtml(item.filename)}</strong><span title="${escapeHtml(item.relative_path)}">${escapeHtml(item.source_kind.replaceAll("_", " "))} · ${escapeHtml(item.relative_path)}</span></div>
    </div>
    <span>${formatDate(item.captured_at || item.modified_at)}</span>
    <span>${formatBytes(item.size_bytes)}</span>
    <span class="plan-label${planClass}">${dispositionLabel(item.disposition)}</span>
    <span class="copy-label${copyClass}">${copyText}</span>
  </article>`;
}

function renderItems() {
  $("#media-list").innerHTML = state.items.map(itemTemplate).join("");
  $("#inventory-empty").hidden = state.items.length > 0;
  renderSelection();
}

function renderSelection() {
  const selected = currentSelection();
  const bytes = selected.reduce((sum, item) => sum + Number(item.size_bytes || 0), 0);
  $("#selection-count").textContent = `${selected.length} selected`;
  $("#selection-size").textContent = formatBytes(bytes);
  $("#delete-selection-count").textContent = `${selected.length} selected`;
  $("#select-all").checked = state.items.length > 0 && selected.length === state.items.length;
  $("#select-all").indeterminate = selected.length > 0 && selected.length < state.items.length;
}

async function loadItems() {
  const params = new URLSearchParams();
  if ($("#filter-search").value) params.set("search", $("#filter-search").value);
  if ($("#filter-from").value) params.set("date_from", $("#filter-from").value);
  if ($("#filter-to").value) params.set("date_to", $("#filter-to").value);
  if ($("#filter-kind").value) params.set("media_kind", $("#filter-kind").value);
  params.set("limit", "1000");
  const value = await api(`/api/items?${params}`);
  state.items = value.items;
  state.total = value.total;
  const visible = new Set(state.items.map(item => item.item_id));
  state.selected = new Set([...state.selected].filter(itemId => visible.has(itemId)));
  renderItems();
}

function sourceTemplate(source) {
  const status = source.last_error ? source.last_error : source.last_scan_at ? `Last scanned ${formatDate(source.last_scan_at)}` : "Not scanned yet";
  return `<article class="source-row" data-id="${source.source_id}">
    <div><span class="source-kind">${escapeHtml(source.kind.replaceAll("_", " "))}</span><h3>${escapeHtml(source.label)}</h3></div>
    <p title="${escapeHtml(source.path || "Windows portable device")}">${escapeHtml(source.path || "Unlocked iPhone over USB")}</p>
    <p>${escapeHtml(status)}</p>
    <button class="quiet-button scan-source" type="button">Scan</button>
  </article>`;
}

async function loadSources() {
  const value = await api("/api/sources");
  state.sources = value.sources;
  $("#source-list").innerHTML = state.sources.length ? state.sources.map(sourceTemplate).join("") : '<div class="empty-state"><h2>No sources configured</h2><p>Add your iPhone USB connection or an Apple media folder below.</p></div>';
}

function jobTemplate(job) {
  const countProgress = job.total_items ? job.completed_items / job.total_items : 0;
  const byteProgress = job.total_bytes ? job.completed_bytes / job.total_bytes : 0;
  const progress = Math.max(countProgress, byteProgress) * 100;
  const active = ["queued", "running"].includes(job.status);
  return `<article class="job-row" data-id="${job.job_id}">
    <div><span class="source-kind">${escapeHtml(job.kind)}</span><h3>${job.completed_items} of ${job.total_items} items</h3><p>${escapeHtml(job.error || job.details.destination || "Local background job")}</p></div>
    <span class="job-status">${escapeHtml(job.status)}</span>
    <div class="job-progress"><span style="width:${Math.min(100, progress)}%"></span></div>
    ${active ? '<button class="quiet-button cancel-job" type="button">Cancel</button>' : ""}
  </article>`;
}

async function loadJobs() {
  const value = await api("/api/jobs");
  state.jobs = value.jobs;
  $("#job-list").innerHTML = state.jobs.length ? state.jobs.map(jobTemplate).join("") : '<div class="empty-state"><h2>No transfer activity</h2><p>Jobs appear here after you download or transcribe selected media.</p></div>';
}

async function loadDuplicates() {
  const value = await api("/api/duplicates");
  const bytes = value.groups.reduce((sum, group) => sum + Number(group.bytes || 0), 0);
  $("#duplicate-groups").textContent = value.groups.length;
  $("#duplicate-bytes").textContent = formatBytes(bytes);
  $("#duplicate-list").innerHTML = value.groups.map(group => `<article class="duplicate-row"><div><span class="source-kind">SHA-256 MATCH</span><h3>${group.items.map(item => escapeHtml(item.filename)).join(" · ")}</h3></div><span>${group.count} files</span><span>${formatBytes(group.bytes)}</span></article>`).join("") || '<div class="empty-state"><h2>No exact duplicates found</h2><p>Only verified archived originals are compared.</p></div>';
}

async function pickFolder(targetInput) {
  const value = await api("/api/destination/pick", {method: "POST", body: "{}"});
  if (!value.cancelled && value.path) targetInput.value = value.path;
}

async function scanOne(sourceId) {
  toast("Scanning source…");
  try {
    const value = await api(`/api/sources/${sourceId}/scan`, {method: "POST", body: "{}"});
    toast(`Found ${value.count} supported media files.`);
    await Promise.all([loadItems(), loadStatus()]);
  } finally {
    await loadSources();
  }
}

function openTransferDialog() {
  const selected = currentSelection().filter(item => item.disposition !== "keep_on_phone");
  if (!selected.length) return toast("Select items planned for download first.", true);
  $("#transfer-count").textContent = `${selected.length} items`;
  $("#transfer-size").textContent = formatBytes(selected.reduce((sum, item) => sum + item.size_bytes, 0));
  $("#transfer-destination").value = state.status.destination?.path || "";
  const secondary = state.status.secondary_destination;
  $("#transfer-secondary").disabled = !secondary?.writable;
  $("#transfer-secondary").checked = Boolean(secondary?.writable);
  $("#transfer-secondary-label").textContent = secondary?.writable
    ? `Create and verify a second copy at ${secondary.path}`
    : "Create and verify a second copy on another drive — configure in Settings";
  $("#transfer-google").checked = Boolean(state.status.google?.connected);
  $("#transfer-dialog").showModal();
}

async function startTransfer() {
  const selected = currentSelection().filter(item => item.disposition !== "keep_on_phone");
  const value = await api("/api/transfers", {
    method: "POST",
    body: JSON.stringify({
      item_ids: selected.map(item => item.item_id),
      destination: $("#transfer-destination").value,
      secondary_destination: $("#transfer-secondary").checked ? state.status.secondary_destination?.path : null,
      upload_google: $("#transfer-google").checked,
    }),
  });
  $("#transfer-dialog").close();
  toast(`Transfer job ${value.job_id.slice(0, 8)} started.`);
  showView("transfers");
  await loadJobs();
}

async function previewDeletion() {
  const selected = currentSelection();
  if (!selected.length) return toast("Select deletion candidates in Inventory first.", true);
  const preview = await api("/api/deletions/preview", {method: "POST", body: JSON.stringify({item_ids: selected.map(item => item.item_id)})});
  if (preview.blocked.length) {
    $("#deletion-result").innerHTML = `<h3>Deletion remains locked</h3>${preview.blocked.map(item => `<div class="preview-delete-row"><strong>${escapeHtml(item.filename)}</strong><span>${escapeHtml(item.reasons.join(" · "))}</span></div>`).join("")}`;
    return toast("One or more selected items have not passed the two-copy gate.", true);
  }
  state.deletionPreview = preview;
  $("#delete-preview-items").innerHTML = preview.eligible.map(item => `<div class="preview-delete-row"><strong>${escapeHtml(item.filename)}</strong><span>${escapeHtml(item.source_kind)}</span></div>`).join("");
  $("#delete-confirm-label").textContent = `Type ${preview.confirmation_text}`;
  $("#delete-confirm-input").value = "";
  $("#delete-dialog").showModal();
}

async function executeDeletion() {
  const value = await api("/api/deletions/execute", {method: "POST", body: JSON.stringify({token: state.deletionPreview.token, confirmation_text: $("#delete-confirm-input").value})});
  $("#delete-dialog").close();
  $("#deletion-result").innerHTML = `<h3>${value.deleted} deleted directly</h3>${value.results.map(item => `<div class="preview-delete-row"><strong>${escapeHtml(item.filename)}</strong><span>${escapeHtml(item.status)}${item.error ? ` · ${escapeHtml(item.error)}` : ""}</span></div>`).join("")}`;
  toast("Deletion attempt finished; review each recorded result.");
  await loadItems();
}

$$(".nav-item").forEach(button => button.addEventListener("click", () => showView(button.dataset.view)));
$$('[data-jump]').forEach(button => button.addEventListener("click", () => showView(button.dataset.jump)));
$("#refresh-all").addEventListener("click", async () => { await Promise.all([loadStatus(), loadSources(), loadItems()]); toast("Workspace refreshed."); });
$("#apply-filters").addEventListener("click", () => loadItems().catch(error => toast(error.message, true)));
$("#filter-search").addEventListener("keydown", event => { if (event.key === "Enter") loadItems().catch(error => toast(error.message, true)); });
$("#media-list").addEventListener("change", event => {
  const check = event.target.closest(".media-check");
  if (!check) return;
  const row = check.closest(".media-row");
  check.checked ? state.selected.add(row.dataset.id) : state.selected.delete(row.dataset.id);
  row.classList.toggle("selected", check.checked);
  renderSelection();
});
$("#select-all").addEventListener("change", event => {
  state.selected = event.target.checked ? new Set(state.items.map(item => item.item_id)) : new Set();
  renderItems();
});
$("#set-disposition").addEventListener("click", async () => {
  try {
    const ids = [...state.selected];
    await api("/api/items/disposition", {method: "PATCH", body: JSON.stringify({item_ids: ids, disposition: $("#bulk-disposition").value})});
    await loadItems(); toast("Selected item plan updated.");
  } catch (error) { toast(error.message, true); }
});
$("#start-transfer").addEventListener("click", openTransferDialog);
$("#confirm-transfer").addEventListener("click", () => startTransfer().catch(error => toast(error.message, true)));
$("#source-kind").addEventListener("change", updateSourcePathControls);
$("#source-form").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    const kind = $("#source-kind").value;
    await api("/api/sources", {method: "POST", body: JSON.stringify({kind, label: $("#source-label").value, path: kind === "iphone_usb" ? null : $("#source-path").value})});
    event.target.reset(); updateSourcePathControls(); await loadSources(); toast("Source added.");
  } catch (error) { toast(error.message, true); }
});
$("#pick-source").addEventListener("click", () => pickFolder($("#source-path")).catch(error => toast(error.message, true)));
$("#source-list").addEventListener("click", event => {
  const button = event.target.closest(".scan-source");
  if (button) scanOne(button.closest(".source-row").dataset.id).catch(error => toast(error.message, true));
});
$("#scan-all").addEventListener("click", async () => {
  for (const source of state.sources) {
    try { await scanOne(source.source_id); } catch (error) { toast(`${source.label}: ${error.message}`, true); }
  }
});
$("#refresh-jobs").addEventListener("click", () => loadJobs().catch(error => toast(error.message, true)));
$("#job-list").addEventListener("click", async event => {
  const button = event.target.closest(".cancel-job");
  if (!button) return;
  try { await api(`/api/jobs/${button.closest(".job-row").dataset.id}/cancel`, {method: "POST", body: "{}"}); await loadJobs(); } catch (error) { toast(error.message, true); }
});
$("#refresh-duplicates").addEventListener("click", () => loadDuplicates().catch(error => toast(error.message, true)));
$("#transcribe-selected").addEventListener("click", async () => {
  try {
    const ids = currentSelection().filter(item => item.media_kind === "audio").map(item => item.item_id);
    const value = await api("/api/transcriptions", {method: "POST", body: JSON.stringify({item_ids: ids, model: $("#transcription-model").value})});
    toast(`Transcription job ${value.job_id.slice(0, 8)} started.`); showView("transfers");
  } catch (error) { toast(error.message, true); }
});
$("#preview-deletion").addEventListener("click", () => previewDeletion().catch(error => toast(error.message, true)));
$("#confirm-deletion").addEventListener("click", () => executeDeletion().catch(error => toast(error.message, true)));
$("#pick-destination").addEventListener("click", () => pickFolder($("#destination-path")).catch(error => toast(error.message, true)));
$("#pick-secondary-destination").addEventListener("click", () => pickFolder($("#secondary-destination-path")).catch(error => toast(error.message, true)));
$("#destination-form").addEventListener("submit", async event => {
  event.preventDefault();
  try { await api("/api/destination", {method: "POST", body: JSON.stringify({path: $("#destination-path").value})}); await loadStatus(); toast("Archive destination verified and saved."); } catch (error) { toast(error.message, true); }
});
$("#secondary-destination-form").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    await api("/api/secondary-destination", {method: "POST", body: JSON.stringify({path: $("#secondary-destination-path").value})});
    await loadStatus(); toast("Independent second-copy destination verified and saved.");
  } catch (error) { toast(error.message, true); }
});
$("#limits-form").addEventListener("submit", async event => {
  event.preventDefault();
  const toBytes = value => value ? Math.round(Number(value) * 1024 ** 3) : null;
  try { await api("/api/settings/limits", {method: "POST", body: JSON.stringify({batch_bytes: toBytes($("#batch-limit").value), file_bytes: toBytes($("#file-limit").value)})}); await loadStatus(); toast("Download limits saved."); } catch (error) { toast(error.message, true); }
});
$("#google-form").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    await api("/api/google/destination", {method: "POST", body: JSON.stringify({name: $("#google-folder").value})});
    toast("Complete Google authorization in the browser window.");
    await api("/api/google/connect", {method: "POST", body: JSON.stringify({client_secrets_path: $("#google-secrets").value})});
    await loadStatus(); toast("Google Drive connected.");
  } catch (error) { toast(error.message, true); }
});

async function initialize() {
  try {
    await Promise.all([loadStatus(), loadSources(), loadItems()]);
    updateSourcePathControls();
    setInterval(() => {
      if ($("#transfers-view").classList.contains("active")) loadJobs().catch(() => {});
    }, 2500);
  } catch (error) {
    toast(error.message, true);
  }
}

initialize();
