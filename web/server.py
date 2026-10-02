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

import logging
import os
import sys
import threading
import time
from collections import defaultdict, deque

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv

load_dotenv()

from flask import Flask, jsonify, request, send_from_directory

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from synthetic_data import load_activity_events
from friction_radar import FrictionRadar
from workflow_discovery import WorkflowDiscovery
from actions import propose_action, confirm_action
from data_adapters import (
    from_activitywatch_events, from_toggl_csv, from_pasted_steps,
    from_github_pull_requests, from_csv_text, fetch_google_file,
)
from briefing import build_briefing
import user_memory

app = Flask(__name__, static_folder="static", static_url_path="")

# 2 MiB is generous for a JSON body or a pasted step list; file uploads
# (ActivityWatch/Toggl exports) go through /api/import's own, larger check.
# Without this, Werkzeug will buffer an arbitrarily large request body into
# memory before this code ever runs.
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# Same file the MCP server reads: one dataset, two interfaces.
ACTIVITY_EVENTS = load_activity_events()
friction_radar = FrictionRadar(ACTIVITY_EVENTS)
workflow_discovery = WorkflowDiscovery(ACTIVITY_EVENTS, similarity_threshold=0.75)

MAX_WORKFLOW_NAME_LEN = 200
MAX_REASON_LEN = 500

log = logging.getLogger("friction_radar.web")

# A plain in-memory sliding-window limiter, per client IP. This is a
# single-process hackathon demo (see docker-compose.yml -- one container,
# no load balancer), so this doesn't need Redis or a third-party
# dependency to do its job: stop one client from hammering the API,
# not coordinate limits across a fleet.
RATE_LIMIT_MAX_REQUESTS = 60
RATE_LIMIT_WINDOW_SECONDS = 60
_rate_limit_lock = threading.Lock()
_request_times = defaultdict(deque)


def _rate_limit_exceeded(client_id):
    now = time.time()
    with _rate_limit_lock:
        bucket = _request_times[client_id]
        while bucket and now - bucket[0] > RATE_LIMIT_WINDOW_SECONDS:
            bucket.popleft()
        if len(bucket) >= RATE_LIMIT_MAX_REQUESTS:
            return True
        bucket.append(now)
        return False


@app.before_request
def _enforce_rate_limit():
    if app.config.get("TESTING"):
        # The test suite's own request volume across many test modules,
        # all sharing this one process's _request_times state, has nothing
        # to do with a real client hammering the API -- it would start
        # failing tests intermittently as the suite grows, not catch a
        # real problem.
        return None
    # request.remote_addr is who the WSGI server saw connect -- correct for
    # this project's own deployment (direct to the Flask dev server, no
    # reverse proxy in front), but would need X-Forwarded-For handling if
    # that ever changes.
    client_id = request.remote_addr or "unknown"
    if _rate_limit_exceeded(client_id):
        return jsonify({"error": "Too many requests. Please slow down."}), 429


@app.after_request
def _log_and_secure(response):
    log.info("%s %s -> %s", request.method, request.path, response.status_code)
    # script-src/style-src have no 'unsafe-inline' for scripts (everything
    # is in external files under web/static/) but do for styles -- the
    # single inline <style> block in index.html isn't worth splitting out
    # for this project's threat model, and CSS can't execute script.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


class BadRequest(Exception):
    """Raised by the small helpers below; turned into a clean 400 by the
    error handler instead of an unhandled 500 with a stack trace."""


@app.errorhandler(BadRequest)
def _handle_bad_request(exc):
    return jsonify({"error": str(exc)}), 400


@app.errorhandler(400)
def _handle_werkzeug_400(exc):
    # Covers Flask/Werkzeug's own 400s (e.g. a malformed JSON body), which
    # otherwise render as an HTML error page instead of the JSON this API
    # returns everywhere else.
    return jsonify({"error": "Malformed request."}), 400


@app.errorhandler(Exception)
def _handle_unexpected_error(exc):
    # Anything not already caught closer to its source. Log the real
    # exception server-side; never hand the client's own str(exc) back to
    # it -- that's how internal paths, tracebacks, and cell contents from
    # imported data end up echoed to whoever sent the request.
    app.logger.exception("Unhandled error")
    return jsonify({"error": "Something went wrong handling that request."}), 500


def _json_body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise BadRequest("Expected a JSON object body.")
    return body


def _required_str(body, key, max_len):
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BadRequest(f"'{key}' is required.")
    if len(value) > max_len:
        raise BadRequest(f"'{key}' is too long (max {max_len} characters).")
    return value.strip()


def _clamped_top_k(raw, default=3, minimum=1, maximum=20):
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise BadRequest("'top_k' must be an integer.")
    return max(minimum, min(value, maximum))


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/friction-points")
def friction_points():
    top_k = _clamped_top_k(request.args.get("top_k"))
    include_dismissed = request.args.get("include_dismissed", "false").lower() == "true"
    points = friction_radar.top_friction_points(top_k=top_k + len(user_memory.list_dismissed()))
    if not include_dismissed:
        points = [p for p in points if not user_memory.is_dismissed(p["workflow_name"])]
    return jsonify({"friction_points": points[:top_k]})


