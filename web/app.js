const AUTO_READ_STORAGE_KEY = "veridex.readAutomatically";
const DELIVERY_POLL_INTERVAL_MS = 15_000;
const MONITOR_STATUS_POLL_INTERVAL_MS = 15_000;
const SpeechRecognitionApi = window.SpeechRecognition || window.webkitSpeechRecognition;
const savedAutoRead = (() => {
  try { return window.localStorage.getItem(AUTO_READ_STORAGE_KEY) === "true"; }
  catch { return false; }
})();

const state = {
  workspace: null,
  session: null,
  workspaces: [],
  sessions: [],
  messages: [],
  files: [],
  rooms: [],
  contacts: [],
  contactSync: { completed: false },
  connectedAccounts: null,
  marketplace: {
    loaded: false,
    loading: false,
    busy: false,
    drafts: [],
    groups: [],
    cases: [],
    images: [],
    currentDraftId: "",
    selectedPhotoIds: new Set(),
    selectedGroupIds: new Set(),
    notice: "",
  },
  artImages: [],
  artImagesLoading: false,
  artImagesLoaded: false,
  selectedArtImageId: "",
  attachingArtImageId: "",
  artStudio: {
    loaded: false,
    loading: false,
    mode: "create",
    providers: [],
    models: [],
    presets: [],
    aspects: [],
    projects: [],
    currentProjectId: "",
    selectedFileId: "",
    previewReferenceId: "",
    referenceIds: new Set(),
    variants: [],
    activeJob: null,
    pollTimer: null,
    criticNotes: "",
  },
  roomFiles: [],
  roomFilesLoading: false,
  roomFilesRoomId: "",
  selectedRoomFileId: "",
  attachingRoomFileId: "",
  deliveryAlerts: [],
  monitor: {
    health: { status: "pending", issues: [], issue_signature: "" },
    mail: { status: "pending", alerts: [], unseen_count: 0, checked_at: "" },
    promptedSignatures: new Set(),
    knownUnseenIds: new Set(),
    initialized: false,
    checking: false,
    errorShown: false,
  },
  governance: {},
  antiques: { shopping_mode: { active: false }, settings: {}, sources: [], cases: [], external_uploads: [] },
  administration: { versions: {}, proposals: [], audit: [], rooms: [] },
  adminTokens: {},
  selectedFiles: new Set(),
  emailAttachments: [],
  runtime: { access_mode: "full", access_label: "Full computer access" },
  route: null,
  sending: false,
  stopping: false,
  activeRequestId: null,
  uploading: false,
  uploadTarget: "",
  switchingRoom: false,
  autoRead: savedAutoRead,
  bootstrapped: false,
  speakingMessageId: null,
  recognition: null,
  listening: false,
  dictationBase: "",
  dictationFinal: "",
  syncingContacts: false,
  checkingDelivery: false,
  deliveryErrorShown: false,
  recipientSuggestionIndex: -1,
  emailRetryFailureId: "",
  resume: {
    loaded: false,
    loading: false,
    busy: false,
    step: "profile",
    profile: null,
    templates: [],
    projects: [],
    draft: null,
    review: null,
    analysis: null,
    currentProjectId: "",
    route: null,
  },
  museum: {
    loaded: false,
    mode: "quick",
    cases: [],
    settings: {},
    shoppingMode: { active: false },
    photoRoles: {},
    regions: {},
    cropFileId: "",
    cropStart: null,
    activeJob: null,
    pollTimer: null,
    result: null,
  },
  itemSelector: {
    sourceFileId: "",
    selections: [],
    activeSelectionId: "",
    interaction: null,
    draftRegion: null,
    batchId: "",
    searchMode: "full",
    researchDepth: "quick",
    zoom: 1,
    activeJob: null,
    pollTimer: null,
  },
  priceSearch: {
    activeJob: null,
    pollTimer: null,
  },
  animation: {
    loaded: false,
    loading: false,
    busy: false,
    tools: {},
    projects: [],
    workflow: [],
    currentProjectId: "",
    assets: [],
    selectedAssetId: "",
    storyboard: [],
    audioTracks: [],
    selectedTrackId: "",
    mouthRigs: [],
    selectedRigId: "",
    lipsyncTakes: [],
    selectedTakeId: "",
    manualRecording: null,
    manualSelection: null,
    manualEdit: null,
    manualDialogOpen: false,
    manualDialogOrigin: null,
    manualDirty: false,
    manualHistory: { undo: [], redo: [] },
    quickFix: null,
    quickFixHistory: { undo: [], redo: [] },
    placementEditing: false,
    waveform: { fileId: "", samples: null, duration: 0, loading: false, failed: false, token: 0 },
    waveformInteraction: null,
    waveformLastDrag: false,
    mouthTimer: null,
    mouthAudioId: "",
    renderedShots: [],
    notice: "",
  },
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
  const priorMessageIds = new Set(state.messages.map((message) => message.message_id).filter(Boolean));
  const wasBootstrapped = state.bootstrapped;
  const workspaceChanged = state.workspace?.workspace_id
    && state.workspace.workspace_id !== value.workspace?.workspace_id;
  const sessionChanged = state.session?.session_id && state.session.session_id !== value.session?.session_id;
  if (sessionChanged && window.speechSynthesis) {
    window.speechSynthesis.cancel();
    state.speakingMessageId = null;
  }
  state.workspace = value.workspace;
  state.session = value.session;
  state.workspaces = value.workspaces || [];
  state.sessions = value.sessions || [];
  state.messages = value.messages || [];
  state.files = value.files || [];
  state.rooms = value.rooms || state.rooms;
  state.runtime = value.runtime || state.runtime;
  state.governance = value.governance || state.governance;
  state.antiques = value.antiques || state.antiques;
  state.administration = value.administration || state.administration;
  if (sessionChanged) {
    state.selectedFiles.clear();
    state.emailAttachments = [];
    state.deliveryAlerts = [];
    state.museum.photoRoles = {};
    state.museum.regions = {};
    state.museum.cropFileId = "";
    state.museum.result = null;
    resetItemSelector();
    window.clearTimeout(state.priceSearch.pollTimer);
    state.priceSearch.activeJob = null;
    state.priceSearch.pollTimer = null;
  }
  if (state.animation.manualEdit?.timer) window.clearInterval(state.animation.manualEdit.timer);
  state.animation.manualRecording = null;
  state.animation.manualEdit = null;
  state.animation.manualDialogOpen = false;
  state.animation.manualDialogOrigin = null;
  state.animation.manualDirty = false;
  state.animation.manualHistory = { undo: [], redo: [] };
  state.animation.quickFix = null;
  state.animation.quickFixHistory = { undo: [], redo: [] };
  state.animation.placementEditing = false;
  stopAnimationMouthClock();
  state.animation.waveform = { fileId: "", samples: null, duration: 0, loading: false, failed: false, token: 0 };
  state.animation.waveformInteraction = null;
  state.animation.waveformLastDrag = false;
  if (workspaceChanged) {
    state.monitor.health = { status: "pending", issues: [], issue_signature: "" };
    state.monitor.mail = { status: "pending", alerts: [], unseen_count: 0, checked_at: "" };
    state.monitor.knownUnseenIds.clear();
    state.monitor.initialized = false;
    state.monitor.errorShown = false;
    state.connectedAccounts = null;
    state.marketplace.loaded = false;
    state.marketplace.drafts = [];
    state.marketplace.groups = [];
    state.marketplace.cases = [];
    state.marketplace.images = [];
    state.marketplace.currentDraftId = "";
    state.marketplace.selectedPhotoIds.clear();
    state.marketplace.selectedGroupIds.clear();
    state.marketplace.notice = "";
    state.artImages = [];
    state.artImagesLoaded = false;
    state.selectedArtImageId = "";
    state.artStudio.loaded = false;
    state.artStudio.projects = [];
    state.animation.loaded = false;
    state.animation.projects = [];
    state.animation.currentProjectId = "";
    state.animation.assets = [];
    state.animation.selectedAssetId = "";
    state.animation.storyboard = [];
    state.animation.audioTracks = [];
    state.animation.selectedTrackId = "";
    state.animation.mouthRigs = [];
    state.animation.selectedRigId = "";
    state.animation.lipsyncTakes = [];
    state.animation.selectedTakeId = "";
    state.animation.manualSelection = null;
    state.animation.manualDialogOpen = false;
    state.animation.manualDialogOrigin = null;
    state.animation.manualDirty = false;
    state.animation.manualHistory = { undo: [], redo: [] };
    state.animation.placementEditing = false;
    state.animation.renderedShots = [];
    state.animation.notice = "";
    state.artStudio.currentProjectId = "";
    state.artStudio.selectedFileId = "";
    state.artStudio.previewReferenceId = "";
    state.artStudio.referenceIds.clear();
    state.artStudio.variants = [];
    state.roomFiles = [];
    state.roomFilesRoomId = "";
    state.selectedRoomFileId = "";
    state.resume.loaded = false;
    state.resume.profile = null;
    state.resume.projects = [];
    state.resume.draft = null;
    state.resume.review = null;
    state.museum.loaded = false;
    state.museum.cases = [];
    state.museum.settings = {};
    state.museum.shoppingMode = { active: false };
    state.museum.photoRoles = {};
    state.museum.regions = {};
    state.museum.cropFileId = "";
    state.museum.activeJob = null;
    state.museum.result = null;
    resetItemSelector();
  }
  if (!preserveRoute) state.route = savedRoute(state.messages);
  if (value.account) el("account-name").textContent = value.account.display_name || "Local User";
  render();
  state.bootstrapped = true;
  if (wasBootstrapped && !sessionChanged && state.autoRead) {
    const newestReply = [...state.messages].reverse().find(
      (message) => message.role === "assistant" && message.message_id && !priorMessageIds.has(message.message_id),
    );
    if (newestReply) window.setTimeout(() => speakMessage(newestReply), 0);
  }
  if (wasBootstrapped && sessionChanged && state.session?.active_room === "my_office") {
    window.setTimeout(checkDeliveryFailures, 0);
  }
}

function speechTextForMessage(row) {
  const gmail = row.gmail || {};
  if (row.message_kind === "gmail_search" && Array.isArray(gmail.messages) && gmail.messages.length) {
    return gmail.messages.map((message, index) => [
      gmail.messages.length > 1 ? `Email ${index + 1}.` : "",
      `From ${message.from || "unknown sender"}.`,
      `Subject: ${message.subject || "no subject"}.`,
      message.snippet || "",
    ].filter(Boolean).join(" ")).join(" ");
  }
  if (row.message_kind === "gmail_send_confirmation" && gmail.draft) {
    const attachments = Array.isArray(gmail.draft.attachments) && gmail.draft.attachments.length
      ? ` Attachments: ${gmail.draft.attachments.map((file) => file.name).join(", ")}.`
      : "";
    return [
      "Review this email before sending.",
      `To ${(gmail.draft.to || []).join(", ")}.`,
      `Subject: ${gmail.draft.subject || "no subject"}.`,
      gmail.draft.body || "",
      attachments,
    ].filter(Boolean).join(" ");
  }
  return String(row.text || "")
    .replace(/https?:\/\/\S+/g, "link")
    .replace(/[*_`#]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function stopSpeech() {
  if (window.speechSynthesis) window.speechSynthesis.cancel();
  state.speakingMessageId = null;
  render();
}

function speakMessage(row) {
  if (!("speechSynthesis" in window) || !("SpeechSynthesisUtterance" in window)) {
    showError("Read aloud is not supported by this browser.");
    return;
  }
  const messageId = row.message_id || "current";
  if (state.speakingMessageId === messageId) {
    stopSpeech();
    return;
  }
  const text = speechTextForMessage(row);
  if (!text) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 1;
  utterance.pitch = 1;
  utterance.onend = utterance.onerror = () => {
    if (state.speakingMessageId === messageId) {
      state.speakingMessageId = null;
      render();
    }
  };
  state.speakingMessageId = messageId;
  render();
  window.speechSynthesis.speak(utterance);
}

function updateDictationText(interim = "") {
  const input = el("message-input");
  input.value = [state.dictationBase, state.dictationFinal, interim]
    .map((part) => String(part || "").trim())
    .filter(Boolean)
    .join(" ");
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

function ensureRecognition() {
  if (state.recognition || !SpeechRecognitionApi) return state.recognition;
  const recognition = new SpeechRecognitionApi();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.lang = navigator.language || "en-US";
  recognition.onstart = () => {
    state.listening = true;
    render();
  };
  recognition.onresult = (event) => {
    let interim = "";
    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      const transcript = event.results[index][0]?.transcript || "";
      if (event.results[index].isFinal) state.dictationFinal += `${transcript.trim()} `;
      else interim += transcript;
    }
    updateDictationText(interim);
  };
  recognition.onerror = (event) => {
    if (event.error !== "aborted" && event.error !== "no-speech") {
      const detail = event.error === "not-allowed"
        ? "Microphone permission was denied. Allow microphone access in the browser and try again."
        : `Dictation stopped: ${event.error}.`;
      showError(detail);
    }
  };
  recognition.onend = () => {
    state.listening = false;
    updateDictationText();
    render();
    el("message-input").focus();
  };
  state.recognition = recognition;
  return recognition;
}

function toggleDictation() {
  if (!SpeechRecognitionApi) {
    showError("Microphone dictation is not supported by this browser. Use Chrome or Edge.");
    return;
  }
  const recognition = ensureRecognition();
  if (state.listening) {
    recognition.stop();
    return;
  }
  state.dictationBase = el("message-input").value.trim();
  state.dictationFinal = "";
  try { recognition.start(); }
  catch (error) { showError(error.message || "Dictation could not start."); }
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

function emailAddress(value) {
  const text = String(value || "").trim();
  const bracketed = text.match(/<([^<>\s]+@[^<>\s]+)>/);
  const plain = text.match(/[\w.!#$%&'*+/=?^`{|}~-]+@[\w.-]+\.[A-Za-z]{2,}/);
  return (bracketed?.[1] || plain?.[0] || "").trim();
}

function readableEmailDate(value) {
  const text = String(value || "").trim();
  if (!text) return "Date unavailable";
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) return text;
  return parsed.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function renderEmailAttachments() {
  const list = el("email-file-list");
  list.replaceChildren();
  if (state.uploading && state.uploadTarget === "email") {
    const uploading = document.createElement("span");
    uploading.className = "email-file-uploading";
    uploading.textContent = "Saving attachment…";
    list.append(uploading);
  }
  state.emailAttachments.forEach((file) => {
    const chip = document.createElement("span");
    chip.className = "email-file-chip";
    const name = document.createElement("span");
    name.textContent = `${file.name} · ${formatBytes(file.size || 0)}`;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.setAttribute("aria-label", `Remove ${file.name}`);
    remove.title = `Remove ${file.name}`;
    remove.textContent = "×";
    remove.disabled = state.uploading;
    remove.addEventListener("click", () => {
      state.emailAttachments = state.emailAttachments.filter((row) => row.file_id !== file.file_id);
      renderEmailAttachments();
    });
    chip.append(name, remove);
    list.append(chip);
  });
}

function openEmailComposer(draft = {}) {
  const dialog = el("email-compose-dialog");
  el("email-to").value = Array.isArray(draft.to) ? draft.to.join(", ") : (draft.to || "");
  el("email-subject").value = draft.subject || "";
  el("email-body").value = draft.body || "";
  state.emailAttachments = Array.isArray(draft.attachments) ? draft.attachments.map((file) => ({ ...file })) : [];
  state.emailRetryFailureId = draft.failure_id || draft.retry_failure_id || "";
  renderEmailAttachments();
  if (!dialog.open) dialog.showModal();
  loadContacts().then((result) => {
    if (!result.sync?.completed) syncContacts();
  }).catch(() => { /* Nancy will show a Gmail connection error when the user opens the address book. */ });
  window.setTimeout(() => (el("email-to").value ? el("email-body") : el("email-to")).focus(), 0);
}

function closeEmailComposer({ clearAttachments = true } = {}) {
  const dialog = el("email-compose-dialog");
  if (dialog.open) dialog.close();
  el("email-recipient-suggestions").hidden = true;
  if (clearAttachments) {
    state.emailAttachments = [];
    state.emailRetryFailureId = "";
    renderEmailAttachments();
  }
}

async function loadContacts() {
  const query = new URLSearchParams({ workspace_id: state.workspace.workspace_id, session_id: state.session.session_id });
  const result = await api(`/api/contacts?${query}`);
  state.contacts = result.contacts || [];
  state.contactSync = result.sync || state.contactSync;
  renderContacts();
  renderRecipientSuggestions();
  return result;
}

function contactLabel(contact) {
  return contact.name ? `${contact.name} <${contact.email}>` : contact.email;
}

function showContactForm(contact = {}) {
  el("contact-form").hidden = false;
  el("contact-form-title").textContent = contact.contact_id ? "Edit contact" : "Add contact";
  el("contact-id").value = contact.contact_id || "";
  el("contact-name").value = contact.name || "";
  el("contact-email").value = contact.email || "";
  el("contact-phone").value = contact.phone || "";
  el("contact-company").value = contact.company || "";
  el("contact-notes").value = contact.notes || "";
  el(contact.email ? "contact-name" : "contact-email").focus();
  renderContacts();
}

function hideContactForm() {
  el("contact-form").hidden = true;
  el("contact-id").value = "";
  renderContacts();
}

function emailContact(contact) {
  closeAddressBook();
  openEmailComposer({ to: [contactLabel(contact)] });
}

async function deleteContact(contact) {
  const label = contact.name || contact.email;
  if (!window.confirm(`Delete ${label} from the address book?`)) return;
  try {
    const result = await api("/api/contacts/delete", {
      method: "POST",
      body: accountRequestBody({ contact_id: contact.contact_id }),
    });
    state.contacts = result.contacts || state.contacts.filter((row) => row.contact_id !== contact.contact_id);
    if (el("contact-id").value === contact.contact_id) hideContactForm();
    else renderContacts();
    el("contact-sync-status").textContent = `Deleted ${label}.`;
  } catch (error) {
    showError(error.message || String(error));
  }
}

function renderContacts() {
  const list = el("contact-list");
  if (!list) return;
  const query = String(el("contact-search").value || "").trim().toLowerCase();
  const contacts = state.contacts.filter((contact) => [
    contact.name, contact.email, contact.company, contact.notes,
  ].some((value) => String(value || "").toLowerCase().includes(query)));
  list.replaceChildren();
  if (!contacts.length) {
    const empty = document.createElement("div");
    empty.className = "contact-empty";
    empty.textContent = state.contactSync.completed
      ? "No contacts match this search."
      : "Sent-mail contacts have not been synced yet.";
    list.append(empty);
    return;
  }
  const selectedId = el("contact-id").value;
  contacts.forEach((contact) => {
    const row = document.createElement("div");
    row.className = `contact-row${selectedId === contact.contact_id ? " active" : ""}`;
    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "contact-row-main";
    edit.title = `Edit ${contact.name || contact.email}`;
    const name = document.createElement("strong");
    name.textContent = contact.name || contact.email;
    const address = document.createElement("span");
    address.textContent = [contact.email, contact.company, contact.phone].filter(Boolean).join(" · ");
    const count = document.createElement("small");
    count.textContent = `${Number(contact.email_count || 0)} sent`;
    edit.append(name, address);
    edit.addEventListener("click", () => showContactForm(contact));

    const meta = document.createElement("div");
    meta.className = "contact-row-meta";
    const actions = document.createElement("div");
    actions.className = "contact-row-actions";
    const email = document.createElement("button");
    email.type = "button";
    email.className = "contact-email-action";
    email.textContent = "Email";
    email.addEventListener("click", () => emailContact(contact));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "contact-delete-action";
    remove.textContent = "Delete";
    remove.addEventListener("click", () => deleteContact(contact));
    actions.append(email, remove);
    meta.append(count, actions);
    row.append(edit, meta);
    list.append(row);
  });
}

async function syncContacts() {
  if (state.syncingContacts) return;
  state.syncingContacts = true;
  el("contact-sync").disabled = true;
  el("contact-sync-status").textContent = "Nancy is reading the 500 most recent Sent messages...";
  try {
    const result = await api("/api/contacts/sync", { method: "POST", body: accountRequestBody() });
    state.contacts = result.contacts || [];
    state.contactSync = result.sync || { completed: true };
    el("contact-sync-status").textContent = `Scanned ${result.messages_scanned || 0} messages and added ${result.contact_events_added || 0} new contact records.`;
    renderContacts();
  } catch (error) {
    el("contact-sync-status").textContent = "Sent-mail sync could not be completed.";
    showError(error.message || String(error));
  } finally {
    state.syncingContacts = false;
    el("contact-sync").disabled = false;
  }
}

async function openAddressBook() {
  const dialog = el("address-book-dialog");
  if (!dialog.open) dialog.showModal();
  el("contact-sync-status").textContent = "Loading contacts...";
  try {
    await loadContacts();
    el("contact-sync-status").textContent = state.contactSync.completed
      ? `Last Sent-mail sync: ${readableEmailDate(state.contactSync.updated_at)}`
      : "Sent-mail contacts will be imported now.";
    if (!state.contactSync.completed) await syncContacts();
  } catch (error) {
    el("contact-sync-status").textContent = "Contacts could not be loaded.";
    showError(error.message || String(error));
  }
  el("contact-search").focus();
}

function closeAddressBook() {
  hideContactForm();
  if (el("address-book-dialog").open) el("address-book-dialog").close();
}

function recipientFragment() {
  return String(el("email-to").value || "").split(",").pop().trim().toLowerCase();
}

