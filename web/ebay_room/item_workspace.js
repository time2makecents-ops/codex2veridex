/* Full-page eBay item workspace. Loaded after app.js so it can reuse governed APIs. */
let workspaceItem = null;
let workspaceTab = "item";
let workspaceMarket = "ebay";
let workspaceMarkets = [];
let workspaceListingPhotos = [];
let workspaceZipFile = null;
let workspaceDraftOverrides = {};
let workspaceThreadResults = {};
let workspaceGroups = [];
let workspaceSelectedGroupId = "";
let workspaceFetchedGroupAccess = null;
let workspaceGroupFetchAttemptedUrl = "";
let workspaceGroupFilter = "";
let workspaceGroupDecisionFilter = "all";
let workspaceGroupAutosaveTimer = 0;
let workspaceSavePromise = null;
let workspaceQuestions = [];
let workspaceSelectedQuestionId = "";

const workspaceTabs = [
  ["item", "Item"],
  ["gallery", "Gallery"],
  ["research", "Research & Questions"],
  ["market", "Market"],
  ["threads", "AI Chat Threads"],
  ["groups", "Groups"],
];

function workspaceQuery() { return new URLSearchParams(location.search); }
function workspaceUrl(replace = false) {
  const query = workspaceQuery();
  if (workspaceItem) {
    query.set("item_id", workspaceItem.item_id);
    query.set("tab", workspaceTab);
    if (workspaceTab === "market") query.set("market", workspaceMarket);
    else query.delete("market");
  } else {
    query.delete("item_id"); query.delete("tab"); query.delete("market");
  }
  history[replace ? "replaceState" : "pushState"]({}, "", `${location.pathname}?${query}`);
}
function workspaceDraft(channel) {
  if (workspaceDraftOverrides[channel]) return workspaceDraftOverrides[channel];
  const row = (state.data?.board?.items || []).find((entry) => entry.item_id === workspaceItem?.item_id);
  return (row?.channel_drafts || []).find((draft) => draft.channel === channel)?.payload || {};
}
function workspaceShowBoard(push = true) {
  workspaceItem = null;
  state.activeItemId = "";
  document.body.classList.remove("item-open");
  $("item-page").hidden = true;
  if (push) workspaceUrl();
}
function workspaceStatus(message = "") {
  const node = $("workspace-status");
  if (node) node.textContent = message;
}
function workspaceHeader() {
  const photos = (workspaceItem.assets || []).filter((row) => row.role === "photo");
  const saveButton = '<button id="workspace-save-all" class="primary" type="button">Save</button>';
  $("item-page-header").innerHTML = `<div class="item-page-title"><button id="workspace-back" type="button">← Inventory</button><h1>${esc(workspaceItem.title || "Untitled item")}</h1><div class="item-page-meta"><span>${esc(workspaceItem.reference_id || "No reference")}</span><span>${photos.length} source photo${photos.length === 1 ? "" : "s"}</span><span>${workspaceListingPhotos.length} listing photo${workspaceListingPhotos.length === 1 ? "" : "s"}</span><span>${money(workspaceItem.estimated_value, workspaceItem.currency)}</span></div></div><div class="item-page-actions"><span id="workspace-status" class="inline-status"></span><button id="workspace-refresh" type="button">Refresh item</button></div>`;
  document.querySelector(".item-page-actions")?.insertAdjacentHTML("afterbegin", saveButton);
  $("workspace-back").onclick = async () => { await workspaceSaveCurrent({ silent: true }); workspaceShowBoard(); };
  $("workspace-refresh").onclick = async () => { await workspaceSaveCurrent({ silent: true }); openItem(workspaceItem.item_id, { replace: true }); };
  $("workspace-save-all").onclick = () => workspaceSaveCurrent();
  $("item-tabs").innerHTML = workspaceTabs.map(([key, label]) => `<button type="button" data-workspace-tab="${key}" class="${workspaceTab === key ? "active" : ""}">${label}</button>`).join("");
  document.querySelectorAll("[data-workspace-tab]").forEach((button) => button.onclick = () => workspaceSwitchTab(button.dataset.workspaceTab));
}
async function workspaceSwitchTab(tab, replace = false) {
  if (workspaceItem && tab !== workspaceTab) await workspaceSaveCurrent({ silent: true });
  workspaceTab = workspaceTabs.some(([key]) => key === tab) ? tab : "item";
  workspaceUrl(replace);
  workspaceHeader();
  workspaceRender();
}
function workspaceRender() {
  if (!workspaceItem) return;
  if (workspaceTab === "item") workspaceRenderItem();
  else if (workspaceTab === "research") workspaceRenderQuestions();
  else if (workspaceTab === "market") workspaceRenderMarket();
  else if (workspaceTab === "threads") workspaceRenderThreads();
  else if (workspaceTab === "groups") workspaceRenderGroupsV2();
  else workspaceRenderGallery();
}

async function workspaceSaveCurrent({ silent = false } = {}) {
  if (!workspaceItem) return true;
  if (workspaceSavePromise) return workspaceSavePromise;
  workspaceSavePromise = (async () => {
    try {
      workspaceStatus("Saving…");
      if (workspaceTab === "gallery") {
        const result = await api("/api/ebay-room/listing-photos", { method: "POST", body: JSON.stringify(payload({ item_id: workspaceItem.item_id, asset_ids: workspaceListingPhotos.map((row) => row.asset_id) })) });
        workspaceItem = result.item || workspaceItem;
        state.details.set(workspaceItem.item_id, workspaceItem);
      } else if (workspaceTab === "research" && $("workspace-notes")) {
        const result = await api("/api/item-intake/items/update", { method: "POST", body: JSON.stringify({ item_id: workspaceItem.item_id, notes: $("workspace-notes").value }) });
        workspaceItem = result.item || workspaceItem;
        state.details.set(workspaceItem.item_id, workspaceItem);
        const draftFinding = $("workspace-question-finding")?.value.trim();
        if (draftFinding && workspaceSelectedQuestionId) await api("/api/ebay-room/research/attach", { method: "POST", body: JSON.stringify(payload({ item_id: workspaceItem.item_id, question_id: workspaceSelectedQuestionId, claim: draftFinding, confirm: true })) });
      } else if (workspaceTab === "market" && $("workspace-market-fields")) {
        const listing = workspaceReadMarketForm();
        if (String(listing.title || "").trim()) {
          state.data = await api("/api/ebay-room/drafts", { method: "POST", body: JSON.stringify(payload({ item_id: workspaceItem.item_id, channel: workspaceMarket, listing })) });
          delete workspaceDraftOverrides[workspaceMarket];
        }
      } else if (workspaceTab === "groups" && $("group-name")?.value.trim()) {
        await workspaceSaveGroup(false, true);
      } else if (workspaceTab === "threads") {
        const values = { chatgpt_thread_url: $("workspace-chatgpt-url")?.value.trim() || workspaceItem.chatgpt_thread_url || "", gemini_thread_url: $("workspace-gemini-url")?.value.trim() || workspaceItem.gemini_thread_url || "" };
        const result = await api("/api/item-intake/items/update", { method: "POST", body: JSON.stringify({ item_id: workspaceItem.item_id, ...values }) });
        workspaceItem = result.item || workspaceItem;
        state.details.set(workspaceItem.item_id, workspaceItem);
      } else if (workspaceTab === "item" && $("home-title")) {
        const price = $("home-price").value;
        const result = await api("/api/item-intake/items/update", { method: "POST", body: JSON.stringify({ item_id: workspaceItem.item_id, title: $("home-title").value.trim(), reference_id: $("home-reference").value.trim(), estimated_value: price === "" ? null : Number(price), status: $("home-status").value, tags: $("home-tags").value.split(",").map((value) => value.trim()).filter(Boolean) }) });
        workspaceItem = result.item || workspaceItem;
        state.details.set(workspaceItem.item_id, workspaceItem);
      }
      workspaceStatus("Saved");
      if (!silent) toast("Work saved.");
      return true;
    } catch (error) {
      workspaceStatus("Save failed");
      if (!silent) toast(error.message);
      return false;
    } finally {
      workspaceSavePromise = null;
    }
  })();
  return workspaceSavePromise;
}

function workspaceRenderItem() {
  const photos = (workspaceItem.assets || []).filter((row) => row.role === "photo");
  const evidence = workspaceItem.evidence || [];
  const markets = workspaceMarkets.filter((row) => row.kind !== "default");
  $("item-tab-panel").innerHTML = `<div class="tab-scroll item-home"><section class="item-home-lead"><div><p class="eyebrow">Item home</p><h2>${esc(workspaceItem.title || "Untitled item")}</h2><p class="item-home-description">${esc(workspaceItem.description || "Add a description so every marketplace draft starts with the same reviewed source.")}</p><div class="item-home-tags">${(workspaceItem.tags || []).map((tag) => `<span>${esc(tag)}</span>`).join("") || "<span>No tags yet</span>"}</div></div><div class="item-home-value"><small>Asking price</small><strong>${money(workspaceItem.estimated_value, workspaceItem.currency)}</strong><span class="item-status">${esc(String(workspaceItem.status || "intake").replaceAll("_", " "))}</span></div></section><div class="item-home-grid"><section class="item-home-section"><div class="item-home-section-head"><div><p class="eyebrow">Master details</p><h3>Keep the source record current</h3></div><button id="workspace-save-home" class="primary" type="button">Save item</button></div><div class="item-home-fields"><label>Title<input id="home-title" value="${esc(workspaceItem.title || "")}"></label><label>Reference<input id="home-reference" value="${esc(workspaceItem.reference_id || "")}"></label><label>Asking price<input id="home-price" type="number" step="0.01" value="${esc(workspaceItem.estimated_value ?? "")}"></label><label>Status<select id="home-status">${["intake", "needs_review", "research_ready", "listed"].map((value) => `<option value="${value}" ${workspaceItem.status === value ? "selected" : ""}>${value.replaceAll("_", " ")}</option>`).join("")}</select></label><label class="wide">Tags<input id="home-tags" value="${esc((workspaceItem.tags || []).join(", "))}"></label></div></section><aside class="item-home-section item-home-stats"><p class="eyebrow">Workspace status</p><div class="item-stat"><strong>${photos.length}</strong><span>source photos</span><button data-home-tab="gallery" type="button">Open gallery →</button></div><div class="item-stat"><strong>${workspaceListingPhotos.length}</strong><span>selected listing photos</span><button data-home-tab="gallery" type="button">Set order →</button></div><div class="item-stat"><strong>${evidence.length}</strong><span>reviewed findings</span><button data-home-tab="research" type="button">Open research →</button></div><div class="item-stat"><strong>${workspaceMarkets.length}</strong><span>market forms</span><button data-home-tab="market" type="button">Open market →</button></div></aside></div><section class="item-home-next"><div><p class="eyebrow">Continue working</p><h3>Choose the next workspace</h3></div><div class="item-home-actions"><button data-home-tab="gallery" type="button">Gallery</button><button data-home-tab="research" type="button">Research & Questions</button><button data-home-tab="market" type="button">Market</button><button data-home-tab="threads" type="button">AI Chat Threads</button></div></section>${markets.length ? `<p class="item-home-footnote">Additional marketplaces: ${markets.map((row) => esc(row.name)).join(", ")}</p>` : ""}</div>`;
  const plannedGroups = workspaceGroups.filter((group) => group.targeted);
  const nextPlannedGroup = plannedGroups.find((group) => group.target?.status === "ready") || plannedGroups.find((group) => group.target?.status === "planned") || plannedGroups[0];
  const groupPlan = nextPlannedGroup
    ? `<button type="button" data-home-group="${esc(nextPlannedGroup.group_id)}"><strong>${esc(nextPlannedGroup.name)}</strong><small>${esc(nextPlannedGroup.posting_recommendation?.reason || "Open the saved group plan to review its rules and capacity.")}</small></button>${plannedGroups.length > 1 ? `<button type="button" data-home-tab="groups">View all ${plannedGroups.length} planned groups</button>` : ""}`
    : `<button type="button" data-home-tab="groups">Choose a Facebook group</button>`;
  const groupPlanCopy = nextPlannedGroup
    ? `${plannedGroups.length} group${plannedGroups.length === 1 ? "" : "s"} explicitly planned for this item.`
    : "No group is planned for this item yet.";
  document.querySelector(".item-home-next")?.insertAdjacentHTML("afterend", `<section class="item-home-next item-home-group-plan"><div><p class="eyebrow">Facebook group plan</p><h3>${nextPlannedGroup ? "Next planned group" : "Choose where this item belongs"}</h3><p class="item-home-footnote">${esc(groupPlanCopy)}</p></div><div class="item-home-actions">${groupPlan}</div></section>`);
  workspaceBindItemHome();
}
function workspaceBindItemHome() {
  document.querySelectorAll("[data-home-tab]").forEach((button) => button.onclick = () => workspaceSwitchTab(button.dataset.homeTab));
  document.querySelectorAll("[data-home-group]").forEach((button) => button.onclick = () => { workspaceSelectedGroupId = button.dataset.homeGroup; workspaceSwitchTab("groups"); });
  $("workspace-save-home").onclick = workspaceSaveItemHome;
}
async function workspaceSaveItemHome() {
  try {
    const price = $("home-price").value;
    const result = await api("/api/item-intake/items/update", { method: "POST", body: JSON.stringify({ item_id: workspaceItem.item_id, title: $("home-title").value.trim(), reference_id: $("home-reference").value.trim(), estimated_value: price === "" ? null : Number(price), status: $("home-status").value, tags: $("home-tags").value.split(",").map((value) => value.trim()).filter(Boolean) }) });
    workspaceItem = result.item; state.details.set(workspaceItem.item_id, workspaceItem); workspaceHeader(); workspaceRenderItem(); toast("Item details saved.");
  } catch (error) { toast(error.message); }
}

