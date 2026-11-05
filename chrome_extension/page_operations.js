/* Injected in Chrome's isolated world on the explicitly selected tab only. */
(() => {
  if (globalThis.__veridexPage) return;
  const documentId = crypto.randomUUID();
  let snapshotId = "";
  let targets = new Map();
  const forbidden = /password|one.?time|verification.?code|security.?code|credit.?card|card.?number|\bcc-|\bssn\b|\botp\b/i;
  const visible = (node) => {
    const rect = node.getBoundingClientRect();
    const css = getComputedStyle(node);
    return rect.width > 0 && rect.height > 0 && css.visibility !== "hidden" && css.display !== "none" &&
      node.checkVisibility?.({checkOpacity: true, checkVisibilityCSS: true}) !== false;
  };
  const descriptor = (node) => ({
    tag: node.tagName.toLowerCase(), type: node.type || "", role: node.getAttribute("role") || "",
    label: (node.getAttribute("aria-label") || node.labels?.[0]?.innerText || node.innerText || node.getAttribute("placeholder") || node.name || node.id || "").slice(0, 160),
    disabled: Boolean(node.disabled || node.getAttribute("aria-disabled") === "true"),
    read_only: Boolean(node.readOnly), href: node.tagName === "A" ? node.href : ""
  });
  function observe() {
    snapshotId = crypto.randomUUID();
    targets = new Map();
    const elements = [];
    for (const node of document.querySelectorAll("a[href],button,input,textarea,select,[role=button],[role=link]")) {
      if (!visible(node) || node.type === "password" || node.type === "hidden") continue;
      const row = descriptor(node);
      if (row.href && !/^https?:/i.test(row.href)) row.href = "";
      const id = `t${elements.length + 1}`;
      targets.set(id, {node, fingerprint: JSON.stringify(descriptor(node))});
      elements.push({target_id: id, ...row});
      if (elements.length === 100) break;
    }
    return {document_id: documentId, snapshot_id: snapshotId, url: location.href,
      title: document.title.slice(0, 300), text: (document.body?.innerText || "").slice(0, 12000), elements,
      observed_at: new Date().toISOString(), scope: "top-level document; cross-origin frames are not inspected"};
  }
  async function run(action, args) {
    if (action === "read") return {status: "completed", observation: observe()};
    if (!["click", "fill"].includes(action)) throw new Error("Unsupported page operation");
    if (args.document_id !== documentId || args.snapshot_id !== snapshotId) throw new Error("Stale page observation; read the page again");
    const target = targets.get(args.target_id);
    if (!target || !target.node.isConnected || !visible(target.node) || target.fingerprint !== JSON.stringify(descriptor(target.node))) {
      throw new Error("Target changed; read the page again");
    }
    const node = target.node;
    const before = descriptor(node);
    if (before.disabled) throw new Error("Target is disabled");
    if (action === "fill") {
      if (!["INPUT", "TEXTAREA"].includes(node.tagName) || node.readOnly ||
          (node.tagName === "INPUT" && !["text", "search", "email", "tel", "url", "number"].includes(node.type))) {
        throw new Error("This field is not supported for filling");
      }
      const identity = [node.name, node.id, node.autocomplete, node.getAttribute("aria-label"), node.getAttribute("placeholder")].join(" ");
      if (forbidden.test(identity)) throw new Error("Credential, payment and identity fields require manual entry");
      if (typeof args.text !== "string" || args.text.length > 4000) throw new Error("Invalid field text");
      const proto = node.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, "value").set.call(node, args.text);
      node.dispatchEvent(new Event("input", {bubbles: true}));
      node.dispatchEvent(new Event("change", {bubbles: true}));
      await new Promise(resolve => setTimeout(resolve, 100));
      return {status: node.value === args.text ? "completed" : "limited", effect_verified: node.value === args.text,
        observation: observe(), message: "Field value checked after input/change events; form was not submitted"};
    }
    if ((args.expect_text || args.expect_url) && (!args.expect_text || (document.body?.innerText || "").includes(args.expect_text)) &&
        (!args.expect_url || location.href === new URL(args.expect_url).href)) {
      return {status: "completed", effect_verified: true, observation: observe(), execution: "not_needed",
        message: "Expected state already present; no click dispatched"};
    }
    node.click();
    await new Promise(resolve => setTimeout(resolve, 250));
    const observation = observe();
    const expected = Boolean(args.expect_text || args.expect_url);
    const verified = expected && (!args.expect_text || observation.text.includes(args.expect_text)) &&
      (!args.expect_url || location.href === new URL(args.expect_url).href);
    return {status: verified ? "completed" : "limited", effect_verified: verified, observation,
      message: verified ? "Expected page state observed" : "Click dispatched; intended effect not verified. Do not automatically repeat."};
  }
  globalThis.__veridexPage = {run};
})();
