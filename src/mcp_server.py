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
from mcp.types import ToolAnnotations

from synthetic_data import generate_information_stream, generate_activity_events
from friction_radar import FrictionRadar
from actions import propose_action, confirm_action
from workflow_discovery import WorkflowDiscovery
from briefing import build_briefing
from data_adapters import from_activitywatch_events, from_toggl_csv
from safe_import import resolve_import_path, UnsafeImportPath
import user_memory
from workspace import get_workspace, UnknownDataset, SAMPLE_ID
from diagnosis import diagnose
import llm_advisor

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

# FastMCP only auto-enables DNS-rebinding/Origin protection when host is
# exactly "127.0.0.1", "localhost", or "::1" (see mcp/server/transport_security.py
# in the installed 1.30.0 SDK) -- for any other host, including "0.0.0.0",
# protection defaults OFF unless explicitly configured. So: default to the
# loopback bind (safe, and it's what a judge running this locally needs
# anyway); binding wider is an explicit opt-in via MCP_BIND_HOST, and when
# that's not a loopback address we build TransportSecuritySettings
# ourselves from MCP_ALLOWED_HOSTS/MCP_ALLOWED_ORIGINS so it doesn't fall
# back to silently unprotected.
_bind_host = os.environ.get("MCP_BIND_HOST", "127.0.0.1")
_transport_security = None
if _bind_host not in ("127.0.0.1", "localhost", "::1"):
    from mcp.server.transport_security import TransportSecuritySettings

    allowed_hosts = [h.strip() for h in os.environ.get("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    allowed_origins = [o.strip() for o in os.environ.get("MCP_ALLOWED_ORIGINS", "").split(",") if o.strip()]
    if not allowed_hosts or not allowed_origins:
        raise RuntimeError(
            "MCP_BIND_HOST is set to a non-loopback address, which disables FastMCP's "
            "automatic DNS-rebinding protection. Set MCP_ALLOWED_HOSTS and "
            "MCP_ALLOWED_ORIGINS (comma-separated) to run this way -- e.g. inside Docker, "
            "where MCP_ALLOWED_HOSTS=localhost:8000 and MCP_ALLOWED_ORIGINS=http://localhost:8000 "
            "if the container is only ever reached via a mapped localhost port on the host."
        )
    _transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )

mcp = FastMCP(
    "friction-radar",
    host=_bind_host,
    port=int(os.environ.get("MCP_SERVER_PORT", "8000")),
    transport_security=_transport_security,
)



def _ws(dataset_id):
    """(workspace, None) or (None, error dict). dataset_id 'sample' is the built-in data."""
    try:
        return get_workspace(dataset_id or SAMPLE_ID), None
    except UnknownDataset as exc:
        return None, {"error": str(exc.args[0])}


# ---------------------------- Discovery tools -------------------------------

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False))
def discover_workflows(dataset_id: str = "sample") -> dict:
    """Discover recurring workflows directly from the raw activity event
    sequences, using sequence-similarity clustering -- not from any
    pre-existing workflow label. Use this to show how workflows were found,
    or when the user asks what patterns exist in their activity."""
    ws, err = _ws(dataset_id)
    if err:
        return err
    return {"discovered_workflows": ws.discovery.discover()}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False))