function recipientSearchText(value) {
  return String(value || "")
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function recipientEditDistance(left, right) {
  const source = recipientSearchText(left);
  const target = recipientSearchText(right);
  if (source === target) return 0;
  if (!source.length) return target.length;
  if (!target.length) return source.length;
  const matrix = Array.from({ length: source.length + 1 }, (_, row) => {
    const values = new Array(target.length + 1).fill(0);
    values[0] = row;
    return values;
  });
  for (let column = 0; column <= target.length; column += 1) matrix[0][column] = column;
  for (let row = 1; row <= source.length; row += 1) {
    for (let column = 1; column <= target.length; column += 1) {
      const cost = source[row - 1] === target[column - 1] ? 0 : 1;
      matrix[row][column] = Math.min(
        matrix[row - 1][column] + 1,
        matrix[row][column - 1] + 1,
        matrix[row - 1][column - 1] + cost,
      );
      if (
        row > 1 && column > 1
        && source[row - 1] === target[column - 2]
        && source[row - 2] === target[column - 1]
      ) {
        matrix[row][column] = Math.min(matrix[row][column], matrix[row - 2][column - 2] + cost);
      }
    }
  }
  return matrix[source.length][target.length];
}

function recipientMatchScore(contact, fragment) {
  const query = recipientSearchText(fragment);
  if (!query) return null;
  const email = recipientSearchText(contact.email);
  const localPart = email.split("@")[0];
  const candidates = [email, localPart, contact.name, contact.company]
    .map(recipientSearchText)
    .filter(Boolean);
  let best = Number.POSITIVE_INFINITY;
  candidates.forEach((candidate) => {
    if (candidate === query) best = Math.min(best, 0);
    else if (candidate.startsWith(query)) best = Math.min(best, 0.05 + ((candidate.length - query.length) / 1000));
    else if (candidate.includes(query)) best = Math.min(best, 0.15 + (candidate.indexOf(query) / 1000));
    else {
      const distance = recipientEditDistance(query, candidate);
      const allowed = query.length < 6 ? 1 : query.length < 12 ? 2 : query.length < 24 ? 3 : 4;
      if (distance <= allowed || distance / Math.max(query.length, candidate.length) <= 0.22) {
        best = Math.min(best, 1 + (distance / Math.max(query.length, candidate.length)));
      }
    }
  });
  return Number.isFinite(best) ? best : null;
}

function matchingRecipientContacts() {
  const fragment = recipientFragment();
  if (!fragment) return [];
  const selected = new Set(
    String(el("email-to").value || "").split(",").slice(0, -1)
      .map(emailAddress).filter(Boolean).map((value) => value.toLowerCase()),
  );
  return state.contacts
    .filter((contact) => !selected.has(String(contact.email || "").toLowerCase()))
    .map((contact) => ({ contact, score: recipientMatchScore(contact, fragment) }))
    .filter((match) => match.score !== null)
    .sort((left, right) => left.score - right.score
      || Number(right.contact.email_count || 0) - Number(left.contact.email_count || 0)
      || String(left.contact.email || "").localeCompare(String(right.contact.email || "")))
    .slice(0, 8)
    .map((match) => match.contact);
}

function chooseRecipient(contact) {
  const input = el("email-to");
  const parts = String(input.value || "").split(",");
  parts[parts.length - 1] = contactLabel(contact);
  input.value = parts.map((value) => value.trim()).filter(Boolean).join(", ");
  state.recipientSuggestionIndex = -1;
  renderRecipientSuggestions();
  input.focus();
}

function renderRecipientSuggestions() {
  const container = el("email-recipient-suggestions");
  if (!container) return;
  const contacts = matchingRecipientContacts();
  container.replaceChildren();
  container.hidden = !contacts.length || document.activeElement !== el("email-to");
  contacts.forEach((contact, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.role = "option";
    button.setAttribute("aria-selected", index === state.recipientSuggestionIndex ? "true" : "false");
    button.className = `recipient-suggestion${index === state.recipientSuggestionIndex ? " active" : ""}`;
    const name = document.createElement("strong");
    name.textContent = contact.name || contact.email;
    const detail = document.createElement("span");
    detail.textContent = [contact.email, contact.company].filter(Boolean).join(" · ");
    button.append(name, detail);
    button.addEventListener("mousedown", (event) => event.preventDefault());
    button.addEventListener("click", () => chooseRecipient(contact));
    container.append(button);
  });
}

function renderDeliveryAlerts() {
  const container = el("delivery-alerts");
  if (!container) return;
  const visible = state.session?.active_room === "my_office" && state.deliveryAlerts.length;
  container.hidden = !visible;
  container.replaceChildren();
  if (!visible) return;
  state.deliveryAlerts.forEach((alert) => {
    const card = document.createElement("article");
    card.className = "delivery-alert";
    const copy = document.createElement("div");
    copy.className = "delivery-alert-copy";
    const title = document.createElement("strong");
    title.textContent = `Delivery failed: ${alert.recipient || "unknown recipient"}`;
    const detail = document.createElement("span");
    detail.textContent = `${alert.subject || "(unknown subject)"} · ${alert.diagnostic || "The message was returned."}`;
    copy.append(title, detail);
    const actions = document.createElement("div");
    actions.className = "delivery-alert-actions";
    const dismiss = document.createElement("button");
    dismiss.type = "button";
    dismiss.textContent = "Dismiss";
    dismiss.addEventListener("click", () => resolveDeliveryAlert(alert.failure_id));
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "primary-action";
    retry.textContent = "Fix and resend";
    retry.addEventListener("click", () => {
      openEmailComposer(alert.retry || {});
      if (alert.retry?.unavailable_attachments?.length) {
        showError(`Reattach unavailable files: ${alert.retry.unavailable_attachments.join(", ")}`);
      }
    });
    actions.append(dismiss, retry);
    card.append(copy, actions);
    container.append(card);
  });
}

async function resolveDeliveryAlert(failureId) {
  try {
    const result = await api("/api/mail/alerts/resolve", {
      method: "POST",
      body: JSON.stringify({
        failure_id: failureId,
        workspace_id: state.workspace.workspace_id,
        session_id: state.session.session_id,
      }),
    });
    state.deliveryAlerts = result.alerts || [];
    renderDeliveryAlerts();
  } catch (error) { showError(error.message || String(error)); }
}

async function checkDeliveryFailures() {
  if (state.checkingDelivery || state.session?.active_room !== "my_office") return;
  state.checkingDelivery = true;
  try {
    const result = await api("/api/mail/check-delivery", {
      method: "POST",
      body: JSON.stringify({
        workspace_id: state.workspace.workspace_id,
        session_id: state.session.session_id,
      }),
    });
    state.deliveryAlerts = result.alerts || [];
    state.deliveryErrorShown = false;
    if (result.new_failure_count) {
      await loadState(state.workspace.workspace_id, state.session.session_id, true);
      showError(result.new_failure_count === 1 ? "Nancy found a returned email." : `Nancy found ${result.new_failure_count} returned emails.`);
    }
    renderDeliveryAlerts();
  } catch (error) {
    if (!state.deliveryErrorShown) {
      state.deliveryErrorShown = true;
      showError(`Nancy could not check returned mail: ${error.message || String(error)}`);
    }
  } finally {
    state.checkingDelivery = false;
  }
}

function gmailCard(message) {
  const card = document.createElement("section");
  card.className = "email-card";
  const top = document.createElement("div");
  top.className = "email-card-top";
  const sender = document.createElement("strong");
  sender.className = "email-sender";
  sender.textContent = message.from || "Unknown sender";
  const date = document.createElement("time");
  date.className = "email-date";
  date.textContent = readableEmailDate(message.date);
  const subject = document.createElement("h3");
  subject.textContent = message.subject || "(no subject)";
  const snippet = document.createElement("p");
  snippet.textContent = message.snippet || "No preview available.";
  const actions = document.createElement("div");
  actions.className = "email-card-actions";
  const reply = document.createElement("button");
  reply.type = "button";
  reply.textContent = "Reply";
  reply.addEventListener("click", () => openEmailComposer({
    to: emailAddress(message.from),
    subject: /^re:/i.test(message.subject || "") ? message.subject : `Re: ${message.subject || ""}`,
  }));
  const open = document.createElement("a");
  open.target = "_blank";
  open.rel = "noopener";
  open.href = `https://mail.google.com/mail/u/0/#inbox/${encodeURIComponent(message.threadId || message.id || "")}`;
  open.textContent = "Open in Gmail";
  actions.append(reply, open);
  top.append(sender, date);
  card.append(top, subject, snippet, actions);
  return card;
}

function renderGmailMessage(row, article, body) {
  const gmail = row.gmail || {};
  if (row.message_kind === "gmail_search" && Array.isArray(gmail.messages)) {
    article.classList.add("email-result");
    const count = gmail.messages.length;
    body.textContent = count === 1 ? "Here is the email you asked for." : `Here are ${count} emails.`;
    const list = document.createElement("div");
    list.className = "email-card-list";
    gmail.messages.forEach((message) => list.append(gmailCard(message)));
    article.append(list);
    return true;
  }
  if (row.message_kind === "gmail_search") {
    article.classList.add("email-result", "legacy-email-result");
    const original = body.textContent;
    body.textContent = "Earlier Gmail result from the previous list format.";
    const details = document.createElement("details");
    details.className = "legacy-email-details";
    const summary = document.createElement("summary");
    summary.textContent = "View original email list";
    const content = document.createElement("div");
    content.textContent = original;
    details.append(summary, content);
    article.append(details);
    return true;
  }
  if (row.message_kind === "gmail_send_confirmation" && gmail.draft) {
    article.classList.add("email-result");
    body.textContent = "Review this email before Nancy sends it.";
    const review = document.createElement("section");
    review.className = "email-review";
    const heading = document.createElement("div");
    heading.className = "email-review-heading";
    const title = document.createElement("strong");
    title.textContent = "Ready to send";
    const stateLabel = document.createElement("span");
    stateLabel.textContent = "Waiting for your confirmation";
    heading.append(title, stateLabel);
    const facts = document.createElement("dl");
    const fields = [
      ["To", (gmail.draft.to || []).join(", ")],
      ["Subject", gmail.draft.subject || "(no subject)"],
      ["Message", gmail.draft.body || ""],
    ];
    if (Array.isArray(gmail.draft.attachments) && gmail.draft.attachments.length) {
      fields.push([
        "Attachments",
        gmail.draft.attachments.map((file) => `${file.name} · ${formatBytes(file.size || 0)}`).join("\n"),
      ]);
    }
    fields.forEach(([label, value]) => {
      const group = document.createElement("div");
      const term = document.createElement("dt");
      const detail = document.createElement("dd");
      term.textContent = label;
      detail.textContent = value;
      group.append(term, detail);
      facts.append(group);
    });
    const actions = document.createElement("div");
    actions.className = "email-review-actions";
    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "secondary-action";
    edit.textContent = "Edit";
    edit.addEventListener("click", () => openEmailComposer(gmail.draft));
    const send = document.createElement("button");
    send.type = "button";
    send.className = "primary-action";
    send.textContent = "Send email";
    send.addEventListener("click", () => sendMessage("confirm send", { attachments: [] }));
    actions.append(edit, send);
    review.append(heading, facts, actions);
    article.append(review);
    return true;
  }
  return false;
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

function renderAntiquesMessage(row, article) {
  const antiques = row.antiques || {};
  if (!String(row.message_kind || "").startsWith("antiques_")) return;
  article.classList.add("antiques-message");
  if (antiques.status === "confirmation_required") {
    const confirm = document.createElement("button");
    confirm.type = "button";
    confirm.className = "primary-action";
    confirm.textContent = "Confirm Google Lens upload";
    confirm.addEventListener("click", () => sendMessage("confirm Google Lens research", { attachments: [] }));
    article.append(confirm);
    return;
  }
  const sources = Array.isArray(antiques.sources) ? antiques.sources : [];
  const errors = Array.isArray(antiques.source_errors) ? antiques.source_errors : [];
  if (!sources.length && !errors.length) return;
  const details = document.createElement("details");
  details.className = "antiques-evidence";
  const summary = document.createElement("summary");
  summary.textContent = `${sources.length} research source${sources.length === 1 ? "" : "s"} · ${errors.length} unavailable`;
  const list = document.createElement("div");
  sources.forEach((source) => {
    const line = document.createElement("div");
    const label = document.createElement("strong");
    const sourceStatus = source.status ? ` · ${String(source.status).replaceAll("_", " ")}` : "";
    label.textContent = `${String(source.source_id || source.provider || "source").replaceAll("_", " ")}${sourceStatus}`;
    line.append(label);
    const urls = [source.page_url, ...(source.links || []).map((link) => link.url)].filter(Boolean);
    [...new Set(urls)].slice(0, 4).forEach((url, index) => {
      const link = document.createElement("a");
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = index ? `Source ${index + 1}` : "Open evidence";
      line.append(link);
    });
    list.append(line);
  });
  errors.forEach((error) => {
    const line = document.createElement("div");
    const label = document.createElement("span");
    label.textContent = `${String(error.source_id || "source").replaceAll("_", " ")}: ${error.error || "Unavailable"}`;
    line.append(label);
    if (error.manual_url) {
      const link = document.createElement("a");
      link.href = error.manual_url;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = "Open manually";
      line.append(link);
    }
    list.append(line);
  });
  details.append(summary, list);
  article.append(details);
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
      if (String(row.message_kind || "").startsWith("navigator_")) article.classList.add("navigator-message");
      const role = document.createElement("div");
      role.className = "message-role";
      role.textContent = row.role === "user" ? "You" : (row.speaker || "Veridex");
      const body = document.createElement("div");
      body.className = "message-body";
      body.textContent = row.text || "";
      article.append(role, body);
      renderGmailMessage(row, article, body);
      renderAntiquesMessage(row, article);
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
      if (Array.isArray(row.generated_artifacts) && row.generated_artifacts.length) {
        const artifacts = document.createElement("div");
        artifacts.className = "generated-artifacts";
        row.generated_artifacts.forEach((file) => {
          const item = document.createElement("figure");
          item.className = "generated-artifact";
          const query = new URLSearchParams({
            workspace_id: state.workspace.workspace_id,
            session_id: state.session.session_id,
            file_id: file.file_id,
          });
          const contentUrl = `/api/files/content?${query}`;
          if (String(file.content_type || "").startsWith("image/")) {
            const preview = document.createElement("img");
            preview.src = contentUrl;
            preview.alt = file.name || "Generated image";
            preview.loading = "lazy";
            item.append(preview);
          }
          const caption = document.createElement("figcaption");
          const open = document.createElement("a");
          open.href = contentUrl;
          open.target = "_blank";
          open.rel = "noopener";
          open.textContent = file.name || "Open generated file";
          const facts = document.createElement("span");
          facts.textContent = `${formatBytes(file.size || 0)} · Artifact #${file.artifact_number} · SHA-256 ${file.sha256 || "unavailable"}`;
          const path = document.createElement("code");
          path.textContent = file.path || "Path unavailable";
          caption.append(open, facts, path);
          item.append(caption);
          artifacts.append(item);
        });
        article.append(artifacts);
      }
      if (row.role === "assistant" && row.text) {
        const actions = document.createElement("div");
        actions.className = "message-actions";
        const read = document.createElement("button");
        const isSpeaking = state.speakingMessageId === (row.message_id || "current");
        read.type = "button";
        read.className = `read-message${isSpeaking ? " speaking" : ""}`;
        read.textContent = isSpeaking ? "Stop" : "Read";
        read.disabled = !("speechSynthesis" in window);
        read.setAttribute("aria-label", `${isSpeaking ? "Stop reading" : "Read aloud"} message from ${row.speaker || "Veridex"}`);
        read.addEventListener("click", () => speakMessage(row));
        actions.append(read);
        article.append(actions);
      }
      if (row.model) {
        const route = document.createElement("div");
        route.className = "message-route";
        route.textContent = `${row.model} · ${row.reasoning_effort || "default"} reasoning · ${row.task_type || "conversation"}`;
        article.append(route);
      }
      if (row.incident_id || (Array.isArray(row.gate_ids) && row.gate_ids.length)) {
        const governanceMeta = document.createElement("div");
        governanceMeta.className = "message-governance";
        governanceMeta.textContent = [
          row.gate_ids?.length ? `Gates: ${row.gate_ids.join(", ")}` : "",
          row.incident_id ? `Incident: ${row.incident_id}` : "",
        ].filter(Boolean).join(" · ");
        article.append(governanceMeta);
      }
      container.append(article);
    });
  }
  if (state.sending) {
    const processing = document.createElement("article");
    processing.className = "message assistant processing";
    processing.textContent = state.stopping ? "Stopping…" : "Veridex is working…";
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
  const recentFiles = state.files
    .map((file, index) => ({ file, index }))
    .sort((left, right) => {
      const leftTime = String(left.file.linked_at || left.file.updated_at || left.file.created_at || left.file.ledgered_at || "");
      const rightTime = String(right.file.linked_at || right.file.updated_at || right.file.created_at || right.file.ledgered_at || "");
      return rightTime.localeCompare(leftTime) || right.index - left.index;
    })
    .slice(0, 4)
    .map((entry) => entry.file);
  recentFiles.forEach((file) => {
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

function artImageContentUrl(image) {
  const query = new URLSearchParams({
    workspace_id: state.workspace.workspace_id,
    session_id: image.source_session_id || state.session.session_id,
    file_id: image.file_id,
  });
  return `/api/files/content?${query}`;
}

function artReferenceCandidates() {
  const candidates = new Map();
  state.files
    .filter((file) => String(file.content_type || "").startsWith("image/"))
    .forEach((file) => candidates.set(file.file_id, {
      ...file,
      source_session_id: file.source_session_id || state.session?.session_id || "",
      provider: file.provider || "upload",
      model: file.model || "original",
      operation: file.operation || "reference_upload",
    }));
  state.artImages.forEach((image) => candidates.set(image.file_id, image));
  return [...candidates.values()];
}

function selectedArtImage() {
  return state.artImages.find((image) => image.file_id === state.selectedArtImageId)
    || state.artImages[0]
    || null;
}

async function loadArtImages() {
  if (!state.workspace || state.artImagesLoading) return;
  state.artImagesLoading = true;
  renderArtGallery();
  try {
    const query = new URLSearchParams({ workspace_id: state.workspace.workspace_id });
    const result = await api(`/api/art/images?${query}`);
    state.artImages = result.images || [];
    state.artImagesLoaded = true;
    if (!state.artImages.some((image) => image.file_id === state.selectedArtImageId)) {
      state.selectedArtImageId = state.artImages[0]?.file_id || "";
    }
  } catch (error) {
    showError(error.message || String(error));
  } finally {
    state.artImagesLoading = false;
    renderArtGallery();
  }
}

async function attachArtImage(image) {
  if (!image || state.attachingArtImageId || state.selectedFiles.has(image.file_id)) return;
  state.attachingArtImageId = image.file_id;
  renderArtGallery();
  try {
    const result = await api("/api/art/images/attach", {
      method: "POST",
      body: JSON.stringify({
        workspace_id: state.workspace.workspace_id,
        session_id: state.session.session_id,
        file_id: image.file_id,
      }),
    });
    state.files = result.files || state.files;
    state.selectedFiles.add(image.file_id);
    renderFiles();
  } catch (error) {
    showError(error.message || String(error));
  } finally {
    state.attachingArtImageId = "";
    renderArtGallery();
  }
}

function renderArtGallery() {
  const dialog = el("art-gallery-dialog");
  if (!dialog) return;
  const grid = el("art-gallery-grid");
  const preview = el("art-gallery-preview");
  const empty = el("art-gallery-empty");
  grid.replaceChildren();
  preview.replaceChildren();
  el("art-gallery-summary").textContent = state.artImagesLoading
    ? "Loading verified artworkâ€¦"
    : `${state.artImages.length} verified ${state.artImages.length === 1 ? "image" : "images"} across Visual Design sessions`;
  empty.hidden = state.artImagesLoading || state.artImages.length > 0;
  el("art-gallery-content").hidden = state.artImagesLoading || !state.artImages.length;
  if (state.artImagesLoading || !state.artImages.length) return;

  const selected = selectedArtImage();
  state.artImages.forEach((image) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `art-gallery-thumb${selected?.file_id === image.file_id ? " active" : ""}`;
    button.setAttribute("aria-pressed", String(selected?.file_id === image.file_id));
    button.setAttribute("aria-label", `Preview ${image.name || "generated image"}`);
    const thumbnail = document.createElement("img");
    thumbnail.src = artImageContentUrl(image);
    thumbnail.alt = "";
    thumbnail.loading = "lazy";
    const label = document.createElement("span");
    label.textContent = image.name || "Generated image";
    button.append(thumbnail, label);
    button.addEventListener("click", () => {
      state.selectedArtImageId = image.file_id;
      renderArtGallery();
    });
    grid.append(button);
  });

  if (!selected) return;
  const hero = document.createElement("figure");
  const image = document.createElement("img");
  image.src = artImageContentUrl(selected);
  image.alt = selected.name || "Generated image";
  const caption = document.createElement("figcaption");
  const name = document.createElement("h3");
  name.textContent = selected.name || "Generated image";
  const facts = document.createElement("p");
  facts.textContent = [
    selected.artifact_number ? `Artifact #${selected.artifact_number}` : "Verified artifact",
    formatBytes(Number(selected.size || 0)),
    readableEmailDate(selected.created_at || selected.ledgered_at),
    selected.source_session_title,
  ].filter(Boolean).join(" Â· ");
  caption.append(name, facts);
  hero.append(image, caption);

  const actions = document.createElement("div");
  actions.className = "art-gallery-preview-actions";
  const open = document.createElement("a");
  open.href = artImageContentUrl(selected);
  open.target = "_blank";
  open.rel = "noopener";
  open.textContent = "Open original";
  const download = document.createElement("a");
  download.href = artImageContentUrl(selected);
  download.download = selected.name || "generated-image";
  download.textContent = "Download";
  const attach = document.createElement("button");
  const attached = state.selectedFiles.has(selected.file_id);
  attach.type = "button";
  attach.className = "primary-action";
  attach.disabled = attached || Boolean(state.attachingArtImageId);
  attach.textContent = attached
    ? "Attached to next message"
    : state.attachingArtImageId === selected.file_id ? "Attachingâ€¦" : "Attach to next message";
  attach.addEventListener("click", () => attachArtImage(selected));
  actions.append(open, download, attach);
  preview.append(hero, actions);
}

async function openArtGallery() {
  if (state.session?.active_room !== "art_department") return;
  const dialog = el("art-gallery-dialog");
  if (!dialog.open) dialog.showModal();
  await loadArtImages();
}

function closeArtGallery() {
  const dialog = el("art-gallery-dialog");
  if (dialog.open) dialog.close();
}

function selectedStudioImage() {
  return artReferenceCandidates().find((image) => image.file_id === state.artStudio.previewReferenceId)
    || state.artImages.find((image) => image.file_id === state.artStudio.selectedFileId)
    || state.artStudio.variants.find((image) => image.file_id === state.artStudio.selectedFileId)
    || state.artStudio.variants[0]
    || null;
}

function fillArtSelect(id, rows, label, fallback = "") {
  const select = el(id);
  const previous = select.value || fallback;
  select.replaceChildren();
  rows.forEach((row) => {
    const option = document.createElement("option");
    option.value = row.id;
    option.textContent = label(row);
    select.append(option);
  });
  if ([...select.options].some((option) => option.value === previous)) select.value = previous;
}

function setArtMode(mode) {
  state.artStudio.mode = mode;
  renderArtStudio();
}

function artFactRow(term, value) {
  const row = document.createElement("div");
  const dt = document.createElement("dt");
  const dd = document.createElement("dd");
  dt.textContent = term;
  dd.textContent = String(value || "—");
  row.append(dt, dd);
  return row;
}

function renderArtStudio() {
  const studio = state.artStudio;
  const dialog = el("art-studio-dialog");
  if (!dialog) return;
  document.querySelectorAll("[data-art-mode]").forEach((button) => button.classList.toggle("active", button.dataset.artMode === studio.mode));
  document.querySelectorAll(".art-mode-panel").forEach((panel) => panel.classList.toggle("active", panel.id === `art-mode-${studio.mode}`));

  if (studio.loaded) {
    fillArtSelect("art-preset", studio.presets, (row) => row.name, "photography");
    const readyProviders = new Set(studio.providers.filter((row) => row.configured).map((row) => row.id));
    const availableModels = studio.models.filter((row) => row.id === "auto" || readyProviders.has(row.provider));
    fillArtSelect("art-model", availableModels, (row) => row.name, "auto");
    ["art-aspect", "art-edit-aspect"].forEach((id) => fillArtSelect(id, studio.aspects, (row) => `${row.id.replaceAll("_", " ")} · ${row.width}×${row.height}`, "square"));
  }

  const generationProviders = studio.providers.filter((row) => row.id !== "local");
  const configured = generationProviders.filter((row) => row.configured).length;
  el("art-provider-status").textContent = studio.loading
    ? "Loading generation routes…"
    : `${configured} generation route${configured === 1 ? "" : "s"} ready`;
  const providerList = el("art-provider-list");
  providerList.replaceChildren();
  studio.providers.forEach((provider) => {
    const row = document.createElement("div");
    row.className = `art-provider-row${provider.configured ? " ready" : ""}`;
    const dot = document.createElement("i");
    const name = document.createElement("strong");
    const detail = document.createElement("span");
    name.textContent = provider.name;
    detail.textContent = provider.configured
      ? `${provider.quota_label || "Available"}${provider.balance != null ? ` · ${provider.balance} Pollen` : ""}`
      : "Not configured";
    row.append(dot, name, detail);
    providerList.append(row);
  });

  const referenceList = el("art-reference-list");
  referenceList.replaceChildren();
  const referenceCandidates = artReferenceCandidates();
  referenceCandidates.forEach((image) => {
    const isSelected = studio.referenceIds.has(image.file_id);
    const button = document.createElement("button");
    button.type = "button";
    button.className = `art-reference-choice${isSelected ? " active" : ""}`;
    button.setAttribute("aria-pressed", String(isSelected));
    button.title = isSelected ? "Preview and remove from this edit" : "Preview and select for editing";
    const preview = document.createElement("img");
    preview.src = artImageContentUrl(image);
    preview.alt = image.name || "Reference image";
    const name = document.createElement("span");
    name.className = "art-reference-name";
    name.textContent = image.name || "Artwork";
    const stateLabel = document.createElement("strong");
    stateLabel.className = "art-reference-state";
    stateLabel.textContent = isSelected ? "Selected" : "Select";
    button.append(preview, name, stateLabel);
    button.addEventListener("click", () => {
      studio.previewReferenceId = image.file_id;
      if (studio.referenceIds.has(image.file_id)) studio.referenceIds.delete(image.file_id);
      else if (studio.referenceIds.size < 4) studio.referenceIds.add(image.file_id);
      else showError("Reference edits support up to four images.");
      renderArtStudio();
    });
    referenceList.append(button);
  });
  if (!referenceCandidates.length) {
    const empty = document.createElement("p");
    empty.textContent = "Create an image or upload one from your computer.";
    referenceList.append(empty);
  }

  const finishSource = el("art-finish-source");
  const previousSource = finishSource.value || studio.selectedFileId;
  finishSource.replaceChildren();
  referenceCandidates.forEach((image) => {
    const option = document.createElement("option");
    option.value = image.file_id;
    option.textContent = image.name || "Artwork";
    finishSource.append(option);
  });
  if ([...finishSource.options].some((option) => option.value === previousSource)) finishSource.value = previousSource;

  const projectSelect = el("art-project-select");
  const previousProject = projectSelect.value || studio.currentProjectId;
  projectSelect.replaceChildren(new Option("New project", ""));
  studio.projects.forEach((project) => projectSelect.append(new Option(`${project.name} · v${project.version}`, project.project_id)));
  if ([...projectSelect.options].some((option) => option.value === previousProject)) projectSelect.value = previousProject;
  const project = studio.projects.find((row) => row.project_id === (projectSelect.value || studio.currentProjectId));
  el("art-project-summary").textContent = project
    ? `Version ${project.version} · ${(project.file_ids || []).length} linked images · saved ${readableEmailDate(project.updated_at)}`
    : "No project selected.";

  const selected = selectedStudioImage();
  el("art-canvas-empty").hidden = Boolean(selected);
  el("art-canvas").hidden = !selected;
  if (selected) {
    el("art-canvas-image").src = artImageContentUrl(selected);
    el("art-canvas-name").textContent = selected.name || "Artwork";
    el("art-canvas-facts").textContent = [selected.provider, selected.model, selected.width && selected.height ? `${selected.width}×${selected.height}` : "", selected.artifact_number ? `Artifact #${selected.artifact_number}` : ""].filter(Boolean).join(" · ");
  }
  const variantStrip = el("art-variant-strip");
  variantStrip.replaceChildren();
  studio.variants.forEach((image) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = image.file_id === selected?.file_id ? "active" : "";
    const preview = document.createElement("img");
    preview.src = artImageContentUrl(image);
    preview.alt = `Select ${image.name || "variant"}`;
    button.append(preview);
    button.addEventListener("click", () => {
      studio.previewReferenceId = "";
      studio.selectedFileId = image.file_id;
      renderArtStudio();
    });
    variantStrip.append(button);
  });

  const facts = el("art-output-facts");
  facts.replaceChildren();
  if (selected) {
    facts.append(
      artFactRow("Provider", selected.provider || "Verified import"),
      artFactRow("Model", selected.model || "—"),
      artFactRow("Operation", selected.operation || "generated"),
      artFactRow("Seed", selected.seed ?? "—"),
      artFactRow("Lineage", (selected.parent_file_ids || []).length ? `${selected.parent_file_ids.length} source images` : "Original"),
      artFactRow("Artifact", selected.artifact_number ? `#${selected.artifact_number}` : "Verified"),
    );
  } else facts.append(artFactRow("Status", "No image selected"));
  el("art-critic-notes").textContent = studio.criticNotes || "Run a critique for composition, legibility, and visible defects.";

  const job = studio.activeJob;
  const active = Boolean(job && !["completed", "failed", "canceled"].includes(job.status));
  const failed = job?.status === "failed";
  el("art-job-progress").hidden = !(active || failed);
  el("art-job-progress").classList.toggle("failed", failed);
  el("art-job-cancel").hidden = !active;
  if (job) {
    el("art-job-message").textContent = job.message || job.status;
    el("art-job-percent").textContent = `${job.progress || 0}%`;
    el("art-job-meter").value = job.progress || 0;
  }
  ["art-generate", "art-edit", "art-finish", "art-improve-prompt", "art-critique", "art-project-save"].forEach((id) => { el(id).disabled = active || studio.loading; });
  el("art-reference-upload").disabled = active || studio.loading || (state.uploading && state.uploadTarget === "art");
  el("art-reference-upload-status").textContent = state.uploading && state.uploadTarget === "art"
    ? "Uploading and verifying image…"
    : `${studio.referenceIds.size} of 4 selected · PNG, JPEG, or WebP`;
  el("art-edit").disabled ||= !studio.referenceIds.size;
  el("art-finish").disabled ||= !finishSource.value;
  el("art-critique").disabled ||= !selected;
  el("art-use-reference").disabled = !selected;
  el("art-download").disabled = !selected;
  el("art-attach").disabled = !selected || state.selectedFiles.has(selected?.file_id);
  el("art-attach").textContent = selected && state.selectedFiles.has(selected.file_id) ? "Attached" : "Attach to chat";
}

async function openArtStudio() {
  if (state.session?.active_room !== "art_department") return;
  const dialog = el("art-studio-dialog");
  if (!dialog.open) dialog.showModal();
  if (!state.artImagesLoaded) await loadArtImages();
  if (state.artStudio.loaded || state.artStudio.loading) { renderArtStudio(); return; }
  state.artStudio.loading = true;
  renderArtStudio();
  try {
    const query = new URLSearchParams({ workspace_id: state.workspace.workspace_id, session_id: state.session.session_id });
    const result = await api(`/api/art/studio?${query}`);
    Object.assign(state.artStudio, {
      providers: result.providers || [], models: result.models || [], presets: result.presets || [],
      aspects: result.aspects || [], projects: result.projects || [], loaded: true,
    });
  } catch (error) { showError(error.message || String(error)); }
  finally { state.artStudio.loading = false; renderArtStudio(); }
}

function closeArtStudio() {
  const dialog = el("art-studio-dialog");
  if (dialog.open) dialog.close();
}

async function pollArtJob(jobId) {
  window.clearTimeout(state.artStudio.pollTimer);
  try {
    const job = await api(`/api/art/jobs/${encodeURIComponent(jobId)}`);
    state.artStudio.activeJob = job;
    renderArtStudio();
    if (["queued", "running", "canceling"].includes(job.status)) {
      state.artStudio.pollTimer = window.setTimeout(() => pollArtJob(jobId), 900);
      return;
    }
    if (job.status === "failed") throw new Error(job.error || job.message || "Art Studio job failed");
    if (job.status === "canceled") return;
    const result = job.result || {};
    if (result.kind === "text") el("art-prompt").value = result.text || el("art-prompt").value;
    if (result.kind === "critique") state.artStudio.criticNotes = result.text || "No critique returned.";
    if (result.kind === "images") {
      const files = result.files || [];
      const byId = new Map([...files, ...state.artImages].map((image) => [image.file_id, image]));
      state.artImages = [...byId.values()];
      state.artImagesLoaded = true;
      state.artStudio.variants = files;
      state.artStudio.previewReferenceId = "";
      state.artStudio.selectedFileId = files[0]?.file_id || state.artStudio.selectedFileId;
      state.selectedArtImageId = state.artStudio.selectedFileId;
      await loadState(state.workspace.workspace_id, state.session.session_id, true);
    }
  } catch (error) {
    state.artStudio.activeJob = { ...(state.artStudio.activeJob || {}), status: "failed", progress: 100, message: error.message || String(error) };
    showError(error.message || String(error));
  }
  renderArtStudio();
}

async function startArtJob(payload) {
  if (state.artStudio.activeJob && ["queued", "running", "canceling"].includes(state.artStudio.activeJob.status)) return;
  try {
    const job = await api("/api/art/jobs", { method: "POST", body: JSON.stringify({
      workspace_id: state.workspace.workspace_id,
      session_id: state.session.session_id,
      project_id: state.artStudio.currentProjectId,
      ...payload,
    }) });
    state.artStudio.activeJob = job;
    renderArtStudio();
    await pollArtJob(job.job_id);
  } catch (error) {
    state.artStudio.activeJob = { status: "failed", progress: 100, message: error.message || String(error) };
    showError(error.message || String(error));
    renderArtStudio();
  }
}

function generateArt() {
  startArtJob({
    operation: "generate", prompt: el("art-prompt").value.trim(), preset_id: el("art-preset").value,
    model_id: el("art-model").value, aspect: el("art-aspect").value, variants: Number(el("art-variants").value),
    seed: Number(el("art-seed").value || 0), negative_prompt: el("art-negative-prompt").value.trim(),
    improve_prompt: el("art-auto-improve").checked,
  });
}

function editArt() {
  startArtJob({
    operation: "edit", prompt: el("art-edit-prompt").value.trim(), preset_id: el("art-preset").value,
    model_id: "edit", aspect: el("art-edit-aspect").value, variants: 1,
    seed: Number(el("art-edit-seed").value || 0), source_file_ids: [...state.artStudio.referenceIds],
  });
}

function finishArt() {
  const source = el("art-finish-source").value;
  const operation = el("art-finish-operation").value;
  const sourceIds = operation === "collage" && state.artStudio.referenceIds.size
    ? [...state.artStudio.referenceIds]
    : [source];
  startArtJob({ operation, source_file_ids: sourceIds, options: {
    width: Number(el("art-finish-width").value || 0), height: Number(el("art-finish-height").value || 0),
    scale: Number(el("art-finish-scale").value || 2), format: el("art-finish-format").value,
    quality: Number(el("art-finish-quality").value || 92), text: el("art-finish-text").value.trim(),
  } });
}

async function saveArtProject() {
  const selected = selectedStudioImage();
  try {
    const result = await api("/api/art/projects/save", { method: "POST", body: JSON.stringify({
      workspace_id: state.workspace.workspace_id, session_id: state.session.session_id, confirm: true,
      project: {
        project_id: state.artStudio.currentProjectId,
        name: el("art-project-name").value.trim() || "Untitled art project",
        prompt: el("art-prompt").value.trim(), preset_id: el("art-preset").value,
        model_id: el("art-model").value, aspect: el("art-aspect").value,
        selected_file_id: selected?.file_id || "", file_ids: state.artStudio.variants.map((image) => image.file_id),
      },
    }) });
    state.artStudio.currentProjectId = result.project.project_id;
    state.artStudio.projects = result.projects || state.artStudio.projects;
    renderArtStudio();
  } catch (error) { showError(error.message || String(error)); }
}

function loadArtProject() {
  const project = state.artStudio.projects.find((row) => row.project_id === el("art-project-select").value);
  if (!project) return;
  state.artStudio.currentProjectId = project.project_id;
  el("art-project-name").value = project.name || "";
  el("art-prompt").value = project.prompt || "";
  el("art-preset").value = project.preset_id || "photography";
  el("art-model").value = project.model_id || "auto";
  el("art-aspect").value = project.aspect || "square";
  state.artStudio.variants = state.artImages.filter((image) => (project.file_ids || []).includes(image.file_id));
  state.artStudio.selectedFileId = project.selected_file_id || state.artStudio.variants[0]?.file_id || "";
  setArtMode("create");
}

function animationProjectFromForm() {
  const rows = (id) => el(id).value.split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
  return {
    project_id: state.animation.currentProjectId || el("animation-project-title").value,
    title: el("animation-project-title").value,
    width: Number(el("animation-width").value || 1920),
    height: Number(el("animation-height").value || 1080),
    frame_rate: Number(el("animation-fps").value || 24),
    sets: rows("animation-sets"),
    characters: rows("animation-characters"),
    reusable_actions: rows("animation-actions-list"),
    assets: state.animation.assets.map((row) => ({ ...row })),
    storyboard: state.animation.storyboard.map((row) => ({ ...row })),
    audio_tracks: state.animation.audioTracks.map((row) => ({ ...row })),
    mouth_rigs: state.animation.mouthRigs.map((row) => ({ ...row, shapes: { ...(row.shapes || {}) } })),
    lipsync_takes: state.animation.lipsyncTakes.map((row) => ({
      ...row,
      mouth_cues: (row.mouth_cues || []).map((cue) => ({ ...cue })),
      manual_jaw_points: (row.manual_jaw_points || []).map((point) => ({ ...point })),
      manual_jaw_segments: (row.manual_jaw_segments || []).map((segment) => ({ ...segment, points: (segment.points || []).map((point) => ({ ...point })) })),
      manual_jaw_corrections: (row.manual_jaw_corrections || []).map((correction) => ({ ...correction })),
    })),
    rendered_shots: state.animation.renderedShots.map((row) => ({ ...row })),
    notes: el("animation-notes").value,
  };
}

function fillAnimationProject(project) {
  if (!project) return;
  state.animation.currentProjectId = project.saved ? project.project_id || "" : "";
  el("animation-project-title").value = project.title || "Eternia Late Night";
  el("animation-width").value = project.width || 1920;
  el("animation-height").value = project.height || 1080;
  el("animation-fps").value = String(project.frame_rate || 24);
  el("animation-sets").value = (project.sets || []).join("\n");
  el("animation-characters").value = (project.characters || []).join("\n");
  el("animation-actions-list").value = (project.reusable_actions || []).join("\n");
  el("animation-notes").value = project.notes || "";
  state.animation.assets = (project.assets || []).map((row) => ({ ...row }));
  state.animation.storyboard = (project.storyboard || []).map((row) => ({ ...row }));
  state.animation.audioTracks = (project.audio_tracks || []).map((row) => ({ ...row }));
  state.animation.mouthRigs = (project.mouth_rigs || []).map((row) => ({ ...row, shapes: { ...(row.shapes || {}) } }));
  state.animation.lipsyncTakes = (project.lipsync_takes || []).map((row) => ({
    ...row,
    mouth_cues: (row.mouth_cues || []).map((cue) => ({ ...cue })),
    manual_jaw_points: (row.manual_jaw_points || []).map((point) => ({ ...point })),
    manual_jaw_segments: (row.manual_jaw_segments || []).map((segment) => ({ ...segment, points: (segment.points || []).map((point) => ({ ...point })) })),
    manual_jaw_corrections: (row.manual_jaw_corrections || []).map((correction) => ({ ...correction })),
  }));
  state.animation.renderedShots = (project.rendered_shots || []).map((row) => ({ ...row }));
  state.animation.selectedAssetId = state.animation.assets.some((row) => row.asset_id === state.animation.selectedAssetId)
    ? state.animation.selectedAssetId : state.animation.assets[0]?.asset_id || "";
  state.animation.selectedTrackId = state.animation.audioTracks.some((row) => row.track_id === state.animation.selectedTrackId)
    ? state.animation.selectedTrackId : state.animation.audioTracks[0]?.track_id || "";
  state.animation.selectedRigId = state.animation.mouthRigs.some((row) => row.rig_id === state.animation.selectedRigId)
    ? state.animation.selectedRigId : state.animation.mouthRigs[0]?.rig_id || "";
  state.animation.selectedTakeId = state.animation.lipsyncTakes.some((row) => row.take_id === state.animation.selectedTakeId)
    ? state.animation.selectedTakeId : state.animation.lipsyncTakes[0]?.take_id || "";
  state.animation.manualSelection = null;
  state.animation.manualEdit = null;
  state.animation.manualDirty = false;
  state.animation.manualHistory = { undo: [], redo: [] };
  state.animation.quickFix = null;
  state.animation.quickFixHistory = { undo: [], redo: [] };
  state.animation.placementEditing = false;
  stopAnimationMouthClock();
  state.animation.waveform = { fileId: "", samples: null, duration: 0, loading: false, failed: false, token: 0 };
  state.animation.waveformInteraction = null;
  state.animation.waveformLastDrag = false;
  el("animation-project-select").value = project.revision_id || state.animation.currentProjectId;
}

function animationFileUrl(row) {
  if (!row?.file_id || !state.workspace || !state.session) return "";
  return `/api/files/content?${new URLSearchParams({
    workspace_id: state.workspace.workspace_id,
    session_id: row.source_session_id || state.session.session_id,
    file_id: row.file_id,
  })}`;
}

function selectedAnimationAsset() {
  return state.animation.assets.find((row) => row.asset_id === state.animation.selectedAssetId) || null;
}

function selectedAnimationTrack() {
  return state.animation.audioTracks.find((row) => row.track_id === state.animation.selectedTrackId) || null;
}

function addAnimationAssetFile(file) {
  if (!file?.file_id || state.animation.assets.some((row) => row.file_id === file.file_id)) return;
  const asset = {
    asset_id: `asset-${file.file_id}`,
    file_id: file.file_id,
    source_session_id: state.session.session_id,
    name: file.name || "Production image",
    role: "prop",
    width_percent: 35,
    x_percent: 50,
    y_percent: 60,
    opacity_percent: 100,
  };
  state.animation.assets.push(asset);
  state.animation.selectedAssetId = asset.asset_id;
}

function addAnimationAudioFile(file) {
  if (!file?.file_id || state.animation.audioTracks.some((row) => row.file_id === file.file_id)) return;
  const track = {
    track_id: `track-${file.file_id}`,
    file_id: file.file_id,
    source_session_id: state.session.session_id,
    name: file.name || "Audio track",
    track_type: "dialogue",
    character: "",
    shot_id: "",
    start_seconds: 0,
    trim_in_seconds: 0,
    trim_out_seconds: 0,
    volume_db: 0,
    pan_percent: 0,
    fade_in_seconds: 0,
    fade_out_seconds: 0,
    muted: false,
    solo: false,
  };
  state.animation.audioTracks.push(track);
  state.animation.selectedTrackId = track.track_id;
}

function renderAnimationAssets() {
  const list = el("animation-asset-list");
  list.replaceChildren();
  list.hidden = !state.animation.assets.length;
  state.animation.assets.forEach((asset) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = asset.asset_id === state.animation.selectedAssetId ? "active" : "";
    button.title = asset.name || "Image";
    const image = document.createElement("img");
    image.src = animationFileUrl(asset);
    image.alt = "";
    const copy = document.createElement("span");
    const name = document.createElement("strong");
    const role = document.createElement("small");
    name.textContent = asset.name || "Image";
    name.title = asset.name || "Image";
    role.textContent = String(asset.role || "prop").replaceAll("_", " ");
    copy.append(name, role);
    button.append(image, copy);
    button.addEventListener("click", () => {
      state.animation.selectedAssetId = asset.asset_id;
      renderAnimationAssets();
    });
    list.append(button);
  });
  const asset = selectedAnimationAsset();
  const preview = el("animation-stage-image");
  el("animation-stage-empty").hidden = Boolean(asset);
  el("animation-asset-controls").hidden = !asset;
  preview.hidden = !asset;
  if (!asset) {
    preview.removeAttribute("src");
    return;
  }
  preview.src = animationFileUrl(asset);
  preview.alt = asset.name || "Selected production asset";
  preview.style.width = `${Number(asset.width_percent || 35)}%`;
  preview.style.left = `${Number(asset.x_percent ?? 50)}%`;
  preview.style.top = `${Number(asset.y_percent ?? 60)}%`;
  preview.style.opacity = String(Number(asset.opacity_percent ?? 100) / 100);
  el("animation-asset-role").value = asset.role || "prop";
  [["width", "width_percent"], ["x", "x_percent"], ["y", "y_percent"], ["opacity", "opacity_percent"]].forEach(([control, key]) => {
    el(`animation-asset-${control}`).value = asset[key];
    el(`animation-asset-${control}-value`).textContent = `${Number(asset[key])}%`;
  });
  el("animation-open-gimp").disabled = state.animation.busy || !state.animation.tools?.gimp?.available;
  el("animation-open-synfig").disabled = state.animation.busy || !state.animation.tools?.synfig?.available;
}

function storyboardAssetSelect(shot) {
  const select = document.createElement("select");
  select.setAttribute("aria-label", `Image for ${shot.title || "shot"}`);
  select.append(new Option("No image", ""));
  state.animation.assets.forEach((asset) => select.add(new Option(asset.name || "Image", asset.asset_id)));
  select.value = shot.asset_id || "";
  select.addEventListener("change", () => {
    shot.asset_id = select.value;
    renderAnimationStoryboard();
  });
  return select;
}

