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
from mcp.server.fastmcp import FastMCP

from synthetic_data import generate_information_stream, generate_activity_events
from friction_radar import FrictionRadar
from actions import propose_action, confirm_action
from workflow_discovery import WorkflowDiscovery

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

mcp = FastMCP("friction-radar")


# ---------------------------- Discovery tools -------------------------------

@mcp.tool()
def discover_workflows() -> dict:
    """Discover recurring workflows directly from the raw activity event
    sequences, using sequence-similarity clustering -- not from any
    pre-existing workflow label. Use this to show how workflows were found,
    or when the user asks what patterns exist in their activity."""
    clusters = workflow_discovery.discover()
    return {"discovered_workflows": clusters}


# ---------------------------- Friction Radar tools --------------------------

@mcp.tool()
def get_top_friction_points(top_k: int = 3) -> dict:
    """Return the workflows costing the user the most time, ranked by total
    time cost, with an automation-potential score for each. Use this when the
    user asks where they're wasting time or what's inefficient."""
    return {"friction_points": friction_radar.top_friction_points(top_k=top_k)}


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


# ---------------------------- Action tools ----------------------------------

@mcp.tool()
def propose_automation(workflow_name: str) -> dict:
    """Propose automating the low-judgment steps of a workflow, based on its
    debug_workflow breakdown. This NEVER executes anything -- it only returns
    a proposal_id. Use confirm_automation with that id to actually execute,
    and only after the user has explicitly agreed."""
    debug_result = friction_radar.debug_workflow(workflow_name)
    return propose_action(workflow_name, debug_result)


@mcp.tool()
def confirm_automation(proposal_id: str) -> dict:
    """Execute a previously proposed automation. Only call this after the
    user has explicitly said yes to a specific proposal_id returned by
    propose_automation -- never call it speculatively."""
    return confirm_action(proposal_id)


if __name__ == "__main__":
    # Streamable HTTP transport, per MCP spec 2025-11-25+
    mcp.run(transport="streamable-http")
