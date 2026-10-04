import json
import os
import shutil
import subprocess
import sys

import pytest

STATIC = os.path.join(os.path.dirname(__file__), "..", "web", "static")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "web"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _classify(text):
    script = (
        "const {classifyIntent} = require(process.argv[1]);"
        "process.stdout.write(JSON.stringify(classifyIntent(process.argv[2])));"
    )
    out = subprocess.run(
        ["node", "-e", script, os.path.join(STATIC, "intents.js"), text],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


@needs_node
@pytest.mark.parametrize("text,intent,workflow", [
    # the phrase that used to be misrouted: "stop" contains "top"
    ("stop suggesting bug triage", "dismiss", "bug_triage"),
    ("Stop suggesting bug triage", "dismiss", "bug_triage"),
    ("what's costing me the most time", "friction", None),
    ("what is the top time sink", "friction", None),
    ("why is reporting slow", "why", "weekly_reporting"),
    ("explain the onboarding bottleneck", "why", "onboarding_new_partner"),
    ("any unusual runs in the tickets", "anomalies", "bug_triage"),
    ("automate it", "automate", None),
    ("yes please", "automate", None),
    ("go ahead and handle it", "automate", None),
    ("brief me", "brief", None),
    ("give me a rundown", "brief", None),
    ("restore bug triage", "restore", "bug_triage"),
    ("bring back reporting", "restore", "weekly_reporting"),
    ("undo that", "restore", None),
    ("what have I dismissed", "dismissed_list", None),
    ("never mind", "dismiss", None),
    ("don't suggest that again", "dismiss", None),
    ("help", "help", None),
    ("purple monkey dishwasher", "unknown", None),
])
def test_phrases_route_to_the_right_intent(text, intent, workflow):
    result = _classify(text)
    assert result["intent"] == intent
    assert result["workflow"] == workflow


@needs_node
def test_words_are_matched_whole_not_as_substrings():
    # "stop" must not trigger the friction rule via "top"; "reported" must
    # not be read as "report"; "spotty" must not be read as "spot".
    assert _classify("stop")["intent"] == "dismiss"
    assert _classify("the reported issue")["workflow"] is None
    assert _classify("a bugle")["workflow"] is None


def test_page_uses_the_tested_router_not_an_inline_copy():
    # index.html loads intents.js and app.js as external files (no inline
    # <script>, so the page can run a strict script-src 'self' CSP); the
    # actual call into the router now lives in app.js.
    html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    assert 'src="/intents.js"' in html
    assert "HexiIntents.classifyIntent" in js
    # the old inline matcher must be gone, or the tests above prove nothing
    assert "WORKFLOW_SYNONYMS" not in html and "WORKFLOW_SYNONYMS" not in js
    assert "/(waste|costing|most time|top|biggest|friction)/" not in html
    assert "/(waste|costing|most time|top|biggest|friction)/" not in js


def test_page_exposes_the_new_controls():
    html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    assert 'id="micBtn"' in html
    assert 'id="chips"' in html
    assert "/api/brief" in js
    assert "google_link" in js


def test_intents_helper_is_served():
    import server as web_server
    with web_server.app.test_client() as c:
        assert c.get("/intents.js").status_code == 200
        assert c.get("/app.js").status_code == 200


@needs_node
@pytest.mark.parametrize("text,intent", [
    ("automte it", "automate"),
    ("brieff me", "brief"),
    ("anomolies in the tickets", "anomalies"),
    ("Could you please explian the bottlenek", "why"),
    ("grief", "unknown"),           # first-letter rule: not "brief"
    ("unbox", "unknown"),           # not "inbox"
    ("", "empty"),
    ("   \t\n", "empty"),
])
def test_typos_are_corrected_and_lookalikes_are_not(text, intent):
    assert _classify(text)["intent"] == intent


@needs_node
def test_hostile_or_malformed_input_never_throws():
    script = (
        "const {classifyIntent} = require(process.argv[1]);"
        "const inputs = [null, undefined, 42, true, {}, [], ['brief'], '', 'x'.repeat(200000),"
        " '<script>alert(1)</script>', '\\u0000\\u0007brief me', '%s %s %n', '\\ud83d\\ude00'.repeat(500),"
        " 'a '.repeat(50000), '(((((', '\\\\', 'SELECT * FROM users; --'];"
        "const out = inputs.map(i => classifyIntent(i));"
        "process.stdout.write(JSON.stringify(out.every(o => typeof o.intent === 'string')));"
    )
    out = subprocess.run(["node", "-e", script, os.path.join(STATIC, "intents.js")],
                         capture_output=True, text=True, check=True, timeout=30).stdout
    assert json.loads(out) is True