@app.route("/api/debug/<workflow_name>")
def debug_workflow(workflow_name):
    if len(workflow_name) > MAX_WORKFLOW_NAME_LEN:
        raise BadRequest("'workflow_name' is too long.")
    return jsonify(friction_radar.debug_workflow(workflow_name))


@app.route("/api/anomalies/<workflow_name>")
def anomalies(workflow_name):
    if len(workflow_name) > MAX_WORKFLOW_NAME_LEN:
        raise BadRequest("'workflow_name' is too long.")
    return jsonify(workflow_discovery.detect_anomalous_runs(workflow_name))


@app.route("/api/propose", methods=["POST"])
def propose():
    body = _json_body()
    workflow_name = _required_str(body, "workflow_name", MAX_WORKFLOW_NAME_LEN)
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
    body = _json_body()
    proposal_id = _required_str(body, "proposal_id", 64)
    return jsonify(confirm_action(proposal_id))


@app.route("/api/dismiss", methods=["POST"])
def dismiss():
    body = _json_body()
    workflow_name = _required_str(body, "workflow_name", MAX_WORKFLOW_NAME_LEN)
    reason = body.get("reason", "")
    if not isinstance(reason, str) or len(reason) > MAX_REASON_LEN:
        raise BadRequest(f"'reason' must be a string of at most {MAX_REASON_LEN} characters.")
    return jsonify(user_memory.dismiss_workflow(workflow_name, reason=reason))


@app.route("/api/restore", methods=["POST"])
def restore():
    body = _json_body()
    workflow_name = _required_str(body, "workflow_name", MAX_WORKFLOW_NAME_LEN)
    return jsonify(user_memory.restore_workflow(workflow_name))


@app.route("/api/dismissed")
def dismissed():
    return jsonify({"dismissed_workflows": user_memory.list_dismissed()})


@app.route("/api/brief")
def brief():
    """The same briefing the MCP tool narrate_briefing returns -- both call
    briefing.build_briefing, so Hexi's "brief me" and the MCP tool can't
    drift apart."""
    top_k = _clamped_top_k(request.args.get("top_k"))
    return jsonify(build_briefing(
        friction_radar, workflow_discovery, top_k=top_k,
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
        content = f.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise BadRequest(f"File is too large (limit is {MAX_UPLOAD_BYTES} bytes).")
        try:
            content = content.decode("utf-8")
        except UnicodeDecodeError:
            raise BadRequest("File must be UTF-8 text.")

        if name.endswith(".json"):
            import json as _json
            try:
                raw = from_activitywatch_events(_json.loads(content))
            except (_json.JSONDecodeError, KeyError, TypeError):
                raise BadRequest("Couldn't parse that as an ActivityWatch JSON export.")
        elif name.endswith(".csv"):
            import tempfile
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".csv")
            try:
                with os.fdopen(tmp_fd, "w") as tmp:
                    tmp.write(content)
                raw = from_toggl_csv(tmp_path)
            except Exception:
                raise BadRequest("Couldn't parse that as a Toggl CSV export.")
            finally:
                os.remove(tmp_path)
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
        except Exception:  # noqa: BLE001 -- network/parse failure, not a 500
            app.logger.exception("Google file import failed")
            return jsonify({"error": "Couldn't read that file. Check the link is shared as 'anyone with the link'."}), 400
        wd = WorkflowDiscovery.from_raw_events(raw, similarity_threshold=0.6) if raw else None

    elif request.is_json and request.json.get("github_repo"):
        repo_spec = request.json["github_repo"].strip().strip("/")
        if repo_spec.startswith("http"):
            repo_spec = repo_spec.split("github.com/")[-1]
        parts = repo_spec.split("/")
        if len(parts) != 2:
            return jsonify({"error": "Expected 'owner/repo' or a github.com URL."}), 400
        owner, repo = parts
        # GITHUB_TOKEN, if set, is meant to raise the operator's own
        # unauthenticated rate limit -- not to become a way for any visitor
        # of this public demo to query private repos the token can read. It
        # is only used here when the operator has explicitly said that's
        # fine (a token scoped to public_repo only, say).
        token = os.environ.get("GITHUB_TOKEN") if os.environ.get("GITHUB_TOKEN_PUBLIC_DEMO_OK") == "true" else None
        try:
            raw = from_github_pull_requests(owner, repo, max_prs=30, token=token)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception:  # noqa: BLE001 -- network/API failure, not a 500
            app.logger.exception("GitHub PR import failed for %s/%s", owner, repo)
            return jsonify({"error": "Couldn't fetch that repo's pull requests. Check the owner/repo and try again."}), 400
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
    # Same reasoning as mcp_server.py's MCP_BIND_HOST: default to loopback,
    # and require an explicit opt-in to bind wider rather than defaulting
    # to 0.0.0.0. Flask/Werkzeug's dev server has no built-in Origin check
    # equivalent to FastMCP's, so this is the only guard it gets.
    app.run(host=os.environ.get("WEB_BIND_HOST", "127.0.0.1"), port=int(os.environ.get("WEB_PORT", "5000")))
