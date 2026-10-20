"""
Lets Hexi's voice path act through the real MCP server instead of importing
the analysis modules directly. The browser transcribes speech and
web/static/intents.js classifies it; this module turns the resulting
{intent, workflow} into calls to the MCP server's tools, over Streamable HTTP,
using the official MCP client -- the same way Alexa+ would.

The connection refuses to proceed if the server negotiates a protocol older
than 2025-11-25 (the hackathon minimum), so a downgrade fails loudly instead
of quietly running on an unsupported version.

Two-step automation for voice: a spoken "automate it" only calls
propose_automation and returns the proposal id; the automation runs only when
a second utterance arrives carrying that id. A single misheard word therefore
can't trigger confirm_automation on its own.
"""

import asyncio
import json
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

MIN_PROTOCOL = "2025-11-25"  # ISO dates, so string comparison is ordered
NEEDS_WORKFLOW = {"why", "anomalies", "automate", "dismiss", "restore"}
EXAMPLES = [
    "what's costing me time", "why is reporting slow", "any unusual runs in the tickets",
    "automate it", "stop suggesting bug triage", "what have I dismissed", "brief me",
]


class McpUnavailable(Exception):
    """Server unreachable, or it answered in a way we can't use."""


def default_url():
    port = os.environ.get("MCP_SERVER_PORT", "8000")
    return os.environ.get("HEXI_MCP_URL", f"http://127.0.0.1:{port}/mcp")


async def _session_calls(url, calls):
    async with streamable_http_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            version = (await session.initialize()).protocolVersion
            if version < MIN_PROTOCOL:
                raise McpUnavailable(f"server negotiated {version}; need {MIN_PROTOCOL}+")
            results = []
            for name, args in calls:
                res = await session.call_tool(name, args)
                text = res.content[0].text if res.content else ""
                if res.isError:
                    raise McpUnavailable(f"tool {name} failed: {text}")
                results.append(json.loads(text))
            return version, results


def call_tools(calls, url=None, timeout=15):
    """Run tool calls in one MCP session. Returns (protocol_version, results)."""
    try:
        return asyncio.run(asyncio.wait_for(_session_calls(url or default_url(), calls), timeout))
    except KeyboardInterrupt:
        raise
    except BaseException as exc:
        # The client runs inside an anyio task group, so our own errors come
        # back wrapped in an ExceptionGroup; unwrap to keep the real message.
        for leaf in _leaves(exc):
            if isinstance(leaf, McpUnavailable):
                raise leaf from None
        raise McpUnavailable(f"couldn't reach the MCP server: {exc}") from exc


def call_tool(name, args, url=None, timeout=15):
    """Call a single MCP tool. Returns (protocol_version, result_dict)."""
    version, (data,) = call_tools([(name, args)], url=url, timeout=timeout)
    return version, data


def _leaves(exc):
    if isinstance(exc, BaseExceptionGroup):
        for inner in exc.exceptions:
            yield from _leaves(inner)
    else:
        yield exc


def _hours(minutes):
    return round(minutes / 60, 1)


def describe_opportunities(data):
    """One spoken-length answer to "what can I automate?"."""
    ops = data.get("opportunities") or []
    if not ops:
        why = (data.get("not_automatable") or [{}])[0].get("why_not") or []
        return "Nothing here is safe to automate without a person." + (f" For example, {why[0]}." if why else "")
    top = ops[0]
    steps = ", ".join(s.replace("_", " ") for s in top["automate_steps"])
    more = f" {len(ops) - 1} more worth a look." if len(ops) > 1 else ""
    return (f"I'd start with '{top['workflow_name']}': automate {steps} and replaying your history saves about "
            f"{top['hours_saved_per_week']} hours a week. Across all pipelines that's {data['total_hours_saved_per_week']} hours a week.{more} "
            "Say 'automate it' to propose it.")