openItem = async function workspaceOpenItem(id, options = {}) {
  try {
    state.activeItemId = id;
    workspaceItem = await itemDetail(id, true);
    workspaceListingPhotos = [...(workspaceItem.listing_photos || [])];
    const queryBase = `workspace_id=${encodeURIComponent(state.workspaceId)}&session_id=${encodeURIComponent(state.sessionId)}&item_id=${encodeURIComponent(id)}`;
    const [marketResult, groupResult, questionResult] = await Promise.all([api(`/api/ebay-room/markets?${queryBase}`), api(`/api/ebay-room/groups?${queryBase}`), api(`/api/ebay-room/questions?item_id=${encodeURIComponent(id)}`)]);
    workspaceMarkets = marketResult.markets || [];
    workspaceGroups = groupResult.groups || [];
    workspaceQuestions = questionResult.questions || [];
    if (!workspaceQuestions.some((row) => row.question_id === workspaceSelectedQuestionId)) workspaceSelectedQuestionId = workspaceQuestions[0]?.question_id || "";
    if (!workspaceGroups.some((group) => group.group_id === workspaceSelectedGroupId)) workspaceSelectedGroupId = workspaceGroups[0]?.group_id || "";
    const query = workspaceQuery();
    workspaceTab = workspaceTabs.some(([key]) => key === query.get("tab")) ? query.get("tab") : "item";
    const requestedMarket = query.get("market");
    if (requestedMarket && workspaceMarkets.some((row) => row.market_id === requestedMarket)) workspaceMarket = requestedMarket;
    if (!workspaceMarkets.some((row) => row.market_id === workspaceMarket)) workspaceMarket = "ebay";
    document.body.classList.add("item-open");
    $("item-page").hidden = false;
    workspaceHeader();
    workspaceRender();
    workspaceUrl(Boolean(options.replace));
  } catch (error) { toast(error.message); }
};

window.addEventListener("popstate", async () => {
  const query = workspaceQuery(), id = query.get("item_id");
  if (!id) return workspaceShowBoard(false);
  workspaceTab = query.get("tab") || "gallery";
  workspaceMarket = query.get("market") || "ebay";
  await openItem(id, { replace: true });
});

function workspaceRenderGallery() {
  const photos = (workspaceItem.assets || []).filter((row) => row.role === "photo");
  const selected = new Set(workspaceListingPhotos.map((row) => row.asset_id));
  $("item-tab-panel").innerHTML = `<div class="tab-scroll"><div class="tab-heading"><div><h2>Source materials</h2><p>Add everything here, then choose only the photos that belong in the listing.</p></div></div><div class="gallery-layout"><section class="gallery-library"><div><div id="drop-intake" class="drop-intake"><div class="drop-copy"><strong>Drop photos or a ZIP here</strong><small>Single or multiple photos are supported.</small></div><div class="drop-actions"><label class="button">Add photos<input id="workspace-photo-input" class="hidden-file" type="file" accept="image/*" multiple></label><button id="workspace-zip-choose" type="button">Choose ZIP</button><input id="workspace-zip-input" class="hidden-file" type="file" accept=".zip,application/zip"></div></div><div id="workspace-zip-row" class="zip-inline" ${workspaceZipFile ? "" : "hidden"}><span id="workspace-zip-name">${esc(workspaceZipFile?.name || "")}</span><div><button id="item-zip-extract" class="primary" type="button">Extract</button><button id="workspace-zip-remove" type="button">Remove</button></div></div></div><div class="gallery-grid">${photos.map((photo) => `<article class="gallery-tile ${selected.has(photo.asset_id) ? "selected" : ""}"><button class="gallery-select" data-gallery-select="${esc(photo.asset_id)}" type="button" aria-label="${selected.has(photo.asset_id) ? "Remove from" : "Add to"} listing">${selected.has(photo.asset_id) ? "✓" : "+"}</button><a href="${imageUrl(photo.asset_id)}" target="_blank"><img loading="lazy" src="${imageUrl(photo.asset_id)}" alt="${esc(photo.name)}"></a><div class="gallery-tile-copy"><strong>${esc(photo.name)}</strong><small>${photo.source_asset_id ? "Edited copy" : "Original"}</small></div><div class="gallery-tile-tools"><button data-workspace-touchup="${esc(photo.asset_id)}" type="button">Touch up</button><button class="danger" data-workspace-delete="${esc(photo.asset_id)}" type="button">Delete</button></div></article>`).join("") || '<p class="empty">No photos yet. Add or drop photos above.</p>'}</div></section><aside class="listing-rail"><div class="listing-rail-head"><div><h3>Listing photos</h3><small>First photo is the main image.</small></div><strong>${workspaceListingPhotos.length}</strong></div><div id="workspace-rail" class="listing-rail-list">${workspaceListingPhotos.map((photo, index) => workspaceRailPhoto(photo, index)).join("") || '<p class="empty">Select photos from the gallery.</p>'}</div><button id="workspace-save-order" class="primary" type="button">Save listing selection</button></aside></div></div>`;
  workspaceBindGallery();
}
function workspaceRailPhoto(photo, index) {
  return `<article class="rail-photo" draggable="true" data-rail-photo="${esc(photo.asset_id)}"><strong>${index === 0 ? "Main" : `#${index + 1}`}</strong><img src="${imageUrl(photo.asset_id)}" alt="${esc(photo.name)}"><div><strong>${esc(photo.name)}</strong><div class="rail-actions"><button data-rail-move="${esc(photo.asset_id)}" data-direction="up" ${index === 0 ? "disabled" : ""}>↑</button><button data-rail-move="${esc(photo.asset_id)}" data-direction="down" ${index === workspaceListingPhotos.length - 1 ? "disabled" : ""}>↓</button><button data-gallery-select="${esc(photo.asset_id)}">Remove</button></div></div></article>`;
}
function workspaceTogglePhoto(assetId) {
  const at = workspaceListingPhotos.findIndex((row) => row.asset_id === assetId);
  if (at >= 0) workspaceListingPhotos.splice(at, 1);
  else {
    const photo = (workspaceItem.assets || []).find((row) => row.asset_id === assetId);
    if (photo) workspaceListingPhotos.push(photo);
  }
  workspaceRenderGallery();
}
function workspaceMovePhoto(assetId, direction) {
  const from = workspaceListingPhotos.findIndex((row) => row.asset_id === assetId);
  const to = direction === "up" ? from - 1 : from + 1;
  if (from < 0 || to < 0 || to >= workspaceListingPhotos.length) return;
  [workspaceListingPhotos[from], workspaceListingPhotos[to]] = [workspaceListingPhotos[to], workspaceListingPhotos[from]];
  workspaceRenderGallery();
}
async function workspaceUploadPhotos(files) {
  const images = [...(files || [])].filter((file) => file.type.startsWith("image/"));
  if (!images.length) return;
  workspaceStatus(`Adding ${images.length} photo${images.length === 1 ? "" : "s"}…`);
  for (const file of images) await api(`/api/item-intake/items/${workspaceItem.item_id}/assets?name=${encodeURIComponent(file.name)}&role=photo`, { method: "POST", headers: { "Content-Type": file.type || "application/octet-stream" }, body: file });
  state.details.delete(workspaceItem.item_id);
  await load(state.activeBatchId);
  await openItem(workspaceItem.item_id, { replace: true });
  toast("Photos added to this item.");
}
function workspaceBindGallery() {
  document.querySelectorAll("[data-gallery-select]").forEach((button) => button.onclick = () => workspaceTogglePhoto(button.dataset.gallerySelect));
  document.querySelectorAll("[data-rail-move]").forEach((button) => button.onclick = () => workspaceMovePhoto(button.dataset.railMove, button.dataset.direction));
  document.querySelectorAll("[data-workspace-touchup]").forEach((button) => button.onclick = () => openPhotoTouchup(button.dataset.workspaceTouchup));
  document.querySelectorAll("[data-workspace-delete]").forEach((button) => button.onclick = () => deletePhoto(workspaceItem.item_id, button.dataset.workspaceDelete));
  $("workspace-save-order").onclick = () => saveListingPhotos(workspaceItem.item_id, workspaceListingPhotos.map((row) => row.asset_id));
  $("workspace-photo-input").onchange = (event) => workspaceUploadPhotos(event.target.files).catch((error) => toast(error.message));
  $("workspace-zip-choose").onclick = () => $("workspace-zip-input").click();
  $("workspace-zip-input").onchange = (event) => { workspaceZipFile = event.target.files?.[0] || null; workspaceRenderGallery(); };
  if ($("workspace-zip-remove")) $("workspace-zip-remove").onclick = () => { workspaceZipFile = null; workspaceRenderGallery(); };
  if ($("item-zip-extract")) $("item-zip-extract").onclick = () => extractZip(workspaceItem.item_id, workspaceZipFile);
  const drop = $("drop-intake");
  ["dragenter", "dragover"].forEach((name) => drop.addEventListener(name, (event) => { event.preventDefault(); drop.classList.add("dragover"); }));
  ["dragleave", "drop"].forEach((name) => drop.addEventListener(name, (event) => { event.preventDefault(); drop.classList.remove("dragover"); }));
  drop.addEventListener("drop", (event) => {
    const files = [...event.dataTransfer.files];
    const zip = files.find((file) => file.name.toLowerCase().endsWith(".zip"));
    if (zip) workspaceZipFile = zip;
    workspaceUploadPhotos(files).then(() => { if (!files.some((file) => file.type.startsWith("image/"))) workspaceRenderGallery(); }).catch((error) => toast(error.message));
  });
  let dragged = "";
  document.querySelectorAll("[data-rail-photo]").forEach((row) => {
    row.ondragstart = () => { dragged = row.dataset.railPhoto; };
    row.ondragover = (event) => event.preventDefault();
    row.ondrop = () => {
      const from = workspaceListingPhotos.findIndex((photo) => photo.asset_id === dragged), to = workspaceListingPhotos.findIndex((photo) => photo.asset_id === row.dataset.railPhoto);
      if (from >= 0 && to >= 0 && from !== to) { const [photo] = workspaceListingPhotos.splice(from, 1); workspaceListingPhotos.splice(to, 0, photo); workspaceRenderGallery(); }
    };
  });
}

