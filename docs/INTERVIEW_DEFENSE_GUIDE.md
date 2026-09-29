# Interview Defense Guide — Isse Automate Kardo

One page per topic a judge is likely to press on, written to be read right
before the viva, not during it. Each section: what it is, why it's built
that way, and the question most likely to expose a soft spot.

---

## 1. The pitch, in one breath

Alexa+ watches how you actually work (an event stream), finds recurring
workflows in that stream with no pre-existing labels, ranks them by time
cost, root-causes the slow ones, flags the runs that went unusually long,
and proposes automating the low-judgment steps — but never executes
anything until you say yes. Bedrock's only job is turning the finished
analysis into a sentence Alexa+ can speak.

**Track:** Alexa+ (self-hosted MCP server, Streamable HTTP, spec
2025-11-25+). **Mini challenges:** AWS Builder (Bedrock narration).

---

## 2. Architecture, and why it's shaped this way

```
Alexa+ → MCP server (Streamable HTTP) → {workflow_discovery, friction_radar,
                                          actions, bedrock_narrator}
                                              ↑
                                       synthetic_data.py
```

Every analytical module (discovery, scoring, anomaly detection) is plain
Python + scikit-learn/numpy — no LLM call anywhere in that path. The one
LLM call in the whole system lives in `bedrock_narrator.py`, downstream of
all of it, and only phrases numbers that already exist.

**Why keep the LLM out of the analysis?** Two reasons, and both should be
said out loud if asked: (1) an automation *decision* needs to be
explainable and reproducible — "why did you propose automating this step"
needs a deterministic answer, not "the model felt like it," and (2) it's
cheaper and faster to run sequence clustering and IQR fences in Python
than to route every tool call through an LLM.

**Judge question:** *"Isn't this just data engineering with an MCP wrapper
— where's the AI?"* Answer: the AI is in `narrate_briefing` (Bedrock) and
in the *methodology* — sequence clustering and trace clustering are
process-mining techniques (see docs/RESEARCH_AND_NOTES.md), not
hand-rolled if/else rules. The deliberate choice to keep scoring
deterministic and push language generation to the edge is itself the
design decision to defend, not a gap.

---

## 3. Workflow discovery — the hardest, most defensible piece

`workflow_discovery.py`'s `discover()` does NOT use the `workflow_name`
field the synthetic data happens to carry. It:

1. Groups raw events into runs (via a `run_id` field, or via
   `session_segmentation.py` if there isn't one — see §4).
2. Computes pairwise sequence similarity between every two runs using
   **normalized Longest Common Subsequence** (`sequence_similarity`).
3. Union-finds runs into clusters wherever similarity ≥ threshold
   (default 0.75).
4. Picks each cluster's **medoid** (the run most similar, on average, to
   every other run in its cluster) as the canonical sequence.
5. Only *afterward*, for readability in the demo, majority-votes the
   ground-truth `workflow_name` onto each cluster — this label is never
   used by the clustering itself, and gracefully falls back to
   `discovered_workflow_N` when no such field exists at all (the
   genuinely-raw path, exercised in `from_raw_events`).

**Why LCS, not exact match or edit distance?** Two runs of "the same"
workflow won't be byte-identical — a step might get skipped, retried, or
reordered slightly. LCS tolerates insertions/deletions while still being
order-aware (unlike a bag-of-steps / set-similarity approach, which would
treat `[a, b, c]` and `[c, b, a]` as identical, which is wrong for a
process).

