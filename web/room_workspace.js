(() => {
  const main = document.getElementById('chat-panel');
  const messages = document.getElementById('messages');
  const composer = main.querySelector('.composer-wrap');
  const workspace = document.createElement('section');
  workspace.className = 'video-workspace room-workspace';
  workspace.innerHTML = `<header class="video-workspace-bar"><div class="room-workspace-heading"><span class="eyebrow" data-room-name></span><h2 data-title>Workspace</h2></div><nav data-actions aria-label="Room actions"></nav><button data-chat type="button"></button></header><div data-content class="room-workspace-content"><div data-overview class="room-workspace-overview"></div><div data-media hidden></div></div>`;
  main.querySelector('.workspace-toolbar').after(workspace);
  main.classList.add('video-production-active');
  const q = selector => workspace.querySelector(selector);
  const chat = document.createElement('section');
  chat.className = 'video-floating-chat room-floating-chat';
  chat.hidden = true;
  chat.innerHTML = '<header data-drag><button type="button" data-model aria-label="Chat model" aria-haspopup="dialog" aria-expanded="false" aria-controls="chat-model-picker" title="Choose model and reasoning"></button><strong data-chat-title></strong><div class="chat-window-controls"><button data-minimize type="button" aria-label="Minimize chat" title="Minimize">&#x2212;</button><button data-maximize type="button" aria-label="Maximize chat" title="Maximize">&#x25a1;</button><button data-close type="button" title="Close">&#xd7;</button></div></header>';
  const modelSelect = chat.querySelector('[data-model]');
  const modelSelections = new Map();
  let models = {default_model:'Automatic', choices:[]};
  let modelScope = '';
  let automaticLabel = 'Automatic (default)';
  const picker = document.createElement('div');
  picker.id = 'chat-model-picker'; picker.className = 'chat-model-picker'; picker.hidden = true;
  picker.setAttribute('role', 'dialog'); picker.setAttribute('aria-label', 'Model and reasoning');
  picker.innerHTML = '<section data-model-list aria-label="Models"></section><section data-reasoning aria-label="Reasoning options"></section>';
  document.body.append(picker);
  const effortLabels = {low:'Low',medium:'Medium',high:'High',xhigh:'Extra high',max:'Max'};
  function closePicker() { picker.hidden = true; modelSelect.setAttribute('aria-expanded','false'); }
  function renderModelControl() {
    const selected = modelSelections.get(modelScope);
    const choice = models.choices.find(row => row.id === selected?.id);
    modelSelect.textContent = choice ? `${choice.label} \u00b7 ${effortLabels[selected.reasoning] || selected.reasoning || 'Provider default'} \u25be` : `${automaticLabel} \u25be`;
  }
  function chooseModel(id, reasoning='') {
    modelSelections.set(modelScope, {id, reasoning}); renderModelControl(); closePicker(); modelSelect.focus();
  }
  function showReasoning(choice, sourceButton) {
    picker.querySelectorAll('[data-model-list] button').forEach(button => button.setAttribute('aria-expanded', String(button === sourceButton)));
    const panel = picker.querySelector('[data-reasoning]'); panel.replaceChildren();
    const title = document.createElement('strong'); title.textContent = choice.label; panel.append(title);
    const options = choice.reasoning_options || [];
    if (!options.length) {
      const note = document.createElement('p'); note.textContent = choice.id === 'default' ? 'Model and reasoning follow automatic task routing.' : 'Reasoning is not adjustable through this provider.'; panel.append(note);
      const use = document.createElement('button'); use.type='button'; use.textContent=choice.id === 'default' ? 'Use default' : 'Use model'; use.onclick=()=>chooseModel(choice.id); panel.append(use);
    }
    for (const effort of options) {
      const button = document.createElement('button'); button.type='button';
      button.textContent = `${effortLabels[effort] || effort}${effort === choice.default_reasoning ? ' (default)' : ''}`;
      const selected = modelSelections.get(modelScope);
      button.setAttribute('aria-pressed', String(selected?.id === choice.id && (selected.reasoning || choice.default_reasoning) === effort));
      button.onclick = () => chooseModel(choice.id, effort); panel.append(button);
    }
  }
  modelSelect.onclick = () => {
    if (!picker.hidden) { closePicker(); return; }
    const list = picker.querySelector('[data-model-list]'); list.replaceChildren();
    const selected = modelSelections.get(modelScope)?.id || 'default';
    let first;
    for (const choice of [{id:'default',label:automaticLabel,available:true}, ...models.choices]) {
      const button = document.createElement('button'); button.type='button'; button.textContent = `${choice.label} \u203a`;
      button.disabled = !choice.available; button.setAttribute('aria-expanded','false');
      button.onclick = () => showReasoning(choice, button); list.append(button);
      if (choice.id === selected) first = {choice,button};
    }
    picker.hidden = false; modelSelect.setAttribute('aria-expanded','true');
    if (first) { showReasoning(first.choice, first.button); first.button.focus(); }
    const rect = modelSelect.getBoundingClientRect();
    picker.style.left = Math.max(8,Math.min(rect.left,innerWidth-picker.offsetWidth-8))+'px';
    picker.style.top = Math.max(8,Math.min(rect.bottom+4,innerHeight-picker.offsetHeight-8))+'px';
  };
  document.addEventListener('pointerdown', event => { if (!picker.contains(event.target) && !modelSelect.contains(event.target)) closePicker(); });
  picker.addEventListener('keydown', event => { if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); closePicker(); modelSelect.focus(); } });
  window.addEventListener('resize', closePicker);
  api('/api/chat/models').then(value => { models = value; window.renderRoomWorkspace?.(); }).catch(() => { modelSelect.title = 'Model choices could not be loaded. Default routing remains active.'; });
  let restoreStyle = '';
  function restoreWindow() {
    chat.classList.remove('is-maximized', 'is-minimized'); chat.style.cssText = restoreStyle;
    const button = chat.querySelector('[data-maximize]');
    button.setAttribute('aria-label', 'Maximize chat'); button.title = 'Maximize'; button.textContent = '\u25a1';
  }
  chat.querySelector('[data-minimize]').onclick = () => { chat.classList.remove('is-maximized'); chat.classList.add('is-minimized'); };
  chat.querySelector('[data-maximize]').onclick = () => {
    if (chat.classList.contains('is-maximized')) restoreWindow();
    else { if (!chat.classList.contains('is-minimized')) restoreStyle = chat.style.cssText; chat.classList.remove('is-minimized'); chat.classList.add('is-maximized'); }
    const maximized = chat.classList.contains('is-maximized');
    chat.querySelector('[data-maximize]').setAttribute('aria-label', maximized ? 'Restore chat' : 'Maximize chat');
    chat.querySelector('[data-maximize]').title = maximized ? 'Restore' : 'Maximize';
    chat.querySelector('[data-maximize]').textContent = maximized ? '\u2750' : '\u25a1';
  };
  document.body.append(chat);
  chat.append(messages, composer);
  bindFileDrop(chat, 'chat', active => chat.classList.toggle('drag-active', active));
  chat.addEventListener('paste', pasteBettingImages);
  const attach = document.createElement('button');
  attach.type = 'button'; attach.textContent = 'Attach';
  attach.title = 'Attach files to the next chat message';
  attach.onclick = () => document.getElementById('file-input').click();
  document.getElementById('composer').prepend(attach);
  function openChat() { if (chat.classList.contains('is-minimized')) restoreWindow(); chat.hidden = false; messages.scrollTop = messages.scrollHeight; document.getElementById('message-input').focus(); }
  function closeChat() { closePicker(); chat.hidden = true; q('[data-chat]').focus(); }
  q('[data-chat]').onclick = openChat;
  chat.querySelector('[data-close]').onclick = closeChat;
  chat.addEventListener('keydown', event => { if (event.key === 'Escape') { event.preventDefault(); closeChat(); } });
  let drag;
  const clampChat = () => {
    if (!chat.style.left || chat.classList.contains('is-maximized') || innerWidth < 760) return;
    chat.style.left = Math.max(0, Math.min(parseFloat(chat.style.left), innerWidth - chat.offsetWidth)) + 'px';
    chat.style.top = Math.max(0, Math.min(parseFloat(chat.style.top) || 0, innerHeight - 60)) + 'px';
  };
  const handle = chat.querySelector('[data-drag]');
  handle.addEventListener('pointerdown', event => {
    if (event.target.closest('button, select') || chat.classList.contains('is-maximized') || innerWidth < 760) return;
    const rect = chat.getBoundingClientRect();
    drag = {x:event.clientX - rect.left, y:event.clientY - rect.top}; handle.setPointerCapture(event.pointerId);
  });
  handle.addEventListener('pointermove', event => {
    if (!drag) return;
    chat.style.left = (event.clientX - drag.x) + 'px'; chat.style.top = (event.clientY - drag.y) + 'px';
    chat.style.right = 'auto'; chat.style.bottom = 'auto'; clampChat();
  });
  handle.addEventListener('pointerup', () => drag = null);
  handle.addEventListener('lostpointercapture', () => drag = null);
  window.addEventListener('resize', clampChat);
  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(clampChat).observe(chat);

  const actionIds = ['room-file-actions', 'art-actions', 'antiques-actions', 'animation-actions', 'resume-actions', 'betting-actions'];
  actionIds.forEach(id => q('[data-actions]').append(document.getElementById(id)));
  function action(label, handler) {
    const button = document.createElement('button'); button.type = 'button'; button.textContent = label;
    button.onclick = handler; q('[data-actions]').append(button); return button;
  }
  const logs = action('View logs', () => document.getElementById('open-system-log').click());
  const governance = action('Governance', () => document.getElementById('navigator-status').click());
  const administration = action('Administration', () => document.getElementById('open-administration').click());
  const ebay = action('eBay workspace', () => document.getElementById('open-ebay-room').click());
  const intake = document.createElement('a'); intake.textContent = 'Item Intake'; q('[data-actions]').append(intake);

  const mail = document.createElement('dialog'); mail.className = 'room-email-dialog';
  mail.setAttribute('aria-label', 'Nancy Mail');
  mail.innerHTML = '<header><h2>Email</h2><button type="button">Close</button></header><p>Read important mail, compose a message, or open your address book.</p>';
  mail.querySelector('button').onclick = () => mail.close();
  document.body.append(mail);
  ['nancy-important-mail', 'delivery-alerts', 'email-actions'].forEach(id => mail.append(document.getElementById(id)));
  const email = action('Email', () => mail.showModal());
  const calendar = action('Calendar · Not implemented', () => {});
  calendar.disabled = true; calendar.title = 'Calendar integration is not implemented';
  let scope = '', jobsVisible = false;
  function showJobs(visible=true) {
    jobsVisible=visible;
    const video=currentRoom()?.id==='video_production';
    q('[data-media]').hidden=!video || jobsVisible;
    q('[data-overview]').hidden=video && !jobsVisible;
  }
  window.roomWorkspace = {mediaMount:q('[data-media]'), openChat, showJobs, chatModel:() => modelSelections.get(modelScope)?.id || 'default', chatReasoning:() => modelSelections.get(modelScope)?.reasoning || '', openEmail:() => { if (!mail.open) mail.showModal(); }};
  window.renderRoomWorkspace = () => {
    const room = currentRoom();
    if (!room || !state.session) return;
    const nextScope = `${state.workspace?.workspace_id}/${state.session.session_id}/${room.id}`;
    if (nextScope !== scope) { closePicker(); chat.hidden = true; drag = null; jobsVisible = false; if (mail.open) mail.close(); scope = nextScope; }
    modelScope = nextScope;
    const routedModel = ['codex_cli','gemini_api'].includes(state.route?.provider) && state.route.model && state.route.model !== 'deterministic' ? state.route.model : models.default_model;
    automaticLabel = `${routedModel} (default)`;
    renderModelControl();
    modelSelect.disabled = Boolean(state.sending || state.uploading || state.switchingRoom);
    if (modelSelect.disabled) closePicker();
    const persona = state.session.active_persona || room.default_persona;
    workspace.setAttribute('aria-label', `${room.title} workspace`);
    q('[data-room-name]').textContent = room.title;
    q('[data-title]').textContent = room.id === 'video_production' ? 'Media workspace' : 'Workspace';
    q('[data-chat]').textContent = `Chat with ${persona}`;
    chat.setAttribute('aria-label', `${persona} chat`);
    chat.querySelector('[data-chat-title]').textContent = `${persona} · ${room.title}`;
    chat.querySelector('[data-close]').setAttribute('aria-label', `Close ${persona} chat`);
    showJobs(jobsVisible);
    logs.hidden = !['control_room', 'infrastructure_room'].includes(room.id);
    governance.hidden = room.id !== 'control_room';
    administration.hidden = room.id !== 'infrastructure_room';
    ebay.hidden = intake.hidden = room.id !== 'ebay';
    intake.href = document.getElementById('open-item-intake').href;
    email.hidden = calendar.hidden = room.id !== 'my_office';
    const busy = state.sending || state.uploading || state.switchingRoom;
    [logs, governance, administration, ebay, email].forEach(button => button.disabled = busy);
    intake.setAttribute('aria-disabled', String(Boolean(busy)));
    intake.onclick = event => { if (busy) event.preventDefault(); };
  };
  window.renderRoomWorkspace();
})();