def discover_workflows_from_import(source: str, file_path: str) -> dict:
    """Run the same label-free discovery pipeline against real, imported
    activity data instead of this project's synthetic dataset -- proof the
    pipeline isn't tied to synthetic data. `source` is "activitywatch" (a
    JSON export of ActivityWatch events, github.com/ActivityWatch) or
    "toggl" (a Toggl Track CSV export). `file_path` names a file that has
    been placed in this server's import directory (IMPORT_DIR, default
    data/imports/) -- it is never opened relative to the server's working
    directory or the filesystem root, so it can't be used to read files
    outside that directory. Imported data has no outcome/rework labels, so
    only the unsupervised half of this project (segmentation, clustering,
    anomaly detection) runs on it -- see data_adapters.py for exactly what
    that trade-off is and why."""
    extensions = {"activitywatch": {".json"}, "toggl": {".csv"}}.get(source)
    if extensions is None:
        return {"error": f"Unknown source '{source}'. Use 'activitywatch' or 'toggl'."}

    try:
        safe_path = resolve_import_path(file_path, extensions)
    except UnsafeImportPath as exc:
        return {"error": str(exc)}

    try:
        if source == "activitywatch":
            with open(safe_path) as f:
                raw = from_activitywatch_events(json.load(f))
        else:
            raw = from_toggl_csv(safe_path)
    except Exception:
        # Never echo the parse exception: for a JSON/CSV parse failure it
        # can include a fragment of the file's own content.
        return {"error": f"Couldn't parse '{os.path.basename(file_path)}' as {source} data."}

    wd = WorkflowDiscovery.from_raw_events(raw)
    return {"source": source, "events_imported": len(raw), "discovered_workflows": wd.discover()}


# ---------------------------- Friction Radar tools --------------------------

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False))
def get_top_friction_points(top_k: int = 3, include_dismissed: bool = False, dataset_id: str = "sample") -> dict:
    """Return the workflows costing the user the most time, ranked by total
    time cost, with an automation-potential score for each. Use this when the
    user asks where they're wasting time or what's inefficient. Workflows the
    user has previously dismissed (see dismiss_workflow_suggestions) are left
    out by default -- pass include_dismissed=True only if the user explicitly
    asks to see everything regardless of past dismissals."""
    ws, err = _ws(dataset_id)
    if err:
        return err
    points = ws.radar.top_friction_points(top_k=top_k + len(user_memory.list_dismissed()))
    if not include_dismissed:
        points = [p for p in points if not user_memory.is_dismissed(p["workflow_name"])]
    return {"friction_points": points[:top_k]}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False))
def find_automation_opportunities(dataset_id: str = "sample") -> dict:
    """Scan every workflow in the dataset and rank which ones are worth
    automating, with the safe-to-automate steps and a replay-based estimate of
    hours saved per week for each. Use this when the user asks what they can
    automate, without naming a workflow. Read-only: nothing is proposed or run."""
    from diagnosis import automation_opportunities
    ws, err = _ws(dataset_id)
    if err:
        return err
    return automation_opportunities(ws, dismissed={w["workflow_name"] for w in user_memory.list_dismissed()})


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False))
def explain_friction(workflow_name: str, dataset_id: str = "sample") -> dict:
    """Explain in plain terms why a given workflow is or isn't a good
    automation candidate."""
    ws, err = _ws(dataset_id)
    if err:
        return err
    return {"workflow_name": workflow_name, "explanation": ws.radar.explain(workflow_name)}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False))
def estimate_time_cost(workflow_name: str, dataset_id: str = "sample") -> dict:
    """Return the total and average time cost for a named recurring
    workflow."""
    ws, err = _ws(dataset_id)
    if err:
        return err
    result = ws.radar.estimate_time_cost(workflow_name)
    if result is None:
        return {"error": f"No data for workflow '{workflow_name}'"}
    return result


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False))
def debug_workflow(workflow_name: str, dataset_id: str = "sample") -> dict:
    """Root-cause a slow workflow: break down which specific steps actually
    consume the time, not just the total. Use this when the user asks why
    something takes so long or where the time in a workflow actually goes."""
    ws, err = _ws(dataset_id)
    if err:
        return err
    return ws.radar.debug_workflow(workflow_name)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False))
def detect_anomalous_runs(workflow_name: str, top_k: int = 3, dataset_id: str = "sample") -> dict:
    """Find specific occurrences of a workflow that took unusually long
    compared to that workflow's own typical pattern, and identify which
    step likely caused the delay. Use this when the user asks if anything
    unusual happened, or wants to know about a specific bad instance rather
    than the average."""
    ws, err = _ws(dataset_id)
    if err:
        return err
    return ws.discovery.detect_anomalous_runs(workflow_name, top_k=top_k)