function workspaceRenderResearch() {
  $("item-tab-panel").innerHTML = `<div class="tab-scroll"><div class="tab-heading"><div><h2>Research & questions</h2><p>Keep your working notes, reviewed findings, and item-specific conversation together.</p></div></div><div class="research-layout"><section class="research-column"><label>Working notes<textarea id="workspace-notes" placeholder="Questions, measurements, observations, and next steps">${esc(workspaceItem.notes || "")}</textarea></label><button id="workspace-save-notes" class="primary" type="button">Save notes</button><div class="research-list"><h3>Reviewed findings</h3>${(workspaceItem.evidence || []).map((row) => `<article class="research-finding"><strong>${esc(row.claim)}</strong><div class="meta">${esc(row.kind || "note")} · ${esc(row.confidence || "unrated")}</div></article>`).join("") || '<p class="empty">No reviewed findings yet.</p>'}</div><label>Add a reviewed finding<textarea id="workspace-finding" placeholder="A conclusion you reviewed and want stored with this item"></textarea></label><button id="workspace-save-finding" type="button">Save finding</button></section><section class="bob-chat"><div class="bob-chat-head"><div><p class="eyebrow">Item assistant</p><h3>Bob</h3></div><small>Only this item's chat</small></div><div id="workspace-bob-messages" class="bob-messages"><p class="empty">Loading conversation…</p></div><div class="bob-composer"><textarea id="workspace-bob-input" placeholder="Ask Bob to research, compare, or prepare listing copy for this item"></textarea><button id="workspace-bob-send" class="primary" type="button">Send</button></div></section></div></div>`;
  $("workspace-save-notes").onclick = workspaceSaveNotes;
  $("workspace-save-finding").onclick = workspaceSaveFinding;
  $("workspace-bob-send").onclick = workspaceSendBob;
  workspaceLoadBob();
}
async function workspaceSaveNotes() {
  try {
    const result = await api("/api/item-intake/items/update", { method: "POST", body: JSON.stringify({ item_id: workspaceItem.item_id, notes: $("workspace-notes").value }) });
    workspaceItem = result.item; state.details.set(workspaceItem.item_id, workspaceItem); toast("Notes saved.");
  } catch (error) { toast(error.message); }
}
async function workspaceAttachFinding(claim) {
  await api("/api/ebay-room/research/attach", { method: "POST", body: JSON.stringify(payload({ item_id: workspaceItem.item_id, claim })) });
  state.details.delete(workspaceItem.item_id);
  await openItem(workspaceItem.item_id, { replace: true });
}
async function workspaceSaveFinding() {
  const claim = $("workspace-finding").value.trim();
  if (!claim) return toast("Write the reviewed finding first.");
  try { await workspaceAttachFinding(claim); toast("Finding saved with this item."); } catch (error) { toast(error.message); }
}
async function workspaceLoadBob() {
  try {
    const result = await api(`/api/ebay-room/item-chat?workspace_id=${encodeURIComponent(state.workspaceId)}&session_id=${encodeURIComponent(state.sessionId)}&item_id=${encodeURIComponent(workspaceItem.item_id)}`);
    workspaceRenderBobMessages(result.messages || []);
  } catch (error) { $("workspace-bob-messages").innerHTML = `<p class="empty">${esc(error.message)}</p>`; }
}
function workspaceRenderBobMessages(messages) {
  const box = $("workspace-bob-messages");
  if (!box) return;
  box.innerHTML = messages.map((row, index) => `<article class="bob-message ${row.role === "user" ? "user" : "assistant"}">${esc(row.content || row.text || "")}${row.role === "assistant" ? `<footer><button data-save-bob="${index}" type="button">Save as finding</button></footer>` : ""}</article>`).join("") || '<p class="empty">Ask Bob a question about this item.</p>';
  document.querySelectorAll("[data-save-bob]").forEach((button) => button.onclick = async () => {
    const row = messages[Number(button.dataset.saveBob)], claim = String(row?.content || row?.text || "").trim();
    if (!claim || !confirm("Save this reviewed Bob response as an item finding?")) return;
    try { await workspaceAttachFinding(claim); toast("Bob's response was saved as a reviewed finding."); } catch (error) { toast(error.message); }
  });
  box.scrollTop = box.scrollHeight;
}
async function workspaceSendBob() {
  const input = $("workspace-bob-input"), text = input.value.trim(), button = $("workspace-bob-send");
  if (!text) return;
  button.disabled = true; button.textContent = "Working…";
  try {
    const result = await api("/api/ebay-room/item-chat", { method: "POST", body: JSON.stringify(payload({ item_id: workspaceItem.item_id, text })) });
    input.value = ""; workspaceRenderBobMessages(result.messages || []);
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; button.textContent = "Send"; }
}

const workspaceMarketFields = {
  ebay: [["title", "Title", "text", true], ["price", "Price", "number"], ["condition", "Condition", "text"], ["category", "Category", "text"], ["shipping", "Shipping", "text", true], ["item_specifics", "Item specifics", "textarea", true], ["description", "Description", "textarea", true]],
  facebook: [["title", "Title", "text", true], ["price", "Price", "number"], ["category", "Category", "text"], ["condition", "Condition", "text"], ["location", "Location", "text", true], ["description", "Description", "textarea", true]],
  craigslist: [["title", "Title", "text", true], ["price", "Price", "number"], ["category", "Category", "text"], ["condition", "Condition", "text"], ["area", "Area", "text"], ["fulfillment", "Pickup / delivery", "text"], ["description", "Description", "textarea", true]],
  etsy: [["title", "Title", "text", true], ["price", "Price", "number"], ["quantity", "Quantity", "number"], ["category", "Category", "text"], ["maker", "Who made it", "text"], ["made_when", "When made", "text"], ["materials", "Materials", "text", true], ["tags", "Tags", "text", true], ["shipping", "Shipping", "text", true], ["description", "Description", "textarea", true]],
};
function workspaceGenericFields() { return [["title", "Title", "text", true], ["price", "Price", "number"], ["category", "Category", "text"], ["condition", "Condition", "text"], ["shipping", "Shipping / pickup", "text", true], ["description", "Description", "textarea", true]]; }
function workspaceFieldsFor(market) { return workspaceMarketFields[market] || workspaceGenericFields(); }
function workspaceInitialDraft(market) {
  const draft = { ...workspaceDraft(market) };
  if (draft.title == null) draft.title = workspaceItem.title || "";
  if (draft.description == null) draft.description = workspaceItem.description || "";
  if (draft.price == null) draft.price = workspaceItem.estimated_value ?? "";
  if (draft.currency == null) draft.currency = workspaceItem.currency || "USD";
  return draft;
}
function workspaceRenderMarket() {
  const market = workspaceMarkets.find((row) => row.market_id === workspaceMarket) || workspaceMarkets[0];
  if (!market) return;
  workspaceMarket = market.market_id;
  const draft = workspaceInitialDraft(workspaceMarket), fields = workspaceFieldsFor(workspaceMarket);
  $("item-tab-panel").innerHTML = `<div class="tab-scroll market-layout"><div class="tab-heading"><div><h2>Market</h2><p>Build one marketplace listing at a time. Drafts stay local until you use a governed handoff.</p></div></div><div><div class="market-tabs">${workspaceMarkets.map((row) => `<button type="button" data-market-tab="${esc(row.market_id)}" class="${row.market_id === workspaceMarket ? "active" : ""}">${esc(row.name)}</button>`).join("")}<button id="workspace-add-market" type="button">+ Add</button></div><div id="workspace-add-market-menu" class="add-market-menu" hidden><span>Presets:</span>${[["offerup", "OfferUp"], ["mercari", "Mercari"], ["poshmark", "Poshmark"], ["depop", "Depop"]].map(([id, label]) => `<button data-add-preset="${id}" type="button">${label}</button>`).join("")}<input id="workspace-custom-market" placeholder="Other marketplace"><button id="workspace-add-custom" type="button">Add custom</button></div></div><section class="market-form-shell"><details class="item-basics"><summary>Master item details</summary><div class="item-basics-body"><div class="market-fields"><label>Item title<input id="master-title" value="${esc(workspaceItem.title || "")}"></label><label>Reference<input id="master-reference" value="${esc(workspaceItem.reference_id || "")}"></label><label>Asking price<input id="master-price" type="number" step="0.01" value="${esc(workspaceItem.estimated_value ?? "")}"></label><label>Status<select id="master-status">${["intake", "needs_review", "research_ready", "listed"].map((value) => `<option value="${value}" ${workspaceItem.status === value ? "selected" : ""}>${value.replaceAll("_", " ")}</option>`).join("")}</select></label><label class="wide">Tags<input id="master-tags" value="${esc((workspaceItem.tags || []).join(", "))}"></label><label class="wide">Master description<textarea id="master-description">${esc(workspaceItem.description || "")}</textarea></label></div><button id="workspace-save-master" type="button">Save master item</button></div></details><div class="market-form-head"><div><p class="eyebrow">${esc(market.kind || "market")}</p><h3>${esc(market.name)} listing</h3></div><div class="market-actions"><button id="workspace-populate-item" type="button">Populate from item</button>${workspaceDraftOverrides[workspaceMarket] ? '<button id="workspace-use-ai" type="button">Use AI draft</button>' : ""}<button id="workspace-save-market" class="primary" type="button">Save local draft</button></div></div><div id="workspace-market-fields" class="market-fields">${fields.map(([key, label, kind, wide]) => `<label class="${wide ? "wide" : ""}">${label}${kind === "textarea" ? `<textarea data-market-field="${key}">${esc(typeof draft[key] === "object" ? JSON.stringify(draft[key], null, 2) : draft[key] ?? "")}</textarea>` : `<input data-market-field="${key}" type="${kind}" step="${kind === "number" ? "0.01" : ""}" value="${esc(draft[key] ?? "")}">`}</label>`).join("")}</div>${workspaceMarket === "ebay" ? '<div class="market-actions"><input id="detail-ebay-listing" placeholder="eBay item number or listing URL"><button id="workspace-find-ebay" type="button">Find connected eBay listing</button></div>' : ""}${workspaceMarket === "facebook" ? '<div class="market-actions"><button id="workspace-prepare-facebook" type="button">Prepare Facebook Marketplace</button><small>You make the final Publish click.</small></div>' : ""}</section></div>`;
  workspaceBindMarket();
}

