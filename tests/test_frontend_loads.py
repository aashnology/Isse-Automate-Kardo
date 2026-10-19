import os
import shutil
import subprocess
import textwrap

import pytest

STATIC = os.path.join(os.path.dirname(__file__), "..", "web", "static")
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

# Runs the page scripts in the same order as index.html against a stub browser.
# Any top-level error (a ReferenceError from load order, a missing element) fails
# the test, which is the failure that leaves the real page blank.
HARNESS = textwrap.dedent("""
    const fs = require("fs"), vm = require("vm"), path = require("path");
    const dir = process.argv[1];
    const stub = () => new Proxy(function () {}, {
      get: (t, p) => (p === Symbol.toPrimitive ? () => "" : p === "length" ? 0 : stub()),
      apply: () => stub(), construct: () => stub(), set: () => true,
    });
    const storage = { getItem: () => null, setItem() {}, removeItem() {} };
    const win = {
      speechSynthesis: { getVoices: () => [], addEventListener() {}, cancel() {}, speak() {} },
      SpeechSynthesisUtterance: function () {}, localStorage: storage,
      AudioContext: function () {}, addEventListener() {},
    };
    const ctx = vm.createContext(Object.assign(win, {
      window: win, document: stub(), localStorage: storage, console, setTimeout, clearTimeout,
      fetch: () => Promise.reject(new Error("offline")), globalThis: win,
      SpeechSynthesisUtterance: win.SpeechSynthesisUtterance,
    }));
    ctx.window = ctx;
    const html = fs.readFileSync(path.join(dir, "index.html"), "utf8");
    const scripts = [...html.matchAll(/<script src="\\/([^"]+)"/g)].map(m => m[1]);
    for (const name of scripts) vm.runInContext(fs.readFileSync(path.join(dir, name), "utf8"), ctx, { filename: name });
    console.log("loaded " + scripts.join(","));
""")


@needs_node
def test_page_scripts_load_without_errors():
    out = subprocess.run(["node", "-e", HARNESS, STATIC], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-1500:]
    assert "app.js" in out.stdout
