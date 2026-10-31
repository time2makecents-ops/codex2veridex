/* Shared, non-destructive command menu for every Veridex browser surface. */
(() => {
  const query = new URLSearchParams(location.search);
  const rootUrl = (menu = "") => {
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
  };
  const rooms = (panel) => {
    const selector = document.getElementById("room-selector");
    if (!selector) { location.href = rootUrl("rooms"); return; }
    panel.querySelector(".veridex-action-menu-body").innerHTML = `<p class="veridex-menu-label">Choose a room</p><div class="veridex-room-list">${[...selector.options].map((option) => `<button type="button" data-veridex-room="${option.value}">${option.textContent}</button>`).join("")}</div>`;
    panel.querySelectorAll("[data-veridex-room]").forEach((button) => button.addEventListener("click", async () => {
      close();
      if (typeof window.navigateToRoom === "function") await window.navigateToRoom(button.dataset.veridexRoom);
    }));
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
    if (action === "rooms") return rooms(panel);
    if (action === "email" || action === "calendar") { close(); return goOffice(action); }
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
    if (document.getElementById("veridex-action-trigger")) return;
    const style = document.createElement("style");
    style.textContent = `.veridex-command{position:fixed;z-index:100;top:16px;right:18px}.veridex-action-trigger{width:42px;height:42px;display:grid;place-items:center;border:1px solid #315d3d;border-radius:8px;padding:0;color:#3dd06f;background:#18251d;box-shadow:0 9px 24px rgba(14,31,20,.2);font:700 22px/1 Georgia,serif}.veridex-action-trigger:hover,.veridex-action-trigger[aria-expanded="true"]{color:#fff;border-color:#3dd06f;background:#146331}.veridex-action-trigger:focus-visible,.veridex-action-menu button:focus-visible{outline:3px solid #8ce8a8;outline-offset:2px}.veridex-action-menu{position:absolute;top:50px;right:0;width:min(310px,calc(100vw - 28px));overflow:hidden;border:1px solid #cdd8cf;border-radius:12px;background:#fff;box-shadow:0 18px 44px rgba(15,31,21,.24);animation:veridex-menu-in 140ms ease both}.veridex-action-menu[hidden]{display:none}.veridex-action-menu header{display:flex;align-items:center;justify-content:space-between;padding:13px 14px 10px;border-bottom:1px solid #dce2dc;font:600 18px/1 Georgia,serif}.veridex-action-menu header button{border:0;padding:0 4px;color:#667069;background:transparent;font-size:22px}.veridex-action-menu-body{display:grid;padding:7px}.veridex-action-menu-body>button,.veridex-room-list button{display:grid;gap:2px;width:100%;border:0;border-radius:8px;padding:10px 11px;color:#172019;background:transparent;text-align:left}.veridex-action-menu-body>button:hover,.veridex-room-list button:hover{background:#eef7ef}.veridex-action-menu-body span{font-size:13px;font-weight:800}.veridex-action-menu-body small{color:#667069;font-size:11px}.veridex-menu-label{margin:4px 5px 8px;color:#667069;font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.08em}.veridex-room-list{display:grid;gap:3px;max-height:min(48vh,370px);overflow:auto}.veridex-room-list button{border:1px solid transparent;font-size:12px;font-weight:700}@keyframes veridex-menu-in{from{opacity:0;transform:translateY(-5px) scale(.98)}to{opacity:1;transform:translateY(0) scale(1)}}`;
    document.head.append(style);
    const shell = document.createElement("div");
    shell.className = "veridex-command";
    shell.innerHTML = `<button id="veridex-action-trigger" class="veridex-action-trigger" type="button" aria-label="Open Veridex actions" aria-expanded="false" aria-controls="veridex-action-menu">V</button><section id="veridex-action-menu" class="veridex-action-menu" aria-label="Veridex actions" hidden><header><strong>Veridex</strong><button type="button" data-veridex-close aria-label="Close actions">×</button></header><div class="veridex-action-menu-body"><button type="button" data-veridex-action="rooms"><span>Rooms</span><small>Choose where to work</small></button><button type="button" data-veridex-action="email"><span>Email</span><small>Open Nancy’s composer</small></button><button type="button" data-veridex-action="calendar"><span>Calendar</span><small>Ask Nancy about your schedule</small></button><button type="button" data-veridex-action="navigator"><span>Navigator</span><small>Open governance status</small></button><button type="button" data-veridex-action="file"><span>Add file</span><small>Save to this session’s archive</small></button></div></section>`;
    document.body.append(shell);
    const trigger = shell.querySelector("#veridex-action-trigger"), panel = shell.querySelector("#veridex-action-menu");
    trigger.addEventListener("click", () => { const open = panel.hidden; panel.hidden = !open; trigger.setAttribute("aria-expanded", String(open)); });
    shell.querySelector("[data-veridex-close]").addEventListener("click", close);
    shell.querySelectorAll("[data-veridex-action]").forEach((button) => button.addEventListener("click", () => act(button.dataset.veridexAction, panel)));
    document.addEventListener("click", (event) => { if (!shell.contains(event.target)) close(); });
    document.addEventListener("keydown", (event) => { if (event.key === "Escape") close(); });
    const requested = query.get("veridex_menu");
    if (requested) window.setTimeout(() => { panel.hidden = false; trigger.setAttribute("aria-expanded", "true"); if (requested === "rooms") rooms(panel); else act(requested, panel); }, 550);
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", build); else build();
})();