function workspaceGroupDraft() {
  return workspaceGroups.find((group) => group.group_id === workspaceSelectedGroupId) || {
    group_id: "", name: "", url: "", description: "", rules_text: "", requirements_text: "", allowed_item_types: "", posting_notes: "", eligibility_status: "not_reviewed", membership_status: "", membership_status_source: "", targeted: false, target: null,
  };
}
function workspaceGroupMissing(group) {
  const labels = [["url", "group link"], ["description", "basic info"], ["rules_text", "rules"], ["requirements_text", "requirements"], ["allowed_item_types", "allowed item types"]];
  return labels.filter(([key]) => !String(group?.[key] || "").trim()).map(([, label]) => label);
}
function workspaceGroupAccessLabel(group) {
  const status = String(group?.facebook_access_status || "unknown").replaceAll("_", " ");
  const detail = String(group?.facebook_access_detail || "No Facebook membership signal has been checked yet.");
  return `${status.charAt(0).toUpperCase()}${status.slice(1)} — ${detail}`;
}
function workspaceMembershipStatus(group) {
  return String(group?.membership_status || group?.facebook_access_status || "unknown").trim().toLowerCase();
}
function workspaceRenderGroupsLegacy() {
  const group = workspaceGroupDraft();
  const postTracking = group.post_tracking || {};
  const recommendation = group.posting_recommendation || { status: "needs_review", reason: "Finish the group profile before posting." };
  const decisionCounts = workspaceGroups.reduce((counts, row) => { const key = String(row.posting_recommendation?.status || "needs_review"); counts[key] = (counts[key] || 0) + 1; return counts; }, {});
  const followUps = workspaceGroups.filter((row) => row.follow_up?.message);
  const quotaMessage = Number(postTracking.limit || 0) > 0
    ? `${Number(postTracking.remaining || 0)} posts remaining (${Number(postTracking.limit)} ${String(postTracking.period || "").replace("per_", "per ").replace("active_total", "active total")}).${postTracking.warning ? " Warning: you are almost out of posts." : ""}${postTracking.next_available_at ? ` Next available after ${String(postTracking.next_available_at).replace("T", " ").replace("Z", " UTC")}.` : ""}`
    : "Set a group limit when its rules specify one.";
  const missing = workspaceGroupMissing(group);
  const reviewReady = group.eligibility_status === "eligible" && !missing.length;
  const statuses = [["not_reviewed", "Not reviewed"], ["eligible", "Eligible"], ["needs_requirements", "Needs requirements"], ["not_allowed", "Not allowed"], ["unclear", "Unclear"]];
  const list = workspaceGroups.map((row) => `<button type="button" class="group-entry ${row.group_id === workspaceSelectedGroupId ? "active" : ""}" data-group-select="${esc(row.group_id)}"><strong>${esc(row.name)}</strong><span>${esc((row.eligibility_status || "not_reviewed").replaceAll("_", " "))}</span><em>${esc((row.posting_recommendation?.status || "needs_review").replaceAll("_", " "))}</em>${row.targeted ? "<em>Targeted for this item</em>" : ""}</button>`).join("");
  $("item-tab-panel").innerHTML = `<div class="tab-scroll groups-page"><div class="tab-heading"><div><p class="eyebrow">Facebook groups</p><h2>Group rules and posting plan</h2><p>Save each group’s rules once, then keep item-specific posting decisions and requirements beside the item. Bob receives the saved rules as context; “Not reviewed” never counts as permission to post.</p></div><div class="group-actions"><button id="workspace-refresh-groups" type="button" ${workspaceGroups.some((row) => row.url) ? "" : "disabled"}>Refresh saved groups</button><button id="workspace-new-group" class="primary" type="button">+ Add group</button></div></div><div class="groups-layout"><aside class="groups-directory"><h3>Your groups</h3>${list || `<p class="empty-state">No groups saved yet. Add one to store its rules.</p>`}</aside><section class="group-detail"><div class="group-detail-head"><div><p class="eyebrow">${group.group_id ? "Saved group" : "New group"}</p><h3>${esc(group.name || "Add a Facebook group")}</h3></div>${group.group_id ? `<span class="group-status-pill">${esc((group.eligibility_status || "not_reviewed").replaceAll("_", " "))}</span>` : ""}</div><div class="group-fields"><label>Group name<input id="group-name" value="${esc(group.name)}" placeholder="e.g. Hawaii Vintage Collectors"></label><label>Group link<input id="group-url" type="url" value="${esc(group.url)}" placeholder="https://www.facebook.com/groups/..."></label><label>Privacy<textarea id="group-privacy" placeholder="Private or Public…">${esc(group.privacy_text || "")}</textarea></label><label>Visibility<textarea id="group-visibility" placeholder="Visible or Hidden…">${esc(group.visibility_text || "")}</textarea></label><label>History<textarea id="group-history" placeholder="When the group was created…">${esc(group.history_text || "")}</textarea></label><label>Tags<textarea id="group-tags" placeholder="Facebook group categories…">${esc(group.tags_text || "")}</textarea></label><label class="wide">Location<textarea id="group-location" placeholder="City, region, or audience location…">${esc(group.location_text || "")}</textarea></label><label class="wide">Basic info<textarea id="group-description" placeholder="Location, audience, pickup/shipping notes…">${esc(group.description)}</textarea></label><label class="wide">Rules (paste the group rules here)<textarea id="group-rules" rows="8" placeholder="Paste the rules exactly as shown by Facebook…">${esc(group.rules_text)}</textarea></label><label>Requirements to post<textarea id="group-requirements" placeholder="Join duration, approval, photos, price, location…">${esc(group.requirements_text)}</textarea></label><label>Allowed item types / exclusions<textarea id="group-types" placeholder="What belongs here; what is prohibited…">${esc(group.allowed_item_types)}</textarea></label><label class="wide">Posting notes<textarea id="group-notes" placeholder="Practical notes for this group…">${esc(group.posting_notes)}</textarea></label><label>Review status<select id="group-status">${statuses.map(([value, label]) => `<option value="${value}" ${group.eligibility_status === value ? "selected" : ""}>${label}</option>`).join("")}</select></label></div><div class="group-actions"><button id="workspace-save-group" class="primary" type="button">Save group</button>${group.group_id ? `<button id="workspace-target-group" type="button">${group.targeted ? "Update item target" : "Target this item"}</button>` : ""}${group.targeted ? `<button id="workspace-remove-group-target" type="button">Remove item target</button>` : ""}<button id="workspace-ask-group" type="button" ${group.group_id ? "" : "disabled"}>Ask Bob about this group</button></div>${group.targeted ? `<div class="group-target-box"><strong>This item is planned for this group.</strong><label>Item-specific posting note<textarea id="group-target-note">${esc(group.target?.note || "")}</textarea></label><label>Facebook post link (optional)<input id="group-target-post-url" type="url" value="${esc(group.target?.post_url || "")}" placeholder="https://www.facebook.com/groups/..."></label><label>Item target status<select id="group-target-status"><option value="planned" ${group.target?.status === "planned" ? "selected" : ""}>Planned</option><option value="ready" ${group.target?.status === "ready" ? "selected" : ""}>Ready for review</option><option value="posted" ${group.target?.status === "posted" ? "selected" : ""}>Posted</option></select></label></div>` : ""}<div class="group-target-items"><h4>Items planned for this group</h4>${(group.target_items || []).map((item) => `<div><span>${esc(item.title)}</span><small>${esc(item.status || "planned")}${item.post_url ? ` · <a href="${esc(item.post_url)}" target="_blank" rel="noopener">Open post</a>` : ""}</small></div>`).join("") || `<p class="empty-state">No items assigned yet.</p>`}</div></section></div></div>`;
  document.querySelector(".tab-heading")?.insertAdjacentHTML("beforeend", `<p class="meta"><strong>${Number(decisionCounts.ready || 0)} ready</strong> · ${Number(decisionCounts.needs_review || 0)} need review · ${Number(decisionCounts.not_allowed || 0)} blocked for this item</p>`);
  document.querySelector(".tab-heading")?.insertAdjacentHTML("afterend", followUps.length ? `<section class="group-review-state group-follow-up-queue"><strong>Group follow-ups</strong><span>${followUps.length} item${followUps.length === 1 ? "" : "s"} need attention before the next listing.</span><small>${followUps.map((row) => `<button type="button" data-group-follow-up="${esc(row.group_id)}">${esc(row.name)} — ${esc(row.follow_up.message)}${row.follow_up.due_at ? ` (${esc(String(row.follow_up.due_at).replace("T", " ").replace("Z", " UTC"))})` : ""}</button>`).join(" ")}</small></section>` : "");
  document.querySelector("#group-url")?.closest("label")?.insertAdjacentHTML("afterend", `<label>Membership status<select id="group-membership" data-source="${esc(group.membership_status_source || "")}">${[["unknown", "Unknown"], ["joined", "Joined"], ["pending", "Pending"], ["not_joined", "Not joined"], ["denied", "Denied"]].map(([value, label]) => `<option value="${value}" ${workspaceMembershipStatus(group) === value ? "selected" : ""}>${label}</option>`).join("")}</select><small>Fetch updates this from visible Facebook controls. Choose Pending or Denied yourself when Facebook does not show it.</small></label>`);
  document.querySelector("#group-membership")?.closest("label")?.insertAdjacentHTML("afterend", `<label>Posting limit<input id="group-posting-limit" type="number" min="0" step="1" value="${esc(group.posting_limit || "")}" placeholder="No limit recorded"></label><label>Limit period<select id="group-posting-period">${[["", "No limit"], ["per_day", "Posts per day"], ["per_week", "Posts per week"], ["active_total", "Active posts total"]].map(([value, label]) => `<option value="${value}" ${String(group.posting_limit_period || "") === value ? "selected" : ""}>${label}</option>`).join("")}</select></label>`);
  document.querySelector("#group-posting-period")?.closest("label")?.insertAdjacentHTML("afterend", `<label>Existing active posts<input id="group-manual-active-posts" type="number" min="0" step="1" value="${esc(group.manual_active_posts || "")}" placeholder="Posts made before Veridex"></label>`);
  document.querySelector(".group-detail-head")?.insertAdjacentHTML("afterend", `<div class="group-review-state ${reviewReady ? "ready" : "needs-review"}"><strong>${reviewReady ? "Ready for item review" : "Needs review"}</strong><span>${reviewReady ? "Rules and posting requirements are complete." : `Complete: ${esc(missing.join(", ") || "review status")}.`}</span><small>Facebook access: ${esc(workspaceGroupAccessLabel(group))}</small></div>`);
  document.querySelector(".group-review-state")?.insertAdjacentHTML("afterend", `<div class="group-review-state ${postTracking.at_limit ? "needs-review" : ""}"><strong>Post tracker</strong><span>${Number(postTracking.active_posts || 0)} active · ${Number(postTracking.posts_today || 0)} posted today · ${Number(postTracking.posts_this_week || 0)} posted this week · ${Number(postTracking.total_recorded_posts || 0)} recorded total</span><small>${esc(quotaMessage)}${postTracking.rule_evidence ? ` Detected rule: ${esc(postTracking.rule_evidence)}.` : ""}${postTracking.count_mismatch ? ` Facebook shows ${Number(postTracking.facebook_visible_items)} visible items while Veridex has ${Number(postTracking.local_active_posts)} locally marked active; the higher count is protecting the limit.` : ""} Mark an item Posted after you manually post it to add it to the tracker.</small></div><div class="group-review-state"><strong>Facebook Your items</strong><span>${Number(group.facebook_visible_items_count) >= 0 ? `${Number(group.facebook_visible_items_count)} visible items in this group` : "Not available on the last Facebook check"}</span><small>${esc(group.facebook_visible_items_detail || "Fetch the group to check Facebook’s Your items view.")}${(group.facebook_visible_items || []).length ? ` Sampled entries saved locally: ${(group.facebook_visible_items || []).slice(0, 4).map((item) => esc(item.text || item)).join(" · ")}.` : ""}</small></div>`);
  document.querySelectorAll(".group-review-state")[2]?.insertAdjacentHTML("afterend", `<div class="group-review-state"><strong>Recognized posting rules</strong><span>${(group.rule_guidance || []).length ? (group.rule_guidance || []).map(esc).join(" · ") : "No clear checklist items were detected yet."}</span><small>These are suggestions extracted from the saved rules; the original Rules field remains authoritative.</small></div>`);
  document.querySelectorAll(".group-review-state")[3]?.insertAdjacentHTML("afterend", `<div class="group-review-state ${recommendation.status === "ready" ? "ready" : "needs-review"}"><strong>Posting decision: ${esc(String(recommendation.status || "needs_review").replaceAll("_", " "))}</strong><span>${esc(recommendation.reason || "Review the group before posting.")}</span>${group.follow_up?.message ? `<small>Follow-up: ${esc(group.follow_up.message)}${group.follow_up.due_at ? ` Due ${esc(String(group.follow_up.due_at).replace("T", " ").replace("Z", " UTC"))}.` : ""}</small>` : ""}</div>`);
  document.querySelectorAll(".group-review-state")[4]?.insertAdjacentHTML("afterend", `<div class="group-review-state"><strong>Recent post activity</strong><span>${(group.post_events || []).length ? (group.post_events || []).map((event) => `${esc(event.title)} — ${esc(String(event.posted_at || "").replace("T", " ").replace("Z", " UTC"))}`).join(" · ") : "No posts have been recorded here yet."}</span><small>This is Veridex’s local posting log. It records a post only after you mark the item Posted.</small></div>`);
  document.querySelectorAll(".group-review-state")[5]?.insertAdjacentHTML("afterend", `<div class="group-review-state ${recommendation.status === "ready" ? "ready" : "needs-review"}"><strong>Pre-post checklist</strong><span>Membership: ${esc(workspaceMembershipStatus(group).replaceAll("_", " "))} · Quota: ${esc(quotaMessage)} · Rules: ${(group.rule_guidance || []).length ? esc((group.rule_guidance || []).join(" ")) : "review original rules"}</span><small>${recommendation.status === "ready" ? "You can prepare the listing for this group. Post it yourself in Facebook, then mark the item Posted here." : "Resolve the posting decision above before posting."}</small></div>`);
  const targetStatus = $("group-target-status");
  if (targetStatus && !reviewReady) {
    ["ready", "posted"].forEach((value) => { const option = targetStatus.querySelector(`option[value="${value}"]`); if (option) option.disabled = true; });
  }
  if (targetStatus && postTracking.at_limit && group.target?.status !== "posted") {
    const posted = targetStatus.querySelector('option[value="posted"]');
    if (posted) posted.disabled = true;
  }
  document.querySelectorAll("[data-group-select]").forEach((button) => button.onclick = () => { workspaceSelectedGroupId = button.dataset.groupSelect; workspaceRenderGroups(); });
  document.querySelectorAll("[data-group-follow-up]").forEach((button) => button.onclick = () => { workspaceSelectedGroupId = button.dataset.groupFollowUp; workspaceRenderGroups(); });
  const groupUrl = $("group-url");
  if (groupUrl) {
    groupUrl.insertAdjacentHTML("afterend", "<button id=\"workspace-fetch-group\" type=\"button\">Fetch public group info</button><small class=\"meta\">Uses the signed-in Facebook profile; rules and permissions still need your review.</small>");
    $("workspace-fetch-group").onclick = workspaceFetchGroupInfo;
  }
  $("group-membership")?.addEventListener("change", (event) => { event.currentTarget.dataset.source = "manual"; });
  const groupEditorFields = ["group-name", "group-url", "group-status", "group-membership", "group-description", "group-rules", "group-requirements", "group-types", "group-notes", "group-posting-limit", "group-posting-period", "group-manual-active-posts", "group-privacy", "group-visibility", "group-history", "group-tags", "group-location"];
  groupEditorFields.forEach((id) => $(id)?.addEventListener("input", () => workspaceScheduleGroupSave(false)));
  groupEditorFields.forEach((id) => $(id)?.addEventListener("change", () => workspaceScheduleGroupSave(false)));
  ["group-target-status", "group-target-post-url", "group-target-note"].forEach((id) => $(id)?.addEventListener("input", () => workspaceScheduleGroupSave(true)));
  ["group-target-status", "group-target-post-url", "group-target-note"].forEach((id) => $(id)?.addEventListener("change", () => workspaceScheduleGroupSave(true)));
  $("workspace-new-group").onclick = () => { workspaceSelectedGroupId = ""; workspaceGroupFetchAttemptedUrl = ""; workspaceRenderGroups(); $("group-name")?.focus(); };
  if ($("workspace-refresh-groups")) $("workspace-refresh-groups").onclick = workspaceRefreshSavedGroups;
  $("workspace-save-group").onclick = workspaceSaveGroup;
  if ($("workspace-target-group")) $("workspace-target-group").onclick = () => workspaceSaveGroup(true);
  if ($("workspace-remove-group-target")) $("workspace-remove-group-target").onclick = () => workspaceSetGroupTarget(true);
  if ($("workspace-ask-group")) $("workspace-ask-group").onclick = () => workspaceSwitchTab("research");
}
function workspaceRenderGroupsV2() {
  const group = workspaceGroupDraft();
  const tracking = group.post_tracking || {};
  const decision = group.posting_recommendation || { status: "needs_review", reason: "Complete the group profile before posting." };
  const missing = workspaceGroupMissing(group);
  const reviewReady = group.eligibility_status === "eligible" && !missing.length;
  const followUps = workspaceGroups.filter((row) => row.follow_up?.message);
  const reviewOptions = [["not_reviewed", "Not reviewed"], ["eligible", "Eligible"], ["needs_requirements", "Needs requirements"], ["not_allowed", "Not allowed"], ["unclear", "Unclear"]];
  const recommendationLabel = String(decision.status || "needs_review").replaceAll("_", " ");
  const quota = Number(tracking.limit || 0) > 0
    ? `${Number(tracking.remaining || 0)} of ${Number(tracking.limit)} remaining · ${String(tracking.period || "").replace("per_", "per ").replace("active_total", "active posts")}`
    : "No numeric limit saved";
  const groupList = workspaceGroups.map((row) => `<button type="button" class="group-nav-row ${row.group_id === workspaceSelectedGroupId ? "active" : ""}" data-group-select="${esc(row.group_id)}" data-group-decision="${esc(row.posting_recommendation?.status || "needs_review")}" data-group-search="${esc(`${row.name} ${row.posting_recommendation?.reason || ""}`.toLowerCase())}"><span class="group-nav-dot ${esc(row.posting_recommendation?.status || "needs_review")}"></span><span><strong>${esc(row.name)}</strong><small>${esc(row.posting_recommendation?.reason || "Needs review")}</small></span>${row.targeted ? "<em>Item</em>" : ""}</button>`).join("");
  const posts = (group.post_events || []).slice(0, 4);
  const itemRecords = (group.target_items || []).slice(0, 8);
  const visibleItems = (group.facebook_visible_items || []).slice(0, 8);
  const targetControls = group.targeted ? `<section class="group-post-plan"><div><p class="eyebrow">This item in this group</p><h4>Post plan</h4></div><div class="group-plan-grid"><label>Status<select id="group-target-status"><option value="planned" ${group.target?.status === "planned" ? "selected" : ""}>Planned</option><option value="ready" ${group.target?.status === "ready" ? "selected" : ""}>Ready for review</option><option value="posted" ${group.target?.status === "posted" ? "selected" : ""}>Posted</option></select></label><label>Post link<input id="group-target-post-url" type="url" value="${esc(group.target?.post_url || "")}" placeholder="Paste after posting"></label><label class="wide">Item note<textarea id="group-target-note" placeholder="What to include or confirm before posting">${esc(group.target?.note || "")}</textarea></label></div></section>` : "";
  $("item-tab-panel").innerHTML = `<div class="tab-scroll groups-v2"><header class="groups-command"><div><p class="eyebrow">Facebook groups</p><h2>Posting plan</h2><p>${workspaceGroups.length ? "Select a group, check its decision, then prepare the item." : "Add a group to start recording its rules and posting limits."}</p></div><div class="groups-command-actions"><button id="workspace-refresh-groups" type="button" ${workspaceGroups.some((row) => row.url) ? "" : "disabled"}>Refresh groups</button><button id="workspace-new-group" class="primary" type="button">Add group</button></div></header>${followUps.length ? `<div class="groups-followup-strip"><strong>${followUps.length} follow-up${followUps.length === 1 ? "" : "s"}</strong>${followUps.map((row) => `<button type="button" data-group-follow-up="${esc(row.group_id)}">${esc(row.name)}</button>`).join("")}</div>` : ""}<div class="groups-workspace"><aside class="groups-nav"><div class="groups-nav-head"><strong>Saved groups</strong><span>${workspaceGroups.length}</span></div><div class="groups-nav-list">${groupList || `<p class="empty-state">No groups saved.</p>`}</div></aside><main class="groups-main"><section class="group-decision ${esc(decision.status || "needs_review")}"><div><p class="eyebrow">${group.group_id ? "Selected group" : "New group"}</p><h3>${esc(group.name || "Add a Facebook group")}</h3><p>${esc(decision.reason || "Review this group before posting.")}</p>${group.follow_up?.message ? `<small>Follow-up: ${esc(group.follow_up.message)}${group.follow_up.due_at ? ` Due ${esc(String(group.follow_up.due_at).replace("T", " ").replace("Z", " UTC"))}.` : ""}</small>` : ""}</div><div class="group-decision-side"><span class="group-decision-badge">${esc(recommendationLabel)}</span><button id="workspace-save-group" class="primary" type="button">Save</button>${group.group_id ? `<button id="workspace-target-group" type="button">${group.targeted ? "Save post plan" : "Plan this item"}</button>` : ""}</div></section><section class="group-signal-grid"><div><small>Membership</small><strong>${esc(workspaceMembershipStatus(group).replaceAll("_", " "))}</strong><span>${esc(workspaceGroupAccessLabel(group))}</span></div><div><small>Posting capacity</small><strong>${esc(quota)}</strong><span>${Number(tracking.active_posts || 0)} active · ${Number(tracking.posts_today || 0)} today</span></div><div><small>Facebook items</small><strong>${Number(group.facebook_visible_items_count) >= 0 ? `${Number(group.facebook_visible_items_count)} visible` : "Not checked"}</strong><span>${esc(group.facebook_visible_items_detail || "Refresh this group to read visible items.")}</span></div></section><section class="group-profile-quick"><label>Group name<input id="group-name" value="${esc(group.name || "")}" placeholder="e.g. Eugene vintage finds"></label><label>Facebook group link<div class="group-url-row"><input id="group-url" type="url" value="${esc(group.url || "")}" placeholder="https://www.facebook.com/groups/..."><button id="workspace-fetch-group" type="button">Fetch</button></div></label><label>Review status<select id="group-status">${reviewOptions.map(([value, label]) => `<option value="${value}" ${group.eligibility_status === value ? "selected" : ""}>${label}</option>`).join("")}</select></label><label>Membership<select id="group-membership" data-source="${esc(group.membership_status_source || "")}">${[["unknown", "Unknown"], ["joined", "Joined"], ["pending", "Pending"], ["not_joined", "Not joined"], ["denied", "Denied"]].map(([value, label]) => `<option value="${value}" ${workspaceMembershipStatus(group) === value ? "selected" : ""}>${label}</option>`).join("")}</select></label></section>${targetControls}<details class="group-details" open><summary><span>Rules & eligibility</span><small>${reviewReady ? "Complete" : `Missing ${missing.length || "review"}`}</small></summary><div class="group-form-grid"><label class="wide">Basic info<textarea id="group-description" placeholder="Audience, location, pickup or shipping notes">${esc(group.description || "")}</textarea></label><label class="wide">Rules<textarea id="group-rules" rows="7" placeholder="Paste the rules exactly as shown by Facebook">${esc(group.rules_text || "")}</textarea></label><label>Requirements to post<textarea id="group-requirements" placeholder="Approval, photos, price, location">${esc(group.requirements_text || "")}</textarea></label><label>Allowed items / exclusions<textarea id="group-types" placeholder="What belongs here and what is prohibited">${esc(group.allowed_item_types || "")}</textarea></label><label class="wide">Posting notes<textarea id="group-notes" placeholder="Useful details for future posts">${esc(group.posting_notes || "")}</textarea></label></div><div class="group-rule-hints">${(group.rule_guidance || []).map((hint) => `<span>${esc(hint)}</span>`).join("") || "<span>No rule checklist detected yet.</span>"}</div></details><details class="group-details"><summary><span>Posting limits & Facebook profile</span><small>${esc(quota)}</small></summary><div class="group-form-grid"><label>Post limit<input id="group-posting-limit" type="number" min="0" step="1" value="${esc(group.posting_limit || "")}" placeholder="No limit"></label><label>Limit period<select id="group-posting-period">${[["", "No limit"], ["per_day", "Posts per day"], ["per_week", "Posts per week"], ["active_total", "Active posts"]].map(([value, label]) => `<option value="${value}" ${String(group.posting_limit_period || "") === value ? "selected" : ""}>${label}</option>`).join("")}</select></label><label>Existing active posts<input id="group-manual-active-posts" type="number" min="0" step="1" value="${esc(group.manual_active_posts || "")}" placeholder="Before Veridex"></label><label>Privacy<textarea id="group-privacy" placeholder="Private or public">${esc(group.privacy_text || "")}</textarea></label><label>Visibility<textarea id="group-visibility" placeholder="Visible or hidden">${esc(group.visibility_text || "")}</textarea></label><label>History<textarea id="group-history" placeholder="Group history">${esc(group.history_text || "")}</textarea></label><label>Tags<textarea id="group-tags" placeholder="Facebook tags">${esc(group.tags_text || "")}</textarea></label><label>Location<textarea id="group-location" placeholder="City or region">${esc(group.location_text || "")}</textarea></label></div></details><details class="group-details"><summary><span>Evidence & activity</span><small>${posts.length} recent posts · ${visibleItems.length} saved entries</small></summary><div class="group-evidence-grid"><div><h4>Recent post activity</h4>${posts.length ? posts.map((post) => `<p><strong>${esc(post.title)}</strong><span>${esc(String(post.posted_at || "").replace("T", " ").replace("Z", " UTC"))}</span></p>`).join("") : "<p class=\"empty-state\">No local posts recorded.</p>"}</div><div><h4>Facebook Your items</h4>${visibleItems.length ? visibleItems.map((item) => `<p>${esc(item.text || item)}</p>`).join("") : "<p class=\"empty-state\">No visible entries saved yet.</p>"}</div><div><h4>Items planned here</h4>${itemRecords.length ? itemRecords.map((item) => `<p><strong>${esc(item.title)}</strong><span>${esc(item.status || "planned")}${item.post_url ? ` · <a href="${esc(item.post_url)}" target="_blank" rel="noopener">Open post</a>` : ""}</span></p>`).join("") : "<p class=\"empty-state\">No items planned here.</p>"}</div></div></details><footer class="groups-footer"><button id="workspace-ask-group" type="button" ${group.group_id ? "" : "disabled"}>Ask Bob about this group</button>${group.targeted ? `<button id="workspace-remove-group-target" type="button">Remove item plan</button>` : ""}</footer></main></div></div>`;
  const targetStatus = $("group-target-status");
  if (targetStatus && !reviewReady) ["ready", "posted"].forEach((value) => { const option = targetStatus.querySelector(`option[value="${value}"]`); if (option) option.disabled = true; });
  if (targetStatus && tracking.at_limit && group.target?.status !== "posted") { const posted = targetStatus.querySelector('option[value="posted"]'); if (posted) posted.disabled = true; }
  document.querySelectorAll("[data-group-select]").forEach((button) => button.onclick = () => { workspaceSelectedGroupId = button.dataset.groupSelect; workspaceRenderGroupsV2(); });
  document.querySelectorAll("[data-group-follow-up]").forEach((button) => button.onclick = () => { workspaceSelectedGroupId = button.dataset.groupFollowUp; workspaceRenderGroupsV2(); });
  document.querySelector(".groups-nav-head")?.insertAdjacentHTML("afterend", `<input id="group-search" class="group-search" value="${esc(workspaceGroupFilter)}" placeholder="Find a group"><div class="group-filter-row">${[["all", "All"], ["ready", "Ready"], ["needs_review", "Review"], ["not_allowed", "Blocked"]].map(([value, label]) => `<button type="button" data-group-filter="${value}" class="${workspaceGroupDecisionFilter === value ? "active" : ""}">${label}</button>`).join("")}</div>`);
  $("group-search")?.addEventListener("input", (event) => { workspaceGroupFilter = event.currentTarget.value; workspaceApplyGroupNavigatorFilter(); });
  document.querySelectorAll("[data-group-filter]").forEach((button) => button.onclick = () => { workspaceGroupDecisionFilter = button.dataset.groupFilter || "all"; document.querySelectorAll("[data-group-filter]").forEach((node) => node.classList.toggle("active", node === button)); workspaceApplyGroupNavigatorFilter(); });
  workspaceApplyGroupNavigatorFilter();
  const signalCards = document.querySelectorAll(".group-signal-grid > div");
  const checkedAt = (value, fallback) => value ? `Checked ${esc(String(value).replace("T", " ").replace("Z", " UTC"))}` : fallback;
  signalCards[0]?.insertAdjacentHTML("beforeend", `<time>${checkedAt(group.facebook_access_checked_at, group.membership_status_source === "manual" ? "Manual membership status" : "Not checked")}</time>`);
  signalCards[2]?.insertAdjacentHTML("beforeend", `<time>${checkedAt(group.facebook_visible_items_checked_at, "Not checked")}</time>`);
  $("workspace-fetch-group").onclick = workspaceFetchGroupInfo;
  $("group-membership")?.addEventListener("change", (event) => { event.currentTarget.dataset.source = "manual"; });
  $("workspace-new-group").onclick = () => { workspaceSelectedGroupId = ""; workspaceGroupFetchAttemptedUrl = ""; workspaceRenderGroupsV2(); $("group-name")?.focus(); };
  if ($("workspace-refresh-groups")) $("workspace-refresh-groups").onclick = workspaceRefreshSavedGroups;
  $("workspace-save-group").onclick = workspaceSaveGroup;
  if ($("workspace-target-group")) $("workspace-target-group").onclick = () => workspaceSaveGroup(true);
  if ($("workspace-remove-group-target")) $("workspace-remove-group-target").onclick = () => workspaceSetGroupTarget(true);
  if ($("workspace-ask-group")) $("workspace-ask-group").onclick = () => workspaceSwitchTab("research");
}
function workspaceApplyGroupNavigatorFilter() {
  const query = String(workspaceGroupFilter || "").trim().toLowerCase();
  document.querySelectorAll("[data-group-select]").forEach((row) => {
    const matchesText = !query || String(row.dataset.groupSearch || "").includes(query);
    const matchesDecision = workspaceGroupDecisionFilter === "all" || row.dataset.groupDecision === workspaceGroupDecisionFilter;
    row.hidden = !(matchesText && matchesDecision);
  });
}
function workspaceScheduleGroupSave(targetPlan = false) {
  clearTimeout(workspaceGroupAutosaveTimer);
  workspaceStatus("Changes pending");
  workspaceGroupAutosaveTimer = setTimeout(async () => {
    if (targetPlan && workspaceGroupDraft().targeted) await workspaceSetGroupTarget(false, true);
    else if ($("group-name")?.value.trim()) await workspaceSaveGroup(false, true);
  }, 900);
}
async function workspaceRefreshSavedGroups() {
  const groups = workspaceGroups.filter((group) => group.group_id && group.url);
  if (!groups.length) return toast("Save at least one group link before refreshing.");
  const button = $("workspace-refresh-groups");
  button.disabled = true;
  let refreshed = 0;
  try {
    for (const group of groups) {
      button.textContent = `Refreshing ${refreshed + 1} of ${groups.length}…`;
      const fetched = await api("/api/ebay-room/groups/fetch-info", { method: "POST", body: JSON.stringify(payload({ item_id: workspaceItem.item_id, url: group.url })) });
      const info = fetched.info || {};
      const manualMembership = group.membership_status_source === "manual";
      const body = payload({
        group_id: group.group_id, item_id: workspaceItem.item_id, name: group.name, url: info.url || group.url,
        description: info.about_complete !== false && info.description ? info.description : group.description,
        rules_text: group.rules_text || info.rules_text || "", requirements_text: group.requirements_text || "",
        allowed_item_types: group.allowed_item_types || "", posting_notes: group.posting_notes || "", eligibility_status: group.eligibility_status || "not_reviewed",
        facebook_access_status: info.facebook_access_status || group.facebook_access_status || "", facebook_access_detail: info.facebook_access_detail || group.facebook_access_detail || "", facebook_access_checked_at: info.facebook_access_checked_at || group.facebook_access_checked_at || "",
        privacy_text: info.privacy_text || group.privacy_text || "", visibility_text: info.visibility_text || group.visibility_text || "", history_text: info.history_text || group.history_text || "", tags_text: info.tags_text || group.tags_text || "", location_text: info.location_text || group.location_text || "",
        membership_status: manualMembership ? group.membership_status : (info.facebook_access_status || group.membership_status || "unknown"), membership_status_source: manualMembership ? "manual" : "observed",
        posting_limit: group.posting_limit || 0, posting_limit_period: group.posting_limit_period || "", manual_active_posts: group.manual_active_posts || 0,
        facebook_visible_items_count: info.facebook_visible_items_count ?? group.facebook_visible_items_count ?? -1, facebook_visible_items_detail: info.facebook_visible_items_detail || group.facebook_visible_items_detail || "", facebook_visible_items: info.facebook_visible_items || [], facebook_visible_items_checked_at: info.facebook_visible_items_checked_at || group.facebook_visible_items_checked_at || "",
      });
      const saved = await api("/api/ebay-room/groups", { method: "POST", body: JSON.stringify(body) });
      workspaceGroups = saved.groups || workspaceGroups;
      refreshed += 1;
    }
    toast(`Refreshed ${refreshed} saved Facebook group${refreshed === 1 ? "" : "s"}. Review any changed rules before posting.`);
  } catch (error) {
    toast(`Refresh stopped after ${refreshed} group${refreshed === 1 ? "" : "s"}: ${error.message}`);
  } finally {
    workspaceFetchedGroupAccess = null;
    workspaceRenderGroupsV2();
  }
}
async function workspaceFetchGroupInfo() {
  const url = $("group-url")?.value.trim();
  if (!url) return toast("Paste a Facebook group URL first.");
  const button = $("workspace-fetch-group"); button.disabled = true; button.textContent = "Fetching…";
  try {
    const result = await api("/api/ebay-room/groups/fetch-info", { method: "POST", body: JSON.stringify(payload({ item_id: workspaceItem.item_id, url })) });
    if (result.info?.name) $("group-name").value = result.info.name;
    if (result.info?.url) $("group-url").value = result.info.url;
    if (result.info?.description && result.info?.about_complete !== false) $("group-description").value = result.info.description;
    [["privacy", "privacy_text"], ["visibility", "visibility_text"], ["history", "history_text"], ["tags", "tags_text"], ["location", "location_text"]].forEach(([field, key]) => { if (result.info?.[key]) $(`group-${field}`).value = result.info[key]; });
    const membership = $("group-membership");
    if (membership && membership.dataset.source !== "manual" && result.info?.facebook_access_status) {
      membership.value = result.info.facebook_access_status;
      membership.dataset.source = "observed";
    }
    workspaceFetchedGroupAccess = result.info || null;
    const rules = String(result.info?.rules_text || "").trim(), rulesBox = $("group-rules"), existingRules = rulesBox.value.trim();
    if (rules && !existingRules) rulesBox.value = rules;
    if (result.info?.about_complete === false) toast("Rules were fetched, but Facebook kept Basic info collapsed. The cut-off text was not inserted; open the group's About section once, then retry.");
    else if (rules && existingRules && existingRules !== rules) toast("Group information fetched. Existing rules were kept; review the About page rules before replacing them.");
    else if (rules) toast(`Group information and rules fetched${result.info?.expanded_count ? " after expanding See more" : ""}. Review them before saving.`);
    else toast("Group information fetched. Facebook did not expose a Rules section on the About page, so add or verify the rules manually.");
    const saved = await workspaceSaveGroup(false, true);
    if (!saved) return;
    toast("Group information fetched and saved locally. Review the rules and requirements before marking it eligible.");
  } catch (error) { toast("Could not fetch group information: " + error.message); }
  finally { button.disabled = false; button.textContent = "Fetch public group info"; }
}
async function workspaceSaveGroup(targetAfterSave = false, silent = false) {
  try {
    const existing = workspaceGroupDraft();
    const url = $("group-url").value.trim();
    if (!existing.group_id && url && !workspaceFetchedGroupAccess && workspaceGroupFetchAttemptedUrl !== url) {
      workspaceGroupFetchAttemptedUrl = url;
      await workspaceFetchGroupInfo();
      return workspaceGroups.find((group) => group.group_id === workspaceSelectedGroupId) || null;
    }
    const access = workspaceFetchedGroupAccess || existing;
    const membership = $("group-membership");
    const body = payload({ group_id: workspaceSelectedGroupId, item_id: workspaceItem.item_id, name: $("group-name").value.trim(), url: $("group-url").value.trim(), description: $("group-description").value, rules_text: $("group-rules").value, requirements_text: $("group-requirements").value, allowed_item_types: $("group-types").value, posting_notes: $("group-notes").value, eligibility_status: $("group-status").value, facebook_access_status: access.facebook_access_status || "", facebook_access_detail: access.facebook_access_detail || "", facebook_access_checked_at: access.facebook_access_checked_at || "", privacy_text: $("group-privacy").value, visibility_text: $("group-visibility").value, history_text: $("group-history").value, tags_text: $("group-tags").value, location_text: $("group-location").value, membership_status: membership?.value || "", membership_status_source: membership?.dataset.source || "", posting_limit: $("group-posting-limit")?.value || 0, posting_limit_period: $("group-posting-period")?.value || "", manual_active_posts: $("group-manual-active-posts")?.value || 0, facebook_visible_items_count: access.facebook_visible_items_count ?? existing.facebook_visible_items_count ?? -1, facebook_visible_items_detail: access.facebook_visible_items_detail || existing.facebook_visible_items_detail || "", facebook_visible_items: access.facebook_visible_items || existing.facebook_visible_items || [], facebook_visible_items_checked_at: access.facebook_visible_items_checked_at || existing.facebook_visible_items_checked_at || "" });
    const result = await api("/api/ebay-room/groups", { method: "POST", body: JSON.stringify(body) });
    workspaceGroups = result.groups || [];
    workspaceFetchedGroupAccess = null;
    workspaceSelectedGroupId = result.group.group_id;
    if (targetAfterSave) await workspaceSetGroupTarget(false);
    else workspaceRenderGroupsV2();
    workspaceStatus("Saved");
    if (!silent) toast("Facebook group saved.");
    return result.group;
  } catch (error) { workspaceStatus("Save failed"); if (!silent) toast(error.message); return null; }
}
async function workspaceSetGroupTarget(remove = false, silent = false) {
  try {
    const result = await api("/api/ebay-room/groups/target", { method: "POST", body: JSON.stringify(payload({ item_id: workspaceItem.item_id, group_id: workspaceSelectedGroupId, status: $("group-target-status")?.value || "planned", note: $("group-target-note")?.value || "", post_url: $("group-target-post-url")?.value || "", remove })) });
    workspaceGroups = result.groups || []; workspaceRenderGroupsV2(); workspaceStatus("Saved"); if (!silent) toast(remove ? "Item removed from group plan." : "Item added to group plan.");
  } catch (error) { if (!silent) toast(error.message); else workspaceStatus("Save failed"); }
}
function workspaceReadMarketForm() {
  const result = { currency: workspaceItem.currency || "USD" };
  document.querySelectorAll("[data-market-field]").forEach((node) => { result[node.dataset.marketField] = node.type === "number" && node.value !== "" ? Number(node.value) : node.value; });
  return result;
}
function workspaceFillMarket(values) {
  document.querySelectorAll("[data-market-field]").forEach((node) => {
    const key = node.dataset.marketField, value = values[key];
    node.value = typeof value === "object" && value !== null ? JSON.stringify(value, null, 2) : value ?? "";
  });
}
async function workspaceSaveMarketDraft() {
  const listing = workspaceReadMarketForm();
  if (!listing.title?.trim()) return toast("Add a listing title first.");
  try {
    state.data = await api("/api/ebay-room/drafts", { method: "POST", body: JSON.stringify(payload({ item_id: workspaceItem.item_id, channel: workspaceMarket, listing })) });
    delete workspaceDraftOverrides[workspaceMarket]; toast(`${workspaceMarkets.find((row) => row.market_id === workspaceMarket)?.name || "Marketplace"} draft saved locally.`);
  } catch (error) { toast(error.message); }
}
async function workspaceSaveMaster() {
  try {
    const price = $("master-price").value;
    const result = await api("/api/item-intake/items/update", { method: "POST", body: JSON.stringify({ item_id: workspaceItem.item_id, title: $("master-title").value.trim(), reference_id: $("master-reference").value.trim(), estimated_value: price === "" ? null : Number(price), description: $("master-description").value, status: $("master-status").value, tags: $("master-tags").value.split(",").map((value) => value.trim()).filter(Boolean) }) });
    workspaceItem = result.item; state.details.set(workspaceItem.item_id, workspaceItem); workspaceHeader(); toast("Master item details saved.");
  } catch (error) { toast(error.message); }
}
async function workspaceAddMarket(values) {
  try {
    const result = await api("/api/ebay-room/markets", { method: "POST", body: JSON.stringify(payload({ item_id: workspaceItem.item_id, ...values })) });
    workspaceMarkets = result.markets || []; workspaceMarket = result.market.market_id; workspaceUrl(true); workspaceRenderMarket();
  } catch (error) { toast(error.message); }
}
function workspaceBindMarket() {
  document.querySelectorAll("[data-market-tab]").forEach((button) => button.onclick = () => { workspaceMarket = button.dataset.marketTab; workspaceUrl(); workspaceRenderMarket(); });
  $("workspace-add-market").onclick = () => { $("workspace-add-market-menu").hidden = !$("workspace-add-market-menu").hidden; };
  document.querySelectorAll("[data-add-preset]").forEach((button) => button.onclick = () => workspaceAddMarket({ preset: button.dataset.addPreset }));
  $("workspace-add-custom").onclick = () => workspaceAddMarket({ name: $("workspace-custom-market").value });
  $("workspace-populate-item").onclick = () => workspaceFillMarket({ title: workspaceItem.title, description: workspaceItem.description, price: workspaceItem.estimated_value });
  if ($("workspace-use-ai")) $("workspace-use-ai").onclick = () => workspaceFillMarket(workspaceDraftOverrides[workspaceMarket] || {});
  $("workspace-save-market").onclick = workspaceSaveMarketDraft;
  $("workspace-save-master").onclick = workspaceSaveMaster;
  if ($("workspace-find-ebay")) $("workspace-find-ebay").onclick = () => findEbayListing(workspaceItem.item_id);
  if ($("workspace-prepare-facebook")) $("workspace-prepare-facebook").onclick = async () => {
    const listing = workspaceReadMarketForm();
    if (!(workspaceItem.listing_photo_asset_ids || []).length) return toast("Choose and save at least one listing photo first.");
    if (!confirm("Fill Facebook Marketplace with this reviewed draft and the ordered listing photos? You make the final Publish click.")) return;
    try { state.data = await api("/api/ebay-room/facebook/prepare", { method: "POST", body: JSON.stringify(payload({ item_id: workspaceItem.item_id, ...listing })) }); toast("Facebook Marketplace was prepared for your final review."); } catch (error) { toast(error.message); }
  };
}