def run_intent(intent, workflow=None, proposal_id=None, url=None, dataset_id=None):
    """Execute one classified voice intent through MCP tools. Returns
    {reply, mood, pending_proposal_id, tools, protocol}."""
    if intent not in NEEDS_WORKFLOW | {"brief", "friction", "dismissed_list", "diagnose", "opportunities"}:
        # Unknown, empty, help, or anything unrecognised: answer with what can
        # be asked rather than an error. No tool is called.
        return {"reply": "I didn't catch a request I can act on. Try: " + "; ".join(EXAMPLES[:4]) + ".",
                "mood": "idle", "pending_proposal_id": proposal_id, "tools": [], "protocol": None,
                "intent": "unknown", "examples": EXAMPLES}

    if (intent in NEEDS_WORKFLOW or intent == "diagnose") and not workflow:
        return {"reply": "Which workflow? Name one from the list on screen.",
                "mood": "idle", "pending_proposal_id": proposal_id, "tools": [], "protocol": None}

    if intent == "brief":
        calls = [("narrate_briefing", {})]
    elif intent == "friction":
        calls = [("get_top_friction_points", {"top_k": 1})]
    elif intent == "opportunities":
        calls = [("find_automation_opportunities", {})]
    elif intent == "why":
        calls = [("debug_workflow", {"workflow_name": workflow})]
    elif intent == "anomalies":
        calls = [("detect_anomalous_runs", {"workflow_name": workflow, "top_k": 1})]
    elif intent == "automate":
        calls = ([("confirm_automation", {"proposal_id": proposal_id})] if proposal_id
                 else [("propose_automation", {"workflow_name": workflow})])
    elif intent == "diagnose":
        calls = [("diagnose_workflow", {"workflow_name": workflow})]
    elif intent == "dismiss":
        calls = [("dismiss_workflow_suggestions", {"workflow_name": workflow, "reason": "dismissed by voice"})]
    elif intent == "restore":
        calls = [("restore_workflow_suggestions", {"workflow_name": workflow})]
    elif intent == "dismissed_list":
        calls = [("list_dismissed_workflow_suggestions", {})]

    if dataset_id and dataset_id != "sample":
        scoped = {"narrate_briefing", "get_top_friction_points", "debug_workflow", "detect_anomalous_runs",
                  "propose_automation", "diagnose_workflow", "find_automation_opportunities"}
        calls = [(n, {**a, "dataset_id": dataset_id} if n in scoped else a) for n, a in calls]

    version, (data,) = call_tools(calls, url=url)
    out = {"reply": "", "mood": "idle", "pending_proposal_id": None,
           "tools": [c[0] for c in calls], "protocol": version}

    if intent == "brief":
        out["reply"], out["mood"] = data["narration"], "curious"
    elif intent == "opportunities":
        out["reply"], out["mood"] = describe_opportunities(data), "suggesting"
        out["opportunities"] = data
    elif intent == "friction":
        pts = data["friction_points"]
        if not pts:
            out["reply"] = "Nothing to report yet."
        else:
            p = pts[0]
            out["reply"] = (f"'{p['workflow_name']}' costs {_hours(p['total_time_cost_minutes'])}h, "
                            f"rated {p['automation_tier']}.")
            out["mood"] = "curious"
    elif intent == "why":
        if "error" in data:
            out["reply"] = data["error"]
        else:
            s = data["step_breakdown"][0]
            out["reply"] = (f"In '{workflow}', '{s['step']}' takes the biggest share — "
                            f"{round(s['share_of_total'] * 100)}% of the total time.")
    elif intent == "anomalies":
        a = data.get("anomalies") or []
        out["reply"] = (f"One run of '{workflow}' ran unusually long — mainly '{a[0]['likely_cause_step']}'."
                        if a else data.get("note") or f"No anomalous runs in '{workflow}'.")
    elif intent == "automate":
        if proposal_id:
            if "error" in data:
                out["reply"] = data["error"]
            else:
                report = data.get("report") or {}
                saved, rel = report.get("time_saved"), report.get("reliability")
                if saved and rel:
                    out["reply"] = (f"Done. Replaying your history, that saves about {saved['minutes_saved_per_run']} minutes a run, "
                                    f"roughly {saved['hours_saved_per_week']} hours a week. Reliability {rel['score']} out of 100, "
                                    f"grade {rel['grade']}.")
                else:
                    out["reply"] = "Done — marked as automated (execution is simulated in this build)."
                out["mood"] = "confirmed"
                out["report"] = report or None
        elif data.get("proposal_id"):
            out["pending_proposal_id"] = data["proposal_id"]
            out["reply"] = f"{data['summary']} Say yes to confirm."
            out["mood"] = "suggesting"
        else:
            out["reply"] = data.get("summary", "Nothing here was safe to automate.")
            out["mood"] = "watching"
    elif intent == "diagnose":
        if "error" in data:
            out["reply"] = data["error"]
        else:
            adv = data["advice"]
            first = adv["prescription"][0]["action"] if adv.get("prescription") else ""
            out["reply"] = f"{adv['headline']} {first}".strip()
            out["mood"] = "curious"
            out["diagnosis"] = data
    elif intent == "dismiss":
        out["reply"] = f"Got it — won't suggest '{workflow}' again, even after a restart."
    elif intent == "restore":
        out["reply"] = data.get("error") or f"Restored — I'll suggest '{workflow}' again if it comes up."
    elif intent == "dismissed_list":
        names = [w["workflow_name"] for w in data["dismissed_workflows"]]
        out["reply"] = (f"You've asked me to stop suggesting: {', '.join(names)}." if names
                        else "You haven't dismissed anything.")
    return out
