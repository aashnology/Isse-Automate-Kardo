# Friction Radar

**Alexa+ doesn't just answer questions — it watches how you work, finds where
the time actually goes, and tells you exactly what could be automated.**

Built for the Amazon Developer Hackathon: Build, Ship, Shape — **Alexa+ track**,
stacked with the **AWS Builder** and **Open Source** mini challenges.

## Positioning

This project is built to demonstrate a specific combination: a data analyst
who can also design and ship AI automation, not just read a dashboard.
Every tool below produces a number, a root cause, and a concrete automation
proposal — not just a summary.

## Scope decision (locked)

An earlier draft of this project also included a "Signal vs Noise" module
(personalized information ranking). That's been **dropped from the core
narrative** — it's a second product, not part of this story, and diluted
the focus. The code still exists in `src/ranking_engine.py` and is tested,
but it is intentionally **not** exposed as an MCP tool. It's documented here
as future work, not deleted, in case it's worth reviving as a real V3.

## The journey this demo proves out

```
"Alexa, what patterns are in my work?"
   -> discover_workflows()             clusters raw event sequences into
                                         workflows -- no pre-existing label,
                                         genuine sequence-similarity clustering

"Where am I wasting time?"
   -> get_top_friction_points()        ranks discovered/named workflows by
                                         total time cost + automation tier

"Why does bug triage take so long?"
   -> debug_workflow()                 step-level bottleneck breakdown

"Was there anything unusual?"
   -> detect_anomalous_runs()          flags specific runs that blew past
                                         that workflow's own typical range,
                                         and names the step that likely caused it

"Can you automate the reporting steps?"
   -> propose_automation()             concrete, step-level proposal;
                                         never executes on its own
"Yes."
   -> confirm_automation()             executes only after explicit confirmation
```

## Why this isn't a "base level" project

The most common shortcut in a workflow-automation demo is to hardcode
workflow labels and pretend that's process mining. This project doesn't:
`discover_workflows()` clusters **raw activity sequences** by
similarity — see `src/workflow_discovery.py` — and only uses the
ground-truth label afterward, to make the demo readable. On the test
dataset it rediscovers all three real workflows with 100% label purity,
using zero label information during clustering. `detect_anomalous_runs()`
adds a second layer: even within a correctly discovered workflow, it flags
the specific instances that were statistically abnormal (IQR-based, robust
to the right-skew you'd expect in time data) and names the step that likely
drove it.

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

No LLM sits inside clustering, scoring, or anomaly detection. Alexa+ (on
the other side of MCP) turns already-computed structured results into
natural language — the analysis itself stays deterministic and inspectable.

## MCP tools (8)

| Tool | Purpose |
|---|---|
| `discover_workflows` | Cluster raw event sequences into workflows, no label used |
| `get_top_friction_points` | Workflows costing the most time, with automation tier |
| `explain_friction` | Why a workflow is/isn't automatable |
| `estimate_time_cost` | Total/average time cost for a named workflow |
| `debug_workflow` | Root-cause: which steps actually consume the time |
| `detect_anomalous_runs` | Specific instances that ran unusually long, and why |
| `propose_automation` / `confirm_automation` | Human-in-the-loop action layer — propose never executes; only a matching confirm does |

## What's actually implemented vs. proposed

**Implemented, tested, and running (this repo):**
- Deterministic synthetic activity-event generator (three real workflows,
  seeded, reproducible)
- Sequence-similarity workflow discovery (LCS-based, union-find clustering) —
  verified to rediscover all ground-truth workflows with 100% purity without
  using the label during clustering
- IQR-based anomaly detection on run duration, with per-step root-cause
  attribution for the anomalous run
- Friction Radar: time-cost aggregation, automation-potential scoring,
  step-level bottleneck analysis
- A propose/confirm action layer with in-memory state (no silent execution)
- MCP server exposing all of the above over real Streamable HTTP — verified
  with raw `tools/list` and `tools/call` requests, not just imports

**Also built and tested, but out of the core narrative:**
- `src/ranking_engine.py` — the Signal vs Noise ranking engine (TF-IDF dedup,
  novelty, MMR diversity) and `src/actions.py`'s `find_related_signal` bridge.
  Kept as documented future work rather than deleted.

**Proposed, not built (future work):**
- Session segmentation from a truly raw event stream (this repo starts from
  pre-segmented `workflow_run_id`s -- segmenting a continuous stream into
  runs via time-gap detection is a separate, unsolved step here, and it's
  named honestly rather than assumed away)
- Real data source integrations (calendar, browser, ticketing system) in
  place of synthetic data
- Real Bedrock-powered narration on the Alexa+ side
- Real (non-simulated) execution behind `confirm_automation`

## Known limitations (worth stating in the demo/README)

- Workflow discovery clusters *pre-segmented* runs, not a continuous raw
  stream -- see "session segmentation" above.
- `confirm_automation` is a simulated execution, clearly commented as such
  in `actions.py`.
- Anomaly detection needs at least 4 runs of a workflow to be reliable;
  it says so rather than guessing on small samples.

## Running it

```bash
pip install -r requirements.txt
python src/synthetic_data.py     # generates data/*.json (idempotent)
python src/mcp_server.py         # serves MCP over Streamable HTTP at :8000/mcp/
python tests/evaluation.py       # sanity-check on the (separate) ranking engine
```

## AWS Builder mini challenge

Bedrock sits on the Alexa+ side of the MCP boundary -- these tools return
structured JSON; a Bedrock call turns that into the spoken narrative in the
example journey above. [Document the specific Bedrock integration here once
wired up during the hackathon window.]

## Open Source mini challenge

This repo is MIT-licensed in full. [Add the separate contribution URL,
GitHub username, and description here once completed.]

## Pre-existing work disclosure

Per the hackathon's submission requirements: the core of this project
(synthetic data, workflow discovery, friction radar, anomaly detection, MCP
server, action layer) was built before the official submission window
opened, to reduce in-window risk. During the submission window itself:
[fill in -- expect this to be the Bedrock integration, the Alexa+-side
conversation flow, demo recording, and polish].

## Interview talking points

- **Data Analyst**: KPI design (automation-potential formula), process
  analysis (workflow reconstruction from raw event sequences), robust
  statistics (IQR outlier detection over naive z-scores, and why), data
  quality (synthetic-data design that stress-tests both clustering and
  outlier detection).
- **Data Science**: unsupervised sequence clustering with a real
  similarity metric (LCS), root-cause attribution, a from-scratch
  automation-potential formula with documented assumptions and limitations.
- **AI/Agent**: MCP tool design (why 8 tools, not 25), the
  deterministic-vs-LLM boundary, a real human-in-the-loop propose/confirm
  pattern instead of autonomous execution, and an honest scope cut
  (Signal vs Noise dropped) explained as a product decision, not a gap.
