import json
import os
import shutil
import subprocess

import pytest

STATIC = os.path.join(os.path.dirname(__file__), "..", "web", "static")
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _route(text, awake_until=0, now=1000):
    script = (
        "const a = require(process.argv[1]);"
        "const r = a.route(process.argv[2], {awakeUntil: +process.argv[3], awaitingConfirm: false}, +process.argv[4]);"
        "process.stdout.write(JSON.stringify(r));"
    )
    out = subprocess.run(
        ["node", "-e", script, os.path.join(STATIC, "alexa.js"), text, str(awake_until), str(now)],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


@needs_node
@pytest.mark.parametrize("said,expected", [
    ("Alexa, ask Hexi what's costing me time", "what's costing me time"),
    ("alexa tell hexi to automate it", "automate it"),
    ("Hey Alexa, ask Hexy why is reporting slow?", "why is reporting slow"),
    ("Alexa, brief me", "brief me"),
    ("Hexi, stop suggesting bug triage", "stop suggesting bug triage"),
])
def test_wake_phrases_extract_the_command(said, expected):
    r = _route(said)
    assert r["action"] == "command" and r["utterance"] == expected


@needs_node
def test_wake_word_alone_opens_a_window_without_a_command():
    assert _route("Alexa")["action"] == "wake_only"
    assert _route("alexa, ask hexi")["action"] == "wake_only"


@needs_node
def test_room_chatter_is_ignored_when_not_awake():
    assert _route("what's for dinner tonight")["action"] == "ignore"
    assert _route("")["action"] == "ignore"
    assert _route("   ")["action"] == "ignore"


@needs_node
def test_followup_accepted_only_inside_the_window():
    inside = _route("yes", awake_until=5000, now=1000)
    assert inside["action"] == "command" and inside["via"] == "followup"
    assert _route("yes", awake_until=500, now=1000)["action"] == "ignore"


@needs_node
def test_alexa_inside_a_word_does_not_wake():
    assert _route("my cousin alexander said hi")["action"] == "ignore"