**Judge question:** *"Why threshold 0.75? Did you tune it?"* Honest
answer: it's a reasonable starting point validated against this project's
own labeled synthetic data (see `label_purity` in the discovery output,
and the cluster counts in `tests/segmentation_eval.py`'s output), not
grid-searched. Say that directly rather than implying it was tuned on a
large validation set — it wasn't, and overclaiming here is an easy thing
for a judge to catch.

**Judge question:** *"What breaks this?"* Two honest answers, already in
the code comments: (1) genuinely concurrent/interleaved workflows (someone
starts task A, switches to B, comes back to A) — the LCS-over-full-run
approach assumes runs don't interleave; (2) very short or very generic
step sequences would cluster everything together indiscriminately, since
LCS similarity saturates fast on short sequences.

---

## 4. Session segmentation — reconstructing runs with zero labels

`session_segmentation.py` answers: *given a totally raw stream (no
run_id, no workflow_name — just timestamp + activity + duration), how do
you even know where one workflow run ends and the next begins?*

Approach: **1D k-means (k=2) on log-transformed inter-event time gaps.**
Within a run, consecutive steps are minutes apart; between runs, the gap
is hours or days — a genuinely bimodal distribution. K-means splits gaps
into "same run" vs. "new run started," and the threshold is the midpoint
between the two cluster centers.

**Why not just take the single biggest gap in the sorted list (the
original, simpler idea)?** Documented directly in the code: it broke on
testing, because a couple of extreme outlier gaps (multi-day breaks over a
weekend) dominated the sorted list and pulled the split point too high,
merging dozens of true runs into one. K-means over the whole distribution
is robust to a handful of extreme values in a way a single max-gap
heuristic isn't. **This is a real thing that went wrong while building
this — say so if asked "did you try anything simpler first."** It's a
stronger answer than pretending k-means was the first idea.

**Validated how?** Against this project's own ground truth (only possible
because the synthetic data happens to carry `workflow_run_id`) using
Adjusted Rand Index: **0.905** on the committed dataset. The failure mode
is also named directly: infrequent workflows (onboarding, ~0-2×/week)
occasionally get merged with whatever ran next to them, because there's
less data for the model to learn that workflow's normal timing rhythm.
Frequent workflows (bug triage, 2-5×/week) segment cleanly.

**Judge question:** *"An ARI of 0.905 — is that good?"* Frame it
honestly: 1.0 is perfect, 0.0 is random. 0.905 with zero labels and a
purely unsupervised time-gap heuristic, on data with genuinely irregular
workflow frequencies, is a solid result for the method's actual
complexity — but it's not "solved," and the failure mode is understood
and named, not hidden.

---

## 5. Friction scoring — the automation-potential formula

`friction_radar.py`'s `_automation_score`:

```
automation_potential = repetition_norm × predictability × time_cost_norm

repetition_norm  = min(1.0, frequency / 10)
predictability   = max(0, (1 − avg_judgment_cost) × (1 − rework_rate))
time_cost_norm   = min(1.0, total_minutes / 300)
```

Each factor is independently explainable: a workflow is worth automating
if it (a) happens often, (b) doesn't need much human judgment and doesn't
frequently need rework, and (c) costs real time in aggregate. The
multiplicative form means a workflow scores near-zero if *any* factor is
near-zero — a workflow needing heavy judgment shouldn't be flagged
"highly automatable" just because it's frequent.

**Judge question:** *"Where does `avg_judgment_cost` come from?"* It's a
hand-assigned constant per step type (`STEP_JUDGMENT_COST` in
`synthetic_data.py`) in this hackathon build — e.g. `file_download: 0.05`
(trivially automatable), `fix_or_escalate: 0.9` (needs real judgment).
Be upfront: this is a reasonable proxy for the demo, not learned from
data. A production version would derive it from historical rework rates
or outcome variance per step, not a hand-set table.

---

## 6. Anomaly detection — IQR, not z-scores

