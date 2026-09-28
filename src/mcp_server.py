"""
Self-hosted MCP server for the Alexa+ "Friction Radar" project.

Implements MCP over Streamable HTTP (per spec 2025-11-25+) using the
official `mcp` Python SDK's FastMCP server. Alexa+ (or any MCP client, or
`mcp-cli` / the MCP Inspector for local testing) talks to this over HTTP.

Run:
    python src/mcp_server.py
Then point an MCP client at:
    http://localhost:8000/mcp

Tool surface is scoped to the locked V1 narrative: workflow discovery,
friction/time-cost analysis, root-cause + anomaly detection, and a
human-in-the-loop automation action layer. The Signal-vs-Noise ranking
engine (ranking_engine.py) still exists and is tested, but is intentionally
NOT exposed here -- it's future work, not part of this product's story.
See README for the scope decision.
"""

import json
import os
from dotenv import load_dotenv

load_dotenv()

from mcp.server.fastmcp import FastMCP

from synthetic_data import generate_information_stream, generate_activity_events
from friction_radar import FrictionRadar
from actions import propose_action, confirm_action
from workflow_discovery import WorkflowDiscovery
from bedrock_narrator import BedrockNarrator
from briefing import build_briefing
from data_adapters import from_activitywatch_events, from_toggl_csv
import user_memory

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

# --- load (or generate, on first run) the deterministic synthetic data ----
info_path = os.path.join(DATA_DIR, "information_stream.json")
events_path = os.path.join(DATA_DIR, "activity_events.json")
os.makedirs(DATA_DIR, exist_ok=True)

if not os.path.exists(info_path):
    generate_information_stream(out_path=info_path)
if not os.path.exists(events_path):
    generate_activity_events(out_path=events_path)

with open(events_path) as f:
    ACTIVITY_EVENTS = json.load(f)

friction_radar = FrictionRadar(ACTIVITY_EVENTS)
workflow_discovery = WorkflowDiscovery(ACTIVITY_EVENTS, similarity_threshold=0.75)
narrator = BedrockNarrator()

# host 0.0.0.0 so this is reachable from outside the container when run via
# Docker; port configurable so it doesn't collide with anything else the
# judge already has running locally.
mcp = FastMCP(
    "friction-radar",
    host="0.0.0.0",
    port=int(os.environ.get("MCP_SERVER_PORT", "8000")),
)


# ---------------------------- Discovery tools -------------------------------

@mcp.tool()
def discover_workflows() -> dict:
    """Discover recurring workflows directly from the raw activity event
    sequences, using sequence-similarity clustering -- not from any
    pre-existing workflow label. Use this to show how workflows were found,
    or when the user asks what patterns exist in their activity."""
    clusters = workflow_discovery.discover()
    return {"discovered_workflows": clusters}


@mcp.tool()
def discover_workflows_from_import(source: str, file_path: str) -> dict:
    """Run the same label-free discovery pipeline against real, imported
    activity data instead of this project's synthetic dataset -- proof the
    pipeline isn't tied to synthetic data. `source` is "activitywatch" (a
    JSON export of ActivityWatch events, github.com/ActivityWatch) or
    "toggl" (a Toggl Track CSV export). `file_path` is a path to that file,
    readable from wherever this server is running. Imported data has no
    outcome/rework labels, so only the unsupervised half of this project
    (segmentation, clustering, anomaly detection) runs on it -- see
    data_adapters.py for exactly what that trade-off is and why."""
    if source == "activitywatch":
        with open(file_path) as f:
            raw = from_activitywatch_events(json.load(f))
    elif source == "toggl":
        raw = from_toggl_csv(file_path)
    else:
        return {"error": f"Unknown source '{source}'. Use 'activitywatch' or 'toggl'."}

    wd = WorkflowDiscovery.from_raw_events(raw)
    return {"source": source, "events_imported": len(raw), "discovered_workflows": wd.discover()}


# ---------------------------- Friction Radar tools --------------------------

@mcp.tool()
def get_top_friction_points(top_k: int = 3, include_dismissed: bool = False) -> dict:
    """Return the workflows costing the user the most time, ranked by total
    time cost, with an automation-potential score for each. Use this when the
    user asks where they're wasting time or what's inefficient. Workflows the
    user has previously dismissed (see dismiss_workflow_suggestions) are left
    out by default -- pass include_dismissed=True only if the user explicitly
    asks to see everything regardless of past dismissals."""
    points = friction_radar.top_friction_points(top_k=top_k + len(user_memory.list_dismissed()))
    if not include_dismissed:
        points = [p for p in points if not user_memory.is_dismissed(p["workflow_name"])]
    return {"friction_points": points[:top_k]}