function renderAnimationStoryboard() {
  const list = el("animation-storyboard-list");
  list.replaceChildren();
  el("animation-storyboard-empty").hidden = Boolean(state.animation.storyboard.length);
  state.animation.storyboard.forEach((shot, index) => {
    const panel = document.createElement("article");
    panel.className = "animation-storyboard-shot";
    const header = document.createElement("header");
    const number = document.createElement("span");
    number.textContent = String(index + 1).padStart(2, "0");
    const title = document.createElement("input");
    title.type = "text";
    title.value = shot.title || `Shot ${index + 1}`;
    title.setAttribute("aria-label", `Shot ${index + 1} title`);
    title.addEventListener("input", () => { shot.title = title.value; });
    const duration = document.createElement("input");
    duration.type = "number";
    duration.min = "0.1";
    duration.step = "0.1";
    duration.value = shot.duration_seconds || 5;
    duration.setAttribute("aria-label", `Shot ${index + 1} duration seconds`);
    duration.addEventListener("input", () => { shot.duration_seconds = Number(duration.value || 5); });
    const actions = document.createElement("div");
    [["↑", -1], ["↓", 1]].forEach(([label, offset]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.disabled = index + offset < 0 || index + offset >= state.animation.storyboard.length;
      button.addEventListener("click", () => {
        const [moved] = state.animation.storyboard.splice(index, 1);
        state.animation.storyboard.splice(index + offset, 0, moved);
        renderAnimationStoryboard();
      });
      actions.append(button);
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Remove";
    remove.addEventListener("click", () => {
      state.animation.storyboard.splice(index, 1);
      state.animation.audioTracks.forEach((track) => { if (track.shot_id === shot.shot_id) track.shot_id = ""; });
      renderAnimationStudio();
    });
    actions.append(remove);
    header.append(number, title, duration, actions);

    const body = document.createElement("div");
    body.className = "animation-storyboard-body";
    const visual = document.createElement("figure");
    const asset = state.animation.assets.find((row) => row.asset_id === shot.asset_id);
    if (asset) {
      const image = document.createElement("img");
      image.src = animationFileUrl(asset);
      image.alt = asset.name || "Storyboard image";
      visual.append(image);
    } else {
      const empty = document.createElement("span");
      empty.textContent = "Choose an image";
      visual.append(empty);
    }
    visual.append(storyboardAssetSelect(shot));
    const description = document.createElement("textarea");
    description.rows = 6;
    description.placeholder = "Describe what happens in this scene…";
    description.value = shot.description || "";
    description.setAttribute("aria-label", `Description for shot ${index + 1}`);
    description.addEventListener("input", () => { shot.description = description.value; });
    body.append(visual, description);

    const notes = document.createElement("div");
    notes.className = "animation-storyboard-notes";
    [["Camera notes", "camera_notes", "Framing, movement, angle, focus…"], ["Editing notes", "editing_notes", "Cut, transition, timing, audio cue…"]].forEach(([label, key, placeholder]) => {
      const wrapper = document.createElement("label");
      wrapper.textContent = label;
      const field = document.createElement("textarea");
      field.rows = 3;
      field.placeholder = placeholder;
      field.value = shot[key] || "";
      field.addEventListener("input", () => { shot[key] = field.value; });
      wrapper.append(field);
      notes.append(wrapper);
    });
    const shotTools = document.createElement("div");
    shotTools.className = "animation-shot-tools";
    const exportButton = document.createElement("button");
    exportButton.type = "button";
    exportButton.textContent = "Export Synfig package";
    exportButton.disabled = state.animation.busy;
    exportButton.addEventListener("click", () => exportAnimationShot(shot));
    const importButton = document.createElement("button");
    importButton.type = "button";
    importButton.textContent = "Import rendered shot";
    importButton.disabled = state.animation.busy;
    const renderInput = document.createElement("input");
    renderInput.type = "file";
    renderInput.accept = "video/*,.avi,.mkv,.mov,.mp4,.webm,.png,.jpg,.jpeg,.webp,.gif";
    renderInput.hidden = true;
    renderInput.addEventListener("change", (event) => {
      const file = event.target.files?.[0];
      event.target.value = "";
      if (file) importAnimationRender(file, shot);
    });
    importButton.addEventListener("click", () => renderInput.click());
    shotTools.append(exportButton, importButton, renderInput);
    const importedRender = [...state.animation.renderedShots].reverse().find((row) => row.shot_id === shot.shot_id);
    if (importedRender) {
      const renderStatus = document.createElement("span");
      renderStatus.className = "animation-shot-render-status";
      renderStatus.textContent = "Imported render:";
      const renderLink = document.createElement("a");
      renderLink.href = animationFileUrl(importedRender);
      renderLink.target = "_blank";
      renderLink.rel = "noopener";
      renderLink.textContent = importedRender.name || "Open render";
      renderStatus.append(" ", renderLink);
      shotTools.append(renderStatus);
    }
    panel.append(header, body, notes, shotTools);
    list.append(panel);
  });
}

function renderAnimationAudio() {
  const list = el("animation-audio-track-list");
  list.replaceChildren();
  list.hidden = !state.animation.audioTracks.length;
  state.animation.audioTracks.forEach((track) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = track.track_id === state.animation.selectedTrackId ? "active" : "";
    const name = document.createElement("strong");
    const detail = document.createElement("small");
    name.textContent = track.name || "Audio";
    detail.textContent = `${String(track.track_type || "dialogue").replaceAll("_", " ")} · ${Number(track.start_seconds || 0).toFixed(1)}s`;
    button.append(name, detail);
    button.addEventListener("click", () => {
      state.animation.selectedTrackId = track.track_id;
      renderAnimationAudio();
    });
    list.append(button);
  });
  const track = selectedAnimationTrack();
  el("animation-audio-empty").hidden = Boolean(track);
  el("animation-audio-editor").hidden = !track;
  if (!track) return;
  const preview = el("animation-audio-preview");
  if (preview.dataset.fileId !== track.file_id) {
    preview.src = animationFileUrl(track);
    preview.dataset.fileId = track.file_id;
    preview.load();
  }
  preview.muted = Boolean(track.muted);
  preview.volume = Math.min(1, Math.max(0, Math.pow(10, Number(track.volume_db || 0) / 20)));
  const boundTake = state.animation.lipsyncTakes.find((take) => take.track_id === track.track_id);
  const boundRig = state.animation.mouthRigs.find((rig) => rig.rig_id === boundTake?.rig_id);
  el("animation-audio-preview-note").textContent = boundTake
    ? `This dialogue playback drives ${boundRig?.character || "the character"} lip-sync below.`
    : "Track preview. Bind a lip-sync take to dialogue to drive a character.";
  const shot = el("animation-track-shot");
  shot.replaceChildren(new Option("Whole episode / unassigned", ""));
  state.animation.storyboard.forEach((row, index) => shot.add(new Option(`${index + 1}. ${row.title || "Shot"}`, row.shot_id)));
  const values = {
    "animation-track-type": track.track_type || "dialogue",
    "animation-track-character": track.character || "",
    "animation-track-shot": track.shot_id || "",
    "animation-track-start": track.start_seconds || 0,
    "animation-track-trim-in": track.trim_in_seconds || 0,
    "animation-track-trim-out": track.trim_out_seconds || 0,
    "animation-track-volume": track.volume_db || 0,
    "animation-track-pan": track.pan_percent || 0,
    "animation-track-fade-in": track.fade_in_seconds || 0,
    "animation-track-fade-out": track.fade_out_seconds || 0,
  };
  Object.entries(values).forEach(([id, value]) => { el(id).value = value; });
  el("animation-track-mute").checked = Boolean(track.muted);
  el("animation-track-solo").checked = Boolean(track.solo);
  el("animation-open-audacity").disabled = state.animation.busy || !state.animation.tools?.audacity?.available;
}

const ANIMATION_MOUTH_SHAPES = ["A", "B", "C", "D", "E", "F", "G", "H", "X"];

function selectedAnimationRig() {
  return state.animation.mouthRigs.find((row) => row.rig_id === state.animation.selectedRigId) || null;
}

function selectedAnimationTake() {
  return state.animation.lipsyncTakes.find((row) => row.take_id === state.animation.selectedTakeId) || null;
}

function activateAnimationTakeForTrack(track, audio) {
  const take = state.animation.lipsyncTakes.find((row) => row.track_id === track?.track_id);
  if (!take) return null;
  if (state.animation.selectedTakeId !== take.take_id || state.animation.selectedRigId !== take.rig_id) {
    state.animation.selectedTakeId = take.take_id;
    state.animation.selectedRigId = take.rig_id;
    renderAnimationLipSync();
  }
  renderLipSyncMouthAt(Number(audio?.currentTime || 0));
  return take;
}

function createAnimationMouthRig() {
  const sequence = state.animation.mouthRigs.length + 1;
  const track = selectedAnimationTrack();
  const rig = {
    rig_id: `mouth-rig-${Date.now()}-${sequence}`,
    character: track?.character || `Character ${sequence}`,
    base_asset_id: state.animation.selectedAssetId || "",
    animation_mode: "jaw_flap",
    shapes: Object.fromEntries(ANIMATION_MOUTH_SHAPES.map((shape) => [shape, ""])),
    mouth_x_percent: 50,
    mouth_y_percent: 58,
    mouth_width_percent: 16,
    mouth_height_percent: 100,
    mouth_anchor_x_percent: 50,
    mouth_anchor_y_percent: 50,
    jaw_open_strength_percent: 100,
    placement_calibrated: false,
    registration_master_asset_id: "",
    registration_canvas_width: 1,
    registration_canvas_height: 1,
    mouth_asset_registrations: {},
  };
  state.animation.mouthRigs.push(rig);
  state.animation.selectedRigId = rig.rig_id;
  state.animation.selectedTakeId = "";
  renderAnimationStudio();
}

function removeSelectedAnimationRig() {
  const rig = selectedAnimationRig();
  if (!rig) return;
  state.animation.mouthRigs = state.animation.mouthRigs.filter((row) => row.rig_id !== rig.rig_id);
  state.animation.lipsyncTakes = state.animation.lipsyncTakes.filter((row) => row.rig_id !== rig.rig_id);
  state.animation.selectedRigId = state.animation.mouthRigs[0]?.rig_id || "";
  state.animation.selectedTakeId = state.animation.lipsyncTakes[0]?.take_id || "";
  renderAnimationStudio();
}

function updateSelectedAnimationRig(key, value) {
  const rig = selectedAnimationRig();
  if (!rig) return;
  rig[key] = value;
  if (["base_asset_id", "mouth_x_percent", "mouth_y_percent", "mouth_width_percent", "mouth_height_percent", "mouth_anchor_x_percent", "mouth_anchor_y_percent"].includes(key)) {
    rig.placement_calibrated = false;
  }
  renderAnimationLipSync();
}

function mouthAssetForCue(rig, cue) {
  if (!rig) return null;
  if (rig.animation_mode === "jaw_flap") {
    const assetId = rig.shapes?.X || rig.shapes?.A || "";
    return state.animation.assets.find((row) => row.asset_id === assetId) || null;
  }
  const fallbacks = { G: "B", H: "C", X: "A" };
  const assetId = rig.shapes?.[cue] || rig.shapes?.[fallbacks[cue]] || rig.shapes?.A || "";
  return state.animation.assets.find((row) => row.asset_id === assetId) || null;
}

function animationJawFlapAmount(cue, rig) {
  const baseAmount = ({ X: 0, A: .18, B: .12, C: .18, D: .24, E: .12, F: .08, G: .12, H: .18 })[cue] ?? .12;
  const strength = Math.min(400, Math.max(25, Number(rig?.jaw_open_strength_percent ?? 100))) / 100;
  return baseAmount * strength;
}

async function animationImageAlphaBounds(asset) {
  const image = new Image();
  image.src = animationFileUrl(asset);
  await image.decode();
  const canvas = document.createElement("canvas");
  canvas.width = image.naturalWidth;
  canvas.height = image.naturalHeight;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  context.drawImage(image, 0, 0);
  const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
  let left = canvas.width;
  let top = canvas.height;
  let right = -1;
  let bottom = -1;
  for (let y = 0; y < canvas.height; y += 1) {
    for (let x = 0; x < canvas.width; x += 1) {
      if (pixels[((y * canvas.width + x) * 4) + 3] < 8) continue;
      left = Math.min(left, x);
      top = Math.min(top, y);
      right = Math.max(right, x);
      bottom = Math.max(bottom, y);
    }
  }
  if (right < left || bottom < top) throw new Error(`${asset.name || "Jaw image"} has no visible pixels.`);
  return { width: canvas.width, height: canvas.height, left, top, right: right + 1, bottom: bottom + 1 };
}

async function confirmAnimationMouthFit() {
  const rig = selectedAnimationRig();
  if (!rig) return;
  const masterAsset = mouthAssetForCue(rig, "X");
  if (!masterAsset) return showError("Map an X/closed jaw image first.");
  state.animation.busy = true;
  renderAnimationLipSync();
  try {
    const master = await animationImageAlphaBounds(masterAsset);
    const masterSpan = Math.max(1, master.right - master.left);
    const registrations = {};
    const assetsById = new Map();
    const mappedAssetIds = rig.animation_mode === "jaw_flap" ? [masterAsset.asset_id] : Object.values(rig.shapes || {});
    mappedAssetIds.filter(Boolean).forEach((assetId) => {
      const asset = state.animation.assets.find((candidate) => candidate.asset_id === assetId);
      if (asset) assetsById.set(assetId, asset);
    });
    for (const asset of assetsById.values()) {
      const bounds = asset.asset_id === masterAsset.asset_id ? master : await animationImageAlphaBounds(asset);
      const scale = masterSpan / Math.max(1, bounds.right - bounds.left);
      registrations[asset.asset_id] = {
        left_percent: ((master.left - (bounds.left * scale)) / master.width) * 100,
        top_percent: ((master.top - (bounds.top * scale)) / master.height) * 100,
        width_percent: ((bounds.width * scale) / master.width) * 100,
      };
    }
    rig.registration_master_asset_id = masterAsset.asset_id;
    rig.registration_canvas_width = master.width;
    rig.registration_canvas_height = master.height;
    rig.mouth_asset_registrations = registrations;
    rig.placement_calibrated = true;
    state.animation.notice = `${Object.keys(registrations).length} jaw image(s) aligned to ${masterAsset.name || "the closed jaw"}.`;
  } catch (error) {
    rig.placement_calibrated = false;
    showError(error.message || String(error));
  } finally {
    state.animation.busy = false;
    renderAnimationLipSync();
  }
}

function flashImportantMailIndicator() {
  const indicator = el("important-mail-indicator");
  indicator.classList.remove("is-flashing");
  void indicator.offsetWidth;
  indicator.classList.add("is-flashing");
}

function renderImportantMailIndicator() {
  const unseen = Number(state.monitor.mail?.unseen_count || 0);
  const indicator = el("important-mail-indicator");
  indicator.hidden = unseen < 1;
  el("important-mail-count").textContent = unseen > 99 ? "99+" : String(unseen);
  indicator.setAttribute("aria-label", unseen === 1
    ? "Open My Office for 1 important email"
    : `Open My Office for ${unseen} important emails`);
}

function mailCategoryLabel(category) {
  if (category === "security") return "Security alert";
  if (category === "buyer_question") return "Buyer question";
  if (category === "sold") return "Sold item";
  return "Offer";
}

function renderNancyImportantMail() {
  const section = el("nancy-important-mail");
  const alerts = Array.isArray(state.monitor.mail?.alerts) ? state.monitor.mail.alerts : [];
  const visible = state.session?.active_room === "my_office" && alerts.length > 0;
  section.hidden = !visible;
  const list = el("nancy-mail-list");
  list.replaceChildren();
  if (!visible) return;
  el("nancy-mail-checked").textContent = state.monitor.mail.checked_at
    ? `Checked ${new Date(state.monitor.mail.checked_at).toLocaleString()}`
    : "Checking mail…";
  alerts.forEach((alert) => {
    const card = document.createElement("article");
    card.className = "nancy-mail-card";
    const copy = document.createElement("div");
    copy.className = "nancy-mail-copy";
    const meta = document.createElement("div");
    meta.className = "nancy-mail-meta";
    meta.textContent = [mailCategoryLabel(alert.category), alert.account_email || alert.account_scope, alert.date].filter(Boolean).join(" · ");
    const subject = document.createElement("strong");
    subject.textContent = alert.subject || "(no subject)";
    const detail = document.createElement("span");
    detail.textContent = [alert.from, alert.snippet].filter(Boolean).join(" · ");
    copy.append(meta, subject, detail);
    const dismiss = document.createElement("button");
    dismiss.type = "button";
    dismiss.textContent = "Dismiss";
    dismiss.addEventListener("click", () => dismissImportantMail(alert.alert_id));
    card.append(copy, dismiss);
    list.append(card);
  });
}

function maybeShowHealthDialog() {
  const health = state.monitor.health || {};
  const issues = Array.isArray(health.issues) ? health.issues : [];
  const signature = String(health.issue_signature || "");
  if (health.status !== "attention" || !signature || !issues.length || !state.workspace) return;
  const promptKey = `${state.workspace.workspace_id}:${signature}`;
  if (state.monitor.promptedSignatures.has(promptKey)) return;
  state.monitor.promptedSignatures.add(promptKey);
  const list = el("startup-health-issues");
  list.replaceChildren();
  issues.forEach((issue) => {
    const item = document.createElement("li");
    const service = document.createElement("strong");
    service.textContent = issue.service || "Veridex";
    item.append(service, document.createTextNode(issue.summary || "A check needs attention."));
    list.append(item);
  });
  const dialog = el("startup-health-dialog");
  if (!dialog.open) dialog.showModal();
}

function applyMonitorStatus(value) {
  const nextMail = value.mail || { status: "pending", alerts: [], unseen_count: 0 };
  const unseenIds = new Set((nextMail.alerts || []).filter((row) => !row.seen).map((row) => row.alert_id));
  const hasNew = [...unseenIds].some((alertId) => !state.monitor.knownUnseenIds.has(alertId));
  state.monitor.health = value.health || state.monitor.health;
  state.monitor.mail = nextMail;
  if ((hasNew || (!state.monitor.initialized && unseenIds.size)) && unseenIds.size) flashImportantMailIndicator();
  state.monitor.knownUnseenIds = unseenIds;
  state.monitor.initialized = true;
  renderImportantMailIndicator();
  renderNancyImportantMail();
  maybeShowHealthDialog();
}

async function refreshBackgroundMonitor() {
  if (state.monitor.checking || !state.workspace || !state.session) return;
  state.monitor.checking = true;
  try {
    const query = new URLSearchParams({
      workspace_id: state.workspace.workspace_id,
      session_id: state.session.session_id,
    });
    applyMonitorStatus(await api(`/api/monitor/status?${query}`));
    state.monitor.errorShown = false;
  } catch (error) {
    if (!state.monitor.errorShown) {
      state.monitor.errorShown = true;
      showError(`Background checks are unavailable: ${error.message || String(error)}`);
    }
  } finally {
    state.monitor.checking = false;
  }
}

async function dismissImportantMail(alertId) {
  try {
    applyMonitorStatus(await api("/api/monitor/mail/dismiss", {
      method: "POST",
      body: JSON.stringify({
        workspace_id: state.workspace.workspace_id,
        session_id: state.session.session_id,
        alert_id: alertId,
      }),
    }));
  } catch (error) { showError(error.message || String(error)); }
}

function manualJawOpeningFromPoints(timeSeconds, points) {
  const rows = (points || []).slice().sort((a, b) => Number(a.time) - Number(b.time));
  if (!rows.length) return null;
  if (timeSeconds <= Number(rows[0].time)) return Number(rows[0].opening_percent || 0);
  for (let index = 1; index < rows.length; index += 1) {
    const prior = rows[index - 1];
    const next = rows[index];
    if (timeSeconds <= Number(next.time)) {
      const span = Math.max(.001, Number(next.time) - Number(prior.time));
      const ratio = Math.max(0, Math.min(1, (timeSeconds - Number(prior.time)) / span));
      return Number(prior.opening_percent || 0) + ((Number(next.opening_percent || 0) - Number(prior.opening_percent || 0)) * ratio);
    }
  }
  return Number(rows[rows.length - 1].opening_percent || 0);
}

function manualJawOpeningAt(timeSeconds, take) {
  const edit = state.animation.manualEdit;
  if (edit?.takeId === take?.take_id && edit.pointerActive) return edit.openingPercent;
  const segment = (take?.manual_jaw_segments || []).find((row) => timeSeconds >= Number(row.start) && timeSeconds <= Number(row.end));
  return segment ? manualJawOpeningFromPoints(timeSeconds, segment.points) : null;
}

function quickJawOpeningAt(timeSeconds, take, rig) {
  const active = state.animation.quickFix;
  if (active?.takeId === take?.take_id && Math.abs(timeSeconds - Number(active.time || 0)) < .002) {
    return Number(active.openingPercent || 0);
  }
  const duration = Math.max(0, Number(take?.duration || 0));
  const corrections = (take?.manual_jaw_corrections || []).slice().sort((a, b) => Number(a.time) - Number(b.time));
  const groups = [];
  corrections.forEach((correction) => {
    const center = Math.max(0, Math.min(duration, Number(correction.time || 0)));
    const blend = Math.max(.03, Math.min(1, Number(correction.blend_seconds || .12)));
    const start = Math.max(0, center - blend);
    const end = Math.min(duration, center + blend);
    const prior = groups[groups.length - 1];
    if (prior && start <= prior.end + .001) {
      prior.end = Math.max(prior.end, end);
      prior.corrections.push(correction);
    } else groups.push({ start, end, corrections: [correction] });
  });
  const group = groups.find((row) => timeSeconds >= row.start && timeSeconds <= row.end);
  if (!group) return null;
  const points = [
    { time: group.start, opening_percent: animationJawOpeningPercentAt(group.start, take, rig) },
    ...group.corrections.map((correction) => ({ time: Number(correction.time), opening_percent: Number(correction.opening_percent) })),
    { time: group.end, opening_percent: animationJawOpeningPercentAt(group.end, take, rig) },
  ].sort((a, b) => a.time - b.time);
  return manualJawOpeningFromPoints(timeSeconds, points);
}

function animationJawFlapScale(cue, rig, take, timeSeconds) {
  const adjustedOpening = manualJawOpeningAt(timeSeconds, take) ?? quickJawOpeningAt(timeSeconds, take, rig);
  if (rig?.animation_mode === "jaw_flap" && adjustedOpening !== null) {
    const strength = Math.min(400, Math.max(25, Number(rig.jaw_open_strength_percent ?? 100))) / 100;
    return 1 + (.24 * strength * (Math.max(0, Math.min(100, adjustedOpening)) / 100));
  }
  return rig?.animation_mode === "jaw_flap" ? 1 + animationJawFlapAmount(cue, rig) : 1;
}

function animationJawOpeningPercentAt(timeSeconds, take, rig) {
  if (rig?.animation_mode !== "jaw_flap") return 0;
  const cue = (take?.mouth_cues || []).find((row) => Number(row.start) <= timeSeconds && Number(row.end) > timeSeconds)?.value || "X";
  const strength = Math.min(400, Math.max(25, Number(rig.jaw_open_strength_percent ?? 100))) / 100;
  return Math.max(0, Math.min(100, (animationJawFlapAmount(cue, rig) / Math.max(.001, .24 * strength)) * 100));
}

function renderLipSyncMouthAt(timeSeconds) {
  const take = selectedAnimationTake();
  const rig = selectedAnimationRig();
  const cue = (take?.mouth_cues || []).find((row) => Number(row.start) <= timeSeconds && Number(row.end) > timeSeconds)?.value || "X";
  const mouthAsset = mouthAssetForCue(rig, cue);
  const mouth = el("animation-lipsync-mouth");
  const mouthBox = el("animation-mouth-transform-box");
  const currentCue = take ? cue : "—";
  const identityMode = take ? "Playing jaw" : "Editing jaw";
  const identityValue = mouthAsset ? `${cue} · ${mouthAsset.name || "Unnamed image"}` : "No jaw selected";
  if (el("animation-current-cue").textContent !== currentCue) el("animation-current-cue").textContent = currentCue;
  if (el("animation-mouth-identity-mode").textContent !== identityMode) el("animation-mouth-identity-mode").textContent = identityMode;
  if (el("animation-mouth-identity-value").textContent !== identityValue) el("animation-mouth-identity-value").textContent = identityValue;
  mouth.hidden = !mouthAsset;
  mouthBox.hidden = !mouthAsset;
  if (mouthAsset) {
    const mouthUrl = animationFileUrl(mouthAsset);
    if (mouth.getAttribute("src") !== mouthUrl) mouth.src = mouthUrl;
    const registration = rig?.mouth_asset_registrations?.[mouthAsset.asset_id] || {};
    const left = `${Number(registration.left_percent || 0)}%`;
    const top = `${Number(registration.top_percent || 0)}%`;
    const width = `${Number(registration.width_percent || 100)}%`;
    if (mouth.style.left !== left) mouth.style.left = left;
    if (mouth.style.top !== top) mouth.style.top = top;
    if (mouth.style.width !== width) mouth.style.width = width;
    const flapScale = animationJawFlapScale(cue, rig, take, timeSeconds);
    if (mouth.style.transformOrigin !== "50% 0%") mouth.style.transformOrigin = "50% 0%";
    const transform = `scaleY(${flapScale})`;
    if (mouth.style.transform !== transform) mouth.style.transform = transform;
  }
}

function manualJawSelectionForTake(take) {
  const duration = Math.max(0, Number(take?.duration || 0));
  const selection = state.animation.manualSelection;
  if (!selection || selection.takeId !== take?.take_id) return { takeId: take?.take_id || "", start: 0, end: duration };
  return {
    takeId: take.take_id,
    start: Math.max(0, Math.min(duration, Number(selection.start || 0))),
    end: Math.max(0, Math.min(duration, Number(selection.end ?? duration))),
  };
}

function waveformFallbackSamples(take, count = 480) {
  const samples = new Array(count).fill(.08);
  (take?.mouth_cues || []).forEach((cue) => {
    const start = Math.max(0, Math.floor((Number(cue.start || 0) / Math.max(.001, Number(take.duration || 0))) * count));
    const end = Math.min(count, Math.ceil((Number(cue.end || 0) / Math.max(.001, Number(take.duration || 0))) * count));
    for (let index = start; index < end; index += 1) {
      const phase = (index - start) / Math.max(1, end - start);
      samples[index] = Math.max(samples[index], .18 + (.22 * Math.abs(Math.sin(phase * Math.PI * 3))));
    }
  });
  return samples;
}

function waveformTimeFromPointer(event, canvas, duration) {
  const rect = canvas.getBoundingClientRect();
  const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / Math.max(1, rect.width)));
  return ratio * Math.max(0, Number(duration || 0));
}

function animationWaveformDuration(take, audio) {
  const decodedDuration = Number(state.animation.waveform.duration || 0);
  if (state.animation.waveform.samples?.length && Number.isFinite(decodedDuration) && decodedDuration > 0) return decodedDuration;
  const mediaDuration = Number(audio?.duration || 0);
  if (Number.isFinite(mediaDuration) && mediaDuration > 0) return mediaDuration;
  return Math.max(0, Number(take?.duration || decodedDuration || 0));
}

function formatAnimationWaveformTime(seconds) {
  const value = Math.max(0, Number(seconds || 0));
  const minutes = Math.floor(value / 60);
  return `${minutes}:${String(Math.floor(value % 60)).padStart(2, "0")}.${String(Math.floor((value % 1) * 100)).padStart(2, "0")}`;
}

function stopAnimationMouthClock() {
  if (state.animation.mouthTimer !== null) window.clearInterval(state.animation.mouthTimer);
  state.animation.mouthTimer = null;
  state.animation.mouthAudioId = "";
}

function startAnimationMouthClock(audio = el("animation-lipsync-audio")) {
  stopAnimationMouthClock();
  if (!audio) return;
  state.animation.mouthAudioId = audio.id;
  const tick = () => {
    const activeAudio = el(state.animation.mouthAudioId);
    if (!activeAudio || activeAudio.paused || activeAudio.ended) {
      stopAnimationMouthClock();
      return;
    }
    renderLipSyncMouthAt(Number(activeAudio.currentTime || 0));
  };
  state.animation.mouthTimer = window.setInterval(tick, 16);
  tick();
}

function updateAnimationPlaybackPosition(take, audio) {
  const duration = Math.max(.001, animationWaveformDuration(take, audio));
  const currentTime = Math.max(0, Math.min(duration, Number(audio?.currentTime || 0)));
  const playhead = el("animation-waveform-playhead");
  if (playhead) {
    playhead.hidden = !take;
    playhead.style.left = `${Math.max(0, Math.min(100, (currentTime / duration) * 100))}%`;
  }
  const timeLabel = el("animation-waveform-time");
  if (timeLabel) timeLabel.textContent = `${formatAnimationWaveformTime(currentTime)} / ${formatAnimationWaveformTime(duration)}`;
  const status = el("animation-waveform-status");
  if (!status) return;
  const showSelection = Boolean(state.animation.manualDialogOpen || el("animation-manual-advanced")?.open);
  if (!take) status.textContent = "Choose a generated take to view its voice waveform";
  else if (state.animation.waveform.loading) status.textContent = "Loading waveform…";
  else if (state.animation.waveform.failed) status.textContent = "Waveform preview unavailable; cue timing is shown";
  else if (audio && !audio.paused && !audio.ended) status.textContent = "Playing — marker follows the voice";
  else status.textContent = showSelection ? "Click to seek · drag to select" : "Click to seek";
}

function drawAnimationWaveform(take, audio) {
  const canvas = el("animation-lipsync-waveform");
  if (!canvas) return;
  const duration = Math.max(.001, animationWaveformDuration(take, audio));
  const width = Math.max(320, Math.round(canvas.clientWidth || 760));
  const height = Math.max(70, Math.round(canvas.clientHeight || 92));
  const dpr = Math.max(1, window.devicePixelRatio || 1);
  if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
  }
  const context = canvas.getContext("2d");
  if (!context) return;
  context.setTransform(dpr, 0, 0, dpr, 0, 0);
  context.clearRect(0, 0, width, height);
  context.fillStyle = "#080c09";
  context.fillRect(0, 0, width, height);
  const showSelection = Boolean(state.animation.manualDialogOpen || el("animation-manual-advanced")?.open);
  if (showSelection) {
    const selection = manualJawSelectionForTake(take);
    const startX = (Math.min(selection.start, selection.end) / duration) * width;
    const endX = (Math.max(selection.start, selection.end) / duration) * width;
    context.fillStyle = "rgba(216,184,102,.16)";
    context.fillRect(startX, 0, Math.max(2, endX - startX), height);
  }
  context.strokeStyle = "rgba(139,180,151,.28)";
  context.beginPath();
  context.moveTo(0, height / 2 + .5);
  context.lineTo(width, height / 2 + .5);
  context.stroke();
  const samples = state.animation.waveform.samples || waveformFallbackSamples(take);
  const barWidth = width / Math.max(1, samples.length);
  context.fillStyle = "#79ad87";
  samples.forEach((amplitude, index) => {
    const x = index * barWidth;
    const level = Math.max(1, Math.min(height * .46, Number(amplitude || 0) * height * .46));
    context.fillRect(x, (height - level) / 2, Math.max(1, barWidth - .5), level);
    context.fillRect(x, (height + level) / 2, Math.max(1, barWidth - .5), level);
  });
  updateAnimationPlaybackPosition(take, audio);
}

async function loadAnimationWaveform(track, take) {
  const fileId = track?.file_id || "";
  if (!fileId || !animationFileUrl(track)) return;
  const cache = state.animation.waveform;
  if (cache.fileId === fileId && (cache.loading || cache.samples || cache.failed)) return;
  const token = Number(cache.token || 0) + 1;
  state.animation.waveform = { fileId, samples: null, duration: Number(take?.duration || 0), loading: true, failed: false, token };
  drawAnimationWaveform(take, el("animation-lipsync-audio"));
  try {
    const response = await fetch(animationFileUrl(track));
    if (!response.ok) throw new Error(`Waveform request failed (${response.status})`);
    const bytes = await response.arrayBuffer();
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) throw new Error("Audio decoding is unavailable");
    const context = new AudioContextClass();
    const buffer = await context.decodeAudioData(bytes.slice(0));
    const channel = buffer.getChannelData(0);
    const count = Math.max(480, Math.min(1600, Math.round(channel.length / Math.max(1, buffer.sampleRate / 90))));
    const block = Math.max(1, Math.floor(channel.length / count));
    const samples = [];
    for (let index = 0; index < count; index += 1) {
      const from = index * block;
      const to = Math.min(channel.length, from + block);
      let peak = 0;
      for (let cursor = from; cursor < to; cursor += 1) peak = Math.max(peak, Math.abs(channel[cursor] || 0));
      samples.push(peak);
    }
    await context.close?.();
    if (state.animation.waveform.token !== token) return;
    state.animation.waveform = { fileId, samples, duration: buffer.duration, loading: false, failed: false, token };
  } catch (error) {
    if (state.animation.waveform.token !== token) return;
    state.animation.waveform = { fileId, samples: null, duration: Number(take?.duration || 0), loading: false, failed: true, token };
  }
  if (selectedAnimationTake()?.take_id === take?.take_id) drawAnimationWaveform(take, el("animation-lipsync-audio"));
}

function updateWaveformSelection(start, end, take, audio) {
  const duration = animationWaveformDuration(take, audio);
  const first = Math.max(0, Math.min(duration, Math.min(start, end)));
  const last = Math.max(first, Math.min(duration, Math.max(start, end)));
  state.animation.manualSelection = { takeId: take.take_id, start: first, end: last };
  if (audio && Math.abs(last - first) < .005) audio.currentTime = first;
  renderManualJawControls(take, audio);
  drawAnimationWaveform(take, audio);
}

function beginAnimationWaveformPointer(event) {
  if (event.button !== 0) return;
  if (!state.animation.manualDialogOpen && !el("animation-manual-advanced")?.open) return;
  const take = selectedAnimationTake();
  const audio = el("animation-lipsync-audio");
  const canvas = el("animation-lipsync-waveform");
  if (!take || !canvas || state.animation.manualEdit) return;
  const time = waveformTimeFromPointer(event, canvas, animationWaveformDuration(take, audio));
  state.animation.waveformInteraction = { pointerId: event.pointerId, anchor: time, moved: false };
  try { canvas.setPointerCapture(event.pointerId); } catch (error) { /* Test/synthetic events may not support capture. */ }
  event.preventDefault();
}

function moveAnimationWaveformPointer(event) {
  const interaction = state.animation.waveformInteraction;
  if (!interaction || event.pointerId !== interaction.pointerId) return;
  const take = selectedAnimationTake();
  const audio = el("animation-lipsync-audio");
  const canvas = el("animation-lipsync-waveform");
  if (!take || !canvas) return;
  const time = waveformTimeFromPointer(event, canvas, animationWaveformDuration(take, audio));
  if (Math.abs(time - interaction.anchor) > .01) interaction.moved = true;
  if (interaction.moved) updateWaveformSelection(interaction.anchor, time, take, audio);
  event.preventDefault();
}

function finishAnimationWaveformPointer(event) {
  const interaction = state.animation.waveformInteraction;
  if (!interaction || event.pointerId !== interaction.pointerId) return;
  const take = selectedAnimationTake();
  const audio = el("animation-lipsync-audio");
  const canvas = el("animation-lipsync-waveform");
  if (take && canvas && !interaction.moved) {
    const time = waveformTimeFromPointer(event, canvas, animationWaveformDuration(take, audio));
    audio.currentTime = time;
    renderLipSyncMouthAt(time);
    drawAnimationWaveform(take, audio);
  }
  state.animation.waveformLastDrag = interaction.moved;
  state.animation.waveformInteraction = null;
}

function seekAnimationWaveform(event) {
  if (state.animation.waveformLastDrag) {
    state.animation.waveformLastDrag = false;
    return;
  }
  const take = selectedAnimationTake();
  const audio = el("animation-lipsync-audio");
  const canvas = el("animation-lipsync-waveform");
  if (!take || !canvas || state.animation.manualEdit) return;
  const time = waveformTimeFromPointer(event, canvas, animationWaveformDuration(take, audio));
  audio.currentTime = time;
  renderLipSyncMouthAt(time);
  drawAnimationWaveform(take, audio);
}

function renderWaveformCorrectionMarkers(take, audio) {
  const container = el("animation-waveform-corrections");
  container.replaceChildren();
  const duration = Math.max(.001, animationWaveformDuration(take, audio));
  (take?.manual_jaw_corrections || []).forEach((correction) => {
    const marker = document.createElement("button");
    marker.type = "button";
    marker.style.left = `${Math.max(0, Math.min(100, (Number(correction.time || 0) / duration) * 100))}%`;
    marker.title = `Jaw correction at ${formatAnimationWaveformTime(correction.time)} · ${Number(correction.opening_percent || 0).toFixed(0)}% open`;
    marker.setAttribute("aria-label", marker.title);
    marker.addEventListener("click", () => beginQuickJawFix(correction));
    container.append(marker);
  });
}

function renderQuickFixControls(take, audio) {
  const quickFix = state.animation.quickFix?.takeId === take?.take_id ? state.animation.quickFix : null;
  const rig = selectedAnimationRig();
  const editor = el("animation-quick-fix-editor");
  editor.hidden = !quickFix;
  el("animation-quick-fix-start").disabled = !take || rig?.animation_mode !== "jaw_flap" || Boolean(state.animation.manualEdit);
  el("animation-quick-fix-undo").disabled = !take || !state.animation.quickFixHistory.undo.length || state.animation.busy;
  el("animation-quick-fix-delete").hidden = !quickFix?.correctionId;
  if (quickFix) {
    el("animation-quick-fix-time").textContent = formatAnimationWaveformTime(quickFix.time);
    el("animation-quick-fix-opening").value = String(quickFix.openingPercent);
    el("animation-quick-fix-opening-value").textContent = `${Number(quickFix.openingPercent).toFixed(0)}%`;
  }
  const correctionCount = (take?.manual_jaw_corrections || []).length;
  el("animation-quick-fix-status").textContent = quickFix
    ? "Adjust the jaw, then save. Automatic lip-sync stays active around it."
    : correctionCount
      ? `${correctionCount} saved correction${correctionCount === 1 ? "" : "s"}. Select an orange waveform marker to revise one.`
      : "Automatic lip-sync remains active everywhere else.";
  const advancedOpen = Boolean(state.animation.manualDialogOpen || el("animation-manual-advanced").open);
  el("animation-waveform-selection-legend").hidden = !advancedOpen;
  el("animation-lipsync-preview").classList.toggle("advanced-manual-open", Boolean(state.animation.manualDialogOpen));
  renderWaveformCorrectionMarkers(take, audio);
}

function beginQuickJawFix(correction = null) {
  const take = selectedAnimationTake();
  const rig = selectedAnimationRig();
  if (!take) return showError("Generate or select a lip-sync take first.");
  if (rig?.animation_mode !== "jaw_flap") return showError("Quick Fix is available for Simple jaw flap rigs.");
  const audio = el("animation-lipsync-audio");
  audio.pause();
  const time = Math.max(0, Math.min(Number(take.duration || audio.duration || 0), Number(correction?.time ?? audio.currentTime ?? 0)));
  if ((take.manual_jaw_segments || []).some((segment) => time >= Number(segment.start) && time <= Number(segment.end))) {
    return showError("This moment already has an Advanced manual-performance edit. Clear or revise that Advanced edit first.");
  }
  const openingPercent = correction
    ? Number(correction.opening_percent || 0)
    : (quickJawOpeningAt(time, take, rig) ?? animationJawOpeningPercentAt(time, take, rig));
  state.animation.quickFix = {
    takeId: take.take_id,
    correctionId: correction?.correction_id || "",
    time: Number(time.toFixed(3)),
    openingPercent: Math.max(0, Math.min(100, Number(openingPercent || 0))),
  };
  audio.currentTime = time;
  renderLipSyncMouthAt(time);
  renderQuickFixControls(take, audio);
  drawAnimationWaveform(take, audio);
}

function cancelQuickJawFix() {
  const take = selectedAnimationTake();
  const audio = el("animation-lipsync-audio");
  const time = Number(state.animation.quickFix?.time ?? audio.currentTime ?? 0);
  state.animation.quickFix = null;
  renderLipSyncMouthAt(time);
  renderQuickFixControls(take, audio);
  drawAnimationWaveform(take, audio);
}

async function persistQuickFixChange(history) {
  const saved = await saveAnimationProject(true);
  if (saved) {
    state.animation.quickFixHistory = history;
    state.animation.quickFix = null;
    renderAnimationLipSync();
  }
  return saved;
}

async function saveQuickJawFix() {
  const take = selectedAnimationTake();
  const quickFix = state.animation.quickFix;
  if (!take || !quickFix || quickFix.takeId !== take.take_id) return;
  const before = JSON.parse(JSON.stringify(take.manual_jaw_corrections || []));
  const history = {
    undo: [...state.animation.quickFixHistory.undo, before],
    redo: [],
  };
  const correction = {
    correction_id: quickFix.correctionId || `jaw-correction-${Date.now()}`,
    time: Number(quickFix.time.toFixed(3)),
    opening_percent: Number(quickFix.openingPercent.toFixed(3)),
    blend_seconds: .12,
  };
  take.manual_jaw_corrections = before.filter((row) => row.correction_id !== correction.correction_id).concat(correction).sort((a, b) => Number(a.time) - Number(b.time));
  state.animation.quickFixHistory = history;
  state.animation.notice = `Jaw correction saved at ${formatAnimationWaveformTime(correction.time)}.`;
  await persistQuickFixChange(history);
}

async function deleteQuickJawFix() {
  const take = selectedAnimationTake();
  const quickFix = state.animation.quickFix;
  if (!take || !quickFix?.correctionId) return;
  const before = JSON.parse(JSON.stringify(take.manual_jaw_corrections || []));
  const history = { undo: [...state.animation.quickFixHistory.undo, before], redo: [] };
  take.manual_jaw_corrections = before.filter((row) => row.correction_id !== quickFix.correctionId);
  state.animation.quickFixHistory = history;
  state.animation.notice = "Jaw correction deleted.";
  await persistQuickFixChange(history);
}

async function undoQuickJawFix() {
  const take = selectedAnimationTake();
  const history = state.animation.quickFixHistory;
  if (!take || !history.undo.length) return;
  const current = JSON.parse(JSON.stringify(take.manual_jaw_corrections || []));
  take.manual_jaw_corrections = history.undo[history.undo.length - 1];
  const nextHistory = { undo: history.undo.slice(0, -1), redo: [...history.redo, current] };
  state.animation.quickFixHistory = nextHistory;
  state.animation.notice = "Last Quick Fix undone.";
  await persistQuickFixChange(nextHistory);
}

function renderManualJawControls(take, audio) {
  const duration = Math.max(0, Number(take?.duration || audio.duration || 0));
  const selection = manualJawSelectionForTake(take);
  const start = Math.min(selection.start, selection.end);
  const end = Math.max(selection.start, selection.end);
  const startInput = el("animation-manual-start");
  const endInput = el("animation-manual-end");
  startInput.max = String(duration);
  endInput.max = String(duration);
  startInput.value = String(start);
  endInput.value = String(end);
  startInput.disabled = !take || Boolean(state.animation.manualEdit);
  endInput.disabled = !take || Boolean(state.animation.manualEdit);
  el("animation-manual-start-value").textContent = `${start.toFixed(2)}s`;
  el("animation-manual-end-value").textContent = `${end.toFixed(2)}s`;
  const editing = state.animation.manualEdit?.takeId === take?.take_id;
  const rig = selectedAnimationRig();
  el("animation-manual-jaw-edit").disabled = !take || rig?.animation_mode !== "jaw_flap" || end - start < .01 || (Boolean(state.animation.manualEdit) && !editing);
  el("animation-manual-jaw-edit").textContent = editing ? "Editing selected section" : (state.animation.manualDialogOpen ? "Start selected edit" : "Open advanced editor");
  el("animation-manual-jaw-clear").disabled = !take || !(take.manual_jaw_segments || []).length || Boolean(state.animation.manualEdit);
  el("animation-manual-playback-rate").disabled = !take;
  el("animation-manual-jaw-status").textContent = editing
    ? "Hold the jaw and move up/down. Release to commit this section."
    : ((take?.manual_jaw_segments || []).length ? "Manual motion is active for this take." : "Select a time range, then edit by holding the jaw.");
  el("animation-lipsync-stage").classList.toggle("manual-editing", editing);
  el("animation-manual-jaw-save").disabled = !state.animation.manualDirty || Boolean(state.animation.manualEdit);
  el("animation-manual-jaw-undo").disabled = !state.animation.manualHistory.undo.length || Boolean(state.animation.manualEdit);
  el("animation-manual-jaw-redo").disabled = !state.animation.manualHistory.redo.length || Boolean(state.animation.manualEdit);
}

function stopManualJawTimer() {
  if (state.animation.manualEdit?.timer) window.clearInterval(state.animation.manualEdit.timer);
  if (state.animation.manualEdit) state.animation.manualEdit.timer = null;
}

function sampleManualJawPoint() {
  const edit = state.animation.manualEdit;
  if (!edit?.pointerActive) return;
  const take = state.animation.lipsyncTakes.find((row) => row.take_id === edit.takeId);
  const audio = el("animation-lipsync-audio");
  if (!take || !audio) return;
  const time = Math.max(edit.start, Math.min(edit.end, Number(audio.currentTime || edit.start)));
  const point = { time: Number(time.toFixed(3)), opening_percent: Number(edit.openingPercent.toFixed(3)) };
  const prior = edit.points[edit.points.length - 1];
  if (prior && Math.abs(prior.time - point.time) < .002) edit.points[edit.points.length - 1] = point;
  else edit.points.push(point);
  renderLipSyncMouthAt(time);
  if (time >= edit.end - .002) finishManualJawEdit();
}

