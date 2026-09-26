# Isse Automate Kardo

Alexa+ watches how you work, finds where the time actually goes, and tells
you exactly what's worth automating — you say yes, and only then does it act.

Built for the Amazon Developer Hackathon: Build, Ship, Shape — Alexa+ track.

## The journey

```
"Alexa, what patterns are in my work?"
   -> discover_workflows()             clusters raw event sequences into
                                         workflows -- no pre-existing label,
                                         genuine sequence-similarity clustering

"Where am I wasting time?"
   -> get_top_friction_points()        ranks workflows by total time cost
                                         + automation tier

"Why does bug triage take so long?"
   -> debug_workflow()                 step-level bottleneck breakdown

"Was there anything unusual?"
   -> detect_anomalous_runs()          flags runs that blew past the usual
                                         range, and names the likely cause

"Can you automate the reporting steps?"
   -> propose_automation()             concrete, step-level proposal;
                                         never executes on its own
"Yes."
   -> confirm_automation()             executes only after you say so
```

## Where things stand

| | |
|---|---|
| ✅ Shipped | Workflow discovery straight from raw activity sequences |
| ✅ Shipped | Time-cost + automation-potential scoring per workflow |
| ✅ Shipped | Root-cause breakdown — which step is the actual bottleneck |
| ✅ Shipped | Anomaly detection on individual runs |
| ✅ Shipped | Human-in-the-loop automation — nothing runs without a yes |
| ✅ Shipped | Segmenting a continuous raw event stream into runs automatically |
| 🔜 Next | Bedrock-powered narration on the Alexa+ side |
| 🔜 Next | Real data source integrations instead of synthetic data |
| 🔜 Next | Real execution behind a confirmed automation (currently simulated) |

## Build status

| Component | Progress |
|---|---|
| Synthetic activity data | `██████████` 100% |
| Workflow discovery (clustering) | `██████████` 100% |
| Friction / time-cost analysis | `██████████` 100% |
| Root-cause bottleneck breakdown | `██████████` 100% |
| Anomaly detection | `██████████` 100% |
| Human-in-the-loop actions | `██████████` 100% |
| MCP server (Streamable HTTP) | `██████████` 100% |
| Raw-stream segmentation | `████████░░` 80% |
| Bedrock narration | `░░░░░░░░░░` 0% |
| Real data integrations | `░░░░░░░░░░` 0% |
| Real automation execution | `░░░░░░░░░░` 0% |

## MCP tools

| Tool | Purpose |
|---|---|
| `discover_workflows` | Cluster raw event sequences into workflows, no label used |
| `get_top_friction_points` | Workflows costing the most time, with automation tier |
| `explain_friction` | Why a workflow is/isn't automatable |
| `estimate_time_cost` | Total/average time cost for a named workflow |
| `debug_workflow` | Root-cause: which steps actually consume the time |
| `detect_anomalous_runs` | Specific instances that ran unusually long, and why |
| `propose_automation` / `confirm_automation` | Propose never executes; only a matching confirm does |

## Architecture

```
                     Alexa+
                       |
                       v
        MCP server (Streamable HTTP, spec 2025-06-18/2025-11-25+)
                       |
    +-------------------+-------------------+
    |                   |                   |
    v                   v                   v
workflow_discovery.py  friction_radar.py   actions.py
(sequence clustering,  (time-cost agg,     (human-in-the-loop
 anomaly detection)     root-cause debug)   propose/confirm)
    |                   |                   |
    +----------- synthetic_data.py ---------+
             (deterministic, seeded)
```

Clustering, scoring, and anomaly detection are all deterministic — no LLM
involved. Alexa+ only turns the already-computed results into speech.

## A few things worth knowing

Workflow discovery no longer needs pre-split runs — it can reconstruct them
from a raw stream using timing alone (see `src/session_segmentation.py`).
It's not perfect: on this project's own data it recovers the true run
boundaries with an Adjusted Rand Index of 0.876, and the mistakes it does
make follow a clear pattern — workflows that only happen a handful of times
a week (like onboarding) occasionally get merged with whatever ran right
next to them, because there's less data to learn that workflow's normal
timing rhythm. Frequent workflows segment cleanly. Worth saying out loud
rather than glossing over.

Confirming an automation doesn't actually trigger anything real right now —
it's a clean stub so the propose → confirm interaction works end to end,
but the actual execution step still needs to be wired up to something.

Anomaly detection needs at least a handful of runs of the same workflow
before it says anything — with only one or two data points it just says so
instead of guessing.

## Running it

```bash
pip install -r requirements.txt
python src/synthetic_data.py     # generates data/*.json (idempotent)
python src/mcp_server.py         # serves MCP over Streamable HTTP at :8000/mcp/
```
