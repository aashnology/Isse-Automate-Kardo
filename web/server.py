"""
A thin REST bridge in front of this project's actual analysis modules, for
the browser demo (Hexi). This is NOT a second implementation of the
pipeline -- it imports and calls the exact same functions mcp_server.py's
tools call. If a judge compares this file's endpoints against
mcp_server.py's tools, they should look like two doors into one house, not
two houses.

Why a separate bridge instead of exposing the MCP server directly to the
browser: MCP speaks a specific protocol (JSON-RPC-shaped, over Streamable
HTTP) meant for MCP clients like Alexa+ or MCP Inspector -- not for a
plain `fetch()` from a browser tab. This is deliberately the thinnest
possible layer that lets a normal web page call the same underlying logic.

What this demo IS: a self-contained, sandboxed workspace built for this
recording, with real analysis running underneath a simulated set of app
panels (ticket queue, spreadsheet, inbox) driven by this project's own
synthetic dataset. What this demo is NOT, and never claims to be: a browser
extension watching your real tabs. That's a genuinely different product
(real cross-tab visibility requires a browser extension with broad host
permissions, and a real consent/privacy design this hackathon build doesn't
attempt) -- see README's "Hexi demo" section for the honest version of this
distinction.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv

load_dotenv()

from flask import Flask, jsonify, request, send_from_directory

from synthetic_data import load_activity_events
from friction_radar import FrictionRadar
from workflow_discovery import WorkflowDiscovery
from actions import propose_action, confirm_action
from data_adapters import (
    from_activitywatch_events, from_toggl_csv, from_pasted_steps,
    from_github_pull_requests, from_csv_text, fetch_google_file,
)
from bedrock_narrator import BedrockNarrator
from briefing import build_briefing
import user_memory

app = Flask(__name__, static_folder="static", static_url_path="")

# Same file the MCP server reads: one dataset, two interfaces.
ACTIVITY_EVENTS = load_activity_events()
friction_radar = FrictionRadar(ACTIVITY_EVENTS)
workflow_discovery = WorkflowDiscovery(ACTIVITY_EVENTS, similarity_threshold=0.75)
narrator = BedrockNarrator()


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/friction-points")
def friction_points():
    top_k = int(request.args.get("top_k", 3))
    include_dismissed = request.args.get("include_dismissed", "false").lower() == "true"
    points = friction_radar.top_friction_points(top_k=top_k + len(user_memory.list_dismissed()))
    if not include_dismissed:
        points = [p for p in points if not user_memory.is_dismissed(p["workflow_name"])]
    return jsonify({"friction_points": points[:top_k]})


@app.route("/api/debug/<workflow_name>")
def debug_workflow(workflow_name):
    return jsonify(friction_radar.debug_workflow(workflow_name))


@app.route("/api/anomalies/<workflow_name>")
def anomalies(workflow_name):
    return jsonify(workflow_discovery.detect_anomalous_runs(workflow_name))


@app.route("/api/propose", methods=["POST"])
def propose():
    workflow_name = request.json["workflow_name"]
    if user_memory.is_dismissed(workflow_name):
        return jsonify({
            "proposal_id": None,
            "workflow_name": workflow_name,
            "summary": f"You previously asked not to be offered automation for '{workflow_name}'.",
        })
    debug_result = friction_radar.debug_workflow(workflow_name)
    return jsonify(propose_action(workflow_name, debug_result))


@app.route("/api/confirm", methods=["POST"])
def confirm():
    proposal_id = request.json["proposal_id"]
    return jsonify(confirm_action(proposal_id))


@app.route("/api/dismiss", methods=["POST"])
def dismiss():
    body = request.json
    return jsonify(user_memory.dismiss_workflow(body["workflow_name"], reason=body.get("reason", "")))


@app.route("/api/restore", methods=["POST"])
def restore():
    workflow_name = request.json["workflow_name"]
    return jsonify(user_memory.restore_workflow(workflow_name))


@app.route("/api/dismissed")
def dismissed():
    return jsonify({"dismissed_workflows": user_memory.list_dismissed()})


@app.route("/api/brief")
def brief():
    """The same briefing the MCP tool narrate_briefing returns -- both call
    briefing.build_briefing, so Hexi's "brief me" and the MCP tool can't
    drift apart."""
    top_k = int(request.args.get("top_k", 3))
    return jsonify(build_briefing(
        friction_radar, workflow_discovery, narrator, top_k=top_k,
        exclude={d["workflow_name"] for d in user_memory.list_dismissed()},
    ))


@app.route("/api/import", methods=["POST"])
def import_data():
    """Bring-your-own-data: an ActivityWatch/Toggl export file, a pasted
    step list, or a public GitHub repo's own PR history -- run through the
    exact same discovery pipeline as the synthetic demo data. Never
    executes anything from a file or repo; every path here only reads and
    parses (see data_adapters.py's docstrings for why that line matters)."""
    if "file" in request.files:
        f = request.files["file"]
        name = (f.filename or "").lower()
        content = f.read().decode("utf-8")
        if name.endswith(".json"):
            import json as _json
            raw = from_activitywatch_events(_json.loads(content))
        elif name.endswith(".csv"):
            import tempfile
            with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            raw = from_toggl_csv(tmp_path)
        else:
            return jsonify({"error": "Use a .json (ActivityWatch) or .csv (Toggl) file."}), 400
        wd = WorkflowDiscovery.from_raw_events(raw, similarity_threshold=0.6)

    elif request.is_json and request.json.get("pasted_text"):
        raw = from_pasted_steps(request.json["pasted_text"])
        wd = WorkflowDiscovery.from_raw_events(raw, similarity_threshold=0.6)

    elif request.is_json and request.json.get("google_link"):
        try:
            text = fetch_google_file(request.json["google_link"])
            if text.lstrip().startswith(("[", "{")):
                import json as _json
                raw = from_activitywatch_events(_json.loads(text))
            else:
                raw = from_csv_text(text)
        except ValueError as exc:  # messages are written to be shown to the user
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:  # noqa: BLE001 -- network/parse failure, not a 500
            return jsonify({"error": f"Couldn't read that file: {exc}"}), 400
        wd = WorkflowDiscovery.from_raw_events(raw, similarity_threshold=0.6) if raw else None

    elif request.is_json and request.json.get("github_repo"):
        repo_spec = request.json["github_repo"].strip().strip("/")
        if repo_spec.startswith("http"):
            repo_spec = repo_spec.split("github.com/")[-1]
        parts = repo_spec.split("/")
        if len(parts) != 2:
            return jsonify({"error": "Expected 'owner/repo' or a github.com URL."}), 400
        owner, repo = parts
        try:
            raw = from_github_pull_requests(owner, repo, max_prs=30, token=os.environ.get("GITHUB_TOKEN"))
        except Exception as exc:  # noqa: BLE001 -- surface as a normal error response, not a 500
            return jsonify({"error": f"Couldn't fetch that repo's PRs: {exc}"}), 400
        if not raw:
            return jsonify({"error": "No closed pull requests found to analyze."}), 400
        # PRs can be open concurrently, so run boundaries are the PR itself,
        # not a time-gap guess -- see from_github_pull_requests' docstring.
        wd = WorkflowDiscovery(raw, similarity_threshold=0.6, run_id_field="workflow_run_id")

    else:
        return jsonify({"error": "Provide a file, pasted_text, github_repo, or google_link."}), 400

    if not raw:
        return jsonify({"error": "No events could be parsed from that input."}), 400

    clusters = wd.discover()
    anomalies_by_cluster = {
        c["matched_label"]: wd.detect_anomalous_runs(c["matched_label"]).get("anomalies", [])
        for c in clusters
    }
    return jsonify({
        "events_imported": len(raw),
        "discovered_workflows": clusters,
        "anomalies_by_cluster": anomalies_by_cluster,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("WEB_PORT", "5000")))