function finishManualJawEdit() {
  const edit = state.animation.manualEdit;
  if (!edit) return;
  stopManualJawTimer();
  const take = state.animation.lipsyncTakes.find((row) => row.take_id === edit.takeId);
  const audio = el("animation-lipsync-audio");
  if (audio) audio.pause();
  if (take && edit.points.length) {
    state.animation.manualHistory.undo.push(JSON.parse(JSON.stringify(take.manual_jaw_segments || [])));
    state.animation.manualHistory.redo = [];
    const existingSegments = take.manual_jaw_segments || [];
    const replacement = {
      start: Number(edit.start.toFixed(3)),
      end: Number(edit.end.toFixed(3)),
      points: edit.points.map((point) => ({ ...point })),
    };
    if (!replacement.points.length || replacement.points[0].time > replacement.start) {
      replacement.points.unshift({ time: replacement.start, opening_percent: 0 });
    }
    if (replacement.points[replacement.points.length - 1].time < replacement.end) {
      replacement.points.push({ time: replacement.end, opening_percent: replacement.points[replacement.points.length - 1].opening_percent });
    }
    take.manual_jaw_segments = existingSegments.filter((segment) => Number(segment.end) <= edit.start || Number(segment.start) >= edit.end).concat(replacement).sort((a, b) => Number(a.start) - Number(b.start));
    state.animation.manualDirty = true;
    state.animation.notice = `Manual jaw motion saved for ${edit.start.toFixed(2)}–${edit.end.toFixed(2)} seconds. Save the project to retain it.`;
  }
  state.animation.manualEdit = null;
  renderAnimationLipSync();
}

function openManualJawEditor() {
  const take = selectedAnimationTake();
  const rig = selectedAnimationRig();
  if (!take) return showError("Generate or select a lip-sync take first.");
  if (rig?.animation_mode !== "jaw_flap") return showError("Manual lower-jaw editing is available for Simple jaw flap rigs.");
  const preview = el("animation-lipsync-preview");
  const body = el("animation-manual-jaw-dialog-body");
  if (!state.animation.manualDialogOrigin) {
    state.animation.manualDialogOrigin = { parent: preview.parentElement, nextSibling: preview.nextSibling };
  }
  state.animation.manualHistory = { undo: [], redo: [] };
  state.animation.manualDialogOpen = true;
  el("animation-manual-advanced").open = true;
  body.append(preview);
  const dialog = el("animation-manual-jaw-dialog");
  if (!dialog.open) dialog.showModal();
  renderAnimationLipSync();
}

function closeManualJawEditor(force = false) {
  if (state.animation.manualDirty && !force && !window.confirm("Close the manual jaw editor without saving the project?")) return;
  stopManualJawTimer();
  const audio = el("animation-lipsync-audio");
  if (audio) audio.pause();
  state.animation.manualEdit = null;
  state.animation.manualDialogOpen = false;
  const preview = el("animation-lipsync-preview");
  const origin = state.animation.manualDialogOrigin;
  if (origin?.parent) {
    if (origin.nextSibling && origin.nextSibling.parentElement === origin.parent) origin.parent.insertBefore(preview, origin.nextSibling);
    else origin.parent.append(preview);
  }
  state.animation.manualDialogOrigin = null;
  const dialog = el("animation-manual-jaw-dialog");
  if (dialog.open) dialog.close();
  renderAnimationLipSync();
}

async function saveManualJawEditor() {
  const saved = await saveAnimationProject();
  if (saved) {
    state.animation.manualDirty = false;
    closeManualJawEditor(true);
  }
}

function undoManualJawEdit() {
  const take = selectedAnimationTake();
  const history = state.animation.manualHistory;
  if (!take || !history.undo.length) return;
  history.redo.push(JSON.parse(JSON.stringify(take.manual_jaw_segments || [])));
  take.manual_jaw_segments = history.undo.pop();
  state.animation.manualDirty = true;
  renderAnimationLipSync();
}

function redoManualJawEdit() {
  const take = selectedAnimationTake();
  const history = state.animation.manualHistory;
  if (!take || !history.redo.length) return;
  history.undo.push(JSON.parse(JSON.stringify(take.manual_jaw_segments || [])));
  take.manual_jaw_segments = history.redo.pop();
  state.animation.manualDirty = true;
  renderAnimationLipSync();
}

function handleManualJawEditButton() {
  if (!state.animation.manualDialogOpen) return openManualJawEditor();
  return startManualJawEdit();
}

function toggleAnimationMouthPlacement() {
  if (state.animation.manualEdit) return;
  state.animation.placementEditing = !state.animation.placementEditing;
  renderAnimationLipSync();
}

function beginManualJawPointer(event) {
  const edit = state.animation.manualEdit;
  if (!edit || event.button !== 0) return;
  event.preventDefault();
  event.stopPropagation();
  const box = el("animation-mouth-transform-box");
  const audio = el("animation-lipsync-audio");
  const stage = el("animation-lipsync-stage");
  edit.pointerActive = true;
  edit.pointerId = event.pointerId;
  edit.pointerStartY = event.clientY;
  const take = selectedAnimationTake();
  const currentTime = Number(audio.currentTime || edit.start);
  edit.openingStartPercent = manualJawOpeningAt(currentTime, take) ?? animationJawOpeningPercentAt(currentTime, take, selectedAnimationRig()) ?? edit.openingPercent ?? 0;
  edit.pointerScale = 100 / Math.max(100, (stage?.getBoundingClientRect().height || 240) * .65);
  edit.openingPercent = edit.openingStartPercent;
  box.classList.add("manual-dragging");
  try { box.setPointerCapture(event.pointerId); } catch (error) { /* Synthetic tests may not have an active pointer capture target. */ }
  audio.currentTime = Math.max(edit.start, Math.min(edit.end, Number(audio.currentTime || edit.start)));
  audio.playbackRate = Number(el("animation-manual-playback-rate").value || 1);
  audio.play().catch(() => {});
  edit.timer = window.setInterval(sampleManualJawPoint, 33);
  sampleManualJawPoint();
}

function moveManualJawPointer(event) {
  const edit = state.animation.manualEdit;
  if (!edit?.pointerActive || event.pointerId !== edit.pointerId) return;
  const deltaY = event.clientY - edit.pointerStartY;
  edit.openingPercent = Math.max(0, Math.min(100, edit.openingStartPercent - (deltaY * edit.pointerScale)));
  sampleManualJawPoint();
}

function finishManualJawPointer(event) {
  const edit = state.animation.manualEdit;
  if (!edit?.pointerActive || event.pointerId !== edit.pointerId) return;
  edit.pointerActive = false;
  el("animation-mouth-transform-box").classList.remove("manual-dragging");
  finishManualJawEdit();
}

function startManualJawEdit() {
  const take = selectedAnimationTake();
  const rig = selectedAnimationRig();
  if (!take) return showError("Generate or select a lip-sync take first.");
  if (rig?.animation_mode !== "jaw_flap") return showError("Manual lower-jaw editing is available for Simple jaw flap rigs.");
  const selection = manualJawSelectionForTake(take);
  if (selection.end - selection.start < .01) return showError("Choose a time range to edit first.");
  const audio = el("animation-lipsync-audio");
  audio.pause();
  audio.playbackRate = Number(el("animation-manual-playback-rate").value || 1);
  audio.currentTime = selection.start;
  state.animation.manualEdit = {
    takeId: take.take_id,
    start: selection.start,
    end: selection.end,
    openingPercent: manualJawOpeningAt(selection.start, take) ?? 0,
    pointerActive: false,
    points: [],
    timer: null,
  };
  renderAnimationLipSync();
  audio.play().catch(() => {
    el("animation-manual-jaw-status").textContent = "Manual edit armed. Click and hold the jaw to begin recording this section.";
  });
}

function clearManualJawEdits() {
  const take = selectedAnimationTake();
  if (!take) return;
  take.manual_jaw_segments = [];
  state.animation.notice = "Manual jaw motion cleared; automatic mouth cues are active again. Save the project to retain the change.";
  renderAnimationLipSync();
}

function markAnimationMouthPlacementChanged(rig) {
  if (!rig) return;
  rig.placement_calibrated = false;
  renderAnimationLipSync();
}

function beginAnimationMouthDrag(event, resizing = false) {
  if (state.animation.manualEdit) return beginManualJawPointer(event);
  if (!state.animation.placementEditing) return;
  const rig = selectedAnimationRig();
  const stage = el("animation-lipsync-stage");
  const box = el("animation-mouth-transform-box");
  if (!rig || box.hidden || event.button !== 0) return;
  event.preventDefault();
  event.stopPropagation();
  const stageRect = stage.getBoundingClientRect();
  const boxRect = box.getBoundingClientRect();
  const start = {
    pointerX: event.clientX,
    pointerY: event.clientY,
    x: Number(rig.mouth_x_percent ?? 50),
    y: Number(rig.mouth_y_percent ?? 58),
    width: Number(rig.mouth_width_percent ?? 16),
    height: Number(rig.mouth_height_percent ?? 100),
    renderedHeight: Math.max(1, boxRect.height),
  };
  box.classList.add(resizing ? "resizing" : "dragging");
  box.setPointerCapture(event.pointerId);
  const move = (moveEvent) => {
    const dx = moveEvent.clientX - start.pointerX;
    const dy = moveEvent.clientY - start.pointerY;
    if (resizing) {
      rig.mouth_width_percent = Math.max(1, Math.min(100, start.width + (dx / Math.max(1, stageRect.width)) * 100));
      rig.mouth_height_percent = Math.max(25, Math.min(200, start.height * ((start.renderedHeight + dy) / start.renderedHeight)));
    } else {
      rig.mouth_x_percent = Math.max(-100, Math.min(200, start.x + (dx / Math.max(1, stageRect.width)) * 100));
      rig.mouth_y_percent = Math.max(-100, Math.min(200, start.y + (dy / Math.max(1, stageRect.height)) * 100));
    }
    markAnimationMouthPlacementChanged(rig);
  };
  const finish = () => {
    box.classList.remove("dragging", "resizing");
    box.removeEventListener("pointermove", move);
    box.removeEventListener("pointerup", finish);
    box.removeEventListener("pointercancel", finish);
  };
  box.addEventListener("pointermove", move);
  box.addEventListener("pointerup", finish);
  box.addEventListener("pointercancel", finish);
}

function renderAnimationLipSync() {
  const rigSelect = el("animation-rig-select");
  const priorRig = state.animation.selectedRigId;
  rigSelect.replaceChildren(new Option("New rig", ""));
  state.animation.mouthRigs.forEach((rig) => rigSelect.add(new Option(rig.character || "Character", rig.rig_id)));
  rigSelect.value = priorRig;
  const rig = selectedAnimationRig();
  el("animation-rig-remove").disabled = !rig;
  el("animation-rig-character").disabled = !rig;
  el("animation-rig-character").value = rig?.character || "";

  const mouthMode = el("animation-mouth-mode");
  mouthMode.disabled = !rig;
  mouthMode.value = rig?.animation_mode === "jaw_flap" ? "jaw_flap" : "mouth_shapes";
  const simpleJaw = el("animation-simple-jaw");
  simpleJaw.replaceChildren(new Option("Choose the closed jaw", ""));
  state.animation.assets.forEach((asset) => simpleJaw.add(new Option(asset.name || "Image", asset.asset_id)));
  simpleJaw.value = rig?.shapes?.X || "";
  simpleJaw.disabled = !rig;
  const simpleMode = mouthMode.value === "jaw_flap";
  el("animation-simple-jaw-field").hidden = !simpleMode;
  el("animation-mouth-shape-fields").hidden = simpleMode;
  el("animation-mouth-calibrate").textContent = simpleMode ? "Use this jaw placement" : "Align all jaws + confirm fit";

  const base = el("animation-rig-base");
  base.replaceChildren(new Option("No base image", ""));
  state.animation.assets.forEach((asset) => base.add(new Option(asset.name || "Image", asset.asset_id)));
  base.value = rig?.base_asset_id || "";
  base.disabled = !rig;

  const shapeGrid = el("animation-mouth-shape-grid");
  shapeGrid.replaceChildren();
  ANIMATION_MOUTH_SHAPES.forEach((shape) => {
    const label = document.createElement("label");
    label.textContent = shape;
    if ("ABCDEF".includes(shape)) label.classList.add("required-shape");
    const select = document.createElement("select");
    select.disabled = !rig;
    select.append(new Option("Not mapped", ""));
    state.animation.assets.forEach((asset) => select.add(new Option(asset.name || "Image", asset.asset_id)));
    select.value = rig?.shapes?.[shape] || "";
    select.addEventListener("change", () => {
      if (!rig) return;
      rig.shapes[shape] = select.value;
      rig.placement_calibrated = false;
      rig.mouth_asset_registrations = {};
      rig.registration_master_asset_id = "";
      renderAnimationLipSync();
    });
    label.append(select);
    shapeGrid.append(label);
  });
  [["x", "mouth_x_percent", 50], ["y", "mouth_y_percent", 58], ["width", "mouth_width_percent", 16], ["height", "mouth_height_percent", 100], ["anchor-x", "mouth_anchor_x_percent", 50], ["anchor-y", "mouth_anchor_y_percent", 50]].forEach(([control, key, fallback]) => {
    const value = Number(rig?.[key] ?? fallback);
    el(`animation-mouth-${control}`).disabled = !rig || !state.animation.placementEditing;
    el(`animation-mouth-${control}`).value = value;
    el(`animation-mouth-${control}-value`).textContent = `${value}%`;
  });
  const jawStrength = Number(rig?.jaw_open_strength_percent ?? 100);
  el("animation-mouth-strength").disabled = !rig;
  el("animation-mouth-strength").value = jawStrength;
  el("animation-mouth-strength-value").textContent = `${jawStrength}%`;

  const takeSelect = el("animation-lipsync-take");
  takeSelect.replaceChildren(new Option("No generated take", ""));
  state.animation.lipsyncTakes.forEach((take, index) => {
    const takeRig = state.animation.mouthRigs.find((row) => row.rig_id === take.rig_id);
    takeSelect.add(new Option(`${takeRig?.character || "Character"} · take ${index + 1}`, take.take_id));
  });
  takeSelect.value = state.animation.selectedTakeId;
  const take = selectedAnimationTake();
  if (take && take.rig_id !== state.animation.selectedRigId) {
    state.animation.selectedRigId = take.rig_id;
    return renderAnimationLipSync();
  }

  const baseAsset = state.animation.assets.find((row) => row.asset_id === rig?.base_asset_id);
  const character = el("animation-lipsync-character");
  character.hidden = !baseAsset;
  if (baseAsset) character.src = animationFileUrl(baseAsset);
  el("animation-lipsync-stage-empty").hidden = Boolean(baseAsset);
  const mouth = el("animation-lipsync-mouth");
  const mouthBox = el("animation-mouth-transform-box");
  mouthBox.style.left = `${Number(rig?.mouth_x_percent ?? 50)}%`;
  mouthBox.style.top = `${Number(rig?.mouth_y_percent ?? 58)}%`;
  mouthBox.style.width = `${Number(rig?.mouth_width_percent ?? 16)}%`;
  mouthBox.style.aspectRatio = `${Number(rig?.registration_canvas_width || 1)} / ${Number(rig?.registration_canvas_height || 1)}`;
  mouthBox.style.transformOrigin = `${Number(rig?.mouth_anchor_x_percent ?? 50)}% ${Number(rig?.mouth_anchor_y_percent ?? 50)}%`;
  mouthBox.style.transform = `translate(-${Number(rig?.mouth_anchor_x_percent ?? 50)}%, -${Number(rig?.mouth_anchor_y_percent ?? 50)}%) scaleY(${Number(rig?.mouth_height_percent ?? 100) / 100})`;
  mouthBox.classList.toggle("placement-editing", Boolean(state.animation.placementEditing));
  const resizeHandle = el("animation-mouth-resize-handle");
  resizeHandle.hidden = !state.animation.placementEditing;
  mouth.style.height = "auto";
  const anchorMarker = el("animation-mouth-anchor-marker");
  anchorMarker.hidden = !rig || !mouthAssetForCue(rig, "X") || (!state.animation.placementEditing && !state.animation.manualEdit);
  anchorMarker.style.left = `${Number(rig?.mouth_x_percent ?? 50)}%`;
  anchorMarker.style.top = `${Number(rig?.mouth_y_percent ?? 58)}%`;

  const track = state.animation.audioTracks.find((row) => row.track_id === take?.track_id)
    || state.animation.audioTracks.find((row) => row.file_id === el("animation-audio-file").value);
  const audio = el("animation-lipsync-audio");
  if (track && audio.dataset.fileId !== track.file_id) {
    audio.src = animationFileUrl(track);
    audio.dataset.fileId = track.file_id;
    audio.load();
  } else if (!track) {
    audio.removeAttribute("src");
    audio.dataset.fileId = "";
    state.animation.waveform = { fileId: "", samples: null, duration: 0, loading: false, failed: false, token: Number(state.animation.waveform.token || 0) + 1 };
  }

  const timeline = el("animation-lipsync-timeline");
  timeline.replaceChildren();
  const duration = Number(take?.duration || 0);
  (take?.mouth_cues || []).slice(0, 1000).forEach((cue) => {
    const segment = document.createElement("button");
    segment.type = "button";
    segment.textContent = cue.value;
    segment.title = `${cue.value} · ${Number(cue.start).toFixed(2)}–${Number(cue.end).toFixed(2)}s`;
    segment.style.flexGrow = String(Math.max(.03, Number(cue.end) - Number(cue.start)));
    segment.addEventListener("click", () => {
      audio.currentTime = Number(cue.start || 0);
      renderLipSyncMouthAt(audio.currentTime);
    });
    timeline.append(segment);
  });
  timeline.hidden = !duration;
  renderLipSyncMouthAt(Number(audio.currentTime || 0));

  const requiredMapped = Boolean(rig && (rig.animation_mode === "jaw_flap" ? rig.shapes?.X : "ABCDEF".split("").every((shape) => rig.shapes?.[shape])));
  const placementCalibrated = Boolean(rig?.placement_calibrated);
  const rhubarbReady = Boolean(state.animation.tools?.rhubarb?.available);
  const calibrationButton = el("animation-mouth-calibrate");
  calibrationButton.disabled = !rig || !baseAsset || !mouthAssetForCue(rig, "X");
  const calibrationStatus = el("animation-mouth-calibration-status");
  calibrationStatus.textContent = placementCalibrated ? "Jaw fit confirmed" : "Calibration required";
  calibrationStatus.classList.toggle("confirmed", placementCalibrated);
  const placementButton = el("animation-mouth-placement-edit");
  placementButton.disabled = !rig || Boolean(state.animation.manualEdit);
  placementButton.textContent = state.animation.placementEditing ? "Done adjusting jaw placement" : "Adjust jaw placement";
  el("animation-lipsync-generate").disabled = state.animation.busy || !rhubarbReady || !el("animation-audio-file").value || !requiredMapped || !placementCalibrated;
}

function renderAnimationStudio() {
  const tools = el("animation-tool-list");
  tools.replaceChildren();
  Object.values(state.animation.tools || {}).forEach((tool) => {
    const row = document.createElement("div");
    row.className = `animation-tool-row ${tool.available ? "available" : "missing"}`;
    const copy = document.createElement("div");
    const name = document.createElement("strong");
    const purpose = document.createElement("span");
    const status = document.createElement("b");
    name.textContent = tool.name;
    purpose.textContent = tool.purpose;
    status.textContent = tool.available ? "Ready" : "Not installed";
    copy.append(name, purpose);
    row.append(copy, status);
    tools.append(row);
  });
  renderAnimationAssets();
  renderAnimationStoryboard();
  renderAnimationAudio();
  const projects = el("animation-project-select");
  const selected = projects.value || state.animation.currentProjectId;
  projects.replaceChildren(new Option("Eternia starter", ""));
  state.animation.projects.forEach((project) => {
    const revisionId = project.revision_id || project.project_id;
    const label = `${project.title} · v${project.project_version}${project.revision_id ? " (saved version)" : " (current)"}`;
    projects.add(new Option(label, revisionId));
  });
  projects.value = selected;
  const audio = el("animation-audio-file");
  const selectedAudio = audio.value;
  audio.replaceChildren(new Option("Choose attached audio", ""));
  const audioCandidates = new Map();
  state.files.filter((file) => String(file.content_type || "").startsWith("audio/") || /\.(aac|flac|m4a|mp3|ogg|wav)$/i.test(file.name || ""))
    .forEach((file) => audioCandidates.set(file.file_id, file));
  state.animation.audioTracks.forEach((track) => audioCandidates.set(track.file_id, track));
  audioCandidates.forEach((file) => audio.add(new Option(file.name || "Audio", file.file_id)));
  const preferredAudio = selectedAudio || selectedAnimationTrack()?.file_id || "";
  if ([...audio.options].some((option) => option.value === preferredAudio)) audio.value = preferredAudio;
  renderAnimationLipSync();
  const workflow = el("animation-workflow-list");
  workflow.replaceChildren();
  state.animation.workflow.forEach((step, index) => {
    const item = document.createElement("li");
    const number = document.createElement("span");
    const copy = document.createElement("p");
    number.textContent = String(index + 1).padStart(2, "0");
    copy.textContent = step;
    item.append(number, copy);
    workflow.append(item);
  });
  const rhubarbReady = Boolean(state.animation.tools?.rhubarb?.available);
  const missingEditors = [["gimp", "GIMP"], ["audacity", "Audacity"]]
    .filter(([key]) => !state.animation.tools?.[key]?.available)
    .map(([, label]) => label);
  const editorStatus = missingEditors.length
    ? `Install ${missingEditors.join(" and ")} for full source editing.`
    : state.animation.tools?.synfig?.available
      ? "GIMP, Audacity, and Synfig are ready."
      : "GIMP and Audacity are ready; Synfig is not installed on this computer.";
  el("animation-project-save").disabled = state.animation.busy;
  el("animation-studio-status").textContent = state.animation.busy
    ? "Working…"
    : state.animation.notice || (rhubarbReady
      ? `Image placement, storyboard, audio tracks, and Rhubarb cue generation are ready. ${editorStatus}`
      : `Image placement, storyboard, and audio tracks are ready. ${editorStatus} Install Rhubarb to generate mouth cues.`
    );
}

function addAnimationStoryboardShot() {
  const sequence = state.animation.storyboard.length + 1;
  const shot = {
    shot_id: `shot-${Date.now()}-${sequence}`,
    title: `Shot ${sequence}`,
    asset_id: state.animation.selectedAssetId || "",
    description: "",
    camera_notes: "",
    editing_notes: "",
    duration_seconds: 5,
  };
  state.animation.storyboard.push(shot);
  renderAnimationStudio();
}

function updateSelectedAnimationAsset(key, value) {
  const asset = selectedAnimationAsset();
  if (!asset) return;
  asset[key] = value;
  renderAnimationAssets();
}

function applyAnimationAssetPreset(preset) {
  const asset = selectedAnimationAsset();
  if (!asset) return;
  const values = {
    background: { role: "background", width_percent: 100, x_percent: 50, y_percent: 50, opacity_percent: 100 },
    character: { role: "character", width_percent: 34, x_percent: 50, y_percent: 62, opacity_percent: 100 },
    prop: { role: "prop", width_percent: 18, x_percent: 50, y_percent: 68, opacity_percent: 100 },
  }[preset];
  if (values) Object.assign(asset, values);
  renderAnimationAssets();
}

function removeSelectedAnimationAsset() {
  const asset = selectedAnimationAsset();
  if (!asset) return;
  state.animation.assets = state.animation.assets.filter((row) => row.asset_id !== asset.asset_id);
  state.animation.storyboard.forEach((shot) => { if (shot.asset_id === asset.asset_id) shot.asset_id = ""; });
  state.animation.selectedAssetId = state.animation.assets[0]?.asset_id || "";
  renderAnimationStudio();
}

function updateSelectedAnimationTrack(key, value) {
  const track = selectedAnimationTrack();
  if (!track) return;
  track[key] = value;
  if (["volume_db", "muted"].includes(key)) renderAnimationAudio();
}

function removeSelectedAnimationTrack() {
  const track = selectedAnimationTrack();
  if (!track) return;
  state.animation.audioTracks = state.animation.audioTracks.filter((row) => row.track_id !== track.track_id);
  state.animation.selectedTrackId = state.animation.audioTracks[0]?.track_id || "";
  renderAnimationAudio();
}

async function openAnimationEditor(tool, row) {
  if (!row?.file_id) return;
  const label = tool === "gimp" ? "GIMP" : tool === "synfig" ? "Synfig" : "Audacity";
  if (!window.confirm(`Open ${row.name || "this file"} in ${label}? The original remains in Veridex.`)) return;
  state.animation.busy = true;
  renderAnimationStudio();
  try {
    const result = await api("/api/animation/tool/open", {
      method: "POST",
      body: JSON.stringify({
        workspace_id: state.workspace.workspace_id,
        session_id: state.session.session_id,
        file_id: row.file_id,
        source_session_id: row.source_session_id || state.session.session_id,
        tool,
        confirm: true,
      }),
    });
    if (result.document?.file_id && !state.files.some((file) => file.file_id === result.document.file_id)) {
      state.files = [...state.files, result.document];
    }
    state.animation.notice = tool === "synfig" && result.document
      ? `${result.tool || label} opened a starter document for ${row.name || "the selected file"}. The original remains unchanged.`
      : `${result.tool || label} opened ${row.name || "the selected file"}. Reimport edited versions so originals stay unchanged.`;
  } catch (error) { showError(error.message || String(error)); }
  finally { state.animation.busy = false; renderAnimationStudio(); }
}

async function loadAnimationStudio() {
  if (state.animation.loading || !state.workspace || !state.session) return;
  state.animation.loading = true;
  try {
    const query = new URLSearchParams({ workspace_id: state.workspace.workspace_id, session_id: state.session.session_id });
    const result = await api(`/api/animation?${query}`);
    state.animation.tools = result.tools || {};
    state.animation.projects = result.projects || [];
    state.animation.workflow = result.workflow || [];
    state.animation.loaded = true;
    const selected = state.animation.projects.find((row) => row.project_id === state.animation.currentProjectId) || result.starter_project;
    fillAnimationProject(selected);
  } finally {
    state.animation.loading = false;
    renderAnimationStudio();
  }
}

async function openAnimationStudio() {
  el("animation-studio-dialog").showModal();
  renderAnimationStudio();
  try { await loadAnimationStudio(); }
  catch (error) { showError(error.message || String(error)); }
}

function closeAnimationStudio() {
  el("animation-studio-dialog").close();
}

async function exportAnimationShot(shot) {
  if (!shot?.shot_id || state.animation.busy) return;
  if (!window.confirm(`Export ${shot.title || "this shot"} as a Synfig package?`)) return;
  state.animation.busy = true;
  renderAnimationStudio();
  try {
    const result = await api("/api/animation/shot/export", {
      method: "POST",
      body: JSON.stringify({
        workspace_id: state.workspace.workspace_id,
        session_id: state.session.session_id,
        project: animationProjectFromForm(),
        shot_id: shot.shot_id,
        confirm: true,
      }),
    });
    state.files = result.files || state.files;
    state.animation.notice = `Synfig package ready: ${result.file?.name || "shot package"} · Artifact #${result.file?.artifact_number || "?"}. It is available in Session files.`;
  } catch (error) { showError(error.message || String(error)); }
  finally { state.animation.busy = false; renderAnimationStudio(); }
}

async function importAnimationRender(file, shot) {
  if (!file || !shot?.shot_id || state.animation.busy) return;
  if (!window.confirm(`Import ${file.name} as the rendered result for ${shot.title || "this shot"}?`)) return;
  state.animation.busy = true;
  renderAnimationStudio();
  try {
    const query = new URLSearchParams({
      workspace_id: state.workspace.workspace_id,
      session_id: state.session.session_id,
      name: file.name,
    });
    const uploadResponse = await fetch(`/api/files?${query}`, {
      method: "POST",
      headers: { "Content-Type": file.type || "application/octet-stream" },
      body: file,
    });
    const upload = await uploadResponse.json();
    if (!uploadResponse.ok) throw new Error(upload.error || `Render upload failed (${uploadResponse.status})`);
    state.files = upload.files || state.files;
    const result = await api("/api/animation/render/import", {
      method: "POST",
      body: JSON.stringify({
        workspace_id: state.workspace.workspace_id,
        session_id: state.session.session_id,
        project: animationProjectFromForm(),
        shot_id: shot.shot_id,
        file_id: upload.file?.file_id,
        source_session_id: state.session.session_id,
        confirm: true,
      }),
    });
    state.animation.projects = result.projects || state.animation.projects;
    fillAnimationProject(result.project);
    state.animation.notice = `Imported ${result.file?.name || file.name} into ${shot.title || "the shot"}. The project was saved as a new version.`;
  } catch (error) { showError(error.message || String(error)); }
  finally { state.animation.busy = false; renderAnimationStudio(); }
}

async function saveAnimationProject(skipPrompt = false) {
  if (!skipPrompt && !window.confirm("Save this Animation Studio project to the current workspace?")) return false;
  state.animation.busy = true;
  renderAnimationStudio();
  try {
    const result = await api("/api/animation/project/save", {
      method: "POST",
      body: JSON.stringify({ workspace_id: state.workspace.workspace_id, session_id: state.session.session_id, project: animationProjectFromForm(), confirm: true }),
    });
    state.animation.projects = result.projects || [];
    state.animation.currentProjectId = result.project.project_id;
    fillAnimationProject(result.project);
    state.animation.loaded = true;
    return true;
  } catch (error) { showError(error.message || String(error)); }
  finally { state.animation.busy = false; renderAnimationStudio(); }
  return false;
}

async function generateAnimationLipsync() {
  const fileId = el("animation-audio-file").value;
  if (!fileId) return showError("Attach and choose a voice-over file first.");
  const rig = selectedAnimationRig();
  if (!rig) return showError("Create a character mouth rig first.");
  const requiredShapes = rig.animation_mode === "jaw_flap" ? ["X"] : "ABCDEF".split("");
  const missingShapes = requiredShapes.filter((shape) => !rig.shapes?.[shape]);
  if (missingShapes.length) return showError(`Map the required ${missingShapes.join(", ")} mouth drawing${missingShapes.length === 1 ? "" : "s"} first.`);
  if (!rig.placement_calibrated) return showError("Fit the closed jaw to the character and confirm the jaw fit first.");
  let track = state.animation.audioTracks.find((row) => row.file_id === fileId);
  if (!track) {
    const file = state.files.find((row) => row.file_id === fileId);
    if (!file) return showError("The selected voice-over is unavailable.");
    addAnimationAudioFile(file);
    track = state.animation.audioTracks.find((row) => row.file_id === fileId);
  }
  state.animation.busy = true;
  renderAnimationStudio();
  try {
    const result = await api("/api/animation/lipsync", {
      method: "POST",
      body: JSON.stringify({
        workspace_id: state.workspace.workspace_id,
        session_id: state.session.session_id,
        file_id: fileId,
        source_session_id: track?.source_session_id || state.session.session_id,
        transcript: el("animation-transcript").value,
        recognizer: el("animation-lipsync-recognizer").value,
        binding: {
          track_id: track.track_id,
          rig_id: rig.rig_id,
          character: rig.character,
          base_asset_id: rig.base_asset_id,
          shapes: { ...(rig.shapes || {}) },
          mouth_x_percent: rig.mouth_x_percent,
          mouth_y_percent: rig.mouth_y_percent,
          mouth_width_percent: rig.mouth_width_percent,
        },
      }),
    });
    const take = {
      take_id: `lipsync-${result.file.file_id}`,
      track_id: track.track_id,
      rig_id: rig.rig_id,
      cue_file_id: result.file.file_id,
      cue_source_session_id: state.session.session_id,
      recognizer: result.recognizer || "pocketSphinx",
      extended_shapes: result.extended_shapes || "",
      duration: Number(result.duration || 0),
      mouth_cues: (result.mouth_cues || []).map((cue) => ({ ...cue })),
      manual_jaw_points: [],
      manual_jaw_segments: [],
      manual_jaw_corrections: [],
      created_at: new Date().toISOString(),
    };
    state.animation.lipsyncTakes.push(take);
    state.animation.selectedTakeId = take.take_id;
    state.animation.selectedTrackId = track.track_id;
    state.animation.notice = `${result.cue_count} mouth cues are ready for ${rig.character}. Save the project to retain this bound take.`;
    el("animation-lipsync-result").textContent = `${result.cue_count} bound mouth cues · ${Number(result.duration || 0).toFixed(2)} seconds · Artifact #${result.file.artifact_number}`;
    await loadState(state.workspace.workspace_id, state.session.session_id, true);
  } catch (error) { showError(error.message || String(error)); }
  finally { state.animation.busy = false; renderAnimationStudio(); }
}

function loadSelectedAnimationProject() {
  const selectedId = el("animation-project-select").value;
  const project = state.animation.projects.find((row) => (row.revision_id || row.project_id) === selectedId);
  if (project) fillAnimationProject(project);
}

function renderAnimationTools() {
  const active = state.session?.active_room === "animation_studio";
  el("animation-actions").hidden = !active;
  el("open-animation-studio").disabled = state.sending || state.uploading || state.switchingRoom;
  if (!active && el("animation-studio-dialog").open) closeAnimationStudio();
}

function currentRoom() {
  return state.rooms.find((room) => room.id === state.session?.active_room) || null;
}

function roomFileContentUrl(file) {
  return artImageContentUrl(file);
}

function roomFileType(file) {
  const extension = String(file.name || "").split(".").pop();
  if (extension && extension !== file.name) return extension.toUpperCase().slice(0, 8);
  return String(file.content_type || "FILE").split("/").pop().toUpperCase().slice(0, 8);
}

function selectedRoomFile() {
  return state.roomFiles.find((file) => file.file_id === state.selectedRoomFileId)
    || state.roomFiles[0]
    || null;
}

async function loadRoomFiles() {
  const roomId = state.session?.active_room || "";
  if (!state.workspace || !roomId || state.roomFilesLoading) return;
  state.roomFilesLoading = true;
  state.roomFilesRoomId = roomId;
  renderRoomFileLibrary();
  try {
    const query = new URLSearchParams({
      workspace_id: state.workspace.workspace_id,
      room_id: roomId,
    });
    const result = await api(`/api/room/files?${query}`);
    if (state.session?.active_room !== roomId) return;
    state.roomFiles = result.files || [];
    if (!state.roomFiles.some((file) => file.file_id === state.selectedRoomFileId)) {
      state.selectedRoomFileId = state.roomFiles[0]?.file_id || "";
    }
  } catch (error) {
    showError(error.message || String(error));
  } finally {
    state.roomFilesLoading = false;
    renderRoomFileLibrary();
  }
}

async function attachRoomFile(file) {
  if (!file || state.attachingRoomFileId || state.selectedFiles.has(file.file_id)) return;
  state.attachingRoomFileId = file.file_id;
  renderRoomFileLibrary();
  try {
    const result = await api("/api/room/files/attach", {
      method: "POST",
      body: JSON.stringify({
        workspace_id: state.workspace.workspace_id,
        session_id: state.session.session_id,
        room_id: state.session.active_room,
        file_id: file.file_id,
      }),
    });
    state.files = result.files || state.files;
    state.selectedFiles.add(file.file_id);
    renderFiles();
  } catch (error) {
    showError(error.message || String(error));
  } finally {
    state.attachingRoomFileId = "";
    renderRoomFileLibrary();
  }
}

function renderRoomFileLibrary() {
  const dialog = el("room-file-dialog");
  if (!dialog) return;
  const room = currentRoom();
  const grid = el("room-file-grid");
  const preview = el("room-file-preview");
  const empty = el("room-file-empty");
  grid.replaceChildren();
  preview.replaceChildren();
  el("room-file-eyebrow").textContent = room?.title || "Room files";
  el("room-file-summary").textContent = state.roomFilesLoading
    ? "Loading room filesâ€¦"
    : `${state.roomFiles.length} ${state.roomFiles.length === 1 ? "file" : "files"} created or added across ${room?.title || "this room"} sessions`;
  empty.hidden = state.roomFilesLoading || state.roomFiles.length > 0;
  el("room-file-content").hidden = state.roomFilesLoading || !state.roomFiles.length;
  if (state.roomFilesLoading || !state.roomFiles.length) return;

  const selected = selectedRoomFile();
  state.roomFiles.forEach((file) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `art-gallery-thumb room-file-thumb${selected?.file_id === file.file_id ? " active" : ""}`;
    button.setAttribute("aria-pressed", String(selected?.file_id === file.file_id));
    button.setAttribute("aria-label", `Preview ${file.name || "file"}`);
    if (String(file.content_type || "").startsWith("image/")) {
      const thumbnail = document.createElement("img");
      thumbnail.src = roomFileContentUrl(file);
      thumbnail.alt = "";
      thumbnail.loading = "lazy";
      button.append(thumbnail);
    } else {
      const type = document.createElement("div");
      type.className = "room-file-type";
      type.textContent = roomFileType(file);
      button.append(type);
    }
    const label = document.createElement("span");
    label.textContent = file.name || "File";
    button.append(label);
    button.addEventListener("click", () => {
      state.selectedRoomFileId = file.file_id;
      renderRoomFileLibrary();
    });
    grid.append(button);
  });

  if (!selected) return;
  const hero = document.createElement("figure");
  if (String(selected.content_type || "").startsWith("image/")) {
    const image = document.createElement("img");
    image.src = roomFileContentUrl(selected);
    image.alt = selected.name || "Room file";
    hero.append(image);
  } else {
    const documentPreview = document.createElement("div");
    documentPreview.className = "room-file-document-preview";
    const type = document.createElement("strong");
    type.textContent = roomFileType(selected);
    const contentType = document.createElement("span");
    contentType.textContent = selected.content_type || "File";
    documentPreview.append(type, contentType);
    hero.append(documentPreview);
  }
  const caption = document.createElement("figcaption");
  const name = document.createElement("h3");
  name.textContent = selected.name || "File";
  const facts = document.createElement("p");
  facts.textContent = [
    selected.artifact_number ? `Artifact #${selected.artifact_number}` : "Ledgered file",
    formatBytes(Number(selected.size || 0)),
    readableEmailDate(selected.created_at || selected.ledgered_at),
    selected.source_session_title,
  ].filter(Boolean).join(" Â· ");
  caption.append(name, facts);
  hero.append(caption);

  const actions = document.createElement("div");
  actions.className = "art-gallery-preview-actions";
  const open = document.createElement("a");
  open.href = roomFileContentUrl(selected);
  open.target = "_blank";
  open.rel = "noopener";
  open.textContent = "Open original";
  const download = document.createElement("a");
  download.href = roomFileContentUrl(selected);
  download.download = selected.name || "room-file";
  download.textContent = "Download";
  const attach = document.createElement("button");
  const attached = state.selectedFiles.has(selected.file_id);
  attach.type = "button";
  attach.className = "primary-action";
  attach.disabled = attached || Boolean(state.attachingRoomFileId);
  attach.textContent = attached
    ? "Attached to next message"
    : state.attachingRoomFileId === selected.file_id ? "Attachingâ€¦" : "Attach to next message";
  attach.addEventListener("click", () => attachRoomFile(selected));
  actions.append(open, download, attach);
  preview.append(hero, actions);
}