@mcp.tool()
def explain_friction(workflow_name: str) -> dict:
    """Explain in plain terms why a given workflow is or isn't a good
    automation candidate."""
    return {"workflow_name": workflow_name, "explanation": friction_radar.explain(workflow_name)}


@mcp.tool()
def estimate_time_cost(workflow_name: str) -> dict:
    """Return the total and average time cost for a named recurring
    workflow."""
    result = friction_radar.estimate_time_cost(workflow_name)
    if result is None:
        return {"error": f"No data for workflow '{workflow_name}'"}
    return result


@mcp.tool()
def debug_workflow(workflow_name: str) -> dict:
    """Root-cause a slow workflow: break down which specific steps actually
    consume the time, not just the total. Use this when the user asks why
    something takes so long or where the time in a workflow actually goes."""
    return friction_radar.debug_workflow(workflow_name)


@mcp.tool()
def detect_anomalous_runs(workflow_name: str, top_k: int = 3) -> dict:
    """Find specific occurrences of a workflow that took unusually long
    compared to that workflow's own typical pattern, and identify which
    step likely caused the delay. Use this when the user asks if anything
    unusual happened, or wants to know about a specific bad instance rather
    than the average."""
    return workflow_discovery.detect_anomalous_runs(workflow_name, top_k=top_k)


# ---------------------------- Narration tool (AWS Bedrock) ------------------

@mcp.tool()
def narrate_briefing(top_k: int = 3) -> dict:
    """Compose one short, spoken-ready briefing covering the top friction
    points and any anomalous runs, using Amazon Bedrock to phrase the
    already-computed analysis (Bedrock never sees raw data and never scores
    anything -- it only turns finished numbers into sentences). Falls back
    to a plain templated summary if Bedrock isn't configured. Use this when
    the user wants one pulled-together update rather than calling several
    tools themselves."""
    return build_briefing(
        friction_radar, workflow_discovery, narrator, top_k=top_k,
        exclude={d["workflow_name"] for d in user_memory.list_dismissed()},
    )


# ---------------------------- Action tools ----------------------------------

@mcp.tool()
def propose_automation(workflow_name: str) -> dict:
    """Propose automating the low-judgment steps of a workflow, based on its
    debug_workflow breakdown. This NEVER executes anything -- it only returns
    a proposal_id. Use confirm_automation with that id to actually execute,
    and only after the user has explicitly agreed. If the user has previously
    dismissed suggestions for this workflow, this respects that standing
    preference instead of proposing anyway -- call restore_workflow_suggestions
    first if the user has changed their mind."""
    if user_memory.is_dismissed(workflow_name):
        return {
            "proposal_id": None,
            "workflow_name": workflow_name,
            "summary": (
                f"You previously asked not to be offered automation for "
                f"'{workflow_name}'. Say the word and I'll bring it back."
            ),
        }
    debug_result = friction_radar.debug_workflow(workflow_name)
    return propose_action(workflow_name, debug_result)


@mcp.tool()
def confirm_automation(proposal_id: str) -> dict:
    """Execute a previously proposed automation. Only call this after the
    user has explicitly said yes to a specific proposal_id returned by
    propose_automation -- never call it speculatively."""
    return confirm_action(proposal_id)


# ---------------------------- Cross-session memory ---------------------------
# The one piece of state here that outlives a single Alexa+ conversation --
# see user_memory.py's docstring for why this, specifically, is the thing
# backed by a file rather than kept in memory like everything else.

@mcp.tool()
def dismiss_workflow_suggestions(workflow_name: str, reason: str = "") -> dict:
    """Stop suggesting automation for this workflow, from now on, across
    future conversations -- not just for the rest of this one. Use this when
    the user says something like "stop asking me about X" or "I always want
    to do that one myself." This persists until restore_workflow_suggestions
    is called for the same workflow."""
    return user_memory.dismiss_workflow(workflow_name, reason=reason)


@mcp.tool()
def restore_workflow_suggestions(workflow_name: str) -> dict:
    """Undo a previous dismissal -- resume offering automation suggestions
    for this workflow. Use this when the user says they've changed their
    mind about a workflow they'd previously dismissed."""
    return user_memory.restore_workflow(workflow_name)


@mcp.tool()
def list_dismissed_workflow_suggestions() -> dict:
    """List every workflow the user has asked not to be offered automation
    for, with why (if given) and when. Use this if the user asks what
    they've previously dismissed, or wants a reminder before deciding
    whether to restore one."""
    return {"dismissed_workflows": user_memory.list_dismissed()}


if __name__ == "__main__":
    # Streamable HTTP transport, per MCP spec 2025-11-25+
    mcp.run(transport="streamable-http")
