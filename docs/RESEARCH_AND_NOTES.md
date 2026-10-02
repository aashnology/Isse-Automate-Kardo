# Research & References, and known limitations

Moved out of the README to keep that a clean manuscript. Nothing here is
new — it's the technical backing for claims the README makes in passing.

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
inspectable and explainable in an interview, rather than being an LLM's
best guess dressed up as analysis.

## Known limitations, said plainly

- **Segmentation isn't perfect.** Reconstructing runs from a raw stream
  using timing alone (`src/session_segmentation.py`) recovers the true run
  boundaries with an Adjusted Rand Index of 0.905 on this project's own
  data. The mistakes follow a clear pattern: workflows that only happen a
  handful of times a week (like onboarding) occasionally get merged with
  whatever ran right next to them, because there's less data to learn that
  workflow's normal timing rhythm. Frequent workflows segment cleanly.
- **Confirming an automation doesn't trigger anything real yet.** It's a
  clean stub so the propose → confirm interaction works end to end, but the
  actual execution step still needs to be wired up to a real target system.
- **Anomaly detection needs a handful of runs of the same workflow before
  it says anything** — with only one or two data points it says so instead
  of guessing.
- **The Google Sheet/Drive import has not been run against real Google
  servers** in this development environment (no network path to Google from
  the build sandbox) — it's tested against a fake response standing in for
  Google's, and the fetch logic is defensive about that gap. Run it once
  against a real public sheet before relying on it live.

## Full MCP tool list

`discover_workflows`, `discover_workflows_from_import`,
`get_top_friction_points`, `explain_friction`, `estimate_time_cost`,
`debug_workflow`, `detect_anomalous_runs`, `narrate_briefing`,
`propose_automation`, `confirm_automation`, `dismiss_workflow_suggestions`,
`restore_workflow_suggestions`, `list_dismissed_workflow_suggestions` — 13
in total, verified end to end with a real MCP client in
`tests/test_mcp_protocol.py`.
