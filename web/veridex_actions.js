/* Shared, non-destructive command menu for every Veridex browser surface. */
(() => {
  let mainMenu = "";
  const rootUrl = (menu = "") => {
    const query = new URLSearchParams(location.search);
    const next = new URLSearchParams();
    ["workspace_id", "session_id"].forEach((key) => { if (query.get(key)) next.set(key, query.get(key)); });
    if (menu) next.set("veridex_menu", menu);
    return `/${next.size ? `?${next}` : ""}`;
  };
  const rootSurface = () => Boolean(document.getElementById("room-selector"));
  const close = () => {
    const panel = document.getElementById("veridex-action-menu");
    const trigger = document.getElementById("veridex-action-trigger");
    if (!panel || !trigger) return;
    panel.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
    if (mainMenu) panel.querySelector(".veridex-action-menu-body").innerHTML = mainMenu;
  };
  const rooms = (panel) => {
    const selector = document.getElementById("room-selector");
    if (!selector) { location.href = rootUrl("rooms"); return; }
    const body = panel.querySelector(".veridex-action-menu-body");
    body.replaceChildren();
    const back = document.createElement("button");
    back.type = "button"; back.dataset.veridexAction = "back"; back.textContent = "← Back";
    body.append(back);
    const label = document.createElement("p");
    label.className = "veridex-menu-label"; label.textContent = selector.disabled ? "Room switching is temporarily unavailable" : "Choose a room";
    body.append(label);
    const list = document.createElement("div"); list.className = "veridex-room-list";
    [...selector.options].forEach((option) => {
      const button = document.createElement("button");
      button.type = "button"; button.textContent = option.textContent;
      button.disabled = selector.disabled || option.disabled;
      if (option.value === selector.value) button.setAttribute("aria-current", "true");
      button.addEventListener("click", () => {
        if (selector.disabled) return;
        selector.value = option.value;
        close();
        selector.dispatchEvent(new Event("change", { bubbles: true }));
      });
      list.append(button);
    });
    if (!selector.options.length) label.textContent = "Rooms are loading. Try again shortly.";
    body.append(list);
  };
  const navigationList = (panel, kind) => {
    if (!rootSurface()) { location.href = rootUrl(kind); return; }
    const isWorkspace = kind === "workspaces";
    const sourceList = document.getElementById(isWorkspace ? "workspace-list" : "session-list");
    const sourceNew = document.getElementById(isWorkspace ? "new-workspace" : "new-session");
    const body = panel.querySelector(".veridex-action-menu-body");
    body.replaceChildren();
    const back = document.createElement("button");
    back.type = "button"; back.dataset.veridexAction = "back"; back.textContent = "← Back";
    body.append(back);
    const label = document.createElement("p"); label.className = "veridex-menu-label";
    label.textContent = isWorkspace ? "Choose a workspace" : "Choose a session";
    body.append(label);
    const add = document.createElement("button"); add.type = "button";
    add.textContent = isWorkspace ? "New workspace" : "New session";
    add.disabled = !sourceNew || sourceNew.disabled;
    add.addEventListener("click", () => { close(); if (sourceNew?.isConnected && !sourceNew.disabled) sourceNew.click(); });
    body.append(add);
    const list = document.createElement("div"); list.className = "veridex-room-list";
    const items = sourceList ? [...sourceList.querySelectorAll("button.nav-item")] : [];
    items.forEach((source) => {
      const button = document.createElement("button"); button.type = "button";
      button.textContent = source.textContent; button.disabled = source.disabled;
      if (source.classList.contains("active")) button.setAttribute("aria-current", "true");
      button.addEventListener("click", () => { close(); if (source.isConnected && !source.disabled) source.click(); });
      list.append(button);
    });
    if (!items.length) { const empty = document.createElement("p"); empty.className = "veridex-menu-label"; empty.textContent = "No items available yet."; list.append(empty); }
    body.append(list);
  };
  const goOffice = async (mode) => {
    if (!rootSurface()) { location.href = rootUrl(mode); return; }
    if (typeof window.navigateToRoom === "function") await window.navigateToRoom("my_office");
    if (mode === "email" && typeof window.openEmailComposer === "function") window.openEmailComposer();
    if (mode === "calendar") {
      const input = document.getElementById("message-input");
      if (input) { input.value = "Nancy, help me with my calendar."; input.focus(); }
    }
  };
  const act = async (action, panel) => {
    if (action === "rooms") { rooms(panel); return; }
    if (action === "workspaces" || action === "sessions") { navigationList(panel, action); return; }
    if (action === "back") { panel.querySelector(".veridex-action-menu-body").innerHTML = mainMenu; return; }
    if (action === "email" || action === "calendar") { close(); return goOffice(action); }
    if (action === "system") {
      if (!rootSurface()) { location.href = rootUrl("system"); return; }
      close(); document.getElementById("open-system-log")?.click(); return;
    }
    if (action === "navigator") {
      if (!rootSurface()) { location.href = rootUrl("navigator"); return; }
      close(); document.getElementById("navigator-status")?.click(); return;
    }
    if (action === "file") {
      if (!rootSurface()) { location.href = rootUrl("file"); return; }
      close(); document.getElementById("file-input")?.click();
    }
  };
  const build = () => {
    const existingTrigger = document.getElementById("veridex-action-trigger");
    if (existingTrigger?.dataset.veridexActionsReady) return;
    const style = document.createElement("style");
    style.textContent = `.veridex-command{position:fixed;z-index:100;top:16px;right:18px}.veridex-action-trigger{width:42px;height:42px;display:grid;place-items:center;border:1px solid #315d3d;border-radius:8px;padding:0;color:#3dd06f;background:#18251d;box-shadow:0 9px 24px rgba(14,31,20,.2);font:700 22px/1 Georgia,serif}.veridex-action-trigger:hover,.veridex-action-trigger[aria-expanded="true"]{color:#fff;border-color:#3dd06f;background:#146331}.veridex-action-trigger:focus-visible,.veridex-action-menu button:focus-visible{outline:3px solid #8ce8a8;outline-offset:2px}.veridex-action-menu{position:absolute;top:50px;right:0;width:min(310px,calc(100vw - 28px));overflow:hidden;border:1px solid #cdd8cf;border-radius:12px;background:#fff;box-shadow:0 18px 44px rgba(15,31,21,.24);animation:veridex-menu-in 140ms ease both}.veridex-action-menu[hidden]{display:none}.veridex-action-menu header{display:flex;align-items:center;justify-content:space-between;padding:13px 14px 10px;border-bottom:1px solid #dce2dc;font:600 18px/1 Georgia,serif}.veridex-action-menu header button{border:0;padding:0 4px;color:#667069;background:transparent;font-size:22px}.veridex-action-menu-body{display:grid;padding:7px}.veridex-action-menu-body>button,.veridex-room-list button{display:grid;gap:2px;width:100%;border:0;border-radius:8px;padding:10px 11px;color:#172019;background:transparent;text-align:left}.veridex-action-menu-body>button:hover,.veridex-room-list button:hover{background:#eef7ef}.veridex-action-menu-body span{font-size:13px;font-weight:800}.veridex-action-menu-body small{color:#667069;font-size:11px}.veridex-menu-label{margin:4px 5px 8px;color:#667069;font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.08em}.veridex-room-list{display:grid;gap:3px;max-height:min(48vh,370px);overflow:auto}.veridex-room-list button{border:1px solid transparent;font-size:12px;font-weight:700}@keyframes veridex-menu-in{from{opacity:0;transform:translateY(-5px) scale(.98)}to{opacity:1;transform:translateY(0) scale(1)}}`;
    style.textContent += `.rail .veridex-action-menu{position:fixed;z-index:110;top:18px;left:280px;right:auto;direction:ltr;text-align:left}.veridex-action-menu *{box-sizing:border-box}.veridex-action-menu header strong{color:#172019;font:600 18px/1.1 Georgia,serif}.veridex-action-menu-body>button{min-height:52px;align-content:center;line-height:1.2;white-space:normal;overflow-wrap:anywhere}.veridex-action-menu-body span{display:block;line-height:1.2}.veridex-action-menu-body small{display:block;margin-top:3px;line-height:1.35}.veridex-room-list button{line-height:1.35;white-space:normal;overflow-wrap:anywhere}@media(max-width:760px){.rail .veridex-action-menu{top:58px;left:12px;right:auto}}`;
    style.textContent += `.veridex-action-menu{max-height:calc(100dvh - 84px);overflow-y:auto;overscroll-behavior:contain}.rail .veridex-action-menu{max-height:calc(100dvh - 36px)}@media(max-width:760px){.rail .veridex-action-menu{max-height:calc(100dvh - 72px)}}`;
    style.textContent += `.veridex-menu-account{display:flex;align-items:center;gap:7px;margin-top:5px;color:#667069;font:600 10px/1.2 system-ui,sans-serif}.veridex-menu-account .presence-dot{width:7px;height:7px;display:inline-block;border-radius:50%;background:#3dd06f;box-shadow:0 0 0 3px rgba(61,208,111,.14)}.veridex-menu-account small{display:block;margin-top:2px;color:#87918a;font-size:9px;font-weight:500}`;
    style.textContent += `@media(max-width:760px){.veridex-action-menu{max-height:calc(100dvh - 72px);overflow-y:auto}.veridex-room-list{max-height:min(48dvh,370px);overscroll-behavior:contain}}.veridex-room-list button[aria-current="true"]{background:#eef7ef}.veridex-room-list button:disabled{opacity:.5}`;
    document.head.append(style);
    const shell = existingTrigger ? existingTrigger.closest(".brand-block") : document.createElement("div");
    if (!existingTrigger) {
      shell.className = "veridex-command";
      shell.innerHTML = `<button id="veridex-action-trigger" class="veridex-action-trigger" type="button" aria-label="Open Veridex actions" aria-expanded="false" aria-controls="veridex-action-menu">V</button>`;
      document.body.append(shell);
    }
    shell.insertAdjacentHTML("beforeend", `<section id="veridex-action-menu" class="veridex-action-menu" aria-label="Veridex actions" hidden><header><strong>Veridex</strong><button type="button" data-veridex-close aria-label="Close actions">×</button></header><div class="veridex-action-menu-body"><button type="button" data-veridex-action="rooms"><span>Rooms</span><small>Choose a room</small></button><button type="button" data-veridex-action="workspaces"><span>Workspaces</span><small>Choose or create a workspace</small></button><button type="button" data-veridex-action="sessions"><span>Sessions</span><small>Choose or create a session</small></button><button type="button" data-veridex-action="email"><span>Email</span><small>Open Nancy’s composer</small></button><button type="button" data-veridex-action="calendar"><span>Calendar</span><small>Ask Nancy about your schedule</small></button><button type="button" data-veridex-action="navigator"><span>Navigator</span><small>Open governance status</small></button><button type="button" data-veridex-action="system"><span>System</span><small>View room changes and system notices</small></button><button type="button" data-veridex-action="file"><span>Add file</span><small>Save to this session’s archive</small></button></div></section>`);
    const panel = shell.querySelector("#veridex-action-menu");
    mainMenu = panel.querySelector(".veridex-action-menu-body").innerHTML;
    const menuHeader = panel?.querySelector("header");
    const menuBrand = menuHeader?.querySelector("strong");
    if (menuBrand && !menuHeader.querySelector(".veridex-menu-account")) {
      const account = document.createElement("div");
      account.className = "veridex-menu-account";
      account.innerHTML = `<span class="presence-dot" aria-hidden="true"></span><span>Local User<small>Single account · saved locally</small></span>`;
      menuBrand.parentElement.append(account);
    }
    const trigger = document.getElementById("veridex-action-trigger");
    trigger.dataset.veridexActionsReady = "true";
    trigger.addEventListener("click", () => { const open = panel.hidden; panel.hidden = !open; trigger.setAttribute("aria-expanded", String(open)); });
    shell.querySelector("[data-veridex-close]").addEventListener("click", close);
    panel.addEventListener("click", (event) => { const button = event.target.closest("[data-veridex-action]"); if (button) act(button.dataset.veridexAction, panel); });
    document.addEventListener("click", (event) => { if (!event.composedPath().includes(shell)) close(); });
    document.addEventListener("keydown", (event) => { if (event.key === "Escape") close(); });
    const railCollapse = document.getElementById("rail-collapse");
    railCollapse?.addEventListener("click", () => {
      const app = document.querySelector(".app-shell"), collapsed = app?.classList.toggle("rail-collapsed");
      railCollapse.setAttribute("aria-expanded", String(!collapsed));
      railCollapse.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
      railCollapse.querySelector(".sr-only").textContent = collapsed ? "Expand sidebar" : "Collapse sidebar";
    });
    const requested = query.get("veridex_menu");
    if (requested) window.setTimeout(() => { panel.hidden = false; trigger.setAttribute("aria-expanded", "true"); if (requested === "rooms") rooms(panel); else act(requested, panel); }, 550);
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", build); else build();
})();
