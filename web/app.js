const AUTO_READ_STORAGE_KEY = "veridex.readAutomatically";
const DELIVERY_POLL_INTERVAL_MS = 15_000;
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
  artImages: [],
  artImagesLoading: false,
  artImagesLoaded: false,
  selectedArtImageId: "",
  attachingArtImageId: "",
  roomFiles: [],
  roomFilesLoading: false,
  roomFilesRoomId: "",
  selectedRoomFileId: "",
  attachingRoomFileId: "",
  deliveryAlerts: [],
  governance: {},
  selectedFiles: new Set(),
  emailAttachments: [],
  runtime: { access_mode: "read_only", access_label: "Read-only computer access" },
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
  if (sessionChanged) {
    state.selectedFiles.clear();
    state.emailAttachments = [];
    state.deliveryAlerts = [];
  }
  if (workspaceChanged) {
    state.artImages = [];
    state.artImagesLoaded = false;
    state.selectedArtImageId = "";
    state.roomFiles = [];
    state.roomFilesRoomId = "";
    state.selectedRoomFileId = "";
    state.resume.loaded = false;
    state.resume.profile = null;
    state.resume.projects = [];
    state.resume.draft = null;
    state.resume.review = null;
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
  const result = await api("/api/contacts");
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
      body: JSON.stringify({ contact_id: contact.contact_id }),
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
    const result = await api("/api/contacts/sync", { method: "POST", body: "{}" });
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
    session_id: image.source_session_id,
    file_id: image.file_id,
  });
  return `/api/files/content?${query}`;
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
    : `${state.artImages.length} verified ${state.artImages.length === 1 ? "image" : "images"} across Art Department sessions`;
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
  if (!isArtDepartment && el("art-gallery-dialog").open) closeArtGallery();
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

  const provenance = el("governance-provenance");
  provenance.replaceChildren();
  (governance.provenance || []).forEach((path) => {
    const row = document.createElement("div");
    row.textContent = path;
    provenance.append(row);
  });
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
  const deterministic = ["veridex_router", "veridex_governance", "veridex_google_router", "veridex_gmail_router"].includes(state.route.provider);
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
    : "Read-only computer access · attach files or restart with -FullAccess · transcripts stay here";
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
  renderEmailTools();
  renderArtTools();
  renderRoomFileTools();
  renderResumeTools();
  renderGovernance();
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
  if (state.session?.active_room === "my_office") {
    const alertQuery = new URLSearchParams({
      workspace_id: state.workspace.workspace_id,
      session_id: state.session.session_id,
    });
    const result = await api(`/api/mail/alerts?${alertQuery}`);
    state.deliveryAlerts = result.alerts || [];
    renderDeliveryAlerts();
  }
}

function routeNotice(next) {
  if (["veridex_router", "veridex_governance", "veridex_google_router", "veridex_gmail_router"].includes(next.provider)) return "Handled deterministically by Veridex governance; no model call was needed.";
  if (!state.route) return `Model selected: ${next.model} · ${next.reasoning_effort} reasoning.`;
  if (state.route.model !== next.model || state.route.reasoning_effort !== next.reasoning_effort) {
    return `Model changed: ${state.route.model} → ${next.model} · ${next.reasoning_effort} reasoning.`;
  }
  if (state.route.task_type !== next.task_type) {
    return `Task route changed: ${state.route.task_type.replaceAll("_", " ")} → ${next.task_type.replaceAll("_", " ")}.`;
  }
  return `Continuing with ${next.model} · ${next.reasoning_effort} reasoning.`;
}

async function sendMessage(text, { attachments, emailDraft } = {}) {
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
  const files = [...fileList].filter((file) => file instanceof File);
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
        else state.selectedFiles.add(result.file.file_id);
      }
    }
  } catch (error) {
    showError(error.message || String(error));
  } finally {
    state.uploading = false;
    state.uploadTarget = "";
    el(target === "email" ? "email-file-input" : "file-input").value = "";
    render();
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

el("room-selector").addEventListener("change", async (event) => {
  const roomId = event.target.value;
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
});

function setGovernancePanel(open) {
  el("governance-panel").hidden = !open;
  el("governance-scrim").hidden = !open;
  el("navigator-status").setAttribute("aria-expanded", String(open));
}

el("navigator-status").addEventListener("click", () => setGovernancePanel(el("governance-panel").hidden));
el("governance-close").addEventListener("click", () => setGovernancePanel(false));
el("governance-scrim").addEventListener("click", () => setGovernancePanel(false));

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

api("/api/bootstrap").then((value) => {
  applyState(value);
  if (state.session?.active_room === "my_office") window.setTimeout(checkDeliveryFailures, 0);
}).catch((error) => showError(error.message || String(error)));
window.setInterval(() => {
  if (state.session?.active_room === "my_office") checkDeliveryFailures();
}, DELIVERY_POLL_INTERVAL_MS);