`detect_anomalous_runs` flags a run as anomalous if its total duration
exceeds `Q3 + 1.5 × IQR` (Tukey's fence), scoped to runs in the same
discovered cluster. Requires ≥4 runs before attempting this at all —
below that it explicitly returns "not enough runs," rather than guessing.

**Why IQR, not a z-score/standard-deviation cutoff?** Time-cost data is
right-skewed by nature (most runs cluster near a typical duration, a
handful blow far past it due to a stuck step or retry) — a z-score
approach assumes roughly symmetric, normally-distributed data, which this
isn't. IQR fences don't make that assumption.

Root-causing *which* step drove the anomaly: compare the run's per-step
durations against the cluster's per-step averages, and report whichever
step has the largest positive excess.

**Judge question:** *"Is that anomaly in the demo real, or cherry-picked?"*
Answer directly rather than dodge it: `synthetic_data.py` deliberately
spikes one specific run's `reproduce_attempt` step to 3.5-4.5x normal, in
the most recent week, so the demo has a guaranteed, named example instead
of depending on per-step noise happening to cross the IQR fence on its own
across the 18 other runs. It's stated in a code comment right where it happens, not
hidden. Worth knowing why this was needed at all: with this seed, ordinary
per-step multiplicative noise averaged out across a 5-step run enough that
*zero* runs crossed the fence naturally — a real, checked finding, not an
assumption. The detection logic itself is unchanged and still genuinely
computes the fence from the data; only one input run was engineered to
guarantee the demo has something to point at.

---

## 7. Human-in-the-loop actions — the autonomy model

`actions.py`: `propose_automation` never executes anything — it inspects
`debug_workflow`'s step breakdown, filters to steps in a known-safe
`AUTOMATABLE_STEPS` set, and returns a `proposal_id`. Only a matching
`confirm_automation(proposal_id)` call executes, and only once — a second
confirm on the same id returns an error rather than "succeeding" silently
again.

**Judge question:** *"What does 'execute' actually do right now?"*
Answer honestly and immediately: it's a stub. `confirm_action` marks the
proposal `executed` and returns a note saying explicitly that a production
version would trigger a real script/integration here. This is stated in
the code, the README, and here — it is not something to be caught
glossing over.

---

## 8. Amazon Bedrock — the AWS Builder integration

`bedrock_narrator.py`'s `BedrockNarrator.narrate()` calls the Bedrock
**Converse API** (default model `amazon.nova-lite-v1:0`, configurable) via
the new `narrate_briefing` MCP tool. It receives the *already-computed*
`top_friction_points` + `detect_anomalous_runs` output as its only input
and is instructed (system prompt) to phrase 2-4 spoken sentences from it,
never invent a number, and never rank or add information.

Gated behind `ENABLE_BEDROCK_NARRATION` (off by default); on any failure
(no credentials, network, throttling) it falls back to a deterministic
template rather than raising — the response always states which path
(`bedrock:<model>` vs. `template`) produced the sentence.

**Judge question:** *"Isn't this the same job Alexa+ itself does — turning
results into speech?"* No, and this is worth stating precisely: Alexa+
narrates a *single* tool's structured JSON output when it calls a tool
directly. `narrate_briefing` composes *across multiple already-computed
results* (friction points + anomalies) into one coherent paragraph before
Alexa+ ever sees it — so Alexa+ gets one clean sentence to speak instead
of reasoning over three separate JSON blobs itself. It's a genuinely
different job: cross-result composition, not per-result text-to-speech.

**Judge question:** *"Why Nova Lite and not Claude or another model?"*
Practical defensible answer: it's an Amazon-native model available in
Bedrock, appropriate for a short, low-stakes phrasing task (not reasoning
or code generation), and the model id is a one-line env var — the
narrator class doesn't hardcode any model-specific behavior.

**Known limitation, worth naming unprompted:** the Bedrock call was
written and reviewed carefully but has not been exercised against a live
AWS account in this build environment (no AWS network egress in the
sandbox this was built in) — the template fallback path has been fully
tested; the live Bedrock path should be smoke-tested once with real
credentials before the demo video is recorded.

---

## 9. Real data adapters — proving it isn't synthetic-only

`data_adapters.py` maps ActivityWatch's event export and Toggl Track's CSV
export onto the pipeline's minimal schema (timestamp, activity, duration —
nothing else), and `discover_workflows_from_import` runs the exact same
sequence-clustering path against it. This is the direct answer to "does
this only work on your synthetic data."

**Judge question:** *"Why not use ActivityWatch or Toggl's outcome/success
field too?"* They don't have one — a time tracker records what you did and
for how long, not whether it succeeded or needed rework. That's stated
directly in the module's docstring: only the unsupervised half of the
pipeline (segmentation, clustering, anomaly detection) runs meaningfully on
imported data; V1's `FrictionRadar` rework-rate scoring needs a field real
time-tracking data doesn't carry. Naming that boundary precisely is a
stronger answer than implying the adapters make everything work identically
to the synthetic path.

**Judge question:** *"Have you run this against your own real
ActivityWatch data?"* Answer honestly based on what was actually done: the
adapters are unit-tested against realistic fixture data shaped exactly like
ActivityWatch's and Toggl's real export formats (verified against their
public API/export docs), including an end-to-end test that feeds adapted
events through the full discovery pipeline and confirms it clusters
correctly — but it has not yet been run against a live personal export. If
you do run it against your own data before the demo, say so and use the
real numbers; if not, describe it exactly as it stands: pipeline-verified
on realistic fixtures, not yet on a live personal export.

## 10. Cross-session memory — real state, not a session variable

`user_memory.py` backs exactly one thing with a file on disk:
`dismiss_workflow_suggestions`. Everything else in this project
(`propose_automation`'s `proposal_id`, for instance) is in-memory and
deliberately short-lived, because it answers "did you confirm *this*
proposal" — a question with no meaning after the process restarts. A
dismissal is different in kind: it's a standing preference ("stop asking
me about weekly_reporting"), and `get_top_friction_points` /
`propose_automation` both check it on every call, not just within one
conversation.

**Why this is the answer to "does this orchestrate across services or
maintain context across sessions"** (the Alexa+ judging doc's own bar for
"creative" vs. "obvious"): it's the second one, concretely. Dismiss a
workflow, restart the server (simulating a new day, a new Alexa+ session,
whatever), and `propose_automation` still refuses to re-propose it — that's
verified directly in `tests/test_user_memory.py`'s reload test, not just
claimed.