async function openRoomFileLibrary() {
  const roomId = state.session?.active_room || "";
  if (!roomId || ["lobby", "art_department"].includes(roomId)) return;
  const dialog = el("room-file-dialog");
  if (!dialog.open) dialog.showModal();
  await loadRoomFiles();
}

function closeRoomFileLibrary() {
  const dialog = el("room-file-dialog");
  if (dialog.open) dialog.close();
}

function setResumeStatus(text) {
  el("resume-studio-status").textContent = text || "";
}

function splitResumeList(value) {
  return String(value || "").split(/[,\n]/).map((item) => item.trim()).filter(Boolean);
}

function resumeProfileFromForm() {
  const prior = state.resume.profile || {};
  return {
    ...prior,
    contact: {
      name: el("resume-name").value.trim(),
      email: el("resume-email").value.trim(),
      phone: el("resume-phone").value.trim(),
      location: el("resume-location").value.trim(),
      links: splitResumeList(el("resume-links").value),
    },
    target_title: el("resume-target-title").value.trim(),
    summary: el("resume-summary").value.trim(),
    skills: splitResumeList(el("resume-skills").value),
    career_history: el("resume-career-history").value.trim(),
    education_notes: el("resume-education").value.trim(),
    federal: {
      citizenship: el("resume-citizenship").value.trim(),
      clearance: el("resume-clearance").value.trim(),
      veterans_preference: el("resume-veterans").value.trim(),
      special_hiring_authority: el("resume-authority").value.trim(),
    },
  };
}

function fillResumeProfile(profile, { preserveExisting = false } = {}) {
  const contact = profile?.contact || {};
  const set = (id, value) => {
    if (!preserveExisting || !el(id).value.trim()) el(id).value = value || "";
  };
  set("resume-name", contact.name);
  set("resume-email", contact.email);
  set("resume-phone", contact.phone);
  set("resume-location", contact.location);
  set("resume-links", (contact.links || []).join(", "));
  set("resume-target-title", profile?.target_title);
  set("resume-summary", profile?.summary);
  set("resume-skills", (profile?.skills || []).join(", "));
  set("resume-career-history", profile?.career_history);
  set("resume-education", profile?.education_notes);
  set("resume-citizenship", profile?.federal?.citizenship);
  set("resume-clearance", profile?.federal?.clearance);
  set("resume-veterans", profile?.federal?.veterans_preference);
  set("resume-authority", profile?.federal?.special_hiring_authority);
  el("resume-profile-version").textContent = profile?.saved
    ? `Saved profile v${profile.profile_version || 1}`
    : "Not saved";
}

function renderResumeImportFiles() {
  const select = el("resume-import-file");
  const selected = select.value;
  select.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Choose PDF, DOCX, or text";
  select.append(placeholder);
  state.files.filter((file) => /\.(pdf|docx|txt|md)$/i.test(file.name || "")).forEach((file) => {
    const option = document.createElement("option");
    option.value = file.file_id;
    option.textContent = `${file.name} · Artifact #${file.artifact_number || "?"}`;
    select.append(option);
  });
  if ([...select.options].some((option) => option.value === selected)) select.value = selected;
}

function renderResumeTemplates() {
  const select = el("resume-template");
  const selected = select.value;
  const type = el("resume-type").value;
  select.replaceChildren();
  state.resume.templates.filter((template) => (template.resume_types || []).includes(type)).forEach((template) => {
    const option = document.createElement("option");
    option.value = template.id;
    option.textContent = `${template.name} — ${template.best_for}`;
    select.append(option);
  });
  if ([...select.options].some((option) => option.value === selected)) select.value = selected;
  else if (type === "federal") select.value = "federal";
}

function renderResumeProjects() {
  const select = el("resume-project-select");
  const selected = state.resume.currentProjectId || select.value;
  select.replaceChildren();
  const fresh = document.createElement("option");
  fresh.value = "";
  fresh.textContent = "New project";
  select.append(fresh);
  state.resume.projects.forEach((project) => {
    const option = document.createElement("option");
    option.value = project.project_id;
    option.textContent = project.name || "Resume project";
    select.append(option);
  });
  if ([...select.options].some((option) => option.value === selected)) select.value = selected;
}

async function loadResumeProject() {
  const projectId = el("resume-project-select").value;
  const project = state.resume.projects.find((row) => row.project_id === projectId);
  if (!project) {
    state.resume.currentProjectId = "";
    state.resume.draft = null;
    state.resume.review = null;
    state.resume.analysis = null;
    ["resume-job-title", "resume-company", "resume-job-description", "resume-job-url", "resume-instructions"].forEach((id) => { el(id).value = ""; });
    el("resume-type").value = "private";
    renderResumeTemplates();
    setResumeStatus("New application project");
    renderResumeStudio();
    return;
  }
  state.resume.currentProjectId = project.project_id;
  el("resume-job-title").value = project.target_job?.title || "";
  el("resume-company").value = project.target_job?.company || "";
  el("resume-job-description").value = project.target_job?.description || "";
  el("resume-job-url").value = project.target_job?.url || "";
  el("resume-type").value = project.resume_type || "private";
  renderResumeTemplates();
  el("resume-template").value = project.template_id || (project.resume_type === "federal" ? "federal" : "ats_classic");
  state.resume.draft = project.draft || null;
  state.resume.review = project.review || null;
  if (state.resume.draft) {
    try { await refreshResumeReview(); }
    catch (error) { showError(error.message || String(error)); }
  }
  setResumeStatus(`Loaded ${project.name || "resume project"}`);
  setResumeStep(state.resume.draft ? "draft" : "target");
  renderResumeStudio();
}

function setResumeStep(step) {
  state.resume.step = step;
  document.querySelectorAll("[data-resume-step]").forEach((button) => button.classList.toggle("active", button.dataset.resumeStep === step));
  document.querySelectorAll(".resume-step").forEach((section) => section.classList.toggle("active", section.id === `resume-step-${step}`));
}

function renderResumeAnalysis() {
  const panel = el("resume-analysis");
  panel.replaceChildren();
  const heading = document.createElement("strong");
  heading.textContent = "Match analysis";
  panel.append(heading);
  const analysis = state.resume.analysis;
  if (!analysis) {
    const copy = document.createElement("p");
    copy.textContent = "Add a job description, then analyze it against your profile.";
    panel.append(copy);
    return;
  }
  const facts = document.createElement("dl");
  const rows = [
    ["Keyword coverage", `${analysis.coverage_percent || 0}%`],
    ["Matched", (analysis.matched_keywords || []).join(", ") || "None yet"],
    ["Missing or unsupported", (analysis.missing_keywords || []).slice(0, 15).join(", ") || "None"],
  ];
  rows.forEach(([label, value]) => {
    const wrapper = document.createElement("div");
    const term = document.createElement("dt");
    const detail = document.createElement("dd");
    term.textContent = label;
    detail.textContent = value;
    wrapper.append(term, detail);
    facts.append(wrapper);
  });
  panel.append(facts);
  const keywords = document.createElement("div");
  keywords.className = "resume-keywords";
  (analysis.keywords || []).slice(0, 20).forEach((keyword) => {
    const chip = document.createElement("span");
    chip.textContent = keyword;
    keywords.append(chip);
  });
  panel.append(keywords);
}

function renderResumeReview() {
  const review = state.resume.review;
  const preview = el("resume-preview");
  preview.textContent = review?.ats_preview || "Generate a draft to see the parser-readable resume.";
  const ready = el("resume-ready-state");
  ready.textContent = !review ? "Not reviewed" : review.ready_to_export ? "Ready to export" : "Needs review";
  const list = el("resume-review");
  list.replaceChildren();
  if (!review) {
    const empty = document.createElement("p");
    empty.textContent = "Generate a draft to run deterministic quality checks.";
    list.append(empty);
  } else {
    const wrapper = document.createElement("div");
    wrapper.className = "resume-review-list";
    const warnings = review.warnings || [];
    if (!warnings.length) {
      const item = document.createElement("div");
      item.className = "resume-review-item good";
      item.innerHTML = '<span class="resume-review-dot"></span><span>Required sections and claim checks passed.</span>';
      wrapper.append(item);
    }
    warnings.forEach((warning) => {
      const item = document.createElement("div");
      item.className = `resume-review-item ${warning.severity || "warning"}`;
      const dot = document.createElement("span");
      dot.className = "resume-review-dot";
      const copy = document.createElement("span");
      copy.textContent = warning.message;
      item.append(dot, copy);
      wrapper.append(item);
    });
    list.append(wrapper);
  }

  const claims = state.resume.draft?.unconfirmed_claims || [];
  el("resume-claim-count").textContent = String(claims.length);
  const claimList = el("resume-claims");
  claimList.replaceChildren();
  if (!claims.length) {
    const empty = document.createElement("p");
    empty.textContent = "No unconfirmed claims.";
    claimList.append(empty);
  } else {
    const wrapper = document.createElement("div");
    wrapper.className = "resume-claim-list";
    claims.forEach((claim) => {
      const item = document.createElement("div");
      item.className = "resume-claim";
      const text = document.createElement("p");
      text.textContent = claim.text;
      const reason = document.createElement("small");
      reason.textContent = claim.reason || "Confirm this is accurate before export.";
      const actions = document.createElement("div");
      actions.className = "resume-claim-actions";
      const confirmed = document.createElement("button");
      confirmed.type = "button";
      confirmed.textContent = "I confirm this is true";
      confirmed.addEventListener("click", () => resolveResumeClaim(claim.claim_id, true));
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "Remove suggestion";
      remove.addEventListener("click", () => resolveResumeClaim(claim.claim_id, false));
      actions.append(confirmed, remove);
      item.append(text, reason, actions);
      wrapper.append(item);
    });
    claimList.append(wrapper);
  }
  renderResumeKit();
}

function addResumeKitBlock(container, title, copy, actionLabel, action) {
  if (!copy) return;
  const block = document.createElement("div");
  block.className = "resume-kit-block";
  const heading = document.createElement("strong");
  heading.textContent = title;
  const text = document.createElement("p");
  text.textContent = copy;
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = actionLabel || "Copy";
  button.addEventListener("click", action || (() => navigator.clipboard.writeText(copy)));
  block.append(heading, text, button);
  container.append(block);
}

function renderResumeKit() {
  const kit = el("resume-kit");
  kit.replaceChildren();
  const draft = state.resume.draft;
  if (!draft) {
    const empty = document.createElement("p");
    empty.textContent = "Cover letter, LinkedIn copy, recruiter email, and interview talking points will appear here.";
    kit.append(empty);
    return;
  }
  addResumeKitBlock(kit, "Cover letter", draft.cover_letter, "Copy", () => navigator.clipboard.writeText(draft.cover_letter || ""));
  addResumeKitBlock(kit, "LinkedIn", [draft.linkedin_headline, draft.linkedin_about].filter(Boolean).join("\n\n"), "Copy");
  addResumeKitBlock(kit, "Recruiter email", draft.recruiter_email, "Review with Nancy", () => {
    openEmailComposer({ subject: draft.recruiter_email_subject || "Introduction", body: draft.recruiter_email || "" });
  });
  addResumeKitBlock(kit, "Interview talking points", (draft.interview_talking_points || []).map((item) => `• ${item}`).join("\n"), "Copy");
  if (!kit.children.length) {
    const empty = document.createElement("p");
    empty.textContent = "No optional application-kit content was generated.";
    kit.append(empty);
  }
}

function renderResumeStudio() {
  renderResumeImportFiles();
  renderResumeTemplates();
  renderResumeProjects();
  renderResumeAnalysis();
  renderResumeReview();
  const busy = state.resume.busy || state.resume.loading;
  el("resume-profile-save").disabled = busy;
  el("resume-import-button").disabled = busy || !el("resume-import-file").value;
  el("resume-analyze").disabled = busy;
  el("resume-load-project").disabled = busy;
  el("resume-fetch-job").disabled = busy || !el("resume-job-url").value.trim();
  el("resume-generate").disabled = busy;
  el("resume-save-project").disabled = busy || !state.resume.draft;
  el("resume-export").disabled = busy || !state.resume.draft || !state.resume.review?.ready_to_export;
}

async function openResumeStudio() {
  if (state.session?.active_room !== "hr_department") return;
  const dialog = el("resume-studio-dialog");
  if (!dialog.open) dialog.showModal();
  if (state.resume.loaded || state.resume.loading) {
    renderResumeStudio();
    return;
  }
  state.resume.loading = true;
  setResumeStatus("Loading career profile…");
  try {
    const query = new URLSearchParams({ workspace_id: state.workspace.workspace_id, session_id: state.session.session_id });
    const result = await api(`/api/resume?${query}`);
    state.resume.profile = result.profile;
    state.resume.templates = result.templates || [];
    state.resume.projects = result.projects || [];
    state.resume.loaded = true;
    fillResumeProfile(result.profile || {});
    setResumeStatus(result.profile?.saved ? `Career profile v${result.profile.profile_version} loaded` : "Career profile is not saved yet");
  } catch (error) {
    showError(error.message || String(error));
    setResumeStatus("Resume Studio could not load");
  } finally {
    state.resume.loading = false;
    renderResumeStudio();
  }
}

function closeResumeStudio() {
  const dialog = el("resume-studio-dialog");
  if (dialog.open) dialog.close();
}

async function saveResumeProfile() {
  state.resume.busy = true;
  setResumeStatus("Saving career profile…");
  renderResumeStudio();
  try {
    const profile = resumeProfileFromForm();
    const result = await api("/api/resume/profile/save", { method: "POST", body: JSON.stringify({
      workspace_id: state.workspace.workspace_id,
      session_id: state.session.session_id,
      profile,
      expected_version: state.resume.profile?.profile_version || 0,
      confirm: true,
    }) });
    state.resume.profile = result.profile;
    fillResumeProfile(result.profile);
    setResumeStatus(`Career profile v${result.profile.profile_version} saved`);
  } catch (error) { showError(error.message || String(error)); setResumeStatus("Profile was not saved"); }
  finally { state.resume.busy = false; renderResumeStudio(); }
}

async function importResumeFile() {
  const fileId = el("resume-import-file").value;
  if (!fileId) return;
  state.resume.busy = true;
  setResumeStatus("Extracting verified resume text…");
  renderResumeStudio();
  try {
    const result = await api("/api/resume/import", { method: "POST", body: JSON.stringify({ workspace_id: state.workspace.workspace_id, session_id: state.session.session_id, file_id: fileId }) });
    const current = resumeProfileFromForm();
    const imported = result.profile || {};
    imported.sources = [...(current.sources || []), ...(imported.sources || [])];
    fillResumeProfile(imported, { preserveExisting: true });
    if (result.text && !el("resume-career-history").value.trim()) el("resume-career-history").value = result.text;
    state.resume.profile = { ...current, sources: imported.sources };
    setResumeStatus(`Imported ${result.source?.name || "resume"}; review before saving`);
  } catch (error) { showError(error.message || String(error)); setResumeStatus("Import failed"); }
  finally { state.resume.busy = false; renderResumeStudio(); }
}

async function analyzeResumeTarget() {
  state.resume.busy = true;
  setResumeStatus("Analyzing job requirements…");
  renderResumeStudio();
  try {
    state.resume.analysis = await api("/api/resume/analyze", { method: "POST", body: JSON.stringify({
      workspace_id: state.workspace.workspace_id,
      session_id: state.session.session_id,
      job_description: el("resume-job-description").value,
      resume_text: [el("resume-summary").value, el("resume-skills").value, el("resume-career-history").value, el("resume-education").value].join("\n"),
    }) });
    setResumeStatus("Match analysis complete");
  } catch (error) { showError(error.message || String(error)); setResumeStatus("Analysis failed"); }
  finally { state.resume.busy = false; renderResumeStudio(); }
}

async function fetchResumeJobDescription() {
  const url = el("resume-job-url").value.trim();
  if (!url) return;
  state.resume.busy = true;
  setResumeStatus("Retrieving job description…");
  renderResumeStudio();
  try {
    const result = await api("/api/resume/job/fetch", { method: "POST", body: JSON.stringify({ workspace_id: state.workspace.workspace_id, session_id: state.session.session_id, url }) });
    el("resume-job-description").value = result.description || "";
    setResumeStatus("Job description retrieved; review it before generating");
  } catch (error) { showError(error.message || String(error)); setResumeStatus("Paste the job description to continue"); }
  finally { state.resume.busy = false; renderResumeStudio(); }
}

function resumeTargetJob() {
  return {
    title: el("resume-job-title").value.trim(),
    company: el("resume-company").value.trim(),
    description: el("resume-job-description").value.trim(),
    url: el("resume-job-url").value.trim(),
  };
}

async function generateResumeDraft() {
  state.resume.busy = true;
  setResumeStatus("HR Manager is drafting with high reasoning…");
  renderResumeStudio();
  try {
    const result = await api("/api/resume/draft", { method: "POST", body: JSON.stringify({
      workspace_id: state.workspace.workspace_id,
      session_id: state.session.session_id,
      profile: resumeProfileFromForm(),
      target_job: resumeTargetJob(),
      resume_type: el("resume-type").value,
      template_id: el("resume-template").value,
      instructions: el("resume-instructions").value.trim(),
    }) });
    state.resume.draft = result.draft;
    state.resume.review = result.review;
    state.resume.route = { model: result.model, reasoning_effort: result.reasoning_effort };
    setResumeStep("draft");
    setResumeStatus(`Drafted with ${result.model} · ${result.reasoning_effort} reasoning`);
  } catch (error) { showError(error.message || String(error)); setResumeStatus("Draft generation failed"); }
  finally { state.resume.busy = false; renderResumeStudio(); }
}

async function refineResumeDraft() {
  if (!state.resume.draft) return;
  const instruction = window.prompt("What should the HR Manager improve?", "Make the language more specific and compelling while preserving every verified fact.")?.trim();
  if (!instruction) return;
  state.resume.busy = true;
  setResumeStatus("HR Manager is refining the draft…");
  renderResumeStudio();
  try {
    const result = await api("/api/resume/draft", { method: "POST", body: JSON.stringify({
      workspace_id: state.workspace.workspace_id,
      session_id: state.session.session_id,
      profile: resumeProfileFromForm(),
      target_job: resumeTargetJob(),
      resume_type: el("resume-type").value,
      template_id: el("resume-template").value,
      current_draft: state.resume.draft,
      instructions: instruction,
    }) });
    state.resume.draft = result.draft;
    state.resume.review = result.review;
    setResumeStatus(`Draft refined with ${result.model} · ${result.reasoning_effort} reasoning`);
  } catch (error) { showError(error.message || String(error)); setResumeStatus("Refinement failed"); }
  finally { state.resume.busy = false; renderResumeStudio(); }
}

async function refreshResumeReview() {
  if (!state.resume.draft) return;
  state.resume.review = await api("/api/resume/review", { method: "POST", body: JSON.stringify({
    workspace_id: state.workspace.workspace_id,
    session_id: state.session.session_id,
    draft: state.resume.draft,
    job_description: el("resume-job-description").value,
    resume_type: el("resume-type").value,
  }) });
}

async function resolveResumeClaim(claimId, confirmed) {
  if (!state.resume.draft) return;
  state.resume.draft.unconfirmed_claims = (state.resume.draft.unconfirmed_claims || []).filter((claim) => claim.claim_id !== claimId);
  setResumeStatus(confirmed ? "Claim confirmed by you" : "Suggestion removed");
  try { await refreshResumeReview(); }
  catch (error) { showError(error.message || String(error)); }
  renderResumeStudio();
}

function currentResumeProject() {
  const target = resumeTargetJob();
  return {
    project_id: state.resume.currentProjectId,
    name: [target.company, target.title].filter(Boolean).join(" — ") || "Resume project",
    resume_type: el("resume-type").value,
    template_id: el("resume-template").value,
    target_job: target,
    profile_version: state.resume.profile?.profile_version || 0,
    draft: state.resume.draft,
    review: state.resume.review,
  };
}

async function saveResumeProject() {
  state.resume.busy = true;
  setResumeStatus("Saving application project…");
  renderResumeStudio();
  try {
    const result = await api("/api/resume/project/save", { method: "POST", body: JSON.stringify({ workspace_id: state.workspace.workspace_id, session_id: state.session.session_id, project: currentResumeProject(), confirm: true }) });
    state.resume.currentProjectId = result.project.project_id;
    state.resume.projects = result.projects || state.resume.projects;
    setResumeStatus("Application project saved");
  } catch (error) { showError(error.message || String(error)); setResumeStatus("Project was not saved"); }
  finally { state.resume.busy = false; renderResumeStudio(); }
}

async function exportResumeFiles() {
  state.resume.busy = true;
  setResumeStatus("Rendering and verifying DOCX, PDF, and text files…");
  renderResumeStudio();
  try {
    const result = await api("/api/resume/export", { method: "POST", body: JSON.stringify({
      workspace_id: state.workspace.workspace_id,
      session_id: state.session.session_id,
      draft: state.resume.draft,
      resume_type: el("resume-type").value,
      template_id: el("resume-template").value,
      job_description: el("resume-job-description").value,
      confirm: true,
    }) });
    state.resume.review = result.review;
    await loadState(state.workspace.workspace_id, state.session.session_id, true);
    setResumeStatus(`${(result.files || []).length} verified files added to HR Department Files`);
  } catch (error) { showError(error.message || String(error)); setResumeStatus("Export failed"); }
  finally { state.resume.busy = false; renderResumeStudio(); }
}

const MUSEUM_PHOTO_ROLES = [
  ["front", "Front overview"], ["back", "Back"], ["signature", "Signature or mark"],
  ["surface_raking_light", "Surface · raking light"], ["edge_support", "Edge or support"],
  ["frame_front", "Frame front"], ["frame_back", "Frame back"], ["label_or_mark", "Label or maker's mark"],
  ["other", "Other view"],
];

function museumSelectedPhotos() {
  return state.files.filter((file) => state.selectedFiles.has(file.file_id) && String(file.content_type || "").startsWith("image/"));
}

function museumFileUrl(file) {
  return artImageContentUrl({ ...file, source_session_id: state.session.session_id });
}

function defaultMuseumRole(file, index) {
  const name = String(file.name || "").toLowerCase();
  if (/sign|mark/.test(name)) return "signature";
  if (/frame.*back|back.*frame/.test(name)) return "frame_back";
  if (/frame/.test(name)) return "frame_front";
  if (/label|stamp/.test(name)) return "label_or_mark";
  if (/back|reverse/.test(name)) return "back";
  if (/edge|side/.test(name)) return "edge_support";
  return index === 0 ? "front" : "other";
}

async function loadMuseumBootstrap() {
  if (!state.workspace || !state.session) return;
  const query = new URLSearchParams({ workspace_id: state.workspace.workspace_id, session_id: state.session.session_id });
  const result = await api(`/api/antiques?${query}`);
  state.museum.loaded = true;
  state.museum.cases = result.cases || [];
  state.museum.settings = result.settings || {};
  state.museum.shoppingMode = result.shopping_mode || { active: false };
  const settings = state.museum.settings;
  el("antiques-fee").value = settings.fee_percent ?? 15;
  el("antiques-shipping").value = settings.packing_shipping_allowance ?? 15;
  el("antiques-reserve").value = settings.uncertainty_reserve_percent ?? 10;
  el("antiques-profit").value = settings.minimum_target_profit ?? 30;
  el("antiques-cap").value = settings.quick_buy_cap_percent ?? 25;
}

function renderMuseumPhotoRoles() {
  const photos = museumSelectedPhotos();
  const container = el("museum-photo-roles");
  container.replaceChildren();
  photos.forEach((file, index) => {
    if (!state.museum.photoRoles[file.file_id]) state.museum.photoRoles[file.file_id] = defaultMuseumRole(file, index);
    const row = document.createElement("label");
    row.className = "museum-photo-role";
    const name = document.createElement("strong");
    name.textContent = file.name || `Photo ${index + 1}`;
    const select = document.createElement("select");
    MUSEUM_PHOTO_ROLES.forEach(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      select.append(option);
    });
    select.value = state.museum.photoRoles[file.file_id];
    select.addEventListener("change", () => { state.museum.photoRoles[file.file_id] = select.value; });
    row.append(name, select);
    container.append(row);
  });
}

function renderMuseumCrop() {
  const photos = museumSelectedPhotos();
  const selector = el("museum-crop-file");
  const prior = state.museum.cropFileId;
  selector.replaceChildren();
  photos.forEach((file) => {
    const option = document.createElement("option");
    option.value = file.file_id;
    option.textContent = file.name;
    selector.append(option);
  });
  state.museum.cropFileId = photos.some((file) => file.file_id === prior) ? prior : (photos[0]?.file_id || "");
  selector.value = state.museum.cropFileId;
  const file = photos.find((row) => row.file_id === state.museum.cropFileId);
  const image = el("museum-crop-image");
  if ((image.dataset.fileId || "") !== (file?.file_id || "")) {
    image.dataset.fileId = file?.file_id || "";
    image.src = file ? museumFileUrl(file) : "";
  }
  const region = state.museum.regions[state.museum.cropFileId]?.[0];
  const box = el("museum-crop-box");
  if (!file || !region || !image.clientWidth) {
    box.hidden = true;
    return;
  }
  const stageRect = el("museum-crop-stage").getBoundingClientRect();
  const imageRect = image.getBoundingClientRect();
  box.hidden = false;
  box.style.left = `${imageRect.left - stageRect.left + region.x * imageRect.width}px`;
  box.style.top = `${imageRect.top - stageRect.top + region.y * imageRect.height}px`;
  box.style.width = `${region.width * imageRect.width}px`;
  box.style.height = `${region.height * imageRect.height}px`;
}

function museumPointerPosition(event) {
  const rect = el("museum-crop-image").getBoundingClientRect();
  return {
    x: Math.min(1, Math.max(0, (event.clientX - rect.left) / Math.max(1, rect.width))),
    y: Math.min(1, Math.max(0, (event.clientY - rect.top) / Math.max(1, rect.height))),
  };
}

function updateMuseumCrop(event, finish = false) {
  if (!state.museum.cropStart || !state.museum.cropFileId) return;
  const current = museumPointerPosition(event);
  const start = state.museum.cropStart;
  const region = {
    label: el("museum-focus").value === "signature" ? "Signature or mark" : "Selected detail",
    x: Math.min(start.x, current.x),
    y: Math.min(start.y, current.y),
    width: Math.abs(start.x - current.x),
    height: Math.abs(start.y - current.y),
  };
  if (region.width >= 0.01 && region.height >= 0.01) state.museum.regions[state.museum.cropFileId] = [region];
  if (finish) state.museum.cropStart = null;
  renderMuseumCrop();
}

function resetItemSelector() {
  if (!state.itemSelector) return;
  window.clearTimeout(state.itemSelector.pollTimer);
  state.itemSelector.sourceFileId = "";
  state.itemSelector.selections = [];
  state.itemSelector.activeSelectionId = "";
  state.itemSelector.interaction = null;
  state.itemSelector.draftRegion = null;
  state.itemSelector.batchId = "";
  state.itemSelector.searchMode = "full";
  state.itemSelector.researchDepth = "quick";
  state.itemSelector.zoom = 1;
  state.itemSelector.activeJob = null;
  state.itemSelector.pollTimer = null;
}

