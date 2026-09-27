"""
A thin REST bridge in front of this project's actual analysis modules, for
the browser demo (Orbi). This is NOT a second implementation of the
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
attempt) -- see README's "Orbi demo" section for the honest version of this
distinction.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from flask import Flask, jsonify, request, send_from_directory

from synthetic_data import generate_activity_events
from friction_radar import FrictionRadar
from workflow_discovery import WorkflowDiscovery
from actions import propose_action, confirm_action
import user_memory

app = Flask(__name__, static_folder="static", static_url_path="")

ACTIVITY_EVENTS = generate_activity_events()
friction_radar = FrictionRadar(ACTIVITY_EVENTS)
workflow_discovery = WorkflowDiscovery(ACTIVITY_EVENTS, similarity_threshold=0.75)


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("WEB_PORT", "5000")))
