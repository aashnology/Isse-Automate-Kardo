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

"Just give me the rundown."
   -> narrate_briefing()               Bedrock phrases the already-computed
                                         findings into one spoken answer
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
| ✅ Shipped | Bedrock-powered briefing narration, with a template fallback when it's off |
| ✅ Shipped | Real data-source import (ActivityWatch, Toggl Track) through the same discovery pipeline |
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
| Bedrock narration | `██████████` 100% |
| Real data integrations | `████████░░` 80% |
| Real automation execution | `░░░░░░░░░░` 0% |

## MCP tools

| Tool | Purpose |
|---|---|
| `discover_workflows` | Cluster raw event sequences into workflows, no label used |
| `discover_workflows_from_import` | Same discovery, run against a real ActivityWatch or Toggl Track export |
| `get_top_friction_points` | Workflows costing the most time, with automation tier |
| `explain_friction` | Why a workflow is/isn't automatable |
| `estimate_time_cost` | Total/average time cost for a named workflow |
| `debug_workflow` | Root-cause: which steps actually consume the time |
| `detect_anomalous_runs` | Specific instances that ran unusually long, and why |
| `narrate_briefing` | One spoken-ready summary, phrased by Bedrock over already-computed results |
| `propose_automation` / `confirm_automation` | Propose never executes; only a matching confirm does |

## Architecture

```
                     Alexa+
                       |
                       v
        MCP server (Streamable HTTP, spec 2025-06-18/2025-11-25+)
                       |
    +-------------------+-------------------+-------------------+
    |                   |                   |                   |
    v                   v                   v                   v
workflow_discovery.py  friction_radar.py   actions.py     bedrock_narrator.py
(sequence clustering,  (time-cost agg,     (human-in-the-loop  (Amazon Bedrock,
 anomaly detection)     root-cause debug)   propose/confirm)    phrasing only)
    |                   |                   |
    +----------- synthetic_data.py ---------+
             (deterministic, seeded)
```

Clustering, scoring, and anomaly detection are all deterministic — no LLM
involved in deciding what matters. The one place an LLM (Bedrock) shows up
is `narrate_briefing`, and its job there is narrow on purpose: turn numbers
this project already computed into a sentence. It doesn't rank, score, or
touch the underlying data — see the docstring in `bedrock_narrator.py` for
exactly where that line is drawn and why it isn't the same job as Alexa+'s
own text-to-speech step.

## Amazon Bedrock (AWS Builder mini challenge)

`narrate_briefing` calls the Bedrock Converse API (`amazon.nova-lite-v1:0`
by default, configurable via `BEDROCK_MODEL_ID`) with the JSON output of
`get_top_friction_points` and `detect_anomalous_runs` already attached, and
asks it to compose 2-4 spoken sentences from that — nothing else. It's
opt-in via `ENABLE_BEDROCK_NARRATION` in `.env` (see `.env.example`) so the
rest of the server works identically without AWS credentials configured. If
the call fails for any reason — no credentials, network, throttling — it
falls back to a deterministic template rather than surfacing an error, and
the response always says which path (`bedrock:<model-id>` or `template`)
produced the sentence, so this is honest about itself in the demo too.

## Real data (not just synthetic)

`data_adapters.py` maps two real, existing export formats onto the same
minimal schema the discovery pipeline needs (timestamp, activity, duration
— nothing else): [ActivityWatch](https://github.com/ActivityWatch/activitywatch)
(an open-source, cross-platform time tracker's event export) and Toggl
Track's CSV export. `discover_workflows_from_import` runs the exact same
label-free clustering against either one — this is what proves the
pipeline isn't secretly dependent on the synthetic dataset's structure.

Honest trade-off, stated once here: neither format carries a success/rework
outcome the way the synthetic data does, so V1's `FrictionRadar` (which
needs that field for rework-rate scoring) can't run meaningfully on
imported data. What does run end to end: segmentation → clustering
(`discover_workflows_from_import`) → anomaly detection — the fully
unsupervised half of this project, which is also the half real data
actually has.

## Research & References

The two harder pieces of this project — discovering workflows with no
labels, and deciding what to show first out of everything discovered —
lean on published methods rather than ad hoc heuristics:

- **Sequence-similarity workflow discovery** (`workflow_discovery.py`)
  adapts the core idea from process mining: recover the structure of a
  process from nothing but its event log. Van der Aalst, Weijters &
  Maruster, ["Workflow Mining: Discovering Process Models from Event
  Logs"](https://doi.org/10.1109/TKDE.2004.47) (IEEE TKDE, 2004) is the
  foundational reference for that framing. The specific clustering step —
  grouping runs by pairwise sequence similarity rather than assuming a
  process model up front — follows the trace-clustering line of that
  field, e.g. Bose & van der Aalst, ["Context Aware Trace
  Clustering"](https://doi.org/10.1137/1.9781611972795.35) (SDM, 2009).
  This project's similarity metric is normalized Longest Common
  Subsequence, chosen specifically because it tolerates the reordering and
  extra/missing steps you'd expect between two "same" workflow runs, unlike
  exact-match grouping.
- **Diversity in the (currently unexposed) ranking engine**
  (`ranking_engine.py`) uses Maximal Marginal Relevance to avoid a top-k
  list that's just five versions of the same story. Carbonell & Goldstein,
  ["The Use of MMR, Diversity-Based Reranking for Reordering Documents and
  Producing Summaries"](https://blog.langchain.com/content/files/~jgc/publication/the_use_mmr_diversity_based_ltmir_1998.pdf)
  (SIGIR, 1998) is the original paper; this project reuses its exact
  relevance/redundancy trade-off, re-run incrementally as each item gets
  selected.
- **Anomaly detection on run durations** (`workflow_discovery.py`) uses
  Tukey's IQR fence (Tukey, *Exploratory Data Analysis*, 1977) rather than
  a normal-distribution z-score, because time-cost data is right-skewed by
  nature — most runs cluster near the median, a handful blow far past it —
  and IQR-based fences don't assume symmetry the way z-scores do.

Each of these was chosen and implemented directly (no library did the
clustering or the diversity trade-off for us) specifically so it stays
inspectable and explainable in this README and in an interview, rather than
being an LLM's best guess dressed up as analysis.

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

Bedrock narration is off by default. Without `ENABLE_BEDROCK_NARRATION=true`
and working AWS credentials, `narrate_briefing` still returns a complete,
correct answer — just from the template path, with `"source": "template"`
in the response so it's never ambiguous which one ran.

## Running it

### Locally

```bash
pip install -r requirements.txt
python src/synthetic_data.py     # generates data/*.json (idempotent)
python src/mcp_server.py         # serves MCP over Streamable HTTP at :8000/mcp/
```

### With Docker

```bash
cp .env.example .env             # edit if you want Bedrock narration on
docker compose up --build
```

### Tests

```bash
pytest tests/                    # unit tests: contracts and edge cases
python tests/evaluation.py       # ranking-engine quality metrics (Precision@k, dedup)
python tests/segmentation_eval.py # segmentation quality vs. ground truth (ARI)
```

CI (`.github/workflows/ci.yml`) runs all three on every push to `main`.