function itemSelectionId() {
  if (window.crypto?.randomUUID) return `selection_${window.crypto.randomUUID().replaceAll("-", "")}`;
  return `selection_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function itemBatchId() {
  if (window.crypto?.randomUUID) return `batch_${window.crypto.randomUUID().replaceAll("-", "")}`;
  return `batch_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function itemSelectorPhotos() {
  return museumSelectedPhotos();
}

function currentItemSelectorPhoto() {
  return itemSelectorPhotos().find((file) => file.file_id === state.itemSelector.sourceFileId) || null;
}

function fitItemSelectorViewport() {
  const stage = el("museum-item-stage");
  const image = el("museum-item-image");
  const viewport = el("museum-item-viewport");
  if (!stage || !image || !viewport || !image.naturalWidth || !image.naturalHeight || !stage.clientWidth || !stage.clientHeight) return false;
  const availableWidth = Math.max(80, stage.clientWidth - 32);
  const availableHeight = Math.max(80, stage.clientHeight - 32);
  const ratio = image.naturalWidth / image.naturalHeight;
  let width = availableWidth;
  let height = width / ratio;
  if (height > availableHeight) {
    height = availableHeight;
    width = height * ratio;
  }
  viewport.style.width = `${Math.max(1, width)}px`;
  viewport.style.height = `${Math.max(1, height)}px`;
  viewport.style.transform = `translate(-50%, -50%) scale(${state.itemSelector.zoom})`;
  return true;
}

function setItemSelectorZoom(value) {
  state.itemSelector.zoom = Math.min(4, Math.max(.5, Number(value) || 1));
  fitItemSelectorViewport();
  el("museum-item-zoom-value").textContent = `${Math.round(state.itemSelector.zoom * 100)}%`;
  renderItemSelector();
}

function itemSelectorPosition(event, allowClamp = false) {
  const image = el("museum-item-image");
  const rect = image.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  const rawX = (event.clientX - rect.left) / rect.width;
  const rawY = (event.clientY - rect.top) / rect.height;
  if (!allowClamp && (rawX < 0 || rawX > 1 || rawY < 0 || rawY > 1)) return null;
  return { x: Math.min(1, Math.max(0, rawX)), y: Math.min(1, Math.max(0, rawY)) };
}

function itemRegionIsLarge(region) {
  const image = el("museum-item-image");
  return Boolean(region && region.width >= .01 && region.height >= .01
    && region.width * image.naturalWidth >= 32 && region.height * image.naturalHeight >= 32);
}

function itemBoxStyle(node, region) {
  const viewportRect = el("museum-item-viewport").getBoundingClientRect();
  const imageRect = el("museum-item-image").getBoundingClientRect();
  node.style.left = `${imageRect.left - viewportRect.left + region.x * imageRect.width}px`;
  node.style.top = `${imageRect.top - viewportRect.top + region.y * imageRect.height}px`;
  node.style.width = `${region.width * imageRect.width}px`;
  node.style.height = `${region.height * imageRect.height}px`;
}

function beginItemInteraction(event, type, selection = null) {
  if (state.itemSelector.activeJob && ["queued", "running", "canceling"].includes(state.itemSelector.activeJob.status)) return;
  const position = itemSelectorPosition(event, type !== "create");
  if (!position) return;
  if (selection) state.itemSelector.activeSelectionId = selection.selection_id;
  state.itemSelector.interaction = {
    type,
    start: position,
    selectionId: selection?.selection_id || "",
    original: selection ? { ...selection.region } : null,
  };
  if (type === "create") state.itemSelector.draftRegion = { x: position.x, y: position.y, width: 0, height: 0 };
}

function updateItemInteraction(event, finish = false) {
  const interaction = state.itemSelector.interaction;
  if (!interaction) return;
  const position = itemSelectorPosition(event, true);
  if (!position) return;
  if (interaction.type === "create") {
    state.itemSelector.draftRegion = {
      x: Math.min(interaction.start.x, position.x),
      y: Math.min(interaction.start.y, position.y),
      width: Math.abs(interaction.start.x - position.x),
      height: Math.abs(interaction.start.y - position.y),
    };
    if (finish && itemRegionIsLarge(state.itemSelector.draftRegion)) {
      if (state.itemSelector.selections.length >= 12) {
        showError("A selection batch can contain at most 12 items.");
      } else {
        const selection = {
          selection_id: itemSelectionId(),
          label: `Item ${state.itemSelector.selections.length + 1}`,
          region: state.itemSelector.draftRegion,
        };
        state.itemSelector.selections.push(selection);
        state.itemSelector.activeSelectionId = selection.selection_id;
      }
    }
  } else {
    const selection = state.itemSelector.selections.find((row) => row.selection_id === interaction.selectionId);
    if (selection) {
      const original = interaction.original;
      if (interaction.type === "move") {
        const dx = position.x - interaction.start.x;
        const dy = position.y - interaction.start.y;
        selection.region = {
          ...original,
          x: Math.min(1 - original.width, Math.max(0, original.x + dx)),
          y: Math.min(1 - original.height, Math.max(0, original.y + dy)),
        };
      } else {
        selection.region = {
          ...original,
          width: Math.max(.001, Math.min(1 - original.x, position.x - original.x)),
          height: Math.max(.001, Math.min(1 - original.y, position.y - original.y)),
        };
      }
      delete selection.status;
      delete selection.error;
      if (finish && !itemRegionIsLarge(selection.region)) selection.region = original;
    }
  }
  if (finish) {
    state.itemSelector.interaction = null;
    state.itemSelector.draftRegion = null;
  }
  renderItemSelector();
}

function cancelItemInteraction() {
  const interaction = state.itemSelector.interaction;
  if (interaction?.selectionId && interaction.original) {
    const selection = state.itemSelector.selections.find((row) => row.selection_id === interaction.selectionId);
    if (selection) selection.region = interaction.original;
  }
  state.itemSelector.interaction = null;
  state.itemSelector.draftRegion = null;
  renderItemSelector();
}

function renderItemCrop(canvas, selection) {
  const image = el("museum-item-image");
  if (!image.complete || !image.naturalWidth) return;
  const context = canvas.getContext("2d");
  const region = selection.region;
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.drawImage(
    image,
    region.x * image.naturalWidth,
    region.y * image.naturalHeight,
    region.width * image.naturalWidth,
    region.height * image.naturalHeight,
    0, 0, canvas.width, canvas.height,
  );
}

function renderItemSelectorJob() {
  const job = state.itemSelector.activeJob;
  const active = job && ["queued", "running", "canceling"].includes(job.status);
  el("museum-item-job-progress").hidden = !job;
  if (job) {
    el("museum-item-job-message").textContent = job.error || job.message || job.status;
    el("museum-item-job-percent").textContent = `${job.progress || 0}%`;
    el("museum-item-job-meter").value = job.progress || 0;
    el("museum-item-job-cancel").hidden = !active;
    el("museum-item-job-progress").classList.toggle("failed", job.status === "failed");
  }
}

function renderItemSelectorResult() {
  const container = el("museum-item-result");
  container.replaceChildren();
  const result = state.itemSelector.activeJob?.result;
  if (!result) return;
  const heading = document.createElement("strong");
  heading.textContent = result.status === "canceled" ? "Search stopped" : result.failed_count ? "Search partly completed" : "Items saved";
  const summary = document.createElement("span");
  summary.textContent = `${result.completed_count || 0} saved · ${result.failed_count || 0} failed · ${result.remaining_count || 0} not started`;
  container.append(heading, summary);
  (result.items || []).filter((item) => item.status === "failed").forEach((item) => {
    const failure = document.createElement("span");
    failure.className = "error";
    failure.textContent = `${item.label}: ${item.error || "Search failed"}`;
    container.append(failure);
  });
}

function renderItemSelector() {
  const photos = itemSelectorPhotos();
  const sourceSelect = el("museum-item-source");
  const prior = state.itemSelector.sourceFileId;
  sourceSelect.replaceChildren();
  photos.forEach((file) => {
    const option = document.createElement("option");
    option.value = file.file_id;
    option.textContent = file.name;
    sourceSelect.append(option);
  });
  state.itemSelector.sourceFileId = photos.some((file) => file.file_id === prior) ? prior : (photos[0]?.file_id || "");
  sourceSelect.value = state.itemSelector.sourceFileId;
  const photo = currentItemSelectorPhoto();
  const image = el("museum-item-image");
  if ((image.dataset.fileId || "") !== (photo?.file_id || "")) {
    image.dataset.fileId = photo?.file_id || "";
    image.src = photo ? museumFileUrl(photo) : "";
  }
  fitItemSelectorViewport();
  el("museum-item-search-mode").value = state.itemSelector.searchMode;
  el("museum-item-depth").value = state.itemSelector.researchDepth;
  el("museum-item-zoom-value").textContent = `${Math.round(state.itemSelector.zoom * 100)}%`;
  el("museum-item-depth").disabled = state.itemSelector.searchMode === "visual_match";
  el("museum-item-count").textContent = `${state.itemSelector.selections.length} of 12 selected`;
  el("museum-item-empty").hidden = Boolean(state.itemSelector.selections.length);
  el("museum-item-undo").disabled = !state.itemSelector.selections.length;
  el("museum-item-clear").disabled = !state.itemSelector.selections.length;

  const overlays = el("museum-item-overlays");
  overlays.replaceChildren();
  if (image.clientWidth) {
    state.itemSelector.selections.forEach((selection, index) => {
      const box = document.createElement("button");
      box.type = "button";
      box.className = `museum-item-box${selection.selection_id === state.itemSelector.activeSelectionId ? " active" : ""}`;
      box.setAttribute("aria-label", `${selection.label}; drag to move`);
      itemBoxStyle(box, selection.region);
      const number = document.createElement("span");
      number.className = "museum-item-box-number";
      number.textContent = String(index + 1);
      const resize = document.createElement("span");
      resize.className = "museum-item-resize";
      resize.setAttribute("aria-hidden", "true");
      resize.addEventListener("pointerdown", (event) => { event.stopPropagation(); beginItemInteraction(event, "resize", selection); });
      box.addEventListener("pointerdown", (event) => { event.stopPropagation(); beginItemInteraction(event, "move", selection); });
      box.append(number, resize);
      overlays.append(box);
    });
    if (state.itemSelector.draftRegion) {
      const draft = document.createElement("span");
      draft.className = "museum-item-box draft";
      itemBoxStyle(draft, state.itemSelector.draftRegion);
      overlays.append(draft);
    }
  }

  const list = el("museum-item-list");
  list.replaceChildren();
  state.itemSelector.selections.forEach((selection, index) => {
    const row = document.createElement("div");
    row.className = `museum-item-row${selection.selection_id === state.itemSelector.activeSelectionId ? " active" : ""}`;
    row.addEventListener("click", () => { state.itemSelector.activeSelectionId = selection.selection_id; renderItemSelector(); });
    const canvas = document.createElement("canvas");
    canvas.width = 140;
    canvas.height = 104;
    renderItemCrop(canvas, selection);
    const label = document.createElement("label");
    label.textContent = `Item ${index + 1}`;
    const input = document.createElement("input");
    input.value = selection.label;
    input.maxLength = 120;
    input.addEventListener("click", (event) => event.stopPropagation());
    input.addEventListener("input", () => { selection.label = input.value.slice(0, 120); delete selection.status; });
    label.append(input);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Delete";
    remove.addEventListener("click", (event) => {
      event.stopPropagation();
      state.itemSelector.selections = state.itemSelector.selections.filter((value) => value.selection_id !== selection.selection_id);
      if (state.itemSelector.activeSelectionId === selection.selection_id) state.itemSelector.activeSelectionId = "";
      renderItemSelector();
    });
    const status = document.createElement("small");
    status.textContent = selection.status === "completed" ? "Saved as a separate case" : selection.status === "failed" ? `Failed · ${selection.error || "retry available"}` : "Ready to search";
    row.append(canvas, label, remove, status);
    list.append(row);
  });
  const activeJob = state.itemSelector.activeJob && ["queued", "running", "canceling"].includes(state.itemSelector.activeJob.status);
  const remaining = state.itemSelector.selections.filter((selection) => selection.status !== "completed");
  el("museum-item-search").disabled = Boolean(activeJob || !remaining.length);
  el("museum-item-search").textContent = state.itemSelector.selections.some((selection) => selection.status === "completed") ? "Retry unfinished items" : "Search selected items";
  renderItemSelectorJob();
  renderItemSelectorResult();
}

function openItemSelector() {
  const photos = itemSelectorPhotos();
  if (!photos.length) {
    showError("Select one image in the file tray, or take a Museum photo first.");
    return;
  }
  resetItemSelector();
  state.itemSelector.sourceFileId = photos[0].file_id;
  state.itemSelector.batchId = itemBatchId();
  el("museum-item-selector-dialog").showModal();
  renderItemSelector();
}

function closeItemSelector() {
  if (el("museum-item-selector-dialog").open) el("museum-item-selector-dialog").close();
}

async function pollItemSelectionJob(jobId) {
  window.clearTimeout(state.itemSelector.pollTimer);
  try {
    const job = await api(`/api/antiques/item-selection/jobs/${encodeURIComponent(jobId)}`);
    state.itemSelector.activeJob = job;
    const itemStatus = new Map((job.result?.items || []).map((item) => [item.selection_id, item]));
    state.itemSelector.selections.forEach((selection) => {
      const result = itemStatus.get(selection.selection_id);
      if (result) {
        selection.status = result.status;
        selection.error = result.error || "";
        selection.caseId = result.case_id || "";
      }
    });
    renderItemSelector();
    if (["queued", "running", "canceling"].includes(job.status)) {
      state.itemSelector.pollTimer = window.setTimeout(() => pollItemSelectionJob(jobId), 900);
      return;
    }
    await loadMuseumBootstrap();
    if (job.result?.completed_count) showToast(`${job.result.completed_count} selected item${job.result.completed_count === 1 ? "" : "s"} saved as separate cases.`);
    renderItemSelector();
  } catch (error) {
    showError(error.message || String(error));
  }
}

async function startItemSelectionSearch() {
  const selections = state.itemSelector.selections.filter((selection) => selection.status !== "completed");
  if (!selections.length || !state.itemSelector.sourceFileId) return;
  let confirmExternal = false;
  if (!state.museum.shoppingMode?.active) {
    confirmExternal = window.confirm(`Send ${selections.length} cropped item image${selections.length === 1 ? "" : "s"} to Google Lens? The full source photo will stay local.`);
    if (!confirmExternal) return;
  }
  try {
    const job = await api("/api/antiques/item-selection/jobs", { method: "POST", body: JSON.stringify({
      workspace_id: state.workspace.workspace_id,
      session_id: state.session.session_id,
      batch_id: state.itemSelector.batchId || itemBatchId(),
      source_file_id: state.itemSelector.sourceFileId,
      search_mode: state.itemSelector.searchMode,
      research_depth: state.itemSelector.researchDepth,
      confirm_external: confirmExternal,
      selections: selections.map((selection) => ({ selection_id: selection.selection_id, label: selection.label.trim() || "Selected item", region: selection.region })),
    }) });
    if (!job.job_id) throw new Error(job.message || "Google Lens confirmation is required");
    state.itemSelector.activeJob = job;
    renderItemSelector();
    pollItemSelectionJob(job.job_id);
  } catch (error) { showError(error.message || String(error)); }
}

function museumEvidenceTitle(file) {
  const metadata = file.metadata?.museum_analysis || {};
  return metadata.label || file.name || "Derived evidence";
}

function appendMuseumList(card, title, values) {
  const rows = (values || []).map((value) => typeof value === "string" ? value : (value.reason || value.role || JSON.stringify(value))).filter(Boolean);
  if (!rows.length) return;
  const heading = document.createElement("strong");
  heading.textContent = title;
  const list = document.createElement("ul");
  rows.forEach((value) => { const item = document.createElement("li"); item.textContent = value; list.append(item); });
  card.append(heading, list);
}

function renderMuseumResult() {
  const container = el("museum-analysis-result");
  container.replaceChildren();
  const report = state.museum.result?.report;
  if (!report) return;
  const summary = document.createElement("section");
  summary.className = "museum-result-card";
  const title = document.createElement("h4");
  title.textContent = report.identification || "Unidentified artwork or object";
  const confidence = document.createElement("p");
  confidence.textContent = `Confidence: ${report.confidence || "low"} · ${report.visual_disclaimer}`;
  summary.append(title, confidence);
  const assessments = [
    ["Medium", report.medium?.assessment], ["Support", report.support?.assessment],
    ["Production", report.production_method?.assessment], ["Signature", report.signature?.application],
    ["Frame", report.frame?.assessment],
  ].filter((row) => row[1]);
  assessments.forEach(([label, value]) => { const line = document.createElement("p"); line.textContent = `${label}: ${value}`; summary.append(line); });
  appendMuseumList(summary, "Visible observations", report.observations);
  appendMuseumList(summary, "Cautious interpretations", report.interpretations);
  appendMuseumList(summary, "Limitations", report.limitations);
  appendMuseumList(summary, "Helpful next photographs", report.recommended_next_photos);
  container.append(summary);
  if (report.signature && (report.signature.transcription_candidates?.length || report.signature.ocr_status !== "not_requested")) {
    const signature = document.createElement("section");
    signature.className = "museum-result-card";
    const heading = document.createElement("h4");
    heading.textContent = "Signature transcription candidates";
    signature.append(heading);
    const ocrStatus = document.createElement("p");
    ocrStatus.textContent = `Optional OCR: ${String(report.signature.ocr_status || "not requested").replaceAll("_", " ")}`;
    signature.append(ocrStatus);
    const readings = (report.signature.transcription_candidates || []).map((candidate) => {
      if (!candidate || typeof candidate !== "object") return String(candidate || "");
      const provenance = [candidate.kind, candidate.source, candidate.confidence && `${candidate.confidence} confidence`]
        .filter(Boolean).join(" · ");
      return provenance ? `${candidate.text} — ${provenance}` : String(candidate.text || "");
    }).filter(Boolean);
    appendMuseumList(signature, "Possible readings", readings);
    appendMuseumList(signature, "Search suggestions", report.signature.query_suggestions);
    appendMuseumList(signature, "Reading limitations", report.signature.limitations);
    container.append(signature);
  }
  if (report.evidence_artifacts?.length) {
    const evidence = document.createElement("section");
    evidence.className = "museum-result-card";
    const heading = document.createElement("h4");
    heading.textContent = "Derived evidence views";
    const grid = document.createElement("div");
    grid.className = "museum-evidence-grid";
    report.evidence_artifacts.slice(0, 24).forEach((file) => {
      const link = document.createElement("a");
      link.href = museumFileUrl(file);
      link.target = "_blank";
      link.rel = "noopener";
      const image = document.createElement("img");
      image.src = link.href;
      image.alt = museumEvidenceTitle(file);
      const label = document.createElement("span");
      label.textContent = museumEvidenceTitle(file);
      link.append(image, label);
      grid.append(link);
    });
    evidence.append(heading, grid);
    container.append(evidence);
  }
}

function renderMuseumJob() {
  const job = state.museum.activeJob;
  const active = job && !["completed", "failed", "canceled"].includes(job.status);
  el("museum-job-progress").hidden = !job;
  if (job) {
    el("museum-job-message").textContent = job.error || job.message || job.status;
    el("museum-job-percent").textContent = `${job.progress || 0}%`;
    el("museum-job-meter").value = job.progress || 0;
    el("museum-job-progress").classList.toggle("failed", job.status === "failed");
    el("museum-job-cancel").hidden = !active;
  }
  el("museum-analysis-start").disabled = Boolean(active);
  renderMuseumResult();
}

function renderMuseumAnalysis() {
  el("museum-analysis-title").textContent = state.museum.mode === "detailed" ? "Detailed visual analysis" : "Quick visual check";
  el("museum-analysis-start").textContent = state.museum.mode === "detailed" ? "Start detailed analysis" : "Start quick check";
  renderMuseumPhotoRoles();
  renderMuseumCrop();
  renderMuseumJob();
}

async function openMuseumAnalysis(mode) {
  const photos = museumSelectedPhotos();
  if (!photos.length) {
    showError("Select at least one image in the file tray, or take Museum photos first.");
    return;
  }
  state.museum.mode = mode === "detailed" ? "detailed" : "quick";
  state.museum.result = null;
  if (!state.museum.cropFileId) state.museum.cropFileId = photos[0].file_id;
  const dialog = el("museum-analysis-dialog");
  if (!dialog.open) dialog.showModal();
  renderMuseumAnalysis();
}

function closeMuseumAnalysis() {
  if (el("museum-analysis-dialog").open) el("museum-analysis-dialog").close();
}

async function pollMuseumJob(jobId) {
  window.clearTimeout(state.museum.pollTimer);
  try {
    const job = await api(`/api/antiques/analysis/jobs/${encodeURIComponent(jobId)}`);
    state.museum.activeJob = job;
    if (job.status === "completed") {
      state.museum.result = job.result;
      await loadMuseumBootstrap();
      renderMuseumAnalysis();
      return;
    }
    if (["failed", "canceled"].includes(job.status)) {
      renderMuseumAnalysis();
      return;
    }
    renderMuseumJob();
    state.museum.pollTimer = window.setTimeout(() => pollMuseumJob(jobId), 900);
  } catch (error) {
    showError(error.message || String(error));
  }
}

async function startMuseumAnalysis() {
  const photos = museumSelectedPhotos();
  if (!photos.length) return;
  const focus = el("museum-focus").value;
  const comparisonPairs = focus === "match" && photos.length > 1
    ? photos.slice(1).map((file) => ({ source_file_id: photos[0].file_id, candidate_file_id: file.file_id }))
    : [];
  state.museum.result = null;
  try {
    const job = await api("/api/antiques/analysis", { method: "POST", body: JSON.stringify({
      workspace_id: state.workspace.workspace_id,
      session_id: state.session.session_id,
      attachment_ids: photos.map((file) => file.file_id),
      mode: state.museum.mode,
      focus,
      notes: el("museum-notes").value.trim(),
      photo_roles: state.museum.photoRoles,
      regions: state.museum.regions,
      comparison_pairs: comparisonPairs,
    }) });
    state.museum.activeJob = job;
    renderMuseumJob();
    pollMuseumJob(job.job_id);
  } catch (error) { showError(error.message || String(error)); }
}

function renderMuseumCases() {
  const container = el("antiques-cases-content");
  container.replaceChildren();
  if (!state.museum.cases.length) {
    const empty = document.createElement("p");
    empty.textContent = "No saved Museum items yet.";
    container.append(empty);
    return;
  }
  state.museum.cases.forEach((item) => {
    const row = document.createElement("div");
    row.className = "antiques-case";
    const title = document.createElement("strong");
    title.textContent = item.title || "Unidentified item";
    const meta = document.createElement("span");
    meta.textContent = `${item.category || "unknown"} · ${item.revisions?.length || 0} revision${item.revisions?.length === 1 ? "" : "s"} · ${readableEmailDate(item.updated_at)}`;
    row.append(title, meta);
    container.append(row);
  });
}

async function openMuseumCases() {
  try {
    await loadMuseumBootstrap();
    renderMuseumCases();
    if (!el("antiques-cases-dialog").open) el("antiques-cases-dialog").showModal();
  } catch (error) { showError(error.message || String(error)); }
}

function closeMuseumCases() {
  if (el("antiques-cases-dialog").open) el("antiques-cases-dialog").close();
}

async function toggleMuseumShoppingMode() {
  const action = state.museum.shoppingMode?.active ? "end" : "start";
  try {
    const result = await api(`/api/antiques/shopping/${action}`, { method: "POST", body: JSON.stringify({ workspace_id: state.workspace.workspace_id, session_id: state.session.session_id }) });
    state.museum.shoppingMode = result.shopping_mode || { active: false };
    renderMuseumTools();
  } catch (error) { showError(error.message || String(error)); }
}

function renderMuseumTools() {
  const isMuseum = state.session?.active_room === "antiques_department";
  const busy = state.sending || state.uploading || state.switchingRoom;
  el("antiques-actions").hidden = !isMuseum;
  ["antiques-camera", "antiques-quick", "antiques-deep", "antiques-select-items", "antiques-cases", "antiques-shopping-toggle"].forEach((id) => { el(id).disabled = busy; });
  el("antiques-shopping-toggle").textContent = state.museum.shoppingMode?.active ? "End shopping mode" : "Start shopping mode";
  el("antiques-mode-label").textContent = state.museum.shoppingMode?.active ? "Shopping-mode consent is active for later external research" : "Visual analysis stays local; external research requires consent";
  if (!isMuseum) {
    closeMuseumAnalysis();
    closeItemSelector();
    closeMuseumCases();
  }
}

function renderResumeTools() {
  const isHr = state.session?.active_room === "hr_department";
  el("resume-actions").hidden = !isHr;
  el("open-resume-studio").disabled = state.sending || state.uploading || state.switchingRoom;
  if (!isHr && el("resume-studio-dialog").open) closeResumeStudio();
}

function renderRoomControl() {
  const selector = el("room-selector");
  selector.replaceChildren();
  state.rooms.forEach((room) => {
    const option = document.createElement("option");
    option.value = room.id;
    option.textContent = `${room.title} · ${room.default_persona}`;
    selector.append(option);
  });
  selector.value = state.session?.active_room || "lobby";
  selector.disabled = state.sending || state.uploading || state.switchingRoom;
}

function renderEmailTools() {
  const actions = el("email-actions");
  actions.hidden = state.session?.active_room !== "my_office";
  el("address-book").disabled = state.sending || state.uploading;
  el("compose-email").disabled = state.sending || state.uploading;
  el("email-attach-button").disabled = state.sending || state.uploading;
  el("email-compose-form").querySelector('[type="submit"]').disabled = state.sending || state.uploading;
  renderEmailAttachments();
  renderDeliveryAlerts();
}

function renderArtTools() {
  const isArtDepartment = state.session?.active_room === "art_department";
  el("art-actions").hidden = !isArtDepartment;
  el("open-art-gallery").disabled = state.sending || state.uploading || state.switchingRoom;
  el("open-art-studio").disabled = state.sending || state.uploading || state.switchingRoom;
  if (!isArtDepartment && el("art-gallery-dialog").open) closeArtGallery();
  if (!isArtDepartment && el("art-studio-dialog").open) closeArtStudio();
  if (el("art-studio-dialog").open) renderArtStudio();
}

function renderAntiquesTools() {
  const active = state.session?.active_room === "antiques_department";
  const actions = el("antiques-actions");
  actions.hidden = !active;
  const shopping = Boolean(state.antiques?.shopping_mode?.active);
  el("antiques-mode-label").textContent = shopping
    ? "Shopping mode active · Google Lens consent continues until ended"
    : "Google Lens photo sharing requires confirmation for each run";
  el("antiques-shopping-toggle").textContent = shopping ? "End shopping mode" : "Start shopping mode";
  ["antiques-camera", "antiques-quick", "antiques-deep", "antiques-cases", "antiques-shopping-toggle"].forEach((id) => {
    el(id).disabled = state.sending || state.uploading || state.switchingRoom;
  });
  if (!active && el("antiques-cases-dialog").open) el("antiques-cases-dialog").close();
}

function priceObservationText(row) {
  const tier = row.match_tier === "same_item_candidate" ? "Same-item candidate" : "Same model / edition";
  const amount = row.amount == null ? "Price unavailable" : `${row.currency || "USD"} ${row.amount}`;
  const basis = String(row.price_basis || row.sale_status || "evidence").replaceAll("_", " ");
  const date = row.sold_at ? String(row.sold_at).split("T", 1)[0] : "date unavailable";
  const venue = row.venue || row.platform || row.source_id || "source";
  const support = row.evidence_status === "supported" ? "source supported" : "limited source evidence";
  return `${tier} · ${amount} · ${basis} · ${date} · ${venue} · ${support}`;
}

function renderEbayTools() {
  el("ebay-actions").hidden = state.session?.active_room !== "ebay";
  el("open-ebay-room").disabled = state.sending || state.uploading || state.switchingRoom;
}

function appendPriceEvidenceGroup(card, headingText, rows) {
  if (!rows.length) return;
  const section = document.createElement("section");
  section.className = "antiques-price-evidence";
  const heading = document.createElement("h4");
  heading.textContent = headingText;
  const list = document.createElement("ul");
  rows.slice(0, 8).forEach((row) => {
    const item = document.createElement("li");
    const label = document.createElement("span");
    label.textContent = priceObservationText(row);
    item.append(label);
    if (row.source_url) {
      const link = document.createElement("a");
      link.href = row.source_url;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = "Open source";
      item.append(link);
    }
    list.append(item);
  });
  section.append(heading, list);
  card.append(section);
}

async function refreshAntiquesCases() {
  const query = new URLSearchParams({
    workspace_id: state.workspace.workspace_id,
    session_id: state.session.session_id,
  });
  state.antiques = await api(`/api/antiques?${query}`);
}

async function pollPriceSearchJob(jobId) {
  window.clearTimeout(state.priceSearch.pollTimer);
  try {
    const job = await api(`/api/antiques/price-search/jobs/${encodeURIComponent(jobId)}`);
    state.priceSearch.activeJob = job;
    if (["completed", "failed", "canceled"].includes(job.status)) {
      if (job.status === "completed") {
        await refreshAntiquesCases();
        const result = job.result || {};
        if (result.status === "similar_approval_required") {
          showToast("No exact match found. You can now choose Search similar.");
        } else if (result.status === "timed_out") {
          showToast("Price search reached its time budget; partial results were not saved.");
        } else {
          showToast(`Price search complete: ${(result.exact_results || []).length} exact, ${(result.similar_results || []).length} similar.`);
        }
      }
      renderAntiquesCases();
      return;
    }
    renderAntiquesCases();
    state.priceSearch.pollTimer = window.setTimeout(() => pollPriceSearchJob(jobId), 900);
  } catch (error) {
    showError(error.message || String(error));
  }
}

async function startPriceSearch(caseId, scope = "exact", preset = "standard") {
  try {
    const job = await api("/api/antiques/price-search", {
      method: "POST",
      body: JSON.stringify({
        workspace_id: state.workspace.workspace_id,
        session_id: state.session.session_id,
        case_id: caseId,
        scope,
        preset,
      }),
    });
    state.priceSearch.activeJob = job;
    renderAntiquesCases();
    pollPriceSearchJob(job.job_id);
  } catch (error) {
    showError(error.message || String(error));
  }
}

function appendPriceSearchControls(card, item) {
  const activeJob = state.priceSearch.activeJob;
  const busy = activeJob && !["completed", "failed", "canceled"].includes(activeJob.status);
  const active = busy && activeJob.item_id === item.case_id;
  const controls = document.createElement("div");
  controls.className = "antiques-price-search-controls";
  const scope = document.createElement("select");
  scope.setAttribute("aria-label", "Price search scope");
  [["exact", "Exact only"], ["all_likeness", "All likeness (exact first)"]].forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    scope.append(option);
  });
  const preset = document.createElement("select");
  preset.setAttribute("aria-label", "Price search depth");
  [["fast", "Fast"], ["standard", "Standard"], ["extended", "Extended"]].forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    option.selected = value === "standard";
    preset.append(option);
  });
  const run = document.createElement("button");
  run.type = "button";
  run.textContent = "Find prices";
  run.disabled = Boolean(busy);
  run.addEventListener("click", () => startPriceSearch(item.case_id, scope.value, preset.value));
  controls.append(scope, preset, run);
  if (active) {
    const progress = document.createElement("span");
    progress.textContent = `${activeJob.progress || 0}% · ${activeJob.message || activeJob.status}`;
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.textContent = "Cancel";
    cancel.addEventListener("click", async () => {
      state.priceSearch.activeJob = await api(`/api/antiques/price-search/jobs/${encodeURIComponent(activeJob.job_id)}/cancel`, {
        method: "POST",
        body: "{}",
      });
      renderAntiquesCases();
    });
    controls.append(progress, cancel);
  } else if (activeJob && activeJob.item_id === item.case_id && activeJob.status === "failed") {
    const failure = document.createElement("span");
    failure.className = "error";
    failure.textContent = activeJob.error || activeJob.message || "Price search failed";
    controls.append(failure);
  }
  card.append(controls);
}

function renderAntiquesCases() {
  const container = el("antiques-cases-content");
  container.replaceChildren();
  const cases = state.antiques?.cases || [];
  const settings = state.antiques?.settings || {};
  el("antiques-fee").value = settings.fee_percent ?? 15;
  el("antiques-shipping").value = settings.packing_shipping_allowance ?? 15;
  el("antiques-reserve").value = settings.uncertainty_reserve_percent ?? 10;
  el("antiques-profit").value = settings.minimum_target_profit ?? 30;
  el("antiques-cap").value = settings.quick_buy_cap_percent ?? 25;
  if (!cases.length) {
    const empty = document.createElement("p");
    empty.textContent = "No researched items yet. Attach photos and ask Leo for quick research.";
    container.append(empty);
    return;
  }
  cases.forEach((item) => {
    const card = document.createElement("article");
    card.className = "antiques-case-card";
    const heading = document.createElement("div");
    const title = document.createElement("strong");
    const meta = document.createElement("small");
    const report = item.latest_report || {};
    const valuation = report.valuation || {};
    const buying = report.buying || {};
    const priceEvaluation = report.price_evaluation || {};
    const priceSearch = report.price_search || {};
    const expected = priceEvaluation.expected_resale || {};
    const evidenceSummary = priceEvaluation.evidence_summary || {};
    const exactResults = Array.isArray(priceEvaluation.exact_results) ? priceEvaluation.exact_results : [];
    title.textContent = item.title || "Unidentified item";
    meta.textContent = `${item.category || "unknown"} · ${report.confidence || "low"} confidence · ${(item.revisions || []).length} report(s)`;
    heading.append(title, meta);
    const facts = document.createElement("p");
    const rangeLow = Object.hasOwn(expected, "low") ? expected.low : valuation.conservative_low;
    const rangeHigh = Object.hasOwn(expected, "high") ? expected.high : valuation.likely_high;
    const rangeCurrency = expected.currency || valuation.currency || "USD";
    const range = rangeLow == null
      ? "Expected resale not established"
      : `Expected resale ${rangeCurrency} ${rangeLow}–${rangeHigh ?? "?"}`;
    const maxBuy = buying.recommended_max_buy == null ? "Max buy withheld" : `Max buy ${buying.currency || "USD"} ${buying.recommended_max_buy}`;
    facts.textContent = `${range} · ${maxBuy}`;
    const evidence = document.createElement("p");
    evidence.className = "antiques-price-summary";
    evidence.textContent = `${evidenceSummary.exact || 0} exact · ${evidenceSummary.exact_sold || 0} exact sold · ${evidenceSummary.exact_active_asking || 0} exact active asking`;
    const notes = document.createElement("p");
    notes.textContent = [report.artist_or_maker, report.medium_or_material, report.frame?.assessment].filter(Boolean).join(" · ") || "Open the related chat entry for full evidence.";
    const deepen = document.createElement("button");
    deepen.type = "button";
    deepen.textContent = "Deepen research";
    deepen.addEventListener("click", async () => {
      const available = new Set(state.files.map((file) => file.file_id));
      state.selectedFiles = new Set((item.attachment_ids || []).filter((fileId) => available.has(fileId)));
      if (!state.selectedFiles.size) {
        showError("Reattach this item’s photos in the current session before deep research.");
        return;
      }
      el("antiques-cases-dialog").close();
      await startAntiquesResearch("deep", item.case_id);
    });
    card.append(heading, facts, evidence, notes);
    appendPriceEvidenceGroup(card, "Exact sold evidence", exactResults.filter((row) => row.sale_status === "sold"));
    appendPriceEvidenceGroup(card, "Exact asking and estimate context", exactResults.filter((row) => row.sale_status !== "sold"));
    if (priceSearch.scope === "all_likeness") {
      const similarResults = Array.isArray(priceEvaluation.similar_candidates) ? priceEvaluation.similar_candidates : [];
      appendPriceEvidenceGroup(card, "Similar results (not used for exact valuation)", similarResults);
    }
    if (!exactResults.length) {
      const prompt = document.createElement("p");
      prompt.className = "antiques-similar-prompt";
      prompt.textContent = priceEvaluation.similar_search_prompt || "No exact match found. Search similar items?";
      card.append(prompt);
      const similar = document.createElement("button");
      similar.type = "button";
      similar.textContent = "Search similar (exact first)";
      similar.disabled = Boolean(state.priceSearch.activeJob && !["completed", "failed", "canceled"].includes(state.priceSearch.activeJob.status));
      similar.addEventListener("click", () => startPriceSearch(item.case_id, "all_likeness", "standard"));
      card.append(similar);
    }
    appendPriceSearchControls(card, item);
    card.append(deepen);
    container.append(card);
  });
}

async function toggleAntiquesShoppingMode() {
  const active = Boolean(state.antiques?.shopping_mode?.active);
  try {
    const result = await api(`/api/antiques/shopping/${active ? "end" : "start"}`, {
      method: "POST",
      body: JSON.stringify({ workspace_id: state.workspace.workspace_id, session_id: state.session.session_id }),
    });
    state.antiques.shopping_mode = result.shopping_mode;
    showToast(active ? "Shopping mode ended" : "Shopping mode active for this Antiques session");
    render();
  } catch (error) { showError(error.message || String(error)); }
}

async function startAntiquesResearch(mode, caseId = "") {
  const photos = state.files.filter((file) => state.selectedFiles.has(file.file_id) && String(file.content_type || "").startsWith("image/"));
  if (!photos.length) {
    showError("Take or attach at least one item photo, then select it for Leo.");
    return;
  }
  let confirmExternal = false;
  if (!state.antiques?.shopping_mode?.active) {
    confirmExternal = window.confirm(`Send sanitized copies of ${photos.length} selected photo${photos.length === 1 ? "" : "s"} to Google Lens for this research run?`);
    if (!confirmExternal) return;
  }
  await sendMessage(`Leo, ${mode} research this thrift-store item. Identify signatures or marks, medium or material, condition, frame value, sold comparables, and a conservative maximum buy.`, {
    attachments: photos,
    confirmExternal,
    antiquesCaseId: caseId,
  });
}

function renderRoomFileTools() {
  const room = currentRoom();
  const hasFileLibrary = Boolean(room && !["lobby", "art_department"].includes(room.id));
  el("room-file-actions").hidden = !hasFileLibrary;
  el("room-file-action-title").textContent = room ? `${room.title} files` : "Room files";
  el("open-room-files").disabled = state.sending || state.uploading || state.switchingRoom;
  if (!hasFileLibrary && el("room-file-dialog").open) closeRoomFileLibrary();
}

function renderGovernance() {
  const governance = state.governance || {};
  const navigator = governance.navigator || {};
  el("governance-navigator-state").textContent = `${navigator.status || "ACTIVE"} · monitoring every room`;
  el("governance-source").textContent = governance.registry_path || "Governance registry unavailable";
  el("governance-snapshot").textContent = governance.registry_version
    ? `v${governance.registry_version} · SHA-256 ${governance.registry_sha256 || "unavailable"}`
    : "Unavailable";
  el("governance-memos").textContent = String(governance.persistent_memo_count || 0);
  el("governance-incident").textContent = governance.latest_incident?.incident_id || "None";

  const workspaceGates = el("governance-workspace-gates");
  workspaceGates.replaceChildren();
  Object.entries(governance.workspace_gates || {}).forEach(([name, enabled]) => {
    const chip = document.createElement("span");
    chip.className = `gate-chip ${enabled ? "enabled" : "disabled"}`;
    chip.textContent = `${name} · ${enabled ? "ON" : "OFF"}`;
    workspaceGates.append(chip);
  });

  const hardGates = el("governance-hard-gates");
  hardGates.replaceChildren();
  (governance.gates || []).forEach((gate) => {
    const row = document.createElement("div");
    const title = document.createElement("strong");
    const detail = document.createElement("span");
    title.textContent = `${gate.id} · ${gate.applicability}`;
    detail.textContent = gate.definition || "";
    row.append(title, detail);
    hardGates.append(row);
  });

  const governanceProposals = el("governance-proposals");
  governanceProposals.replaceChildren();
  const pending = (state.administration?.proposals || []).filter((proposal) =>
    ["awaiting_approval", "awaiting_second_approval"].includes(proposal.status));
  if (!pending.length) {
    const row = document.createElement("div");
    row.textContent = "No changes awaiting approval.";
    governanceProposals.append(row);
  } else {
    pending.slice(0, 8).forEach((proposal) => {
      const row = document.createElement("div");
      const title = document.createElement("strong");
      const detail = document.createElement("span");
      title.textContent = `${proposal.kind.toUpperCase()} · ${proposal.action}`;
      detail.textContent = `${proposal.proposal_id} · ${proposal.status.replaceAll("_", " ")}`;
      row.append(title, detail);
      governanceProposals.append(row);
    });
  }

  const provenance = el("governance-provenance");
  provenance.replaceChildren();
  (governance.provenance || []).forEach((path) => {
    const row = document.createElement("div");
    row.textContent = path;
    provenance.append(row);
  });
}

const ADMIN_ACTIONS = {
  room: ["create", "update", "archive", "restore"],
  rule: ["add", "amend", "disable", "restore"],
  gate: ["add", "amend", "disable", "restore"],
  program: ["change"],
};

function adminProposalSummary(proposal) {
  const payload = proposal.payload || {};
  if (proposal.kind === "room") return payload.title || payload.target_id || "Room change";
  if (["rule", "gate"].includes(proposal.kind)) return payload.id || payload.target_id || "Governance change";
  return payload.title || "Program change";
}

function updateAdministrationForm() {
  const kind = el("admin-kind").value;
  const actionSelect = el("admin-action");
  const previous = actionSelect.value;
  actionSelect.replaceChildren();
  (ADMIN_ACTIONS[kind] || []).forEach((action) => {
    const option = document.createElement("option");
    option.value = action;
    option.textContent = action[0].toUpperCase() + action.slice(1);
    actionSelect.append(option);
  });
  if ([...(ADMIN_ACTIONS[kind] || [])].includes(previous)) actionSelect.value = previous;
  const action = actionSelect.value;
  const creating = (kind === "room" && action === "create") || kind === "program";
  const adding = ["rule", "gate"].includes(kind) && action === "add";
  el("admin-title-field").hidden = !creating;
  el("admin-target-field").hidden = creating || adding;
  el("admin-persona-field").hidden = !(kind === "room" && action === "create");
  el("admin-statement-field").hidden = ["archive", "restore", "disable"].includes(action);
  el("admin-reason-field").hidden = action !== "disable";
  el("admin-paths-field").hidden = kind !== "program";
  el("admin-tests-field").hidden = kind !== "program";
}

function renderAdministration() {
  const administration = state.administration || {};
  const infrastructureActive = state.session?.active_room === "infrastructure_room";
  [...el("admin-kind").options].forEach((option) => {
    if (["room", "program"].includes(option.value)) option.disabled = !infrastructureActive;
  });
  if (!infrastructureActive && ["room", "program"].includes(el("admin-kind").value)) el("admin-kind").value = "rule";
  const versions = administration.versions || {};
  el("admin-room-version").textContent = `v${versions.room_catalog || 1}`;
  el("admin-governance-version").textContent = `v${versions.governance || 1}`;
  el("open-administration").hidden = !infrastructureActive;
  const list = el("administration-proposal-list");
  list.replaceChildren();
  const proposals = administration.proposals || [];
  if (!proposals.length) {
    const empty = document.createElement("p");
    empty.textContent = "No administrative proposals yet.";
    list.append(empty);
  }
  proposals.forEach((proposal) => {
    const row = document.createElement("article");
    row.className = "administration-proposal";
    const head = document.createElement("div");
    head.className = "administration-proposal-head";
    const title = document.createElement("strong");
    title.textContent = adminProposalSummary(proposal);
    const status = document.createElement("span");
    status.textContent = proposal.status.replaceAll("_", " ");
    head.append(title, status);
    const detail = document.createElement("p");
    detail.textContent = `${proposal.kind} · ${proposal.action} · ${proposal.risk_level} risk · ${proposal.approvals_received || 0}/${proposal.approvals_required || 1} approvals`;
    const id = document.createElement("code");
    id.textContent = proposal.proposal_id;
    row.append(head, detail, id);
    const findings = proposal.navigator?.findings || [];
    if (findings.length) {
      const impact = document.createElement("p");
      impact.textContent = `Navigator: ${findings.join(" ")}`;
      row.append(impact);
    }
    const actions = document.createElement("div");
    actions.className = "administration-proposal-actions";
    if (["awaiting_approval", "awaiting_second_approval"].includes(proposal.status)) {
      const approve = document.createElement("button");
      approve.type = "button";
      approve.dataset.adminAction = "approve";
      approve.dataset.proposalId = proposal.proposal_id;
      approve.dataset.expectedVersion = String(proposal.base_version || 0);
      approve.textContent = proposal.status === "awaiting_second_approval" ? "Confirm again" : "Approve";
      const reject = document.createElement("button");
      reject.type = "button";
      reject.className = "danger";
      reject.dataset.adminAction = "reject";
      reject.dataset.proposalId = proposal.proposal_id;
      reject.textContent = "Reject";
      actions.append(approve, reject);
    }
    if (proposal.status === "verified") {
      const rollback = document.createElement("button");
      rollback.type = "button";
      rollback.className = "danger";
      rollback.dataset.adminAction = "rollback";
      rollback.dataset.proposalId = proposal.proposal_id;
      rollback.textContent = "Rollback";
      actions.append(rollback);
    }
    row.append(actions);
    list.append(row);
  });
  const auditList = el("administration-audit-list");
  auditList.replaceChildren();
  [...(administration.audit || [])].reverse().slice(0, 12).forEach((event) => {
    const row = document.createElement("div");
    row.className = "administration-audit-row";
    const time = document.createElement("time");
    time.textContent = new Date(event.timestamp).toLocaleString();
    const text = document.createElement("span");
    text.textContent = `${event.event.replaceAll("_", " ")} · ${event.proposal_id}`;
    row.append(time, text);
    auditList.append(row);
  });
  updateAdministrationForm();
}

