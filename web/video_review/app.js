const state = {
  summary: null,
  batch: 1,
  payload: null,
  cropProposal: null,
  cropImage: null,
  cropPoints: [],
  drawing: false,
};

const elements = {
  grid: document.querySelector("#review-grid"),
  reviewCount: document.querySelector("#review-count"),
  batchRange: document.querySelector("#batch-range"),
  progress: document.querySelector("#progress-bar"),
  previous: document.querySelector("#previous-batch"),
  next: document.querySelector("#next-batch"),
  select: document.querySelector("#batch-select"),
  toast: document.querySelector("#toast"),
  dialog: document.querySelector("#crop-dialog"),
  cropTitle: document.querySelector("#crop-title"),
  canvas: document.querySelector("#crop-canvas"),
  pointCount: document.querySelector("#point-count"),
  clearLasso: document.querySelector("#clear-lasso"),
  saveLasso: document.querySelector("#save-lasso"),
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
}

async function request(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {"Content-Type": "application/json", ...(options.headers || {})},
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `${response.status} ${response.statusText}`);
  return data;
}

let toastTimer;
function showToast(message, error = false) {
  clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.className = `toast visible${error ? " error" : ""}`;
  toastTimer = setTimeout(() => elements.toast.className = "toast", 2800);
}

function statusLabel(value) {
  return ({
    pending: "Pending", keep: "Keep", duplicate: "Duplicate", partial: "Partial",
    trash: "Trash", needs_new_crop: "New crop", unsure: "Unsure",
    corrected_pending_review: "Corrected",
  })[value] || value;
}

function renderSummary() {
  const {reviewed, total, batch_count: batchCount} = state.summary;
  elements.reviewCount.textContent = `${reviewed} of ${total} decisions recorded`;
  elements.progress.style.width = `${total ? (reviewed / total) * 100 : 0}%`;
  elements.select.innerHTML = Array.from({length: batchCount}, (_, index) => {
    const number = index + 1;
    return `<option value="${number}"${number === state.batch ? " selected" : ""}>${number} of ${batchCount}</option>`;
  }).join("");
  elements.previous.disabled = state.batch <= 1;
  elements.next.disabled = state.batch >= batchCount;
}

function cardTemplate(proposal, index) {
  const flags = proposal.quality_flags.length ? proposal.quality_flags.join(" · ").replaceAll("_", " ") : "No automatic warning";
  const revision = proposal.crop_revision ? `<span class="revision">crop v${proposal.crop_revision}</span>` : "";
  const statuses = [
    ["keep", "Keep"], ["duplicate", "Duplicate"], ["partial", "Partial"],
    ["trash", "Trash"], ["needs_new_crop", "Redraw"], ["unsure", "Unsure"],
  ];
  return `
    <article class="proposal" tabindex="0" data-id="${proposal.proposal_id}" data-status="${proposal.review_status}" style="animation-delay:${Math.min(index * 12, 180)}ms">
      <div class="media-stage">
        <img src="${proposal.current_image_url}" alt="Crop ${proposal.sequence_number}" loading="lazy">
        <span class="sequence">#${proposal.sequence_number}</span>${revision}
      </div>
      <div class="proposal-body">
        <div class="proposal-meta"><code>${proposal.proposal_id}</code><span>${proposal.scene_id}</span></div>
        <div class="flag-line">${escapeHtml(flags)}</div>
        <div class="media-switch" aria-label="Image view">
          <button type="button" data-view="current" aria-pressed="true">Crop</button>
          <button type="button" data-view="source" aria-pressed="false">Full scene</button>
          <button type="button" data-view="overlay" aria-pressed="false">Proposals</button>
        </div>
        <div class="decision-row">
          ${statuses.map(([value, label]) => `<button type="button" data-status="${value}" aria-pressed="${proposal.review_status === value}">${label}</button>`).join("")}
        </div>
        <textarea class="note" maxlength="4000" placeholder="Optional note for correction or research">${escapeHtml(proposal.review_note)}</textarea>
      </div>
    </article>`;
}

