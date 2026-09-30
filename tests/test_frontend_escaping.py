"""
Regression test for the XSS fix in web/static/index.html: any string that
can come from imported data (a pasted step name, a CSV cell, a GitHub/Google
error) must be HTML-escaped before it lands in innerHTML. This extracts the
real escapeHtml() function from the shipped file and runs it under Node, so
the test breaks if the function is ever removed or weakened -- not just if
this file's copy of it goes stale.
"""
import re
import subprocess
import os

INDEX_HTML = os.path.join(os.path.dirname(__file__), "..", "web", "static", "index.html")


def _extract_escape_fn():
    with open(INDEX_HTML) as f:
        html = f.read()
    match = re.search(r"function escapeHtml\(value\)\s*\{.*?\n\}", html, re.S)
    assert match, "escapeHtml() not found in index.html -- was it removed?"
    return match.group(0)


def test_escape_html_neutralizes_script_and_event_handlers():
    fn = _extract_escape_fn()
    payloads = [
        "<img src=x onerror=alert(1)>",
        "<script>alert(document.cookie)</script>",
        "\"><svg onload=alert(1)>",
    ]
    for payload in payloads:
        js = f"""
        {fn}
        const out = escapeHtml({payload!r});
        if (out.includes("<") || out.includes(">")) {{
          console.error("UNSAFE:" + out);
          process.exit(1);
        }}
        console.log(out);
        """
        result = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, f"escapeHtml failed to neutralize {payload!r}: {result.stderr}"
        assert "<" not in result.stdout and ">" not in result.stdout


def test_untrusted_render_sites_use_escape_html():
    """Guard against a future edit re-introducing raw interpolation at the
    three sites that render imported/error data via innerHTML."""
    with open(INDEX_HTML) as f:
        html = f.read()
    assert "escapeHtml(debug.error)" in html
    assert "escapeHtml(data.error)" in html
    assert "c.canonical_sequence.map(escapeHtml)" in html
    assert "escapeHtml(anomalies[0].likely_cause_step)" in html
