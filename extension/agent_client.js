// Talks to Hexi's /api/agent and reports each stage as it happens, so the
// panel can show what's running instead of a spinner. Pure logic (fetch and
// the intent classifier are injected) so it's tested in node without Chrome.
(function (root) {
  var DEFAULT_BASE = "http://localhost:5000";
  var HOSTS = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d{1,5})?$/;

  // Only ever talk to this machine. A stored or typed URL that points
  // anywhere else falls back to the default rather than being used.
  function normalizeBase(url) {
    var u = String(url || "").trim().replace(/\/+$/, "");
    return HOSTS.test(u) ? u : DEFAULT_BASE;
  }

  // state: { pendingProposal, lastWorkflow }. Returns { state, reply, mood }.
  // "Automate" is two turns: the first only proposes and stores the id; the
  // next "yes" confirms it. Any other request clears the pending proposal, so
  // a stray "yes" later can't confirm something old.
  async function ask(text, state, deps) {
    var step = deps.onStep || function () {};
    var classify = deps.classify, fetchImpl = deps.fetch, base = normalizeBase(deps.base);
    state = state || { pendingProposal: null, lastWorkflow: null };

    var c = classify(text);
    step({ id: "heard", label: "Heard", detail: c.intent === "empty" ? "(nothing usable)" : String(text).slice(0, 120), status: "done" });
    if (c.intent === "empty") {
      return { state: state, mood: "idle", reply: "Say or type something, for example: " + c.examples[0] + "." };
    }
    var workflow = c.workflow || state.lastWorkflow;
    step({ id: "route", label: "Routed", detail: c.intent + (workflow ? " · " + workflow : "") + (c.corrected ? " (typo corrected)" : ""), status: "done" });

    var body = { intent: c.intent, workflow: workflow, proposal_id: c.intent === "automate" ? state.pendingProposal : null };
    step({ id: "request", label: "Calling MCP via " + base + "/api/agent", detail: "", status: "running" });
    var res;
    try {
      res = await fetchImpl(base + "/api/agent", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    } catch (e) {
      step({ id: "request", label: "Request failed", detail: "can't reach " + base + " — run: python web/server.py", status: "error" });
      return { state: state, mood: "asleep", reply: "I can't reach the Hexi server at " + base + ". Start it with python web/server.py." };
    }
    var data = {};
    try { data = await res.json(); } catch (e) { data = {}; }
    if (!res.ok) {
      step({ id: "request", label: "Request failed", detail: "HTTP " + res.status, status: "error" });
      return { state: state, mood: "idle", reply: data.reply || "The server returned an error (HTTP " + res.status + ")." };
    }
    var tools = Array.isArray(data.tools) ? data.tools : [];
    step({ id: "mcp", label: tools.length ? "MCP tool: " + tools.join(", ") : "No tool needed", detail: data.protocol ? "protocol " + data.protocol : "", status: "done" });
    step({ id: "reply", label: "Reply", detail: "", status: "done" });
    return {
      state: { pendingProposal: data.pending_proposal_id || null, lastWorkflow: workflow },
      mood: data.mood || "idle",
      reply: data.reply || "",
    };
  }

  var api = { ask: ask, normalizeBase: normalizeBase, DEFAULT_BASE: DEFAULT_BASE };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.HexiAgent = api;
})(typeof window !== "undefined" ? window : globalThis);
