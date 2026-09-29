"""
The Chrome extension can't be loaded into a browser in CI, so this checks what
can be checked: the manifest and file references, that the bundled intent
router hasn't drifted from the tested one, the request/step logic in node with
a fake fetch, and that same logic against the two real servers.
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
EXT = os.path.join(ROOT, "extension")
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _manifest():
    return json.load(open(os.path.join(EXT, "manifest.json"), encoding="utf-8"))


def test_manifest_is_mv3_with_a_side_panel():
    m = _manifest()
    assert m["manifest_version"] == 3
    assert "sidePanel" in m["permissions"]
    assert m["side_panel"]["default_path"] == "panel.html"
    assert os.path.exists(os.path.join(EXT, m["background"]["service_worker"]))
    assert "default_popup" not in m.get("action", {})  # a popup would stop the panel opening on click


def test_host_permissions_are_local_only():
    for pattern in _manifest()["host_permissions"]:
        assert pattern.startswith(("http://localhost/", "http://127.0.0.1/"))


@pytest.mark.parametrize("page", ["panel.html", "mic.html"])
def test_pages_use_only_local_scripts_and_no_inline_code(page):
    html = open(os.path.join(EXT, page), encoding="utf-8").read()
    for tag in re.findall(r"<script\b[^>]*>", html):
        src = re.search(r'src="([^"]+)"', tag)
        assert src and not src.group(1).startswith(("http", "//")), tag
        assert os.path.exists(os.path.join(EXT, src.group(1)))
    assert not re.search(r"<script(?![^>]*src)[^>]*>\s*\S", html)  # MV3 forbids inline scripts
    assert not re.search(r"\son\w+=", html)


def test_bundled_intent_router_matches_the_tested_one():
    assert open(os.path.join(EXT, "intents.js"), "rb").read() == \
        open(os.path.join(ROOT, "web", "static", "intents.js"), "rb").read(), \
        "run extension/sync.sh"


def _node(script, *args):
    out = subprocess.run(["node", "-e", script, *args], capture_output=True, text=True, cwd=EXT, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


UNIT = r"""
const {ask, normalizeBase} = require("./agent_client.js");
const {classifyIntent} = require("./intents.js");
(async () => {
  const seen = [], calls = [];
  const fakeFetch = async (url, opts) => { calls.push({url, body: JSON.parse(opts.body)});
    return {ok: true, status: 200, json: async () => ({reply: "ok", mood: "curious", tools: ["get_top_friction_points"],
      protocol: "2025-11-25", pending_proposal_id: "abc123"})}; };
  const a = await ask("what's costing me time", null, {classify: classifyIntent, fetch: fakeFetch, base: "http://localhost:5000", onStep: s => seen.push(s.id + ":" + s.status)});
  const down = await ask("brief me", null, {classify: classifyIntent, fetch: async () => { throw new Error("refused"); }, base: "http://localhost:5000"});
  const empty = await ask("   ", null, {classify: classifyIntent, fetch: fakeFetch});
  const nonJson = await ask("brief me", null, {classify: classifyIntent, base: "http://localhost:5000",
    fetch: async () => ({ok: false, status: 500, json: async () => { throw new Error("bad"); }})});
  // pending proposal is sent on "automate" only
  const first = await ask("automate weekly reporting", null, {classify: classifyIntent, fetch: fakeFetch});
  const yes = await ask("yes", first.state, {classify: classifyIntent, fetch: fakeFetch});
  const other = await ask("brief me", first.state, {classify: classifyIntent, fetch: fakeFetch});
  process.stdout.write(JSON.stringify({seen, url: calls[0].url, downReply: down.reply, downMood: down.mood,
    empty: empty.reply, nonJson: nonJson.reply, sentId: calls[calls.length-2].body.proposal_id,
    firstSent: calls[calls.length-3].body.proposal_id, briefSent: calls[calls.length-1].body.proposal_id,
    pendingAfterOther: other.state.pendingProposal,
    bases: [normalizeBase("http://evil.example"), normalizeBase("http://127.0.0.1:9000/"), normalizeBase(null)]}));
})();
"""


@needs_node
def test_agent_client_stages_errors_and_two_step_state():
    r = _node(UNIT)
    assert r["seen"] == ["heard:done", "route:done", "request:running", "mcp:done", "reply:done"]
    assert r["url"] == "http://localhost:5000/api/agent"
    assert r["downMood"] == "asleep" and "python web/server.py" in r["downReply"]
    assert "Say or type" in r["empty"]
    assert "HTTP 500" in r["nonJson"]
    assert r["firstSent"] is None and r["sentId"] == "abc123"        # first turn proposes, "yes" confirms
    assert r["briefSent"] is None                                     # a non-automate request never carries the id
    assert r["bases"] == ["http://localhost:5000", "http://127.0.0.1:9000", "http://localhost:5000"]


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait(port):
    deadline = time.time() + 25
    while time.time() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            return
        except OSError:
            time.sleep(0.3)
    pytest.fail(f"nothing listening on {port}")


LIVE = r"""
const {ask} = require("./agent_client.js");
const {classifyIntent} = require("./intents.js");
const base = process.argv[1];
(async () => {
  const deps = {classify: classifyIntent, fetch, base};
  const friction = await ask("whats costing me tiem", null, deps);
  const p = await ask("automate weekly reporting", null, deps);
  const done = await ask("yes", p.state, deps);
  const junk = await ask("purple monkey dishwasher", null, deps);
  const steps = [];
  await ask("why is reporting slow", null, {...deps, onStep: s => steps.push(s.id)});
  process.stdout.write(JSON.stringify({friction: friction.reply, proposal: p.reply, pending: !!p.state.pendingProposal,
    done: done.reply, doneMood: done.mood, junk: junk.reply, steps}));
})();
"""


@needs_node
def test_extension_client_against_the_real_servers():
    mcp_port, web_port = _free_port(), _free_port()
    mcp = subprocess.Popen([sys.executable, "mcp_server.py"], cwd=os.path.join(ROOT, "src"),
                           env={**os.environ, "MCP_SERVER_PORT": str(mcp_port)},
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    web = None
    try:
        _wait(mcp_port)
        web = subprocess.Popen([sys.executable, "server.py"], cwd=os.path.join(ROOT, "web"),
                               env={**os.environ, "WEB_PORT": str(web_port),
                                    "HEXI_MCP_URL": f"http://127.0.0.1:{mcp_port}/mcp"},
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _wait(web_port)
        r = _node(LIVE, f"http://127.0.0.1:{web_port}")
    finally:
        for p in (web, mcp):
            if p:
                p.terminate()
                p.wait(timeout=10)
    assert "costs" in r["friction"]                       # "tiem" typo is ignored; "costing" still routes
    assert r["pending"] and "Say yes" in r["proposal"]
    assert r["doneMood"] == "confirmed"
    assert "Try:" in r["junk"]                             # unrecognised phrasing gets examples, not an error
    assert r["steps"] == ["heard", "route", "request", "mcp", "reply"]