function renderBatch() {
  const payload = state.payload;
  elements.batchRange.textContent = `Showing ${payload.range_start}–${payload.range_end}`;
  elements.grid.innerHTML = payload.proposals.map(cardTemplate).join("");
}

async function refreshSummary() {
  state.summary = await request("/api/project");
  renderSummary();
}

async function loadBatch(number) {
  state.batch = number;
  elements.grid.setAttribute("aria-busy", "true");
  try {
    state.payload = await request(`/api/proposals?batch=${number}`);
    state.batch = state.payload.batch_number;
    await refreshSummary();
    renderBatch();
    window.scrollTo({top: 0, behavior: "smooth"});
  } catch (error) {
    showToast(error.message, true);
  } finally {
    elements.grid.removeAttribute("aria-busy");
  }
}

function proposalById(proposalId) {
  return state.payload.proposals.find(item => item.proposal_id === proposalId);
}

async function saveDecision(card, status) {
  const proposal = proposalById(card.dataset.id);
  let duplicateOf = null;
  if (status === "duplicate") {
    duplicateOf = window.prompt("Enter the proposal ID this duplicates (for example proposal_0007):", proposal.duplicate_of || "");
    if (duplicateOf === null) return;
    duplicateOf = duplicateOf.trim();
  }
  const note = card.querySelector(".note").value;
  try {
    const result = await request(`/api/proposals/${proposal.proposal_id}`, {
      method: "PATCH",
      body: JSON.stringify({review_status: status, duplicate_of: duplicateOf, review_note: note}),
    });
    proposal.review_status = result.review_status;
    proposal.duplicate_of = result.duplicate_of;
    proposal.review_note = result.review_note;
    card.dataset.status = result.review_status;
    card.querySelectorAll("[data-status]").forEach(button => {
      button.setAttribute("aria-pressed", String(button.dataset.status === result.review_status));
    });
    await refreshSummary();
    showToast(`${proposal.proposal_id}: ${statusLabel(result.review_status)}`);
    if (status === "needs_new_crop") openCropEditor(proposal);
  } catch (error) {
    showToast(error.message, true);
  }
}

async function saveNote(card) {
  const proposal = proposalById(card.dataset.id);
  const value = card.querySelector(".note").value;
  if (value === proposal.review_note) return;
  try {
    const result = await request(`/api/proposals/${proposal.proposal_id}`, {
      method: "PATCH",
      body: JSON.stringify({review_status: proposal.review_status, duplicate_of: proposal.duplicate_of, review_note: value}),
    });
    proposal.review_note = result.review_note;
    showToast(`${proposal.proposal_id}: note saved`);
  } catch (error) {
    showToast(error.message, true);
  }
}