**Judge question:** *"Why a JSON file, not a real database?"* Answer
directly: this project has exactly one user per deployment — there's no
multi-tenant auth story here, no concurrent-writer problem to solve. A
database would be infrastructure theater for what this actually needs.
The write path is still done properly regardless (temp file + `os.replace`
for atomicity, same pattern as `data_adapters.py`'s export and
`export_for_workflow_mining.py`'s fix) — the honesty is about scale, not
about cutting corners on the part that's actually there.

**Judge question:** *"What happens if I dismiss something by mistake?"*
`restore_workflow_suggestions` reverses it, and `list_dismissed_workflow_suggestions`
shows what's currently dismissed and why — this was built with an undo
path from the start, not bolted on after.

## 11. Hexi — the interactive demo UI, and its honest boundary

`web/server.py` is a thin REST bridge in front of the exact same modules
`mcp_server.py`'s tools call (`FrictionRadar`, `WorkflowDiscovery`,
`actions.py`, `user_memory.py`) — not a second implementation. Hexi
(`web/static/index.html`) is a small animated character whose expression
changes are driven entirely by what those real calls return: it goes
curious → suggesting only when a real `get_top_friction_points` call
returns a workflow that isn't dismissed, and the number in its speech
bubble is the real `total_time_cost_minutes`, not a placeholder.

**Judge question — the one to get right, because it's the obvious
follow-up:** *"Does Hexi actually watch my browser tabs?"* The honest
answer, said directly and without hedging: no, and it structurally can't
from a website — browser tabs are sandboxed from each other and from the
page itself, by design, for everyone's security. Hexi "watches" a
simulated workspace (a ticket queue, spreadsheet, and inbox) built into
this one page, using this project's own synthetic dataset. Real cross-tab
visibility would require a browser extension with broad host permissions
and a genuine consent/privacy design — a different, larger product than
this hackathon build attempts. Getting caught implying otherwise would cost
far more credibility than saying this upfront ever could.

**Judge question:** *"Why build a second interface when you already have
an MCP server?"* MCP Inspector proves the MCP server works; Hexi
demonstrates the *product experience* an Alexa+-style surface is aiming
for, in a form a judge can watch without needing to read JSON. They're
answering different judging criteria: Tech Implementation is Inspector's
job, Design is Hexi's.

**Judge question:** *"Is the propose/confirm flow through Hexi actually
real, or scripted for the demo?"* Show, don't just say: click "Automate
it" on `bug_triage` (whose steps are all outside `AUTOMATABLE_STEPS`) and
Hexi honestly reports nothing was safe to automate, rather than a scripted
success. That asymmetry — one workflow succeeds, another correctly
doesn't — is the proof it's calling the real backend, not playing a
recorded animation.

**The chat box.** Below the workspace, a text input lets you ask Hexi
things directly ("what's costing me the most time," "automate it," "stop
suggesting bug triage"). This is a small keyword-matched intent router in
plain JavaScript — not an LLM, not Bedrock — that calls the exact same
`/api/*` endpoints the tabs call. Say this plainly if asked: it's pattern
matching, not natural-language understanding, and it was built that way on
purpose so the conversational surface doesn't depend on an API call (or a
card) to demo at all. It reads as a real exchange because it's driving
real analysis underneath simple matching, not because the matching itself
is sophisticated.

**Spoken replies.** Hexi reads its chat replies and suggestions aloud with
the browser's native `speechSynthesis` — deliberately not Bedrock, Polly or
any API, so it costs nothing, needs no credentials, and works offline. The
honest framing if asked: this is text-to-speech on the way *out*, not voice
understanding on the way *in* — you still type, and the intent router is
still keyword matching. Voice input is a planned next step, not something
claimed here. Two things worth knowing before a judge asks: the voices are
whatever the viewer's browser and OS provide, so it will sound different on
different machines, and the pure text-cleanup step (`speakable()`) is
unit-tested, but the audio itself can't be asserted in CI — check it by ear
on the machine you'll record the demo on.

