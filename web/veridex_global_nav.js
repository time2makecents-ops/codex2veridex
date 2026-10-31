(() => {
  if (document.querySelector(".rail")) return;

  const style = document.createElement("style");
  style.textContent = `.veridex-global-nav{position:fixed;z-index:120;inset:0 auto 0 0;width:280px;direction:rtl;background:#18251d;color:#fff;padding:24px 46px 18px 18px;display:flex;flex-direction:column;min-height:0;overflow-y:auto;scrollbar-color:#597362 #132119;scrollbar-width:thin;box-shadow:8px 0 24px rgba(20,30,24,.12);transition:width 180ms ease,transform 180ms ease}.veridex-global-nav>*{direction:ltr}.veridex-global-nav .brand-block{display:flex;align-items:center;gap:12px;padding:0 8px 30px}.veridex-global-nav .brand-mark{width:38px;height:38px;display:grid;place-items:center;border:1px solid #43604b;padding:0;color:#3dd06f;background:transparent;font:700 20px/1 Georgia,serif;text-decoration:none}.veridex-global-nav .brand{font:600 22px/1.1 Georgia,serif}.veridex-global-nav .eyebrow{color:#aab7ad;text-transform:uppercase;letter-spacing:.12em;font-size:10px;font-weight:750}.veridex-global-nav .rail-menus{display:grid;gap:7px}.veridex-global-nav .rail-menu{border:1px solid rgba(202,221,207,.15);background:rgba(255,255,255,.025)}.veridex-global-nav .rail-menu>summary{display:flex;align-items:center;min-height:40px;padding:0 12px;color:#edf4ee;cursor:pointer;list-style:none;font-size:11px;font-weight:800;letter-spacing:.04em}.veridex-global-nav .rail-menu>summary::-webkit-details-marker{display:none}.veridex-global-nav .rail-menu>summary::after{content:"+";margin-left:auto;color:#aab7ad;font-size:15px}.veridex-global-nav .rail-menu[open]>summary{border-bottom:1px solid rgba(202,221,207,.12)}.veridex-global-nav .rail-menu[open]>summary::after{transform:rotate(45deg);color:#3dd06f}.veridex-global-nav .rail-menu-body{display:grid;gap:6px;padding:9px 8px 10px}.veridex-global-nav .room-menu-body label{padding:0 4px;color:#aab7ad;font-size:9px;font-weight:800;letter-spacing:.08em;text-transform:uppercase}.veridex-global-nav select{width:100%;border:1px solid #46604d;border-radius:0;padding:9px 28px 9px 10px;color:white;background:#213229;font-size:11px;font-weight:700}.veridex-global-nav .text-action{justify-self:start;color:#3dd06f;background:transparent;border:0;padding:4px;text-transform:uppercase;font-size:9px;letter-spacing:.08em}.veridex-global-nav .nav-list{display:flex;flex-direction:column;gap:2px;max-height:150px;overflow-y:auto}.veridex-global-nav .nav-item{width:100%;color:#cfdbd1;background:transparent;border:0;border-left:2px solid transparent;padding:10px 12px;text-align:left;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-decoration:none;font:inherit}.veridex-global-nav .nav-item.active{color:#fff;background:#273a2f;border-left-color:#3dd06f}.veridex-global-nav .action-menu-body a{width:100%;min-height:35px;border:1px solid rgba(202,221,207,.17);padding:8px 10px;color:#dce9df;background:#203127;text-align:left;font-size:10px;font-weight:750;text-decoration:none}.veridex-global-nav .status-menu .rail-menu-body{gap:10px}.veridex-global-nav .access-status{margin:0;color:#d7e3da;font-size:10px}.veridex-global-nav .navigator-status{width:fit-content;color:#bdebc7;font-size:10px;text-decoration:none}.veridex-global-nav .navigator-dot,.veridex-global-nav .access-dot{width:6px;height:6px;display:inline-block;margin-right:7px;border-radius:50%;background:#3dd06f}.veridex-global-nav .access-dot{background:#88918b}.veridex-global-nav .route-status{border-left:3px solid #63c77a;padding:10px 0 0 11px;color:#eff8f0;font-size:10px}.veridex-global-nav .route-meta{color:#aab7ad}.veridex-global-nav .local-account{border-top:1px solid #35483b;padding:18px 8px 2px;display:flex;gap:10px;align-items:center}.veridex-global-nav .presence-dot{width:8px;height:8px;border-radius:50%;background:#3dd06f;box-shadow:0 0 0 4px rgba(61,208,111,.12)}.veridex-global-nav .local-account strong,.veridex-global-nav .local-account span{display:block}.veridex-global-nav .local-account strong{font-size:13px}.veridex-global-nav .local-account span{color:#aab7ad;font-size:10px;margin-top:2px}.veridex-global-nav .rail-collapse{position:absolute;z-index:4;top:0;right:0;bottom:0;width:28px;border:0;border-left:1px solid #385141;padding:0;color:#9db5a4;background:#15221a;font-size:25px;line-height:1}.veridex-global-nav.is-collapsed{width:28px;padding:0;overflow:hidden}.veridex-global-nav.is-collapsed>:not(.rail-collapse){display:none}.veridex-global-nav.is-collapsed .rail-collapse{width:28px;border-left:0}.has-veridex-global-nav{padding-left:280px}@media(max-width:760px){.veridex-global-nav{width:280px;transform:translateX(-280px)}.veridex-global-nav:focus-within,.veridex-global-nav:hover{transform:none}.has-veridex-global-nav{padding-left:0}}`;
  document.head.append(style);
  document.body.classList.add("has-veridex-global-nav");

  const nav = document.createElement("aside");
  nav.className = "rail veridex-global-nav";
  nav.setAttribute("aria-label", "Veridex navigation");
  nav.innerHTML = `<div class="brand-block"><a class="brand-mark" href="/" aria-label="Open current workspace">V</a><div><div class="eyebrow">Local governed AI</div><div class="brand">Veridex</div></div></div><nav class="rail-menus" aria-label="Veridex navigation"><details class="rail-menu" open><summary>Rooms</summary><div class="rail-menu-body room-menu-body"><label for="global-room-selector">Choose room</label><select id="global-room-selector" aria-label="Active room"></select></div></details><details class="rail-menu" open><summary>Workspaces</summary><div class="rail-menu-body"><button class="text-action" type="button" data-global-action="new-workspace">New workspace</button><nav id="global-workspace-list" class="nav-list" aria-label="Workspaces"></nav></div></details><details class="rail-menu sessions-section" open><summary>Sessions</summary><div class="rail-menu-body"><button class="text-action" type="button" data-global-action="new-session">New session</button><nav id="global-session-list" class="nav-list" aria-label="Sessions"></nav></div></details><details class="rail-menu"><summary>Actions</summary><div class="rail-menu-body action-menu-body"><a href="/?veridex_menu=accounts">Connected accounts</a><a href="/?veridex_menu=facebook">Sell on Facebook</a><a href="/ebay-room">Sell on eBay</a><a href="/item-intake">Item intake</a></div></details><details class="rail-menu status-menu"><summary>Status</summary><div class="rail-menu-body"><div class="access-status"><span class="access-dot"></span>Read-only computer access</div><a class="navigator-status" href="/?veridex_menu=navigator"><span class="navigator-dot"></span>Navigator active · monitoring</a><div class="route-status"><div>Model routing ready</div><div class="route-meta">Codex selects the model automatically</div></div></div></details></nav><div class="local-account"><span class="presence-dot"></span><div><strong>Local User</strong><span>Single account · saved locally</span></div></div><button class="rail-collapse" type="button" aria-label="Collapse sidebar" aria-expanded="true"><span aria-hidden="true">‹</span></button>`;
  document.body.prepend(nav);

  const PAGE_LOCATIONS = [
    { path: "/ebay-room", label: "eBay workspace", roomId: "ebay" },
    { path: "/item-intake", label: "Item Intake", roomId: "ebay" },
    { path: "/market", label: "Market", roomId: "" },
  ];
  const qs = new URLSearchParams(location.search);
  const api = (path, options) => fetch(path, { headers: { "Content-Type": "application/json" }, ...options }).then((response) => response.ok ? response.json() : response.json().then((body) => Promise.reject(new Error(body.error || response.statusText))));
  let context = null;

  function currentPageLocation() {
    const path = location.pathname.replace(/\/$/, "") || "/";
    return PAGE_LOCATIONS.find((page) => path === page.path || path.startsWith(`${page.path}/`)) || null;
  }

  function stateUrl(path, value) {
    const query = new URLSearchParams({
      workspace_id: value?.workspace?.workspace_id || "",
      session_id: value?.session?.session_id || "",
    });
    return `${path}?${query}`;
  }

  function renderRows() {
    const workspaceList = nav.querySelector("#global-workspace-list");
    const sessionList = nav.querySelector("#global-session-list");
    workspaceList.replaceChildren();
    sessionList.replaceChildren();
    (context?.workspaces || []).forEach((row) => {
      const link = document.createElement("button");
      link.className = `nav-item${row.workspace_id === context?.workspace?.workspace_id ? " active" : ""}`;
      link.type = "button";
      link.textContent = row.label;
      link.title = row.label;
      link.addEventListener("click", () => selectState(row.workspace_id, ""));
      workspaceList.append(link);
    });
    (context?.sessions || []).forEach((row) => {
      const link = document.createElement("button");
      link.className = `nav-item${row.session_id === context?.session?.session_id ? " active" : ""}`;
      link.type = "button";
      link.textContent = row.title;
      link.title = row.title;
      link.addEventListener("click", () => selectState(row.workspace_id, row.session_id));
      sessionList.append(link);
    });
  }

  function renderRooms() {
    const selector = nav.querySelector("#global-room-selector");
    selector.replaceChildren();
    const currentPage = currentPageLocation();
    if (currentPage && !currentPage.roomId) {
      const unassigned = document.createElement("option");
      unassigned.value = "page:unassigned";
      unassigned.textContent = "\u2014";
      unassigned.selected = true;
      selector.append(unassigned);
    }
    (context?.rooms || []).forEach((room) => {
      const option = document.createElement("option");
      option.value = room.id;
      option.textContent = `${room.title} · ${room.default_persona}`;
      option.selected = !currentPage && room.id === context?.session?.active_room;
      selector.append(option);
      PAGE_LOCATIONS.filter((page) => page.roomId === room.id).forEach((page) => {
        const pageOption = document.createElement("option");
        pageOption.value = `page:${page.path}`;
        pageOption.textContent = `\u00a0\u00a0\u00a0\u00a0- ${page.label}`;
        pageOption.selected = currentPage?.path === page.path;
        selector.append(pageOption);
      });
    });
  }

  function currentSurfaceFor(value) {
    const page = currentPageLocation();
    if (!page) return "/";
    if (!page.roomId || page.roomId === value?.session?.active_room) return page.path;
    return "/";
  }

  async function selectState(workspaceId, sessionId) {
    try {
      const query = new URLSearchParams();
      if (workspaceId) query.set("workspace_id", workspaceId);
      if (sessionId) query.set("session_id", sessionId);
      const next = await api(`/api/state?${query}`);
      context = next;
      location.href = stateUrl(currentSurfaceFor(next), next);
    } catch (error) { window.alert(error.message || "Could not load that workspace."); }
  }

  nav.querySelector(".rail-collapse").addEventListener("click", () => {
    const collapsed = nav.classList.toggle("is-collapsed");
    nav.querySelector(".rail-collapse").setAttribute("aria-expanded", String(!collapsed));
  });
  nav.querySelector("#global-room-selector").addEventListener("change", async (event) => {
    if (!context?.workspace?.workspace_id || !context?.session?.session_id) return;
    const destination = String(event.target.value || "");
    if (destination === "page:unassigned") return;
    try {
      if (destination.startsWith("page:")) {
        const page = PAGE_LOCATIONS.find((row) => row.path === destination.slice(5));
        if (!page || !page.roomId) return renderRooms();
        let next = context;
        if (context.session.active_room !== page.roomId) {
          next = await api("/api/rooms", { method: "POST", body: JSON.stringify({ workspace_id: context.workspace.workspace_id, session_id: context.session.session_id, room_id: page.roomId }) });
        }
        context = next;
        location.href = stateUrl(page.path, next);
        return;
      }
      const next = await api("/api/rooms", { method: "POST", body: JSON.stringify({ workspace_id: context.workspace.workspace_id, session_id: context.session.session_id, room_id: destination }) });
      context = next;
      location.href = stateUrl("/", next);
    } catch (error) { window.alert(error.message || "Could not change rooms."); renderRooms(); }
  });
  nav.querySelector('[data-global-action="new-workspace"]').addEventListener("click", async () => {
    const label = window.prompt("Workspace name", "New workspace")?.trim();
    if (!label) return;
    try { const next = await api("/api/workspaces", { method: "POST", body: JSON.stringify({ label }) }); context = next; location.href = "/"; } catch (error) { window.alert(error.message || "Could not create workspace."); }
  });
  nav.querySelector('[data-global-action="new-session"]').addEventListener("click", async () => {
    const title = window.prompt("Session name", "New session")?.trim();
    if (!title || !context?.workspace?.workspace_id) return;
    try { const next = await api("/api/sessions", { method: "POST", body: JSON.stringify({ workspace_id: context.workspace.workspace_id, title }) }); context = next; location.href = "/"; } catch (error) { window.alert(error.message || "Could not create session."); }
  });

  const contextUrl = qs.get("workspace_id") && qs.get("session_id")
    ? `/api/state?workspace_id=${encodeURIComponent(qs.get("workspace_id"))}&session_id=${encodeURIComponent(qs.get("session_id"))}`
    : "/api/bootstrap";
  api(contextUrl).then((value) => { context = value; renderRooms(); renderRows(); }).catch(() => {});
})();