function renderRoute() {
  const status = el("route-status");
  if (state.sending) {
    status.className = "route-status checking";
    el("route-model").textContent = state.stopping ? "Stopping active request" : "Checking governed route";
    el("route-meta").textContent = state.stopping
      ? "Cancelling browser and model work"
      : "Matching room control, task, model, and reasoning level";
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
  const deterministic = ["veridex_router", "veridex_governance", "veridex_admin", "veridex_google_router", "veridex_gmail_router", "veridex_antiques_router"].includes(state.route.provider);
  el("route-model").textContent = deterministic
    ? `Veridex · deterministic ${state.route.task_type.replaceAll("_", " ")}`
    : `Codex CLI · ${state.route.model}`;
  el("route-meta").textContent = `${state.route.reasoning_effort} reasoning · ${state.route.task_type.replaceAll("_", " ")}`;
  el("route-notice").textContent = state.route.notice;
}

function render() {
  el("workspace-name").textContent = state.workspace?.label || "Workspace";
  el("session-title").textContent = state.session?.title || "New session";
  const fullAccess = state.runtime.access_mode === "full";
  el("access-status").className = `access-status ${fullAccess ? "full" : "read-only"}`;
  el("access-label").textContent = state.runtime.access_label || (fullAccess ? "Full computer access" : "Read-only computer access");
  el("composer-note").textContent = fullAccess
    ? "Full computer access · Codex can search and work with local files · transcripts stay here"
    : "Read-only computer access · attach files or restart normally for full access · transcripts stay here";
  const sendButton = el("send-button");
  sendButton.disabled = state.uploading || state.stopping;
  sendButton.classList.toggle("stop-button", state.sending);
  sendButton.replaceChildren();
  if (state.sending) {
    const glyph = document.createElement("span");
    glyph.className = "stop-glyph";
    glyph.setAttribute("aria-hidden", "true");
    sendButton.append(glyph);
    sendButton.setAttribute("aria-label", state.stopping ? "Stopping response" : "Stop response");
    sendButton.title = state.stopping ? "Stopping response" : "Stop response";
  } else {
    sendButton.textContent = "Send";
    sendButton.setAttribute("aria-label", "Send message");
    sendButton.title = "Send message";
  }
  el("message-input").disabled = state.sending || state.uploading;
  el("attach-button").disabled = state.sending || state.uploading;
  el("open-marketplace-sell").disabled = state.sending || state.uploading || state.switchingRoom;
  const canRead = "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
  const autoRead = el("auto-read");
  autoRead.checked = state.autoRead;
  autoRead.disabled = !canRead;
  const voiceInput = el("voice-input");
  voiceInput.disabled = state.sending || state.uploading || !SpeechRecognitionApi;
  voiceInput.classList.toggle("listening", state.listening);
  voiceInput.setAttribute("aria-pressed", String(state.listening));
  voiceInput.setAttribute("aria-label", state.listening ? "Stop dictation" : "Dictate a message");
  voiceInput.title = SpeechRecognitionApi
    ? (state.listening ? "Stop dictation" : "Dictate a message")
    : "Dictation requires Chrome or Edge";
  renderRoomControl();
  renderEbayTools();
  renderEmailTools();
  renderArtTools();
  renderMuseumTools();
  renderAnimationTools();
  renderRoomFileTools();
  renderResumeTools();
  renderGovernance();
  renderAdministration();
  renderNavigation();
  renderMessages();
  renderFiles();
  renderRoute();
  renderImportantMailIndicator();
  renderNancyImportantMail();
}

function accountRequestBody(extra = {}) {
  return JSON.stringify({
    workspace_id: state.workspace?.workspace_id || "",
    session_id: state.session?.session_id || "",
    ...extra,
  });
}

function renderConnectedAccounts() {
  const value = state.connectedAccounts || {};
  const instagram = value.instagram || {};
  const facebook = value.facebook || {};
  const gmail = value.gmail || {};
  const ebay = value.ebay || {};
  const ebayNotifications = ebay.notifications || {};
  const sharedGmail = value.shared?.gmail || {};
  el("connected-accounts-workspace").textContent = `${state.workspace?.label || "This workspace"} · isolated workspace accounts + shared corporate services`;

  const sharedGmailState = el("shared-gmail-connection-state");
  sharedGmailState.className = `account-state ${sharedGmail.connected ? "connected" : sharedGmail.configured ? "attention" : ""}`;
  sharedGmailState.textContent = sharedGmail.connected ? "Available everywhere" : sharedGmail.configured ? "Needs attention" : "Not configured";
  el("shared-gmail-active-account").hidden = !sharedGmail.account_email;
  el("shared-gmail-active-account").textContent = sharedGmail.account_email
    ? `Shared corporate account: ${sharedGmail.account_email}`
    : "";
  if (sharedGmail.oauth_error) el("connected-accounts-message").textContent = `Veridex corporate Gmail failed: ${sharedGmail.oauth_error}`;

  const instagramState = el("instagram-connection-state");
  instagramState.className = `account-state ${instagram.connected ? "connected" : instagram.assigned ? "attention" : ""}`;
  instagramState.textContent = instagram.connected ? "Connected" : instagram.assigned ? "Needs attention" : "Not connected";
  el("instagram-username").value = instagram.username || "";
  el("instagram-active-account").hidden = !instagram.assigned;
  el("instagram-active-account").textContent = instagram.connected
    ? `Active for this workspace: @${instagram.username}`
    : instagram.assigned ? `Assigned here: @${instagram.username} · sign-in not yet verified` : "";
  el("instagram-disconnect").hidden = !instagram.assigned;

  const facebookState = el("facebook-connection-state");
  facebookState.className = `account-state ${facebook.connected ? "connected" : facebook.configured ? "attention" : ""}`;
  facebookState.textContent = facebook.connected ? "Connected" : facebook.configured ? "Needs attention" : "Not configured";
  el("facebook-active-account").hidden = !facebook.username && !facebook.connected;
  el("facebook-active-account").textContent = facebook.connected
    ? `Dedicated Facebook session is active${facebook.username ? ` · configured login: ${facebook.username}` : ""}`
    : facebook.username ? `Configured login: ${facebook.username} · sign-in not yet verified` : "";
  el("facebook-connect").disabled = !facebook.configured;
  if (facebook.error) el("connected-accounts-message").textContent = `Facebook connection failed: ${facebook.error}`;

  const gmailState = el("gmail-connection-state");
  gmailState.className = `account-state ${gmail.connected ? "connected" : gmail.assigned ? "attention" : ""}`;
  gmailState.textContent = gmail.connected ? "Connected" : gmail.assigned ? "Needs attention" : "Not connected";
  el("gmail-active-account").hidden = !gmail.assigned;
  el("gmail-active-account").textContent = gmail.connected
    ? `Active for this workspace: ${gmail.account_email}`
    : gmail.assigned ? `Assigned here: ${gmail.account_email || "Google account"} · authorization incomplete` : "";
  if (gmail.oauth_error) el("connected-accounts-message").textContent = `Google connection failed: ${gmail.oauth_error}`;
  el("gmail-disconnect").hidden = !gmail.assigned;

  const ebayState = el("ebay-connection-state");
  ebayState.className = `account-state ${ebay.connected ? "connected" : ebay.assigned ? "attention" : ""}`;
  ebayState.textContent = ebay.connected ? "Connected" : ebay.assigned ? "Needs attention" : "Not connected";
  el("ebay-username").value = ebay.username || "";
  el("ebay-environment").value = ebay.environment || "sandbox";
  el("ebay-marketplace").value = ebay.marketplace_id || "EBAY_US";
  el("ebay-active-account").hidden = !ebay.assigned;
  el("ebay-active-account").textContent = ebay.connected
    ? `Active for this workspace: ${ebay.username} · ${ebay.environment} · ${ebay.marketplace_id}`
    : ebay.assigned ? `Assigned here: ${ebay.username || "eBay seller"} · authorization incomplete` : "";
  const ebayNotificationStatus = el("ebay-notification-status");
  ebayNotificationStatus.hidden = !ebay.assigned;
  const automaticNotifications = ebayNotifications.automatic || {};
  if (ebayNotifications.configured) {
    const workspaceAutoEnabled = automaticNotifications.workspace_enabled !== false;
    const pollState = !workspaceAutoEnabled
      ? "automatic checks turned off for this workspace"
      : automaticNotifications.running
        ? `automatic checks every ${Number(automaticNotifications.interval_seconds || 60)} seconds`
        : automaticNotifications.enabled ? "automatic checks starting" : "automatic checks unavailable";
    const lastPoll = automaticNotifications.last_completed_at
      ? ` · last checked ${new Date(automaticNotifications.last_completed_at).toLocaleString()}`
      : "";
    ebayNotificationStatus.textContent = `Notification relay ready · ${pollState}${lastPoll} · ${Number(ebayNotifications.seller_alerts || 0)} stored seller alert${Number(ebayNotifications.seller_alerts || 0) === 1 ? "" : "s"}`;
  } else {
    ebayNotificationStatus.textContent = `Notification relay needs attention${ebayNotifications.error ? ` · ${ebayNotifications.error}` : ""}`;
  }
  if (ebay.oauth_error) el("connected-accounts-message").textContent = `eBay connection failed: ${ebay.oauth_error}`;
  el("ebay-disconnect").hidden = !ebay.assigned;
  const ebayAutomaticButton = el("ebay-notifications-auto");
  ebayAutomaticButton.hidden = !ebay.assigned;
  ebayAutomaticButton.textContent = automaticNotifications.workspace_enabled === false
    ? "Turn on automatic checks"
    : "Turn off automatic checks";
  el("ebay-notifications-check").hidden = !ebay.assigned;
  el("open-connected-accounts").classList.toggle("has-connection", Boolean(sharedGmail.connected || instagram.connected || facebook.connected || gmail.connected || ebay.connected));
}

function connectedAccountsError(value = {}) {
  const sharedGmail = value.shared?.gmail || {};
  const facebook = value.facebook || {};
  const instagram = value.instagram || {};
  const gmail = value.gmail || {};
  const ebay = value.ebay || {};
  if (sharedGmail.oauth_error) return `Veridex corporate Gmail failed: ${sharedGmail.oauth_error}`;
  if (facebook.error) return `Facebook connection failed: ${facebook.error}`;
  if (instagram.error) return `Instagram connection failed: ${instagram.error}`;
  if (gmail.oauth_error) return `Google connection failed: ${gmail.oauth_error}`;
  if (ebay.oauth_error) return `eBay connection failed: ${ebay.oauth_error}`;
  return "";
}

async function refreshConnectedAccounts(message = "") {
  if (!state.workspace || !state.session) return;
  const query = new URLSearchParams({ workspace_id: state.workspace.workspace_id, session_id: state.session.session_id });
  state.connectedAccounts = await api(`/api/integrations?${query}`);
  renderConnectedAccounts();
  el("connected-accounts-message").textContent = connectedAccountsError(state.connectedAccounts) || message;
}

async function openConnectedAccounts() {
  el("connected-accounts-message").textContent = "Checking this workspace’s account assignments…";
  el("connected-accounts-dialog").showModal();
  try { await refreshConnectedAccounts(); }
  catch (error) { el("connected-accounts-message").textContent = error.message || String(error); }
}

async function connectInstagram(event) {
  event.preventDefault();
  const button = event.submitter || event.currentTarget.querySelector("button[type=submit]");
  button.disabled = true;
  el("connected-accounts-message").textContent = "Opening the dedicated Instagram session for this workspace…";
  try {
    await api("/api/integrations/instagram/connect", { method: "POST", body: accountRequestBody({ username: el("instagram-username").value.trim() }) });
    await refreshConnectedAccounts("Sign in directly on Instagram in the opened Chrome window, then refresh status here.");
  } catch (error) { el("connected-accounts-message").textContent = error.message || String(error); }
  finally { button.disabled = false; }
}

async function connectFacebook() {
  const button = el("facebook-connect");
  button.disabled = true;
  el("connected-accounts-message").textContent = "Checking the dedicated Facebook sessionâ€¦";
  try {
    const result = await api("/api/integrations/facebook/connect", { method: "POST", body: accountRequestBody() });
    const needsInteraction = Boolean(result.facebook?.requires_interaction || !result.facebook?.connected);
    await refreshConnectedAccounts(needsInteraction
      ? "Complete Facebook's security prompt in the dedicated Chrome window, then refresh status."
      : "The dedicated Facebook session is connected.");
  } catch (error) { el("connected-accounts-message").textContent = error.message || String(error); }
  finally { button.disabled = false; }
}

async function integrationAction(path, message) {
  el("connected-accounts-message").textContent = "Working…";
  try {
    await api(path, { method: "POST", body: accountRequestBody() });
    await refreshConnectedAccounts(message);
  } catch (error) { el("connected-accounts-message").textContent = error.message || String(error); }
}

async function connectGmail() {
  el("connected-accounts-message").textContent = "Opening Google authorization in your browser…";
  try {
    await api("/api/integrations/gmail/connect", { method: "POST", body: accountRequestBody({ account_email: el("gmail-account-email").value.trim() }) });
    const email = el("gmail-account-email").value.trim();
    el("connected-accounts-message").textContent = `Complete Google authorization in the opened browser, then choose Refresh status.${email ? ` If Google shows 403 access_denied, add ${email} under Google Auth Platform → Audience → Test users.` : ""}`;
  } catch (error) { el("connected-accounts-message").textContent = error.message || String(error); }
}

async function connectEbay() {
  el("connected-accounts-message").textContent = "Opening eBay authorization in your browser…";
  try {
    await api("/api/integrations/ebay/connect", {
      method: "POST",
      body: accountRequestBody({
        username: el("ebay-username").value.trim(),
        environment: el("ebay-environment").value,
        marketplace_id: el("ebay-marketplace").value.trim() || "EBAY_US",
      }),
    });
    el("connected-accounts-message").textContent = "Complete eBay authorization in the opened browser, then choose Refresh status.";
  } catch (error) { el("connected-accounts-message").textContent = error.message || String(error); }
}

async function checkEbayNotifications() {
  const button = el("ebay-notifications-check");
  button.disabled = true;
  el("connected-accounts-message").textContent = "Checking the workspace’s verified eBay notification queue…";
  try {
    const result = await api("/api/integrations/ebay/notifications/check", {
      method: "POST",
      body: accountRequestBody({ max_events: 100 }),
    });
    const notifications = result.notifications || {};
    const alerts = Number((notifications.alerts || []).length);
    const compliance = Number(notifications.compliance_events || 0);
    const errors = Number((notifications.errors || []).length);
    const parts = [
      `${Number(notifications.acknowledged || 0)} queue event${Number(notifications.acknowledged || 0) === 1 ? "" : "s"} safely stored and acknowledged`,
      `${alerts} new seller alert${alerts === 1 ? "" : "s"}`,
    ];
    if (compliance) parts.push(`${compliance} account-deletion event${compliance === 1 ? "" : "s"} processed without retaining raw user data`);
    if (errors) parts.push(`${errors} event${errors === 1 ? "" : "s"} left unacknowledged because processing failed`);
    await refreshConnectedAccounts(`${parts.join(" · ")}.`);
  } catch (error) {
    el("connected-accounts-message").textContent = error.message || String(error);
  } finally {
    button.disabled = false;
  }
}

async function toggleEbayAutomaticNotifications() {
  const button = el("ebay-notifications-auto");
  const automatic = state.connectedAccounts?.ebay?.notifications?.automatic || {};
  const enabled = automatic.workspace_enabled === false;
  button.disabled = true;
  el("connected-accounts-message").textContent = `${enabled ? "Turning on" : "Turning off"} automatic eBay checks…`;
  try {
    await api("/api/integrations/ebay/notifications/automatic", {
      method: "POST",
      body: accountRequestBody({ enabled }),
    });
    await refreshConnectedAccounts(
      enabled
        ? "Automatic eBay checks are on for this workspace. An immediate check was requested."
        : "Automatic eBay checks are off for this workspace. Check now remains available."
    );
  } catch (error) {
    el("connected-accounts-message").textContent = error.message || String(error);
  } finally {
    button.disabled = false;
  }
}

function marketplaceRequestBody(extra = {}) {
  return JSON.stringify({
    workspace_id: state.workspace?.workspace_id,
    session_id: state.session?.session_id,
    ...extra,
  });
}

function applyMarketplaceBootstrap(value) {
  state.marketplace.drafts = value.drafts || [];
  state.marketplace.groups = value.groups || [];
  state.marketplace.cases = value.cases || [];
  state.marketplace.images = value.images || [];
  state.marketplace.loaded = true;
  if (value.draft?.draft_id) state.marketplace.currentDraftId = value.draft.draft_id;
}

function marketplaceDraft() {
  return state.marketplace.drafts.find((row) => row.draft_id === state.marketplace.currentDraftId) || null;
}

function marketplaceImageUrl(image) {
  return `/api/files/content?${new URLSearchParams({
    workspace_id: state.workspace.workspace_id,
    session_id: image.session_id || state.session.session_id,
    file_id: image.file_id,
  })}`;
}

function clearMarketplaceForm() {
  state.marketplace.currentDraftId = "";
  state.marketplace.selectedPhotoIds.clear();
  state.marketplace.selectedGroupIds.clear();
  el("marketplace-source-case").value = "";
  el("marketplace-title").value = "";
  el("marketplace-price").value = "";
  el("marketplace-category").value = "";
  el("marketplace-condition").value = "good";
  el("marketplace-description").value = "";
  state.marketplace.notice = "New local draft";
  renderMarketplace();
}

function loadMarketplaceDraft(draft) {
  if (!draft) return clearMarketplaceForm();
  state.marketplace.currentDraftId = draft.draft_id;
  state.marketplace.selectedPhotoIds = new Set((draft.photos || []).map((row) => row.file_id));
  state.marketplace.selectedGroupIds = new Set(draft.group_ids || []);
  el("marketplace-source-case").value = draft.source_case_id || "";
  el("marketplace-title").value = draft.title || "";
  el("marketplace-price").value = draft.price ?? "";
  el("marketplace-category").value = draft.category || "";
  el("marketplace-condition").value = draft.condition || "good";
  el("marketplace-description").value = draft.description || "";
  state.marketplace.notice = draft.last_error || "";
  renderMarketplace();
}

function applyMarketplaceCase(caseId) {
  const item = state.marketplace.cases.find((row) => row.case_id === caseId);
  if (!item) {
    clearMarketplaceForm();
    return;
  }
  state.marketplace.currentDraftId = "";
  state.marketplace.selectedPhotoIds = new Set((item.photo_ids || []).filter((fileId) => state.marketplace.images.some((row) => row.file_id === fileId)));
  state.marketplace.selectedGroupIds.clear();
  el("marketplace-source-case").value = caseId;
  el("marketplace-title").value = item.title || "";
  el("marketplace-price").value = item.price_suggestion?.amount ?? "";
  el("marketplace-category").value = item.category || "Antiques & collectibles";
  el("marketplace-condition").value = "good";
  el("marketplace-description").value = item.description || "";
  state.marketplace.notice = item.price_suggestion?.basis || "Review the saved research before accepting this price.";
  renderMarketplace();
}

function renderMarketplace() {
  const current = marketplaceDraft();
  const busy = state.marketplace.busy || state.marketplace.loading || state.uploading;
  const caseSelect = el("marketplace-source-case");
  const selectedCaseId = caseSelect.value;
  caseSelect.replaceChildren(new Option("New one-off listing", ""));
  state.marketplace.cases.forEach((item) => caseSelect.append(new Option(item.title || item.case_id, item.case_id)));
  caseSelect.value = selectedCaseId;

  const drafts = el("marketplace-draft-list");
  drafts.replaceChildren();
  if (!state.marketplace.drafts.length) {
    const empty = document.createElement("p");
    empty.textContent = "No listing drafts yet.";
    drafts.append(empty);
  }
  state.marketplace.drafts.forEach((draft) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = draft.draft_id === state.marketplace.currentDraftId ? "active" : "";
    const title = document.createElement("strong");
    title.textContent = draft.title || "Untitled listing";
    const status = document.createElement("span");
    status.textContent = String(draft.status || "draft").replaceAll("_", " ");
    button.append(title, status);
    button.addEventListener("click", () => loadMarketplaceDraft(draft));
    drafts.append(button);
  });

  const photos = el("marketplace-photo-grid");
  photos.replaceChildren();
  state.marketplace.images.slice().reverse().forEach((image) => {
    const label = document.createElement("label");
    label.className = "marketplace-photo-choice";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.marketplace.selectedPhotoIds.has(image.file_id);
    checkbox.disabled = busy || (!checkbox.checked && state.marketplace.selectedPhotoIds.size >= 10);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) state.marketplace.selectedPhotoIds.add(image.file_id);
      else state.marketplace.selectedPhotoIds.delete(image.file_id);
      renderMarketplace();
    });
    const preview = document.createElement("img");
    preview.src = marketplaceImageUrl(image);
    preview.alt = image.name || "Marketplace item photo";
    const name = document.createElement("span");
    name.textContent = image.name || "Photo";
    label.append(checkbox, preview, name);
    photos.append(label);
  });
  el("marketplace-photo-count").textContent = `${state.marketplace.selectedPhotoIds.size} of 10`;

  const groups = el("marketplace-group-list");
  groups.replaceChildren();
  if (!state.marketplace.groups.length) {
    const empty = document.createElement("p");
    empty.textContent = "No approved groups saved.";
    groups.append(empty);
  }
  state.marketplace.groups.forEach((group) => {
    const row = document.createElement("div");
    row.className = "marketplace-group-row";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.marketplace.selectedGroupIds.has(group.group_id);
    checkbox.disabled = busy;
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) state.marketplace.selectedGroupIds.add(group.group_id);
      else state.marketplace.selectedGroupIds.delete(group.group_id);
    });
    const name = document.createElement("span");
    name.textContent = group.name;
    name.title = group.url;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Remove";
    remove.disabled = busy;
    remove.addEventListener("click", () => deleteMarketplaceGroup(group.group_id));
    row.append(checkbox, name, remove);
    groups.append(row);
  });

  const suggestion = current?.price_suggestion || state.marketplace.cases.find((row) => row.case_id === caseSelect.value)?.price_suggestion;
  el("marketplace-price-basis").textContent = suggestion?.basis || "Enter and review the asking price";
  el("marketplace-status").textContent = busy ? "Working…" : (current?.status || "Draft locally").replaceAll("_", " ");
  const handoff = current ? ({
    draft: ["Draft saved", "Prepare it in the dedicated Facebook profile."],
    facebook_prepared: ["Facebook form prepared", "Review the visible form, then click Next and Publish yourself."],
    human_action_required: ["Your action is needed", state.marketplace.notice || "Complete the visible Facebook step, then resume."],
    published_observed: ["Published listing observed", "Prepare the selected approved groups one at a time."],
    group_share_prepared: ["Group post prepared", "Review the visible group composer and click Post yourself."],
    failed: ["Preparation failed", current?.last_error || "Review the error and retry."],
  }[current.status || "draft"]) : ["Save a draft to continue", "Preparation fills the visible form and stops before Next or Publish."];
  el("marketplace-handoff-title").textContent = handoff[0];
  el("marketplace-handoff-copy").textContent = handoff[1];
  el("marketplace-new-draft").disabled = busy;
  el("marketplace-save-draft").disabled = busy;
  el("marketplace-prepare").disabled = busy;
  el("marketplace-resume").disabled = busy || !current || !["facebook_prepared", "human_action_required"].includes(current.status);
  const preparedGroupIds = new Set((current?.group_preparations || []).map((row) => row.group_id));
  const hasNextGroup = [...state.marketplace.selectedGroupIds].some((groupId) => !preparedGroupIds.has(groupId));
  el("marketplace-prepare-group").disabled = busy || !current || !["published_observed", "group_share_prepared"].includes(current.status) || !hasNextGroup;
}

async function loadMarketplace({ preserveSelection = false } = {}) {
  if (!state.workspace || !state.session) return;
  state.marketplace.loading = true;
  renderMarketplace();
  try {
    const query = new URLSearchParams({ workspace_id: state.workspace.workspace_id, session_id: state.session.session_id });
    const value = await api(`/api/facebook/marketplace?${query}`);
    applyMarketplaceBootstrap(value);
    if (preserveSelection) renderMarketplace();
    else if (state.marketplace.currentDraftId) loadMarketplaceDraft(marketplaceDraft());
    else clearMarketplaceForm();
  } finally {
    state.marketplace.loading = false;
    renderMarketplace();
  }
}

async function openMarketplaceSell() {
  el("marketplace-sell-dialog").showModal();
  try { await loadMarketplace({ preserveSelection: state.marketplace.loaded }); }
  catch (error) { showError(error.message || String(error)); }
}

function marketplaceDraftPayload() {
  return {
    draft_id: state.marketplace.currentDraftId,
    source_case_id: el("marketplace-source-case").value,
    title: el("marketplace-title").value.trim(),
    price: el("marketplace-price").value,
    category: el("marketplace-category").value.trim(),
    condition: el("marketplace-condition").value,
    description: el("marketplace-description").value.trim(),
    photo_ids: [...state.marketplace.selectedPhotoIds],
    group_ids: [...state.marketplace.selectedGroupIds],
  };
}

async function saveMarketplaceDraft() {
  state.marketplace.busy = true;
  renderMarketplace();
  try {
    const value = await api("/api/facebook/marketplace/drafts/save", {
      method: "POST",
      body: marketplaceRequestBody(marketplaceDraftPayload()),
    });
    applyMarketplaceBootstrap(value);
    loadMarketplaceDraft(value.draft);
    showToast("Facebook Marketplace draft saved.");
    return value.draft;
  } catch (error) {
    showError(error.message || String(error));
    return null;
  } finally {
    state.marketplace.busy = false;
    renderMarketplace();
  }
}

async function runMarketplaceAction(path, extra, successMessage) {
  state.marketplace.busy = true;
  renderMarketplace();
  try {
    const value = await api(path, { method: "POST", body: marketplaceRequestBody(extra) });
    applyMarketplaceBootstrap(value);
    if (value.draft) loadMarketplaceDraft(value.draft);
    state.marketplace.notice = value.result?.instruction || "";
    renderMarketplace();
    showToast(value.result?.instruction || successMessage);
    return value;
  } catch (error) {
    showError(error.message || String(error));
    return null;
  } finally {
    state.marketplace.busy = false;
    renderMarketplace();
  }
}

async function prepareMarketplaceListing() {
  const draft = await saveMarketplaceDraft();
  if (!draft) return;
  await runMarketplaceAction("/api/facebook/marketplace/prepare", { draft_id: draft.draft_id }, "Facebook form prepared for review.");
}

async function resumeMarketplaceListing() {
  const draft = marketplaceDraft();
  if (!draft) return;
  await runMarketplaceAction("/api/facebook/marketplace/resume", { draft_id: draft.draft_id }, "Marketplace listing evidence checked.");
}

async function prepareNextMarketplaceGroup() {
  const draft = marketplaceDraft();
  if (!draft) return;
  const prepared = new Set((draft.group_preparations || []).map((row) => row.group_id));
  const groupId = [...state.marketplace.selectedGroupIds].find((value) => !prepared.has(value));
  if (!groupId) return;
  await runMarketplaceAction("/api/facebook/marketplace/groups/prepare", { draft_id: draft.draft_id, group_id: groupId }, "Group post prepared for review.");
}

async function saveMarketplaceGroup(event) {
  event.preventDefault();
  try {
    const value = await api("/api/facebook/marketplace/groups/save", {
      method: "POST",
      body: marketplaceRequestBody({ name: el("marketplace-group-name").value.trim(), url: el("marketplace-group-url").value.trim() }),
    });
    applyMarketplaceBootstrap(value);
    state.marketplace.selectedGroupIds.add(value.group.group_id);
    event.target.reset();
    renderMarketplace();
  } catch (error) { showError(error.message || String(error)); }
}

async function deleteMarketplaceGroup(groupId) {
  if (!window.confirm("Remove this group from the workspace allowlist? Existing Facebook posts are not affected.")) return;
  try {
    const value = await api("/api/facebook/marketplace/groups/delete", {
      method: "POST",
      body: marketplaceRequestBody({ group_id: groupId }),
    });
    applyMarketplaceBootstrap(value);
    state.marketplace.selectedGroupIds.delete(groupId);
    renderMarketplace();
  } catch (error) { showError(error.message || String(error)); }
}

async function researchMarketplacePhotos() {
  const selected = state.marketplace.images.filter((row) => state.marketplace.selectedPhotoIds.has(row.file_id));
  const currentSessionPhotos = selected.filter((row) => (row.session_id || state.session.session_id) === state.session.session_id);
  if (!currentSessionPhotos.length || currentSessionPhotos.length !== selected.length) {
    showError("Leo research can start here only with photos uploaded in the current session. Existing Museum cases already include their saved research.");
    return;
  }
  state.selectedFiles = new Set(currentSessionPhotos.map((row) => row.file_id));
  el("marketplace-sell-dialog").close();
  if (state.session.active_room !== "antiques_department") {
    try {
      const result = await api("/api/rooms", {
        method: "POST",
        body: JSON.stringify({ workspace_id: state.workspace.workspace_id, session_id: state.session.session_id, room_id: "antiques_department" }),
      });
      applyState(result, true);
    } catch (error) { showError(error.message || String(error)); return; }
  }
  render();
  await startAntiquesResearch("quick");
}

async function loadState(workspaceId = "", sessionId = "", preserveRoute = false) {
  const leavingActiveShoppingSession = Boolean(
    state.antiques?.shopping_mode?.active
    && state.session?.active_room === "antiques_department"
    && ((sessionId && sessionId !== state.session.session_id) || (workspaceId && workspaceId !== state.workspace?.workspace_id))
  );
  if (leavingActiveShoppingSession) {
    try {
      await api("/api/antiques/shopping/end", {
        method: "POST",
        body: JSON.stringify({ workspace_id: state.workspace.workspace_id, session_id: state.session.session_id }),
      });
    } catch { /* Expiry and room-exit enforcement still protect the consent scope. */ }
  }
  const query = new URLSearchParams();
  if (workspaceId) query.set("workspace_id", workspaceId);
  if (sessionId) query.set("session_id", sessionId);
  applyState(await api(`/api/state?${query}`), preserveRoute);
  if (state.session?.active_room === "my_office") {
    const alertQuery = new URLSearchParams({
      workspace_id: state.workspace.workspace_id,
      session_id: state.session.session_id,
    });
    const result = await api(`/api/mail/alerts?${alertQuery}`);
    state.deliveryAlerts = result.alerts || [];
    renderDeliveryAlerts();
  }
  await refreshBackgroundMonitor();
}

function routeNotice(next) {
  if (["veridex_router", "veridex_governance", "veridex_admin", "veridex_google_router", "veridex_gmail_router", "veridex_antiques_router"].includes(next.provider)) return "Handled through Veridex's governed room workflow.";
  if (!state.route) return `Model selected: ${next.model} · ${next.reasoning_effort} reasoning.`;
  if (state.route.model !== next.model || state.route.reasoning_effort !== next.reasoning_effort) {
    return `Model changed: ${state.route.model} → ${next.model} · ${next.reasoning_effort} reasoning.`;
  }
  if (state.route.task_type !== next.task_type) {
    return `Task route changed: ${state.route.task_type.replaceAll("_", " ")} → ${next.task_type.replaceAll("_", " ")}.`;
  }
  return `Continuing with ${next.model} · ${next.reasoning_effort} reasoning.`;
}

async function sendMessage(text, { attachments, emailDraft, confirmExternal = false, antiquesCaseId = "", valuationOverrides = {} } = {}) {
  if (state.listening && state.recognition) {
    state.dictationBase = "";
    state.dictationFinal = "";
    state.recognition.abort();
  }
  const usesChatSelection = attachments === undefined;
  const selectedAttachments = usesChatSelection
    ? state.files.filter((file) => state.selectedFiles.has(file.file_id))
    : attachments;
  state.sending = true;
  state.stopping = false;
  state.activeRequestId = globalThis.crypto?.randomUUID?.() || `req_${Date.now()}_${Math.random().toString(16).slice(2)}`;
  state.messages.push({
    role: "user",
    text: text || "Review the attached file or files and summarize what is important.",
    speaker: "You",
    attachments: selectedAttachments,
  });
  render();
  let succeeded = false;
  try {
    const result = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        workspace_id: state.workspace.workspace_id,
        session_id: state.session.session_id,
        text,
        request_id: state.activeRequestId,
        attachment_ids: selectedAttachments.map((file) => file.file_id),
        email_draft: emailDraft,
        confirm_external: confirmExternal,
        antiques_case_id: antiquesCaseId,
        valuation_overrides: valuationOverrides,
      }),
    });
    const nextRoute = {
      provider: result.provider,
      model: result.model,
      reasoning_effort: result.reasoning_effort,
      task_type: result.task_type,
    };
    nextRoute.notice = result.room_transition
      ? `Room changed: ${result.room_transition.room_title} · ${result.room_transition.active_persona}.`
      : routeNotice(nextRoute);
    state.route = nextRoute;
    if (usesChatSelection) state.selectedFiles.clear();
    await loadState(state.workspace.workspace_id, state.session.session_id, true);
    if (result.task_type === "gmail_send" && state.session?.active_room === "my_office") {
      window.setTimeout(checkDeliveryFailures, 5_000);
    }
    succeeded = true;
  } catch (error) {
    showError(error.message || String(error));
    await loadState(state.workspace.workspace_id, state.session.session_id, true);
  } finally {
    state.sending = false;
    state.stopping = false;
    state.activeRequestId = null;
    render();
    if (!el("email-compose-dialog").open) el("message-input").focus();
  }
  return succeeded;
}

async function stopMessage() {
  if (!state.sending || state.stopping || !state.activeRequestId) return;
  state.stopping = true;
  render();
  try {
    const result = await api("/api/chat/cancel", {
      method: "POST",
      body: JSON.stringify({
        request_id: state.activeRequestId,
        session_id: state.session.session_id,
      }),
    });
    if (!result.cancel_requested) showError("The request had already finished.");
  } catch (error) {
    state.stopping = false;
    showError(error.message || String(error));
    render();
  }
}

function showError(message) {
  const toast = el("toast");
  toast.textContent = message;
  toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 7000);
}

function showToast(message) {
  const toast = el("toast");
  toast.textContent = message;
  toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 4500);
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

el("send-button").addEventListener("click", () => {
  if (state.sending) stopMessage();
  else el("composer").requestSubmit();
});

el("auto-read").addEventListener("change", (event) => {
  state.autoRead = event.target.checked;
  try { window.localStorage.setItem(AUTO_READ_STORAGE_KEY, String(state.autoRead)); }
  catch { /* Browser storage is optional; keep the setting for this tab. */ }
  if (!state.autoRead && state.speakingMessageId) stopSpeech();
});
el("voice-input").addEventListener("click", toggleDictation);