**Voice in, and its privacy cost.** The Speak button uses the browser's
`SpeechRecognition`. In Chrome and Edge that streams the audio to the browser
vendor's cloud for transcription — so unlike spoken replies (generated on the
device) it is not "nothing leaves your machine", and the tooltip and README
say so. Firefox has no such API, so the button is hidden there instead of
failing. Say plainly if asked: speech recognition is the browser's, not ours;
what's ours is the router that acts on the transcript.

**Judge question:** *"Did you test the chat router?"* Yes, and the reason is a
real bug. It originally lived inline in the page, matched substrings, and read
"stop suggesting bug triage" as a question about time cost — `stop` contains
`top`. That phrase is one of the demo's own examples, and nothing caught it
until the router was pulled out into `intents.js` and tested with the phrases
people actually say. It now matches whole words and has 20+ phrase tests plus
a test that the page uses the tested module rather than an inline copy.

**Judge question:** *"Are Hexi and the MCP server looking at the same data?"*
They are now, and weren't before. The generators used the global random
generator, so output depended on call order: the MCP server read a file while
Hexi regenerated its own events, and they disagreed (23.5h vs 32.5h for the
same workflow), while the README called the data deterministic. Found by a
test asserting the two interfaces return the same briefing. Fixed with a
private seeded generator per function and one shared loader; regression tests
cover order-independence and that both interfaces load identical events. The
fix changed the dataset, so the numbers were re-measured rather than
carried over (segmentation ARI 0.876 → 0.905), and the claim that natural
noise never crosses the outlier fence was re-checked on the new data (it
holds: 18 other runs, no anomalies).

**Google links.** Public Sheet/Drive links only. The server never fetches what
the user pastes: it extracts an ID (strict pattern) and builds a fixed
`docs.google.com`/`drive.google.com` URL, so a hostile link cannot aim it at an
internal address (tested with hostile inputs). **Not verified against real
Google:** this was built in a sandbox that can't reach Google, so the fetch is
tested with a fake, and Google's actual responses (in particular how it answers
private files) are handled from documented behaviour, not observed. Run it
once with a real public sheet before the demo.

**Bring-your-own-data, and the one genuinely novel piece: GitHub PR
mining.** The "My data" tab's three import paths (ActivityWatch/Toggl
file, pasted steps, or a GitHub repo) all end at the same `discover()` /
`detect_anomalous_runs()` calls as the synthetic demo data — no special
casing downstream of import.

The GitHub path deserves its own defense, because it's the most
interesting and the easiest to over-claim. `from_github_pull_requests`
makes exactly one call to GitHub's public PR-list API (read-only,
unauthenticated by default) and turns each closed PR into a two-step run:
`pr_opened` (created_at → updated_at) and `pr_merged`/`pr_closed`
(updated_at → merged_at/closed_at). Two decisions worth explaining if
asked:

- **Why each PR gets its own run boundary (`run_id_field="workflow_run_id"`
  set to the PR number) instead of going through `from_raw_events`'s
  automatic segmentation:** PRs are routinely open concurrently in any
  active repo. A single global time-gap segmentation would interleave
  events from different PRs incorrectly. Knowing the true boundary (the PR
  itself) sidesteps the problem entirely rather than papering over it —
  this was caught and fixed *before* shipping, by reasoning through what
  real repo activity looks like, not discovered by a bug report.
- **Why it never clones or runs the repo's code:** stated as a hard line,
  not a caveat — reading PR metadata over an API is safe; executing code
  from a pasted link is a real security risk regardless of framing. This
  project does the first and refuses the second categorically.

**Judge question, and the honest answer to have ready:** *"Is the anomaly
detection's root-cause always right?"* No, and it's worth knowing exactly
where it can mislead rather than being surprised by it live: `_step_averages`
in `workflow_discovery.py` uses the mean per step across a cluster. Tested
against a real repo (`pallets/flask`), one PR sat open for roughly 67 days
before closing — a genuine, dramatic outlier. That single value pulls the
cluster's mean `pr_opened` duration up so much that *other* runs' actual
`pr_opened` times end up looking below-average, so `likely_cause_step` can
point at whichever step happens to have the least-negative excess, which
isn't a meaningful answer for those other runs. This is a pre-existing
property of the mean-based root-cause logic, surfaced by testing on real,
noisy external data rather than only ever-tidy synthetic data — exactly
the kind of thing that's easy to miss without testing against something
messier than your own generator. It wasn't patched silently; it's named
here as a known limitation and a legitimate next step (a median-based or
outlier-excluded average would be more robust) rather than corrected
without saying so.

