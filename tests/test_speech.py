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


def _speakable(text):
    script = (
        "const {speakable} = require(process.argv[1]);"
        "process.stdout.write(JSON.stringify(speakable(process.argv[2])));"
    )
    out = subprocess.run(
        ["node", "-e", script, os.path.join(STATIC, "speech.js"), text],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


@needs_node
def test_underscored_names_are_read_as_words():
    assert _speakable("'bug_triage' costs more") == "bug triage costs more"


@needs_node
def test_hours_are_spoken_with_correct_plurals():
    assert _speakable("costs 1.2h") == "costs 1.2 hours"
    assert _speakable("costs 1h") == "costs 1 hour"


@needs_node
def test_percent_and_arrows_are_spoken():
    assert _speakable("58% of time") == "58 percent of time"
    assert _speakable("a → b") == "a then b"


@needs_node
def test_inline_page_script_is_valid_javascript(tmp_path):
    import re
    html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
    inline = "\n".join(re.findall(r"<script(?![^>]*src)[^>]*>(.*?)</script>", html, re.S))
    f = tmp_path / "inline.js"
    f.write_text(inline, encoding="utf-8")
    subprocess.run(["node", "--check", str(f)], check=True)


def test_speech_helper_is_served_and_referenced():
    import server as web_server
    with web_server.app.test_client() as c:
        assert c.get("/speech.js").status_code == 200
        assert b'src="/speech.js"' in c.get("/").data