function workspaceThreadCard(provider, label, value) {
  const shared = isSharedThreadUrl(provider, value || ""), result = workspaceThreadResults[provider];
  return `<section class="thread-source"><h3>${label}</h3><label>Thread link<input id="workspace-${provider}-url" value="${esc(value || "")}" placeholder="Paste a shared ${label} link"></label><p class="meta">${esc(threadKind(provider, value))}</p><div class="thread-actions-row"><button data-thread-save="${provider}" type="button">Save link</button>${value ? `<a class="button" href="${esc(value)}" target="_blank" rel="noreferrer">View</a>` : ""}<button data-thread-extract-inline="${provider}" type="button" ${shared ? "" : "disabled"}>Extract media</button><button data-thread-plan-inline="${provider}" type="button" ${shared ? "" : "disabled"}>Find listing</button><button data-thread-analyze-inline="${provider}" class="primary" type="button" ${shared ? "" : "disabled"}>Analyze</button></div>${result ? `<div class="thread-inline-result"><strong>${esc(result.title || "Thread result")}</strong>\n${esc(result.text || "")}</div>` : ""}</section>`;
}
function workspaceRenderThreads() {
  const plan = workspaceThreadResults.plan;
  $("item-tab-panel").innerHTML = `<div class="tab-scroll"><div class="tab-heading"><div><h2>AI chat threads</h2><p>View original threads, extract media, prepare marketplace drafts, or have Bob analyze the material for this item.</p></div></div><div class="ai-thread-grid">${workspaceThreadCard("chatgpt", "ChatGPT", workspaceItem.chatgpt_thread_url)}${workspaceThreadCard("gemini", "Gemini", workspaceItem.gemini_thread_url)}</div>${plan ? `<section class="ai-plan"><div class="market-form-head"><div><p class="eyebrow">Review required</p><h3>Marketplace listing plan</h3></div><button id="workspace-review-plan" class="primary" type="button">Review in Market</button></div><div class="ai-thread-grid"><div><h4>eBay</h4><strong>${esc(plan.ebay?.title || "Untitled")}</strong><p>${esc(plan.ebay?.description || "")}</p></div><div><h4>Facebook Marketplace</h4><strong>${esc(plan.facebook?.title || "Untitled")}</strong><p>${esc(plan.facebook?.description || "")}</p></div></div></section>` : ""}</div>`;
  document.querySelectorAll("[data-thread-save]").forEach((button) => button.onclick = () => workspaceSaveThreadLinks(button.dataset.threadSave));
  document.querySelectorAll("[data-thread-extract-inline]").forEach((button) => button.onclick = () => workspaceExtractThread(button.dataset.threadExtractInline));
  document.querySelectorAll("[data-thread-plan-inline]").forEach((button) => button.onclick = () => workspacePlanFromThread(button.dataset.threadPlanInline));
  document.querySelectorAll("[data-thread-analyze-inline]").forEach((button) => button.onclick = () => workspaceAnalyzeThread(button.dataset.threadAnalyzeInline));
  if ($("workspace-review-plan")) $("workspace-review-plan").onclick = () => { workspaceTab = "market"; workspaceMarket = "ebay"; workspaceUrl(); workspaceHeader(); workspaceRenderMarket(); };
}
async function workspaceSaveThreadLinks(provider) {
  const values = { chatgpt_thread_url: $("workspace-chatgpt-url").value.trim(), gemini_thread_url: $("workspace-gemini-url").value.trim() };
  try {
    const result = await api("/api/item-intake/items/update", { method: "POST", body: JSON.stringify({ item_id: workspaceItem.item_id, ...values }) });
    workspaceItem = result.item; state.details.set(workspaceItem.item_id, workspaceItem); workspaceRenderThreads(); toast(`${provider === "chatgpt" ? "ChatGPT" : "Gemini"} link saved.`);
  } catch (error) { toast(error.message); }
}
async function workspaceExtractThread(provider) {
  if (!confirm("Extract the reviewed thread text and available images into this item? Existing source files stay unchanged.")) return;
  workspaceThreadResults[provider] = { title: "Extracting…", text: "" }; workspaceRenderThreads();
  try {
    const result = await api("/api/item-intake/threads/import", { method: "POST", body: JSON.stringify({ item_id: workspaceItem.item_id, provider, confirm: true }) });
    workspaceThreadResults[provider] = { title: "Extraction complete", text: `${result.imported?.photos?.length || 0} image(s) added. Thread text was stored with the item.` };
    state.details.delete(workspaceItem.item_id); await load(state.activeBatchId); await openItem(workspaceItem.item_id, { replace: true });
  } catch (error) { workspaceThreadResults[provider] = { title: "Extraction failed", text: error.message }; workspaceRenderThreads(); }
}
async function workspacePlanFromThread(provider) {
  workspaceThreadResults[provider] = { title: "Building marketplace drafts…", text: "" }; workspaceRenderThreads();
  try {
    const result = await api("/api/item-intake/threads/listing-plan", { method: "POST", body: JSON.stringify({ item_id: workspaceItem.item_id, provider }) });
    const plan = result.listing_plan?.plan || {};
    workspaceDraftOverrides.ebay = { ...(plan.ebay || {}), source_kind: "shared_ai_thread", review_required: true };
    workspaceDraftOverrides.facebook = { ...(plan.facebook || {}), source_kind: "shared_ai_thread", review_required: true };
    workspaceThreadResults.plan = plan;
    workspaceThreadResults[provider] = { title: "Listing plan ready", text: "eBay and Facebook drafts are ready for review. Nothing has been published." };
  } catch (error) { workspaceThreadResults[provider] = { title: "Listing plan failed", text: error.message }; }
  workspaceRenderThreads();
}
async function workspaceAnalyzeThread(provider) {
  if (!confirm("Analyze this public thread with Veridex? Its visible text and images will be added to this item, then Bob will analyze the material.")) return;
  workspaceThreadResults[provider] = { title: "Preparing item analysis…", text: "Importing the reviewed thread and attaching it to this item." }; workspaceRenderThreads();
  try {
    const result = await api("/api/item-intake/threads/import", { method: "POST", body: JSON.stringify({ item_id: workspaceItem.item_id, provider, confirm: true }) });
    const assetIds = [result.imported?.source_asset?.asset_id, ...(result.imported?.photos || []).map((row) => row.asset_id)].filter(Boolean);
    const handoff = await api("/api/item-intake/handoff", { method: "POST", body: JSON.stringify(payload({ item_id: workspaceItem.item_id, asset_ids: assetIds })) });
    const attachmentIds = (handoff.handoff?.files || []).map((row) => row.file_id).filter(Boolean);
    const label = provider === "chatgpt" ? "ChatGPT" : "Gemini";
    const analysis = await api("/api/ebay-room/item-chat", { method: "POST", body: JSON.stringify(payload({
      item_id: workspaceItem.item_id,
      attachment_ids: attachmentIds,
      text: `Analyze the attached reviewed ${label} shared-thread material for this item. Build a concise item brief that separates stated facts, reasonable inferences, uncertainties, and missing details. Identify useful next research questions and listing details, but do not change item fields or save claims as verified findings.`,
    })) });
    workspaceThreadResults[provider] = { title: "Analysis complete", text: String(analysis.message?.content || "Bob analyzed the material. Open Research & Questions to continue the item-specific conversation.") };
    state.details.delete(workspaceItem.item_id); await load(state.activeBatchId); workspaceItem = await itemDetail(workspaceItem.item_id, true); workspaceRenderThreads();
  } catch (error) { workspaceThreadResults[provider] = { title: "Analysis failed", text: error.message }; workspaceRenderThreads(); }
}

