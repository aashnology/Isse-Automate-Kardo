# Isse Automate Kardo

Alexa+ watches how you work, finds where the time actually goes, and tells
you exactly what's worth automating — you say yes, and only then does it act.

Built for Amazon's **Build, Ship, Shape** hackathon, **Alexa+ track**, with
an entry in the **Open Source** mini challenge.

## Meet Hexi

<p align="center">
  <img src="docs/assets/hexi/expression-sheet.png" width="720" alt="Hexi's six expressions: asleep, idle, watching, curious, suggesting, confirmed">
</p>

Hexi is the small hexagonal character who lives in this project's browser
demo. She isn't decoration — every expression she makes is a direct
reaction to a real call into the analysis pipeline underneath her, not a
scripted animation.

She starts out **asleep** if the server isn't running yet, and settles into
a calm, breathing **idle** once it is:

<p align="center">
  <img src="docs/assets/hexi/asleep.gif" width="160" alt="Hexi asleep, bobbing gently with drifting z's">
  &nbsp;&nbsp;&nbsp;
  <img src="docs/assets/hexi/idle.gif" width="160" alt="Hexi idle, breathing with an occasional blink">
</p>

As you click through a simulated workspace, or just ask her something, she
goes **watching**, then **curious** the moment a real pattern turns up in
the data, then **suggesting** while she works out whether it's worth
automating — and finally **confirmed** once you've said yes and the
automation actually runs. Say "stop suggesting this" and she remembers it,
even after the server restarts; ask "what's costing me the most time" or
"brief me" and she'll tell you out loud.

Try her yourself — see **Running it** below.

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
   -> narrate_briefing()               turns the already-computed findings
                                         into one spoken answer
```

## How it's built

<p align="center">
  <img src="docs/assets/hexi/architecture.png" width="760" alt="Architecture diagram: Alexa+ and Hexi both call a shared, deterministic core">
</p>

Clustering, scoring, and anomaly detection are all deterministic — no LLM
involved anywhere in this pipeline, including `narrate_briefing`: it turns
numbers this project already computed into a sentence via a fixed
template, never a model call. It never ranks, scores, or touches the
underlying data itself, and it has no external dependency or credential to
configure — it returns the same complete, correct answer every time.

The pipeline isn't tied to synthetic data, either. `data_adapters.py` reads
real [ActivityWatch](https://github.com/ActivityWatch/activitywatch) and
Toggl Track exports, a public GitHub repo's own pull-request history (read
only — it never clones or runs a repository's code), or a public Google
Sheet, and runs the exact same label-free discovery against any of them.

And one thing genuinely persists across sessions: `user_memory.py` is the
one piece of state in this project backed by a file on disk rather than
kept only for the length of a conversation. Tell it to stop suggesting a
workflow, and it stays stopped — restart the server entirely, and it's
still true.

The full research citations behind the clustering and ranking methods,
the complete MCP tool list, and an honest list of what hasn't been tested
yet live in [`docs/RESEARCH_AND_NOTES.md`](docs/RESEARCH_AND_NOTES.md) —
kept out of here so this stays readable, not because there's nothing to
say about them.

## Running it

### Locally

```bash
pip install -r requirements.txt
python src/synthetic_data.py     # generates data/*.json (idempotent)
python src/mcp_server.py         # serves MCP over Streamable HTTP at :8000/mcp
```

### With Docker

```bash
cp .env.example .env             # optional -- see .env.example; fine to skip
docker compose up --build
```

### Hexi (interactive browser demo)

```bash
python web/server.py             # REST bridge + frontend at :5000
```

Open `http://localhost:5000`. Click through the tabs, watch Hexi notice a
repeatable pattern and propose automating it, confirm or dismiss it, then
restart the server and check that a dismissal is still remembered. Type
into the chat box (or click **Speak** and say it), and ask her to brief
you out loud.

**Bring your own data**, from the "My data" tab: an ActivityWatch or Toggl
export, a pasted list of steps, a public GitHub repo, or a public Google
Sheet/Drive link. Every path only ever reads and parses — nothing pasted
in is ever executed.

**Said plainly, because it matters:** a website cannot see your other
browser tabs or other sites — that's a hard security boundary, not a
limitation of this build. Hexi "watches" a sandboxed workspace built into
this one page, not your real tabs. Real cross-tab visibility would need a
browser extension with broad permissions and a real consent design, which
is a different, bigger product than this hackathon build attempts.

### Tests

```bash
pytest tests/                     # unit + integration tests
python tests/evaluation.py        # ranking-engine quality metrics
python tests/segmentation_eval.py # segmentation quality vs. ground truth
```

CI (`.github/workflows/ci.yml`) runs all three on every push to `main`.

---

MIT licensed — see [`LICENSE`](LICENSE).