## 12. Trade-offs and honest gaps (say these before being asked)

| Gap | Why it's there | What "done" would look like |
|---|---|---|
| Synthetic data by default | No live workplace event source connected yet | `data_adapters.py` + `discover_workflows_from_import` now cover this for ActivityWatch/Toggl exports; a live connector (browser extension, calendar) is the next step |
| Automation execution is a stub | Out of scope for a hackathon demo; needs a real target system to call | Hook `confirm_action` to a real script/Zapier-style integration |
| Segmentation assumes no interleaved workflows | Time-gap-only segmentation can't distinguish "switched tasks" from "still working" | Sequence-aware segmentation using activity-type transitions, not just timing |
| `avg_judgment_cost` is a hand-set constant | No historical rework/outcome data to learn it from yet | Derive per-step judgment cost from observed rework rate and duration variance |
| Bedrock narration untested against live AWS | No AWS network access in the build sandbox | Smoke-test with real credentials before recording the demo |

---

## 13. Deployability

- `Dockerfile` (python:3.12-slim, deps cached in their own layer) +
  `docker-compose.yml` for a one-command local run.
- `.env.example` documents every configurable variable; nothing sensitive
  is committed — Bedrock uses standard AWS credential resolution (env
  vars / `~/.aws/credentials` / IAM role), never a hardcoded key.
- `.github/workflows/ci.yml` runs the full pytest suite plus both
  evaluation scripts on every push to `main`.
- `tests/` — 158 tests across 11 pytest files: `test_core.py` (scoring
  invariants, clustering edge cases, segmentation, propose/confirm state
  machine, data-determinism regressions), `test_data_adapters.py`,
  `test_google_and_briefing.py` (CSV/Google link handling with a fake
  fetcher, shared briefing), `test_user_memory.py` and
  `test_session_memory_integration.py` (persistence and its effect on tool
  output), `test_web_bridge.py`, `test_intents.py`, `test_speech.py`
  (chat router and speech cleanup, run in node), and `test_mcp_protocol.py`
  (real server process, real MCP client, protocol 2025-11-25),
  `test_voice_mcp.py` (the `/api/agent` path against a real MCP server), and
  `test_extension.py` (manifest, bundled router drift, client logic against
  both live servers).

---

## 14. If a judge asks you to improve one thing live

Good, safe answer: **learn `STEP_JUDGMENT_COST` from data instead of a
hand-set table** — track actual rework rate and duration variance per
step across runs, and use that instead of a manually assigned constant.
It's a bounded, well-scoped change that doesn't touch the architecture,
and it directly strengthens the one place in the scoring pipeline that's
currently a human guess rather than derived from the event log itself.

---

## 15. Voice through MCP, the extension, and input hardening

**What changed.** Hexi's voice path used to call the analysis modules
in-process, like the typed chat. Now `POST /api/agent` (`web/server.py`)
runs each classified request through the running MCP server using the
official MCP client (`web/mcp_bridge.py`), which refuses a server that
negotiates below 2025-11-25. So the demo's voice interaction exercises the
same Streamable HTTP surface Alexa+ would.

**Judge question:** *"Why does voice go through MCP but typed chat doesn't?"*
Typed chat and the tabs predate the bridge and are kept as the fallback when
the MCP server is down, so the page still demos. Voice is the path that
claims to be agentic, so it's the one that uses the protocol. Say that
directly; don't imply every interaction goes through MCP.

**Judge question:** *"Can a misheard word run an automation?"* No. A spoken
"automate it" only calls `propose_automation`. `confirm_automation` runs on a
later utterance carrying the stored proposal id, and any other request
clears that id. `confirm_action` itself is still a stub, so nothing real
executes either way.

**Judge question:** *"Where's the speech-to-text?"* The browser's. Audio goes
to the browser vendor in Chrome/Edge. What is ours is the router and the
MCP call. Nothing here was run with a real microphone in a real browser.

**Extension.** `extension/` is an MV3 side panel calling `/api/agent`, limited
to localhost. It holds a copy of `intents.js` (extensions can't load scripts
from localhost), and a test fails if the copy drifts. Never loaded into
Chrome in this build; the request logic is tested in node against both real
servers.

**Hardening.** `intents.js` sanitizes input and does narrow typo correction;
`/api/agent` validates every field, caps the body at 4 KB, and answers odd
input with a structured reply. A wrong port in the extension request is the
likely first-run failure: `/api/agent` lives on the Hexi server (:5000), not
the MCP endpoint (:8000).