el("compose-email").addEventListener("click", () => openEmailComposer());
el("address-book").addEventListener("click", openAddressBook);
el("antiques-camera").addEventListener("click", () => el("antiques-camera-input").click());
el("antiques-camera-input").addEventListener("change", (event) => uploadFiles(event.target.files, "museum"));
el("antiques-quick").addEventListener("click", () => openMuseumAnalysis("quick"));
el("antiques-deep").addEventListener("click", () => openMuseumAnalysis("detailed"));
el("antiques-select-items").addEventListener("click", openItemSelector);
el("antiques-cases").addEventListener("click", openMuseumCases);
el("antiques-shopping-toggle").addEventListener("click", toggleMuseumShoppingMode);
el("museum-analysis-close").addEventListener("click", closeMuseumAnalysis);
el("museum-analysis-dialog").addEventListener("cancel", (event) => { event.preventDefault(); closeMuseumAnalysis(); });
el("antiques-cases-close").addEventListener("click", closeMuseumCases);
el("antiques-cases-dialog").addEventListener("cancel", (event) => { event.preventDefault(); closeMuseumCases(); });
el("museum-analysis-start").addEventListener("click", startMuseumAnalysis);
el("museum-crop-file").addEventListener("change", (event) => { state.museum.cropFileId = event.target.value; renderMuseumCrop(); });
el("museum-crop-image").addEventListener("load", renderMuseumCrop);
el("museum-crop-clear").addEventListener("click", () => { delete state.museum.regions[state.museum.cropFileId]; renderMuseumCrop(); });
el("museum-crop-stage").addEventListener("pointerdown", (event) => {
  if (!state.museum.cropFileId) return;
  state.museum.cropStart = museumPointerPosition(event);
  el("museum-crop-stage").setPointerCapture(event.pointerId);
});
el("museum-crop-stage").addEventListener("pointermove", (event) => updateMuseumCrop(event));
el("museum-crop-stage").addEventListener("pointerup", (event) => updateMuseumCrop(event, true));
el("museum-job-cancel").addEventListener("click", async () => {
  const job = state.museum.activeJob;
  if (!job?.job_id) return;
  try {
    state.museum.activeJob = await api(`/api/antiques/analysis/jobs/${encodeURIComponent(job.job_id)}/cancel`, { method: "POST", body: "{}" });
    renderMuseumJob();
  } catch (error) { showError(error.message || String(error)); }
});
el("museum-item-selector-close").addEventListener("click", closeItemSelector);
el("museum-item-selector-dialog").addEventListener("cancel", (event) => { event.preventDefault(); closeItemSelector(); });
el("museum-item-image").addEventListener("load", renderItemSelector);
el("museum-item-source").addEventListener("change", (event) => {
  if (state.itemSelector.selections.length && !window.confirm("Changing the source photo will clear the current boxes. Continue?")) {
    event.target.value = state.itemSelector.sourceFileId;
    return;
  }
  state.itemSelector.sourceFileId = event.target.value;
  state.itemSelector.selections = [];
  state.itemSelector.activeSelectionId = "";
  state.itemSelector.batchId = itemBatchId();
  state.itemSelector.zoom = 1;
  renderItemSelector();
});
el("museum-item-search-mode").addEventListener("change", (event) => { state.itemSelector.searchMode = event.target.value; renderItemSelector(); });
el("museum-item-depth").addEventListener("change", (event) => { state.itemSelector.researchDepth = event.target.value; });
el("museum-item-zoom-out").addEventListener("click", () => setItemSelectorZoom(state.itemSelector.zoom / 1.25));
el("museum-item-zoom-in").addEventListener("click", () => setItemSelectorZoom(state.itemSelector.zoom * 1.25));
el("museum-item-zoom-reset").addEventListener("click", () => setItemSelectorZoom(1));
el("museum-item-stage").addEventListener("pointerdown", (event) => beginItemInteraction(event, "create"));
window.addEventListener("pointermove", (event) => updateItemInteraction(event));
window.addEventListener("pointerup", (event) => updateItemInteraction(event, true));
window.addEventListener("pointercancel", cancelItemInteraction);
el("museum-item-undo").addEventListener("click", () => {
  const removed = state.itemSelector.selections.pop();
  if (removed?.selection_id === state.itemSelector.activeSelectionId) state.itemSelector.activeSelectionId = "";
  renderItemSelector();
});
el("museum-item-clear").addEventListener("click", () => { state.itemSelector.selections = []; state.itemSelector.activeSelectionId = ""; renderItemSelector(); });
el("museum-item-search").addEventListener("click", startItemSelectionSearch);
el("museum-item-job-cancel").addEventListener("click", async () => {
  const job = state.itemSelector.activeJob;
  if (!job?.job_id) return;
  try {
    state.itemSelector.activeJob = await api(`/api/antiques/item-selection/jobs/${encodeURIComponent(job.job_id)}/cancel`, { method: "POST", body: "{}" });
    renderItemSelector();
  } catch (error) { showError(error.message || String(error)); }
});
window.addEventListener("resize", () => { if (el("museum-item-selector-dialog").open) renderItemSelector(); });
el("antiques-settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const result = await api("/api/antiques/settings", { method: "POST", body: JSON.stringify({
      workspace_id: state.workspace.workspace_id,
      session_id: state.session.session_id,
      settings: {
        fee_percent: Number(el("antiques-fee").value),
        packing_shipping_allowance: Number(el("antiques-shipping").value),
        uncertainty_reserve_percent: Number(el("antiques-reserve").value),
        minimum_target_profit: Number(el("antiques-profit").value),
        quick_buy_cap_percent: Number(el("antiques-cap").value),
      },
    }) });
    state.museum.settings = result.settings || state.museum.settings;
    showToast("Museum buying defaults saved.");
  } catch (error) { showError(error.message || String(error)); }
});
el("open-art-studio").addEventListener("click", openArtStudio);
el("art-studio-close").addEventListener("click", closeArtStudio);
el("art-studio-dialog").addEventListener("cancel", (event) => {
  event.preventDefault();
  closeArtStudio();
});
document.querySelectorAll("[data-art-mode]").forEach((button) => button.addEventListener("click", () => setArtMode(button.dataset.artMode)));
el("art-improve-prompt").addEventListener("click", () => startArtJob({ operation: "improve_prompt", prompt: el("art-prompt").value.trim(), preset_id: el("art-preset").value }));
el("art-generate").addEventListener("click", generateArt);
el("art-edit").addEventListener("click", editArt);
el("art-reference-upload").addEventListener("click", () => el("art-reference-input").click());
el("art-reference-input").addEventListener("change", (event) => uploadFiles(event.target.files, "art"));
el("art-finish").addEventListener("click", finishArt);
el("art-project-save").addEventListener("click", saveArtProject);
el("art-project-load").addEventListener("click", loadArtProject);
el("art-project-select").addEventListener("change", renderArtStudio);
el("art-finish-source").addEventListener("change", (event) => { state.artStudio.selectedFileId = event.target.value; renderArtStudio(); });
el("art-critique").addEventListener("click", () => {
  const selected = selectedStudioImage();
  if (selected) startArtJob({ operation: "critique", source_file_ids: [selected.file_id] });
});
el("art-use-reference").addEventListener("click", () => {
  const selected = selectedStudioImage();
  if (!selected) return;
  state.artStudio.referenceIds.add(selected.file_id);
  state.artStudio.previewReferenceId = selected.file_id;
  setArtMode("edit");
});
el("art-download").addEventListener("click", () => {
  const selected = selectedStudioImage();
  if (!selected) return;
  const link = document.createElement("a");
  link.href = artImageContentUrl(selected);
  link.download = selected.name || "veridex-artwork";
  link.click();
});
el("art-attach").addEventListener("click", async () => {
  const selected = selectedStudioImage();
  if (selected) await attachArtImage(selected);
  renderArtStudio();
});
el("art-job-cancel").addEventListener("click", async () => {
  const job = state.artStudio.activeJob;
  if (!job?.job_id) return;
  try {
    state.artStudio.activeJob = await api(`/api/art/jobs/${encodeURIComponent(job.job_id)}/cancel`, { method: "POST", body: "{}" });
    renderArtStudio();
  } catch (error) { showError(error.message || String(error)); }
});
el("open-art-gallery").addEventListener("click", openArtGallery);
el("art-gallery-close").addEventListener("click", closeArtGallery);
el("art-gallery-dialog").addEventListener("cancel", (event) => {
  event.preventDefault();
  closeArtGallery();
});
el("open-room-files").addEventListener("click", openRoomFileLibrary);
el("room-file-close").addEventListener("click", closeRoomFileLibrary);
el("room-file-dialog").addEventListener("cancel", (event) => {
  event.preventDefault();
  closeRoomFileLibrary();
});
el("open-animation-studio").addEventListener("click", openAnimationStudio);
el("open-ebay-room").addEventListener("click", () => {
  const query = new URLSearchParams({ workspace_id: state.workspace.workspace_id, session_id: state.session.session_id });
  window.location.href = `/ebay-room?${query}`;
});
el("animation-studio-close").addEventListener("click", closeAnimationStudio);
el("animation-studio-dialog").addEventListener("cancel", (event) => {
  event.preventDefault();
  closeAnimationStudio();
});
el("animation-project-select").addEventListener("change", loadSelectedAnimationProject);
el("animation-project-save").addEventListener("click", () => saveAnimationProject());
el("animation-image-add").addEventListener("click", () => el("animation-image-upload").click());
el("animation-image-upload").addEventListener("change", (event) => uploadFiles(event.target.files, "animation_image"));
el("animation-audio-add").addEventListener("click", () => el("animation-audio-upload").click());
el("animation-audio-upload").addEventListener("change", (event) => uploadFiles(event.target.files, "animation_audio"));
el("animation-asset-role").addEventListener("change", (event) => updateSelectedAnimationAsset("role", event.target.value));
[["width", "width_percent"], ["x", "x_percent"], ["y", "y_percent"], ["opacity", "opacity_percent"]].forEach(([control, key]) => {
  el(`animation-asset-${control}`).addEventListener("input", (event) => updateSelectedAnimationAsset(key, Number(event.target.value)));
});
document.querySelectorAll("[data-animation-preset]").forEach((button) => button.addEventListener("click", () => applyAnimationAssetPreset(button.dataset.animationPreset)));
el("animation-open-gimp").addEventListener("click", () => openAnimationEditor("gimp", selectedAnimationAsset()));
el("animation-open-synfig").addEventListener("click", () => openAnimationEditor("synfig", selectedAnimationAsset()));
el("animation-asset-remove").addEventListener("click", removeSelectedAnimationAsset);
el("animation-storyboard-add").addEventListener("click", addAnimationStoryboardShot);
const animationTrackFields = {
  "animation-track-type": ["track_type", String],
  "animation-track-character": ["character", String],
  "animation-track-shot": ["shot_id", String],
  "animation-track-start": ["start_seconds", Number],
  "animation-track-trim-in": ["trim_in_seconds", Number],
  "animation-track-trim-out": ["trim_out_seconds", Number],
  "animation-track-volume": ["volume_db", Number],
  "animation-track-pan": ["pan_percent", Number],
  "animation-track-fade-in": ["fade_in_seconds", Number],
  "animation-track-fade-out": ["fade_out_seconds", Number],
};
Object.entries(animationTrackFields).forEach(([id, [key, converter]]) => {
  el(id).addEventListener("input", (event) => updateSelectedAnimationTrack(key, converter(event.target.value)));
});
el("animation-track-mute").addEventListener("change", (event) => updateSelectedAnimationTrack("muted", event.target.checked));
el("animation-track-solo").addEventListener("change", (event) => updateSelectedAnimationTrack("solo", event.target.checked));
el("animation-open-audacity").addEventListener("click", () => openAnimationEditor("audacity", selectedAnimationTrack()));
el("animation-track-remove").addEventListener("click", removeSelectedAnimationTrack);
el("animation-audio-preview").addEventListener("loadedmetadata", (event) => {
  const track = selectedAnimationTrack();
  if (track) event.target.currentTime = Math.min(Number(track.trim_in_seconds || 0), Number(event.target.duration || 0));
});
el("animation-audio-preview").addEventListener("play", (event) => {
  const track = selectedAnimationTrack();
  if (!track) return;
  const trimIn = Number(track.trim_in_seconds || 0);
  const trimOut = Number(track.trim_out_seconds || 0);
  if (event.target.currentTime < trimIn || (trimOut > 0 && event.target.currentTime >= trimOut)) event.target.currentTime = trimIn;
  const lipSyncAudio = el("animation-lipsync-audio");
  if (!lipSyncAudio.paused) lipSyncAudio.pause();
  if (activateAnimationTakeForTrack(track, event.target)) startAnimationMouthClock(event.target);
});
el("animation-audio-preview").addEventListener("timeupdate", (event) => {
  const track = selectedAnimationTrack();
  const trimOut = Number(track?.trim_out_seconds || 0);
  if (trimOut > 0 && event.target.currentTime >= trimOut) event.target.pause();
  if (state.animation.mouthAudioId === event.target.id) renderLipSyncMouthAt(Number(event.target.currentTime || 0));
});
el("animation-audio-preview").addEventListener("seeking", (event) => activateAnimationTakeForTrack(selectedAnimationTrack(), event.target));
el("animation-audio-preview").addEventListener("seeked", (event) => activateAnimationTakeForTrack(selectedAnimationTrack(), event.target));
el("animation-audio-preview").addEventListener("pause", (event) => {
  if (state.animation.mouthAudioId !== event.target.id) return;
  stopAnimationMouthClock();
  renderLipSyncMouthAt(Number(event.target.currentTime || 0));
});
el("animation-audio-preview").addEventListener("ended", (event) => {
  if (state.animation.mouthAudioId === event.target.id) stopAnimationMouthClock();
  renderLipSyncMouthAt(Number.MAX_SAFE_INTEGER);
});
el("animation-rig-new").addEventListener("click", createAnimationMouthRig);
el("animation-rig-remove").addEventListener("click", removeSelectedAnimationRig);
el("animation-rig-select").addEventListener("change", (event) => {
  if (!event.target.value) return createAnimationMouthRig();
  state.animation.selectedRigId = event.target.value;
  state.animation.selectedTakeId = state.animation.lipsyncTakes.find((take) => take.rig_id === event.target.value)?.take_id || "";
  renderAnimationLipSync();
});
el("animation-rig-character").addEventListener("input", (event) => {
  const rig = selectedAnimationRig();
  if (rig) rig.character = event.target.value;
});
el("animation-rig-base").addEventListener("change", (event) => updateSelectedAnimationRig("base_asset_id", event.target.value));
el("animation-mouth-mode").addEventListener("change", (event) => {
  const rig = selectedAnimationRig();
  if (!rig) return;
  rig.animation_mode = event.target.value === "jaw_flap" ? "jaw_flap" : "mouth_shapes";
  rig.placement_calibrated = false;
  renderAnimationLipSync();
});
el("animation-simple-jaw").addEventListener("change", (event) => {
  const rig = selectedAnimationRig();
  if (!rig) return;
  rig.shapes.X = event.target.value;
  rig.placement_calibrated = false;
  rig.mouth_asset_registrations = {};
  rig.registration_master_asset_id = "";
  renderAnimationLipSync();
});
[["x", "mouth_x_percent"], ["y", "mouth_y_percent"], ["width", "mouth_width_percent"], ["height", "mouth_height_percent"], ["anchor-x", "mouth_anchor_x_percent"], ["anchor-y", "mouth_anchor_y_percent"]].forEach(([control, key]) => {
  el(`animation-mouth-${control}`).addEventListener("input", (event) => updateSelectedAnimationRig(key, Number(event.target.value)));
});
el("animation-mouth-strength").addEventListener("input", (event) => updateSelectedAnimationRig("jaw_open_strength_percent", Number(event.target.value)));
el("animation-mouth-placement-edit").addEventListener("click", toggleAnimationMouthPlacement);
el("animation-mouth-calibrate").addEventListener("click", confirmAnimationMouthFit);
el("animation-mouth-transform-box").addEventListener("pointerdown", (event) => {
  if (event.target === el("animation-mouth-resize-handle")) return;
  beginAnimationMouthDrag(event, false);
});
el("animation-mouth-transform-box").addEventListener("pointermove", moveManualJawPointer);
el("animation-mouth-transform-box").addEventListener("pointerup", finishManualJawPointer);
el("animation-mouth-transform-box").addEventListener("pointercancel", finishManualJawPointer);
el("animation-mouth-resize-handle").addEventListener("pointerdown", (event) => beginAnimationMouthDrag(event, true));
el("animation-lipsync-take").addEventListener("change", (event) => {
  state.animation.selectedTakeId = event.target.value;
  state.animation.manualSelection = null;
  state.animation.quickFix = null;
  state.animation.quickFixHistory = { undo: [], redo: [] };
  renderAnimationLipSync();
});
el("animation-manual-start").addEventListener("input", (event) => {
  const take = selectedAnimationTake();
  if (!take) return;
  const duration = Number(take.duration || 0);
  const start = Math.max(0, Math.min(duration, Number(event.target.value || 0)));
  const current = manualJawSelectionForTake(take);
  state.animation.manualSelection = { takeId: take.take_id, start, end: Math.max(start, current.end) };
  renderManualJawControls(take, el("animation-lipsync-audio"));
});
el("animation-manual-end").addEventListener("input", (event) => {
  const take = selectedAnimationTake();
  if (!take) return;
  const duration = Number(take.duration || 0);
  const end = Math.max(0, Math.min(duration, Number(event.target.value || 0)));
  const current = manualJawSelectionForTake(take);
  state.animation.manualSelection = { takeId: take.take_id, start: Math.min(current.start, end), end };
  renderManualJawControls(take, el("animation-lipsync-audio"));
});
el("animation-manual-playback-rate").addEventListener("change", (event) => {
  el("animation-lipsync-audio").playbackRate = Number(event.target.value || 1);
});
el("animation-quick-fix-start").addEventListener("click", () => beginQuickJawFix());
el("animation-quick-fix-opening").addEventListener("input", (event) => {
  const quickFix = state.animation.quickFix;
  if (!quickFix) return;
  quickFix.openingPercent = Math.max(0, Math.min(100, Number(event.target.value || 0)));
  el("animation-quick-fix-opening-value").textContent = `${quickFix.openingPercent.toFixed(0)}%`;
  renderLipSyncMouthAt(quickFix.time);
});
el("animation-quick-fix-save").addEventListener("click", saveQuickJawFix);
el("animation-quick-fix-cancel").addEventListener("click", cancelQuickJawFix);
el("animation-quick-fix-delete").addEventListener("click", deleteQuickJawFix);
el("animation-quick-fix-undo").addEventListener("click", undoQuickJawFix);
el("animation-manual-advanced").addEventListener("toggle", () => {
  const take = selectedAnimationTake();
  const audio = el("animation-lipsync-audio");
  renderQuickFixControls(take, audio);
  drawAnimationWaveform(take, audio);
});
el("animation-manual-jaw-edit").addEventListener("click", handleManualJawEditButton);
el("animation-manual-jaw-clear").addEventListener("click", clearManualJawEdits);
el("animation-manual-jaw-save").addEventListener("click", saveManualJawEditor);
el("animation-manual-jaw-undo").addEventListener("click", undoManualJawEdit);
el("animation-manual-jaw-redo").addEventListener("click", redoManualJawEdit);
el("animation-manual-jaw-close").addEventListener("click", () => closeManualJawEditor());
el("animation-manual-jaw-dialog").addEventListener("cancel", (event) => { event.preventDefault(); closeManualJawEditor(); });
el("animation-lipsync-waveform").addEventListener("pointerdown", beginAnimationWaveformPointer);
el("animation-lipsync-waveform").addEventListener("pointermove", moveAnimationWaveformPointer);
el("animation-lipsync-waveform").addEventListener("pointerup", finishAnimationWaveformPointer);
el("animation-lipsync-waveform").addEventListener("pointercancel", finishAnimationWaveformPointer);
el("animation-lipsync-waveform").addEventListener("click", seekAnimationWaveform);
el("animation-lipsync-audio").addEventListener("play", (event) => {
  const trackPreview = el("animation-audio-preview");
  if (!trackPreview.paused) trackPreview.pause();
  startAnimationMouthClock(event.target);
});
el("animation-lipsync-audio").addEventListener("pause", (event) => {
  if (state.animation.mouthAudioId !== event.target.id) return;
  stopAnimationMouthClock();
  renderLipSyncMouthAt(Number(event.target.currentTime || 0));
});
el("animation-lipsync-audio").addEventListener("seeking", (event) => renderLipSyncMouthAt(Number(event.target.currentTime || 0)));
el("animation-lipsync-audio").addEventListener("seeked", (event) => renderLipSyncMouthAt(Number(event.target.currentTime || 0)));
el("animation-lipsync-audio").addEventListener("timeupdate", (event) => {
  renderLipSyncMouthAt(Number(event.target.currentTime || 0));
});
el("animation-lipsync-audio").addEventListener("ended", () => {
  stopAnimationMouthClock();
  if (state.animation.manualEdit) finishManualJawEdit();
  else renderLipSyncMouthAt(Number.MAX_SAFE_INTEGER);
});
el("animation-audio-file").addEventListener("change", renderAnimationStudio);
el("animation-lipsync-generate").addEventListener("click", generateAnimationLipsync);
el("animation-video-handoff").addEventListener("click", () => {
  closeAnimationStudio();
  el("room-selector").value = "video_production";
  el("room-selector").dispatchEvent(new Event("change", { bubbles: true }));
});
el("open-resume-studio").addEventListener("click", openResumeStudio);
el("resume-studio-close").addEventListener("click", closeResumeStudio);
el("resume-studio-dialog").addEventListener("cancel", (event) => {
  event.preventDefault();
  closeResumeStudio();
});
document.querySelectorAll("[data-resume-step]").forEach((button) => button.addEventListener("click", () => setResumeStep(button.dataset.resumeStep)));
el("resume-profile-save").addEventListener("click", saveResumeProfile);
el("resume-import-file").addEventListener("change", renderResumeStudio);
el("resume-import-button").addEventListener("click", importResumeFile);
el("resume-analyze").addEventListener("click", analyzeResumeTarget);
el("resume-load-project").addEventListener("click", loadResumeProject);
el("resume-fetch-job").addEventListener("click", fetchResumeJobDescription);
el("resume-generate").addEventListener("click", generateResumeDraft);
el("resume-save-project").addEventListener("click", saveResumeProject);
el("resume-export").addEventListener("click", exportResumeFiles);
el("resume-type").addEventListener("change", renderResumeTemplates);
el("resume-job-url").addEventListener("input", renderResumeStudio);
el("resume-refine-chat").addEventListener("click", refineResumeDraft);
el("email-compose-close").addEventListener("click", closeEmailComposer);
el("email-compose-cancel").addEventListener("click", closeEmailComposer);
el("email-compose-dialog").addEventListener("cancel", (event) => {
  event.preventDefault();
  closeEmailComposer();
});
el("address-book-close").addEventListener("click", closeAddressBook);
el("address-book-dialog").addEventListener("cancel", (event) => {
  event.preventDefault();
  closeAddressBook();
});
el("contact-search").addEventListener("input", renderContacts);
el("contact-sync").addEventListener("click", syncContacts);
el("contact-new").addEventListener("click", () => showContactForm());
el("contact-form-cancel").addEventListener("click", hideContactForm);
el("contact-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const result = await api("/api/contacts/save", {
      method: "POST",
      body: JSON.stringify({
        workspace_id: state.workspace.workspace_id,
        session_id: state.session.session_id,
        contact_id: el("contact-id").value,
        name: el("contact-name").value.trim(),
        email: el("contact-email").value.trim(),
        phone: el("contact-phone").value.trim(),
        company: el("contact-company").value.trim(),
        notes: el("contact-notes").value.trim(),
      }),
    });
    state.contacts = result.contacts || state.contacts;
    hideContactForm();
    el("contact-sync-status").textContent = `Saved ${result.contact?.name || result.contact?.email}.`;
  } catch (error) { showError(error.message || String(error)); }
});
el("email-to").addEventListener("focus", renderRecipientSuggestions);
el("email-to").addEventListener("input", () => {
  state.recipientSuggestionIndex = -1;
  renderRecipientSuggestions();
});
el("email-to").addEventListener("blur", () => window.setTimeout(() => {
  el("email-recipient-suggestions").hidden = true;
}, 100));
el("email-to").addEventListener("keydown", (event) => {
  const contacts = matchingRecipientContacts();
  if (!contacts.length) return;
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    const delta = event.key === "ArrowDown" ? 1 : -1;
    state.recipientSuggestionIndex = (state.recipientSuggestionIndex + delta + contacts.length) % contacts.length;
    renderRecipientSuggestions();
  } else if (event.key === "Enter" && state.recipientSuggestionIndex >= 0) {
    event.preventDefault();
    chooseRecipient(contacts[state.recipientSuggestionIndex]);
  } else if (event.key === "Escape") {
    el("email-recipient-suggestions").hidden = true;
  }
});
el("email-compose-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.sending || state.uploading) return;
  const to = el("email-to").value.trim();
  const subject = el("email-subject").value.trim();
  const body = el("email-body").value.trim();
  if (!to || !subject || !body) return;
  const attachments = state.emailAttachments.map((file) => ({ ...file }));
  const sentToReview = await sendMessage(
    `Nancy, compose email to ${to}\nSubject: ${subject}\nBody:\n${body}`,
    {
      attachments,
      emailDraft: {
        to,
        subject,
        body,
        attachment_ids: attachments.map((file) => file.file_id),
        retry_failure_id: state.emailRetryFailureId,
      },
    },
  );
  if (sentToReview) closeEmailComposer();
});

const EMAIL_ATTACHMENT_LIMIT_BYTES = 20 * 1024 * 1024;

async function uploadFiles(fileList, target = "chat") {
  let files = [...fileList].filter((file) => file instanceof File);
  if (!state.workspace || !state.session || !files.length) return;
  if (state.sending || state.uploading) {
    showError("Wait for the current request or upload to finish.");
    return;
  }
  if (target === "email") {
    const currentSize = state.emailAttachments.reduce((total, file) => total + Number(file.size || 0), 0);
    const addedSize = files.reduce((total, file) => total + Number(file.size || 0), 0);
    if (currentSize + addedSize > EMAIL_ATTACHMENT_LIMIT_BYTES) {
      showError("Email attachments must total 20 MB or less.");
      return;
    }
  }
  if (["art", "museum", "animation_image", "sell"].includes(target)) {
    const supportedTypes = new Set(["image/png", "image/jpeg", "image/webp"]);
    const supportedExtensions = target === "animation_image" ? /\.(?:bmp|gif|png|jpe?g|tiff?|webp)$/i : /\.(?:png|jpe?g|webp)$/i;
    if (files.some((file) => !supportedTypes.has(file.type) && !supportedExtensions.test(file.name))) {
      showError(target === "art" ? "Art Studio references must be PNG, JPEG, or WebP images." : target === "animation_image" ? "Animation Studio requires supported image files." : target === "sell" ? "Marketplace photos must be PNG, JPEG, or WebP images." : "Museum analysis requires image files.");
      el(target === "art" ? "art-reference-input" : target === "animation_image" ? "animation-image-upload" : target === "sell" ? "marketplace-photo-input" : "antiques-camera-input").value = "";
      return;
    }
  }
  if (target === "animation_audio" && files.some((file) => !String(file.type || "").startsWith("audio/") && !/\.(?:aac|flac|m4a|mp3|ogg|wav)$/i.test(file.name))) {
    showError("Animation Studio requires WAV, M4A, MP3, FLAC, AAC, or OGG audio files.");
    el("animation-audio-upload").value = "";
    return;
  }
  if (target === "art") {
    const availableSlots = Math.max(0, 4 - state.artStudio.referenceIds.size);
    if (!availableSlots) {
      showError("Remove a reference before adding another. Art Studio supports up to four images.");
      el("art-reference-input").value = "";
      return;
    }
    if (files.length > availableSlots) {
      showError(`Only the first ${availableSlots} image${availableSlots === 1 ? "" : "s"} will be added; Art Studio supports four references.`);
      files = files.slice(0, availableSlots);
    }
  }
  state.uploading = true;
  state.uploadTarget = target;
  render();
  try {
    for (const file of files) {
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
      if (result.file?.file_id) {
        if (target === "email") state.emailAttachments.push(result.file);
        else if (target === "art") {
          state.artStudio.referenceIds.add(result.file.file_id);
          state.artStudio.previewReferenceId = result.file.file_id;
        }
        else if (target === "animation_image") addAnimationAssetFile(result.file);
        else if (target === "animation_audio") addAnimationAudioFile(result.file);
        else if (target === "sell") state.marketplace.selectedPhotoIds.add(result.file.file_id);
        else state.selectedFiles.add(result.file.file_id);
      }
    }
  } catch (error) {
    showError(error.message || String(error));
  } finally {
    state.uploading = false;
    state.uploadTarget = "";
    const inputId = target === "email" ? "email-file-input"
      : target === "art" ? "art-reference-input"
        : target === "museum" ? "antiques-camera-input"
          : target === "sell" ? "marketplace-photo-input"
          : target === "animation_image" ? "animation-image-upload"
            : target === "animation_audio" ? "animation-audio-upload" : "file-input";
    el(inputId).value = "";
    render();
    if (target === "art") renderArtStudio();
    if (target === "sell") {
      try { await loadMarketplace({ preserveSelection: true }); }
      catch (error) { showError(error.message || String(error)); }
    }
    if (["animation_image", "animation_audio"].includes(target)) renderAnimationStudio();
  }
}

el("attach-button").addEventListener("click", () => el("file-input").click());
el("file-input").addEventListener("change", (event) => uploadFiles(event.target.files, "chat"));
el("email-attach-button").addEventListener("click", () => el("email-file-input").click());
el("email-file-input").addEventListener("change", (event) => uploadFiles(event.target.files, "email"));

function isFileDrag(event) {
  return Array.from(event.dataTransfer?.types || []).includes("Files");
}

function bindFileDrop(target, uploadTarget, setActive) {
  let dragDepth = 0;
  target.addEventListener("dragenter", (event) => {
    if (!isFileDrag(event)) return;
    event.preventDefault();
    dragDepth += 1;
    setActive(true);
  });
  target.addEventListener("dragover", (event) => {
    if (!isFileDrag(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  });
  target.addEventListener("dragleave", (event) => {
    if (!isFileDrag(event)) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) setActive(false);
  });
  target.addEventListener("drop", (event) => {
    if (!isFileDrag(event)) return;
    event.preventDefault();
    dragDepth = 0;
    setActive(false);
    uploadFiles(event.dataTransfer.files, uploadTarget);
  });
}

bindFileDrop(el("chat-panel"), "chat", (active) => {
  el("chat-drop-overlay").hidden = !active;
});
bindFileDrop(el("email-drop-zone"), "email", (active) => {
  el("email-drop-zone").classList.toggle("drag-active", active);
});

async function navigateToRoom(roomId) {
  if (!roomId || roomId === state.session?.active_room || state.switchingRoom) return;
  state.switchingRoom = true;
  render();
  try {
    const result = await api("/api/rooms", {
      method: "POST",
      body: JSON.stringify({
        workspace_id: state.workspace.workspace_id,
        session_id: state.session.session_id,
        room_id: roomId,
      }),
    });
    applyState(result, true);
    state.route = result.route;
    state.route.notice = `Room changed: ${result.room_transition.room_title} · ${result.room_transition.active_persona}.`;
    if (state.session?.active_room === "my_office") window.setTimeout(checkDeliveryFailures, 0);
  } catch (error) {
    showError(error.message || String(error));
    await loadState(state.workspace.workspace_id, state.session.session_id, true);
  } finally {
    state.switchingRoom = false;
    render();
  }
}

el("room-selector").addEventListener("change", async (event) => {
  await navigateToRoom(event.target.value);
});

async function openImportantMail() {
  const alertIds = (state.monitor.mail?.alerts || []).filter((row) => !row.seen).map((row) => row.alert_id);
  if (state.session?.active_room !== "my_office") {
    await navigateToRoom("my_office");
    if (state.session?.active_room !== "my_office") return;
  }
  try {
    if (alertIds.length) {
      applyMonitorStatus(await api("/api/monitor/mail/seen", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: state.workspace.workspace_id,
          session_id: state.session.session_id,
          alert_ids: alertIds,
        }),
      }));
    }
    el("nancy-important-mail").scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (error) { showError(error.message || String(error)); }
}

function setGovernancePanel(open) {
  el("governance-panel").hidden = !open;
  el("governance-scrim").hidden = !open;
  el("navigator-status").setAttribute("aria-expanded", String(open));
}

function setAdministrationPanel(open) {
  el("administration-panel").hidden = !open;
  el("administration-scrim").hidden = !open;
  el("open-administration").setAttribute("aria-expanded", String(open));
}

async function refreshAdministration() {
  const result = await api("/api/admin");
  state.administration = result.administration || state.administration;
  renderAdministration();
  renderGovernance();
}

async function submitAdministrationProposal(event) {
  event.preventDefault();
  const kind = el("admin-kind").value;
  const action = el("admin-action").value;
  const title = el("admin-title").value.trim();
  const targetId = el("admin-target").value.trim();
  const statement = el("admin-statement").value.trim();
  const reason = el("admin-reason").value.trim();
  const payload = {};
  if (kind === "room") {
    if (action === "create") Object.assign(payload, { title, default_persona: el("admin-persona").value.trim() || "Room Steward", purpose: statement });
    else Object.assign(payload, { target_id: targetId, ...(statement ? { purpose: statement } : {}) });
  } else if (["rule", "gate"].includes(kind)) {
    if (action === "add") payload[kind === "rule" ? "text" : "definition"] = statement;
    else {
      payload.target_id = targetId;
      if (action === "amend") payload[kind === "rule" ? "text" : "definition"] = statement;
      if (action === "disable") payload.reason = reason;
    }
  } else {
    Object.assign(payload, {
      title,
      instructions: statement,
      allowed_paths: el("admin-paths").value.split(",").map((value) => value.trim()).filter(Boolean),
      tests: el("admin-tests").value.split(";;").map((value) => value.trim()).filter(Boolean),
    });
  }
  try {
    const result = await api("/api/admin/proposals", {
      method: "POST",
      body: JSON.stringify({
        workspace_id: state.workspace?.workspace_id,
        session_id: state.session?.session_id,
        kind,
        action,
        payload,
      }),
    });
    state.administration = result.administration;
    event.target.reset();
    updateAdministrationForm();
    renderAdministration();
    renderGovernance();
    showToast(`Proposal ${result.proposal.proposal_id} is ready for review.`);
  } catch (error) { showError(error.message || String(error)); }
}

async function handleAdministrationAction(event) {
  const button = event.target.closest("button[data-admin-action]");
  if (!button) return;
  const proposalId = button.dataset.proposalId;
  const action = button.dataset.adminAction;
  const proposal = (state.administration.proposals || []).find((row) => row.proposal_id === proposalId);
  if (!proposal) return;
  try {
    if (action === "approve") {
      const second = proposal.status === "awaiting_second_approval";
      const warning = second
        ? "Confirm this governance change a second time? It can weaken an active protection."
        : `Apply ${proposal.kind} ${proposal.action} proposal ${proposalId}?`;
      if (!window.confirm(warning)) return;
      const storageKey = `veridex-admin-token-${proposalId}`;
      const token = second ? (state.adminTokens[proposalId] || window.sessionStorage.getItem(storageKey) || "") : "";
      const result = await api("/api/admin/proposals/apply", {
        method: "POST",
        body: JSON.stringify({
          proposal_id: proposalId,
          expected_version: Number(button.dataset.expectedVersion || proposal.base_version || 0),
          confirm: true,
          second_confirmation_token: token,
        }),
      });
      if (result.status === "second_confirmation_required") {
        state.adminTokens[proposalId] = result.second_confirmation_token;
        window.sessionStorage.setItem(storageKey, result.second_confirmation_token);
        showToast("First approval recorded. Review Navigator's warning, then confirm again.");
      } else {
        window.sessionStorage.removeItem(storageKey);
        delete state.adminTokens[proposalId];
        showToast(`${proposalId} applied and verified.`);
      }
      await loadState(state.workspace.workspace_id, state.session.session_id, true);
      render();
    } else if (action === "reject") {
      if (!window.confirm(`Reject ${proposalId}? No change will be applied.`)) return;
      const result = await api("/api/admin/proposals/reject", { method: "POST", body: JSON.stringify({ proposal_id: proposalId, reason: "Rejected in Administration" }) });
      state.administration = result.administration;
      renderAdministration();
      renderGovernance();
    } else if (action === "rollback") {
      if (!window.confirm(`Rollback ${proposalId}? This restores the recorded prior version and will be audited.`)) return;
      const result = await api("/api/admin/proposals/rollback", { method: "POST", body: JSON.stringify({ proposal_id: proposalId, confirm: true }) });
      state.administration = result.administration;
      await loadState(state.workspace.workspace_id, state.session.session_id, true);
      render();
      showToast(`${proposalId} rolled back.`);
    }
  } catch (error) { showError(error.message || String(error)); }
}

el("navigator-status").addEventListener("click", () => setGovernancePanel(el("governance-panel").hidden));
el("important-mail-indicator").addEventListener("click", openImportantMail);
el("important-mail-indicator").addEventListener("animationend", (event) => event.currentTarget.classList.remove("is-flashing"));
el("startup-health-no").addEventListener("click", () => el("startup-health-dialog").close());
el("startup-health-yes").addEventListener("click", async () => {
  el("startup-health-dialog").close();
  await navigateToRoom("control_room");
});
el("startup-health-dialog").addEventListener("cancel", (event) => {
  event.preventDefault();
  el("startup-health-dialog").close();
});
el("governance-close").addEventListener("click", () => setGovernancePanel(false));
el("governance-scrim").addEventListener("click", () => setGovernancePanel(false));
el("open-administration").addEventListener("click", () => setAdministrationPanel(el("administration-panel").hidden));
el("governance-open-administration").addEventListener("click", () => { setGovernancePanel(false); setAdministrationPanel(true); });
el("administration-close").addEventListener("click", () => setAdministrationPanel(false));
el("administration-scrim").addEventListener("click", () => setAdministrationPanel(false));
el("administration-refresh").addEventListener("click", () => refreshAdministration().catch((error) => showError(error.message || String(error))));
el("administration-form").addEventListener("submit", submitAdministrationProposal);
el("admin-kind").addEventListener("change", updateAdministrationForm);
el("admin-action").addEventListener("change", updateAdministrationForm);
el("administration-proposal-list").addEventListener("click", handleAdministrationAction);

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

el("open-connected-accounts").addEventListener("click", openConnectedAccounts);
el("open-marketplace-sell").addEventListener("click", openMarketplaceSell);
el("marketplace-sell-close").addEventListener("click", () => el("marketplace-sell-dialog").close());
el("marketplace-sell-dialog").addEventListener("cancel", (event) => { event.preventDefault(); el("marketplace-sell-dialog").close(); });
el("marketplace-new-draft").addEventListener("click", clearMarketplaceForm);
el("marketplace-source-case").addEventListener("change", (event) => applyMarketplaceCase(event.target.value));
el("marketplace-add-photos").addEventListener("click", () => el("marketplace-photo-input").click());
el("marketplace-photo-input").addEventListener("change", (event) => uploadFiles(event.target.files, "sell"));
el("marketplace-research-help").addEventListener("click", researchMarketplacePhotos);
el("marketplace-save-draft").addEventListener("click", saveMarketplaceDraft);
el("marketplace-prepare").addEventListener("click", prepareMarketplaceListing);
el("marketplace-resume").addEventListener("click", resumeMarketplaceListing);
el("marketplace-prepare-group").addEventListener("click", prepareNextMarketplaceGroup);
el("marketplace-group-form").addEventListener("submit", saveMarketplaceGroup);
el("connected-accounts-close").addEventListener("click", () => el("connected-accounts-dialog").close());
el("connected-accounts-dialog").addEventListener("cancel", (event) => { event.preventDefault(); el("connected-accounts-dialog").close(); });
el("instagram-connect-form").addEventListener("submit", connectInstagram);
el("instagram-verify").addEventListener("click", () => integrationAction("/api/integrations/instagram/verify", "Instagram status refreshed."));
el("instagram-disconnect").addEventListener("click", () => integrationAction("/api/integrations/instagram/disconnect", "Instagram was unassigned. Its local browser profile was preserved."));
el("facebook-connect").addEventListener("click", connectFacebook);
el("facebook-refresh").addEventListener("click", () => integrationAction("/api/integrations/facebook/verify", "Facebook status refreshed."));
el("gmail-connect").addEventListener("click", connectGmail);
el("gmail-refresh").addEventListener("click", () => refreshConnectedAccounts("Gmail status refreshed.").catch((error) => { el("connected-accounts-message").textContent = error.message || String(error); }));
el("gmail-disconnect").addEventListener("click", () => integrationAction("/api/integrations/gmail/disconnect", "Gmail was unassigned from this workspace."));
el("ebay-connect").addEventListener("click", connectEbay);
el("ebay-refresh").addEventListener("click", () => refreshConnectedAccounts("eBay status refreshed.").catch((error) => { el("connected-accounts-message").textContent = error.message || String(error); }));
el("ebay-notifications-auto").addEventListener("click", toggleEbayAutomaticNotifications);
el("ebay-notifications-check").addEventListener("click", checkEbayNotifications);
el("ebay-disconnect").addEventListener("click", () => integrationAction("/api/integrations/ebay/disconnect", "eBay was disconnected from this workspace."));

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

api("/api/bootstrap").then((value) => {
  applyState(value);
  if (state.session?.active_room === "my_office") window.setTimeout(checkDeliveryFailures, 0);
  window.setTimeout(refreshBackgroundMonitor, 0);
}).catch((error) => showError(error.message || String(error)));
window.setInterval(() => {
  if (state.session?.active_room === "my_office") checkDeliveryFailures();
}, DELIVERY_POLL_INTERVAL_MS);
window.setInterval(refreshBackgroundMonitor, MONITOR_STATUS_POLL_INTERVAL_MS);