# ---------------------------- Narration tool ---------------------------------

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False))
def narrate_briefing(top_k: int = 3, dataset_id: str = "sample") -> dict:
    """Compose one short, spoken-ready briefing covering the top friction
    points and any anomalous runs -- a deterministic template over the
    already-computed analysis, not a language-model call. Use this when the
    user wants one pulled-together update rather than calling several tools
    themselves."""
    ws, err = _ws(dataset_id)
    if err:
        return err
    return build_briefing(
        ws.radar, ws.discovery, top_k=top_k,
        exclude={d["workflow_name"] for d in user_memory.list_dismissed()},
    )


# ---------------------------- Diagnosis tools --------------------------------

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True))
def diagnose_workflow(workflow_name: str, dataset_id: str = "sample") -> dict:
    """Diagnose a workflow and prescribe what to do about it: findings (the
    bottleneck, unstable steps, outliers), ranked actions with expected effect,
    a shadow-mode estimate of time saved with an interval, and a 0-100
    reliability score with its caveats. Use this when the user asks whether
    automating something is worth it, how reliable the result would be, or
    what to do next. `advice` is written by a language model when one is
    configured (and checked so every figure comes from the report); otherwise
    from a template. `advice.source` says which."""
    ws, err = _ws(dataset_id)
    if err:
        return err
    report = diagnose(ws, workflow_name)
    if "error" in report:
        return report
    return {"report": report, "advice": llm_advisor.advise(report)}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False))
def list_datasets(dataset_id: str = "sample") -> dict:
    """Describe a dataset: its label, how many events and runs, and which
    workflows were discovered in it. Use this to see what a dataset_id holds."""
    ws, err = _ws(dataset_id)
    if err:
        return err
    return ws.summary()


# ---------------------------- Action tools ----------------------------------

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
def propose_automation(workflow_name: str, dataset_id: str = "sample") -> dict:
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
    ws, err = _ws(dataset_id)
    if err:
        return err
    debug_result = ws.radar.debug_workflow(workflow_name)
    return propose_action(workflow_name, debug_result, workspace=ws)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False))
def confirm_automation(proposal_id: str) -> dict:
    """Execute a previously proposed automation. Only call this after the
    user has explicitly said yes to a specific proposal_id returned by
    propose_automation -- never call it speculatively. A proposal is only
    valid for an hour after it was made; call propose_automation again for
    a fresh one if confirming fails with an 'expired' error."""
    return confirm_action(proposal_id)


# ---------------------------- Cross-session memory ---------------------------
# The one piece of state here that outlives a single Alexa+ conversation --
# see user_memory.py's docstring for why this, specifically, is the thing
# backed by a file rather than kept in memory like everything else.

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def dismiss_workflow_suggestions(workflow_name: str, reason: str = "") -> dict:
    """Stop suggesting automation for this workflow, from now on, across
    future conversations -- not just for the rest of this one. Use this when
    the user says something like "stop asking me about X" or "I always want
    to do that one myself." This persists until restore_workflow_suggestions
    is called for the same workflow."""
    return user_memory.dismiss_workflow(workflow_name, reason=reason)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def restore_workflow_suggestions(workflow_name: str) -> dict:
    """Undo a previous dismissal -- resume offering automation suggestions
    for this workflow. Use this when the user says they've changed their
    mind about a workflow they'd previously dismissed."""
    return user_memory.restore_workflow(workflow_name)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False))
def list_dismissed_workflow_suggestions() -> dict:
    """List every workflow the user has asked not to be offered automation
    for, with why (if given) and when. Use this if the user asks what
    they've previously dismissed, or wants a reminder before deciding
    whether to restore one."""
    return {"dismissed_workflows": user_memory.list_dismissed()}


if __name__ == "__main__":
    # Streamable HTTP transport, per MCP spec 2025-11-25+
    mcp.run(transport="streamable-http")