function switchMedia(card, view) {
  const proposal = proposalById(card.dataset.id);
  const urls = {current: proposal.current_image_url, source: proposal.source_image_url, overlay: proposal.overlay_image_url};
  card.querySelector("img").src = urls[view];
  card.querySelectorAll("[data-view]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.view === view)));
}

elements.grid.addEventListener("click", event => {
  const card = event.target.closest(".proposal");
  if (!card) return;
  const statusButton = event.target.closest("button[data-status]");
  if (statusButton) saveDecision(card, statusButton.dataset.status);
  const viewButton = event.target.closest("button[data-view]");
  if (viewButton) switchMedia(card, viewButton.dataset.view);
});

elements.grid.addEventListener("focusout", event => {
  if (event.target.classList.contains("note")) saveNote(event.target.closest(".proposal"));
});

elements.grid.addEventListener("keydown", event => {
  if (event.target.matches("textarea, input, button, select")) return;
  const card = event.target.closest(".proposal");
  if (!card) return;
  const status = ({k: "keep", d: "duplicate", p: "partial", t: "trash", c: "needs_new_crop", u: "unsure"})[event.key.toLowerCase()];
  if (status) {
    event.preventDefault();
    saveDecision(card, status);
  }
});

elements.previous.addEventListener("click", () => loadBatch(state.batch - 1));
elements.next.addEventListener("click", () => loadBatch(state.batch + 1));
elements.select.addEventListener("change", () => loadBatch(Number(elements.select.value)));

const context = elements.canvas.getContext("2d");

function canvasPoint(event) {
  const bounds = elements.canvas.getBoundingClientRect();
  return [
    Math.round((event.clientX - bounds.left) * elements.canvas.width / bounds.width),
    Math.round((event.clientY - bounds.top) * elements.canvas.height / bounds.height),
  ];
}

function drawCropCanvas() {
  if (!state.cropImage) return;
  context.clearRect(0, 0, elements.canvas.width, elements.canvas.height);
  context.drawImage(state.cropImage, 0, 0);
  if (state.cropPoints.length > 1) {
    context.save();
    context.strokeStyle = "#7de0c3";
    context.fillStyle = "rgb(125 224 195 / 16%)";
    context.lineWidth = Math.max(3, Math.round(Math.min(elements.canvas.width, elements.canvas.height) * 0.005));
    context.lineJoin = "round";
    context.lineCap = "round";
    context.beginPath();
    context.moveTo(...state.cropPoints[0]);
    state.cropPoints.slice(1).forEach(point => context.lineTo(...point));
    if (!state.drawing && state.cropPoints.length >= 3) {
      context.closePath();
      context.fill();
    }
    context.stroke();
    context.restore();
  }
  elements.pointCount.textContent = state.cropPoints.length ? `${state.cropPoints.length} lasso points` : "Draw a new boundary";
}

async function openCropEditor(proposal) {
  state.cropProposal = proposal;
  state.cropPoints = proposal.points.map(point => [Number(point[0]), Number(point[1])]);
  elements.cropTitle.textContent = `Redraw ${proposal.proposal_id}`;
  const image = new Image();
  image.onload = () => {
    state.cropImage = image;
    elements.canvas.width = image.naturalWidth;
    elements.canvas.height = image.naturalHeight;
    drawCropCanvas();
    if (!elements.dialog.open) elements.dialog.showModal();
  };
  image.onerror = () => showToast("Could not load the source frame", true);
  image.src = proposal.source_image_url;
}

elements.canvas.addEventListener("pointerdown", event => {
  event.preventDefault();
  state.drawing = true;
  state.cropPoints = [canvasPoint(event)];
  elements.canvas.setPointerCapture(event.pointerId);
  drawCropCanvas();
});
elements.canvas.addEventListener("pointermove", event => {
  if (!state.drawing) return;
  const point = canvasPoint(event);
  const last = state.cropPoints.at(-1);
  if (!last || Math.hypot(point[0] - last[0], point[1] - last[1]) >= 3) {
    state.cropPoints.push(point);
    drawCropCanvas();
  }
});
function finishDrawing(event) {
  if (!state.drawing) return;
  state.drawing = false;
  if (event.pointerId !== undefined && elements.canvas.hasPointerCapture(event.pointerId)) elements.canvas.releasePointerCapture(event.pointerId);
  drawCropCanvas();
}
elements.canvas.addEventListener("pointerup", finishDrawing);
elements.canvas.addEventListener("pointercancel", finishDrawing);
elements.clearLasso.addEventListener("click", () => { state.cropPoints = []; drawCropCanvas(); });

elements.saveLasso.addEventListener("click", async () => {
  if (!state.cropProposal || state.cropPoints.length < 3) {
    showToast("Draw at least three lasso points", true);
    return;
  }
  elements.saveLasso.disabled = true;
  try {
    const result = await request(`/api/proposals/${state.cropProposal.proposal_id}/crop`, {
      method: "POST",
      body: JSON.stringify({points: state.cropPoints}),
    });
    state.cropProposal.crop_revision = result.crop_revision;
    state.cropProposal.review_status = result.review_status;
    state.cropProposal.current_image_url = result.current_image_url;
    state.cropProposal.points = state.cropPoints;
    elements.dialog.close();
    await loadBatch(state.batch);
    showToast(`${state.cropProposal.proposal_id}: corrected crop v${result.crop_revision} saved`);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    elements.saveLasso.disabled = false;
  }
});

loadBatch(1);