// Question-centric research view: each titled question owns its findings.
workspaceRenderQuestions = function workspaceRenderQuestions() {
  const question = workspaceQuestions.find((row) => row.question_id === workspaceSelectedQuestionId) || null;
 const questionList = workspaceQuestions.map((row) => `<button type="button" class="research-question-entry ${row.question_id === workspaceSelectedQuestionId ? "active" : ""}" data-question-select="${esc(row.question_id)}"><strong>${esc(row.title)}</strong><span>${(row.findings || []).length} finding(s)</span></button>`).join("");
  /*
  const findings = question ? (question.findings || []).map((row) => \`<article class="research-finding"><strong>\${esc(row.claim)}</strong><div class="meta">\${esc(row.kind || "finding")} · \${esc(row.confidence || "unrated")}</div></article>\`).join("") : '<p class="empty">Choose a question to review its findings.</p>';
  $("item-tab-panel").innerHTML = \`<div class="tab-scroll research-page"><div class="tab-heading"><div><h2>Research & questions</h2><p>Questions stay titled and organized. Select one to add reviewed findings.</p></div><button id="workspace-add-question" class="primary" type="button">+ New question</button></div><div class="research-question-layout"><aside class="research-question-list"><h3>Questions</h3>\${questionList || '<p class="empty">No questions yet.</p>'}</aside><section class="research-question-detail">\${question ? \`<div class="question-detail-head"><div><p class="eyebrow">Selected question</p><h3>\${esc(question.title)}</h3><p>\${esc(question.prompt || "Add the question context below.")}</p></div><button id="workspace-ask-leo" type="button">Ask Leo</button></div><div class="question-findings"><h4>Findings</h4>\${findings}</div><label>Add finding<textarea id="workspace-question-finding" placeholder="Enter a reviewed finding for this question"></textarea></label><button id="workspace-save-question-finding" class="primary" type="button">Save finding</button><div id="workspace-leo-proposal" class="leo-proposal" hidden></div>\` : '<div class="question-empty"><h3>Create your first question</h3><label>Question title<input id="workspace-new-question-title" placeholder="e.g. Is the signature hand-applied?"></label><label>Question context<textarea id="workspace-new-question-prompt" placeholder="What do you need to establish?"></textarea></label><button id="workspace-create-question" class="primary" type="button">Create question</button></div>'}</section></div><section class="research-general-notes"><h3>General notes</h3><textarea id="workspace-notes" placeholder="Questions, measurements, observations, and next steps">\${esc(workspaceItem.notes || "")}</textarea><p class="meta">General notes are saved automatically when you leave this tab or press Save.</p></section></div>\`;
 document.querySelectorAll("[data-question-select]").forEach((button) => button.onclick = () => { workspaceSelectedQuestionId = button.dataset.questionSelect; workspaceRenderQuestions(); });
  */
  const findings = question ? (question.findings || []).map((row) => "<article class=\"research-finding\"><strong>" + esc(row.claim) + "</strong><div class=\"meta\">" + esc(row.kind || "finding") + " · " + esc(row.confidence || "unrated") + "</div></article>").join("") : "<p class=\"empty\">Choose a question to review its findings.</p>";
  const panel = $("item-tab-panel");
  panel.innerHTML = "<div class=\"tab-scroll research-page\"><div class=\"tab-heading\"><div><h2>Research & questions</h2><p>Questions stay titled and organized. Select one to add reviewed findings.</p></div><button id=\"workspace-add-question\" class=\"primary\" type=\"button\">+ New question</button></div><div class=\"research-question-layout\"><aside class=\"research-question-list\"><h3>Questions</h3>" + (questionList || "<p class=\"empty\">No questions yet.</p>") + "</aside><section class=\"research-question-detail\">" + (question ? "<div class=\"question-detail-head\"><div><p class=\"eyebrow\">Selected question</p><h3>" + esc(question.title) + "</h3><p>" + esc(question.prompt || "Add the question context below.") + "</p></div><button id=\"workspace-ask-leo\" type=\"button\">Ask Leo</button></div><div class=\"question-findings\"><h4>Findings</h4>" + findings + "</div><label>Add finding<textarea id=\"workspace-question-finding\" placeholder=\"Enter a reviewed finding for this question\"></textarea></label><button id=\"workspace-save-question-finding\" class=\"primary\" type=\"button\">Save finding</button><div id=\"workspace-leo-proposal\" class=\"leo-proposal\" hidden></div>" : "<div class=\"question-empty\"><h3>Create your first question</h3><label>Question title<input id=\"workspace-new-question-title\" placeholder=\"e.g. Is the signature hand-applied?\"></label><label>Question context<textarea id=\"workspace-new-question-prompt\" placeholder=\"What do you need to establish?\"></textarea></label><button id=\"workspace-create-question\" class=\"primary\" type=\"button\">Create question</button></div>") + "</section></div><section class=\"research-general-notes\"><h3>General notes</h3><textarea id=\"workspace-notes\" placeholder=\"Questions, measurements, observations, and next steps\">" + esc(workspaceItem.notes || "") + "</textarea><p class=\"meta\">General notes save automatically when you leave this tab or press Save.</p></section></div>";
  document.querySelectorAll("[data-question-select]").forEach((button) => button.onclick = () => { workspaceSelectedQuestionId = button.dataset.questionSelect; workspaceRenderQuestions(); });
  if ($("workspace-add-question")) $("workspace-add-question").onclick = () => { workspaceQuestions = [...workspaceQuestions]; workspaceSelectedQuestionId = ""; workspaceRenderQuestions(); };
  if ($("workspace-create-question")) $("workspace-create-question").onclick = workspaceCreateQuestion;
  if ($("workspace-save-question-finding")) $("workspace-save-question-finding").onclick = workspaceSaveQuestionFinding;
  if ($("workspace-ask-leo")) $("workspace-ask-leo").onclick = workspaceAskLeo;
};
workspaceAskLeo = function workspaceAskLeo() {
  const question = workspaceQuestions.find((row) => row.question_id === workspaceSelectedQuestionId);
  if (!question) return;
  const box = $("workspace-leo-proposal");
  box.hidden = false;
  box.innerHTML = "<strong>Leo</strong><p>Do you want me to research your question, or would you like to ask about something else?</p><div class=\"leo-chat-messages\" id=\"workspace-leo-messages\"></div><textarea id=\"workspace-leo-input\" placeholder=\"Tell Leo what to research or ask\"></textarea><button id=\"workspace-leo-send\" class=\"primary\" type=\"button\">Send to Leo</button>";
  $("workspace-leo-send").onclick = workspaceSendLeo;
  $("workspace-leo-input").focus();
};
async function workspaceSendLeo() {
  const question = workspaceQuestions.find((row) => row.question_id === workspaceSelectedQuestionId), input = $("workspace-leo-input"), text = input?.value.trim();
  if (!question || !text) return;
  const messages = $("workspace-leo-messages"); messages.insertAdjacentHTML("beforeend", "<p class=\"leo-user\"><strong>You:</strong> " + esc(text) + "</p>"); input.value = "";
  const button = $("workspace-leo-send"); button.disabled = true; button.textContent = "Leo is researching…";
  try {
    const result = await api("/api/ebay-room/leo-chat", { method: "POST", body: JSON.stringify(payload({ item_id: workspaceItem.item_id, question: question.title + " — " + (question.prompt || ""), findings: (question.findings || []).map((row) => row.claim).join(" | "), text })) });
    const response = result.message?.content || result.text || "Leo could not return a response. Check the request status and try again.";
    messages.insertAdjacentHTML("beforeend", "<article class=\"leo-response\"><strong>Leo:</strong><p>" + esc(response) + "</p><button data-leo-propose type=\"button\">Propose this as a finding</button></article>");
    messages.querySelector("[data-leo-propose]:last-of-type")?.addEventListener("click", () => { $("workspace-question-finding").value = response; if (confirm("Leo proposed this finding. Save it to the selected question?")) workspaceSaveQuestionFinding(); });
  } catch (error) { messages.insertAdjacentHTML("beforeend", "<p class=\"leo-error\"><strong>Leo could not complete the request:</strong> " + esc(error.message) + "</p>"); }
  finally { button.disabled = false; button.textContent = "Send to Leo"; }
}
async function workspaceCreateQuestion() {
  const title = $("workspace-new-question-title")?.value.trim();
  if (!title) return toast("Add a question title first.");
  try {
    const result = await api("/api/ebay-room/questions", { method: "POST", body: JSON.stringify({ item_id: workspaceItem.item_id, title, prompt: $("workspace-new-question-prompt")?.value || "" }) });
    workspaceQuestions = result.questions || [];
    workspaceSelectedQuestionId = result.question.question_id;
    workspaceRenderQuestions();
    toast("Question saved.");
  } catch (error) { toast(error.message); }
}
async function workspaceSaveQuestionFinding() {
  const claim = $("workspace-question-finding")?.value.trim();
  if (!claim || !workspaceSelectedQuestionId) return toast("Choose a question and enter a finding first.");
  try {
    await api("/api/ebay-room/research/attach", { method: "POST", body: JSON.stringify(payload({ item_id: workspaceItem.item_id, question_id: workspaceSelectedQuestionId, claim, confirm: true })) });
    const result = await api("/api/ebay-room/questions?item_id=" + encodeURIComponent(workspaceItem.item_id));
    workspaceQuestions = result.questions || workspaceQuestions;
    workspaceRenderQuestions();
    toast("Finding saved.");
  } catch (error) { toast(error.message); }
}
async function workspaceAskLeo() {
  const question = workspaceQuestions.find((row) => row.question_id === workspaceSelectedQuestionId);
  if (!question) return;
  const button = $("workspace-ask-leo");
  button.disabled = true; button.textContent = "Leo is reviewing…";
  try {
    const result = await api("/api/ebay-room/item-chat", { method: "POST", body: JSON.stringify(payload({ item_id: workspaceItem.item_id, text: "Leo, review the selected research question and its existing findings. Propose a concise new finding only if the evidence supports it. Do not save anything yet. Question: " + question.title + ". Context: " + (question.prompt || "") + ". Findings: " + (question.findings || []).map((row) => row.claim).join(" | ") })) });
    const messages = result.messages || [];
    const proposal = messages.filter((row) => row.role === "assistant").pop()?.content || "Leo did not return a proposal.";
    const box = $("workspace-leo-proposal");
    box.hidden = false;
    box.innerHTML = "<strong>Leo’s proposed finding</strong><p>" + esc(proposal) + "</p><div><button id=\"workspace-leo-yes\" class=\"primary\" type=\"button\">Yes, save to findings</button><button id=\"workspace-leo-no\" type=\"button\">No</button></div>";
    $("workspace-leo-yes").onclick = async () => { $("workspace-question-finding").value = proposal; await workspaceSaveQuestionFinding(); };
    $("workspace-leo-no").onclick = () => { box.hidden = true; };
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; button.textContent = "Ask Leo"; }
}
