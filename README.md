# Isse Automate Kardo

Meet Hexi, an Alexa+ MCP assistant that finds where your time goes, pinpoints the bottleneck step and says "Isse Automate Kardo." It remembers what you dismiss, so it never nags twice.

Built for Amazon's **Build, Ship, Shape** hackathon, **Alexa+ track**, with
an entry in the **Open Source** mini challenge.

Developer manual (PDF): [`docs/Isse-Automate-Kardo-Developer-Manual.pdf`](docs/Isse-Automate-Kardo-Developer-Manual.pdf)

## Quick start

```bash
git clone https://github.com/aashnology/Isse-Automate-Kardo.git && cd Isse-Automate-Kardo
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
python src/mcp_server.py        # terminal 1: MCP server  -> http://localhost:8000/mcp
python web/server.py            # terminal 2: Hexi        -> http://localhost:5000
```

Then, in the browser, to see it work on data it has never seen:

1. Open the **My data** tab and paste the contents of
   [`examples/sales_report_steps.txt`](examples/sales_report_steps.txt) into the step-list box.
2. Click **Analyze this**. Hexi finds one repeating workflow.
3. In the chat, type **Automate it.** Hexi proposes the steps that are safe to
   automate, replays your history to measure the time saved, grades the
   reliability, and writes a diagnosis and prescription.

No API key is needed. Without a model configured, the diagnosis is written by a
built-in template and labelled as such. Tests: `pip install pytest && pytest`.

## Meet Hexi

![Meet Hexi](docs/assets/panels/01-meet-hexi.png)

<p align="center">
  <img src="docs/assets/hexi/asleep.gif" width="160" alt="Hexi asleep, bobbing gently with drifting z's">
  &nbsp;&nbsp;&nbsp;
  <img src="docs/assets/hexi/idle.gif" width="160" alt="Hexi idle, breathing with an occasional blink">
</p>

Try her yourself — see **Running it** below.

## The journey

![The journey](docs/assets/panels/02-the-journey.png)

## How it's built

![How it's built](docs/assets/panels/03-how-its-built.png)

## Any data, then a diagnosis

**Imports are first-class datasets.** An import (ActivityWatch, Toggl, a
pasted step list, a GitHub repo's PR history, a Google Sheet) is clustered
into workflows and saved under a content-hash id (`src/workspace.py`). Every
MCP tool and web route takes an optional `dataset_id`, so propose, confirm
and diagnose run on whatever you brought, not only the built-in sample. State
lives on disk rather than in a process global, so the web server and the MCP
server (separate processes) see the same datasets and concurrent users do not
overwrite each other. An earlier version analysed an import and then threw it
away while propose and confirm kept reading the sample; that is the bug this
layer removes.

**Which steps are safe to automate is decided per step**
(`src/automation_model.py`), from the verbs in the step name (download,
export and rename are mechanical; review, approve and debug are not) and from
the data: how consistently the step appears, how much its duration varies, and
how often it needed rework. Steps the synthetic catalogue already defines keep
their original verdicts. The per-workflow tier agrees with these verdicts, so
a frequent, long workflow made of judgment steps is not called automatable.

**Time saved is measured in shadow mode** (`src/diagnosis.py`). The approved
steps are replayed against the recorded history, keeping 10% of their time for
supervision, and the estimate is checked on a chronological holdout: fitted on
the earlier runs, scored on the later ones. Weekly figures come with an 80%
bootstrap interval. Nothing runs against live applications, and the report
says so.

**Reliability is a 0 to 100 score with named parts**: runs observed, how steady
the step durations are, how many runs contain every proposed step, how alike
the runs are, the holdout error, and whether the data carries outcomes. Data
with no success or rework signal cannot score above 79, because the quality of
an automated result cannot be verified from timings alone. Every caveat that
applies is listed next to the grade.

**Hexi's advisor** (`src/llm_advisor.py`) writes the diagnosis (what is wrong
and why) and the prescription (what to do, in order) from that report. It
works with Anthropic or any OpenAI-compatible endpoint, and otherwise uses a
built-in template; the response says which wrote it. Three guards apply: step
names are reduced to `[a-z0-9_]` and passed as data, the reply must match a
fixed JSON shape, and every figure in it must trace to the report or the whole
reply is discarded for the template.

## Retro UI

The web demo is a pixel-art interface in the spirit of the My-Woofie
companion: navy panels, amber borders, Press Start 2P (SIL OFL, bundled in
`web/static/fonts`), an XP bar, six trophies, 8-bit sound effects (toggle
with SFX), a battle report and a diagnosis panel after each automation. XP and
trophies are cosmetic and stored in your browser; the hours shown are the
shadow-mode estimates, labelled as estimates. Hexi herself is unchanged.

The full research citations behind the clustering and ranking methods,
the complete MCP tool list, and an honest list of what hasn't been tested
yet live in [`docs/RESEARCH_AND_NOTES.md`](docs/RESEARCH_AND_NOTES.md) —
kept out of here so this stays readable, not because there's nothing to
say about them.

## Research & References

Each method below is implemented in this repo, not wrapped from a library, so
it can be read and explained line by line. Fuller notes and the known
limitations are in [docs/RESEARCH_AND_NOTES.md](docs/RESEARCH_AND_NOTES.md).

- **Workflow discovery from raw event logs**, in `src/workflow_discovery.py`.
  Van der Aalst, Weijters & Maruster,
  [Workflow Mining: Discovering Process Models from Event Logs](https://doi.org/10.1109/TKDE.2004.47)
  (IEEE TKDE, 2004), frames the problem: recover a process from events alone.
  Bose & van der Aalst,
  [Context Aware Trace Clustering](https://doi.org/10.1137/1.9781611972795.35)
  (SDM, 2009), is the basis for grouping runs by sequence similarity. We use
  normalized Longest Common Subsequence because it tolerates reordered and
  missing steps between two runs of the same workflow.
- **Diverse ranking**, in `src/ranking_engine.py` (tested, not exposed as a
  tool). Carbonell & Goldstein,
  [The Use of MMR, Diversity-Based Reranking](https://blog.langchain.com/content/files/~jgc/publication/the_use_mmr_diversity_based_ltmir_1998.pdf)
  (SIGIR, 1998), keeps a top-k list from repeating one story.
- **Which steps to automate, and how to specify them**, in
  `src/automation_model.py` and `src/diagnosis.py`. Bosco, Augusto, Dumas,
  La Rosa & Fortino, [Discovering Automatable Routines from User Interaction
  Logs](https://kodu.ut.ee/~dumas/pubs/rpadiscovery.pdf) (BPM Forum, 2019),
  separates discovering routines from deciding which are automatable; we take
  the same split and decide automatability per step from determinism, presence
  and rework. Leno et al., [Discovering executable routine specifications from
  user interaction logs](https://arxiv.org/abs/2106.13446) (2021), turns an
  automatable routine into an executable specification; our `automation_spec`
  is the same idea at a lighter weight (a plan, not a script). Wewerka &
  Reichert, [Robotic Process Automation: a systematic literature review and
  assessment framework](https://arxiv.org/abs/2012.11951) (2020), is where the
  suitability criteria we use (repetition, rule-based steps, error rate)
  come from.
- **Uncertainty on time saved**, in `src/diagnosis.py`. Efron, [Bootstrap
  Methods: Another Look at the Jackknife](https://doi.org/10.1214/aos/1176344552)
  (Annals of Statistics, 1979): a percentile bootstrap gives the 80% interval,
  because per-run savings are few and skewed and a normal approximation
  would overstate our certainty. The holdout is chronological, fit on earlier
  runs and scored on later ones, so it cannot leak the future.
- **Treating imported text as untrusted input to a model**, in
  `src/llm_advisor.py`. Greshake et al., [Not what you've signed up for:
  Compromising Real-World LLM-Integrated Applications with Indirect Prompt
  Injection](https://arxiv.org/abs/2302.12173) (2023), shows that data an
  application retrieves can act as instructions. Step names come from the
  user's files, so they are normalised to a safe character set, passed as a
  data block, and the model's reply is validated and numerically grounded.
- **Anomalous runs**, in `src/workflow_discovery.py`. Tukey's IQR fence
  (*Exploratory Data Analysis*, 1977) rather than a z-score, because run
  durations are right-skewed.

## Agent Skill

![Agent Skill](docs/assets/panels/04-agent-skill.png)

## Running it

![Running it: local and Docker](docs/assets/panels/05-running-it.png)

### Locally

The MCP server alone is enough for any MCP client (Alexa+, MCP Inspector).
Hexi's tabs, chat and voice ask the MCP server first. If it isn't running they
fall back to calling the same Python functions directly, so the page still
works; each API response has a `via` field (`mcp` or `direct`) saying which
answered. The extension needs the MCP server running.

Imported datasets live in a named Docker volume (`datasets`) shared by both
services, so the non-root container user can always write them. The services
were exercised outside Docker with the same environment variables the compose
file sets; the image itself has not been built in the authoring environment,
so the first `docker compose up --build` is the real test.

### Hexi (interactive browser demo)

Open `http://localhost:5000`. Click through the tabs, watch Hexi notice a
repeatable pattern and propose automating it, confirm or dismiss it, then
restart the server and check that a dismissal is still remembered. Type
into the chat box, or click **Speak**, and ask her to brief you out loud.

**Voice runs through MCP.** A spoken request is transcribed by the browser,
classified by `web/static/intents.js`, and sent to `POST /api/agent`, which
calls the matching tool on the MCP server with the official MCP client
(`web/mcp_bridge.py`). The status bar shows which tools ran and the
negotiated protocol. Automation is two utterances: "automate it" only calls
`propose_automation`; the next "yes" calls `confirm_automation`, so one
misheard word can't execute anything. If the MCP server isn't running,
`/api/agent` returns 503 and the page says so and uses its direct path.

Request body: `{intent, workflow?, proposal_id?}`. Response: `reply`,
`mood`, `tools`, `protocol`, `pending_proposal_id`. Malformed or unrecognised
input gets a normal reply listing what can be asked, not an error; the
only error statuses are 413 (oversized body), 503 (MCP server down) and
500 (unexpected failure), each with a `reply` field.

**Input handling.** `intents.js` strips markup and control characters,
caps input at 300 characters, and corrects small typos ("automte it",
"anomolies") with one-edit matching on 5+ letter words that share a first
letter, so lookalikes such as "grief" don't become "brief". It is still
keyword matching, not language understanding: phrasing outside its
vocabulary gets example prompts back.

Voice input uses the browser's speech recognition (Chrome, Edge, Safari).
In Chrome and Edge the audio is sent to the browser vendor's cloud service
for transcription; Hexi's spoken replies are generated on your device.

**Aspen (optional).** Aspen is a separate desktop companion with his own
repository, [My-Woofie](https://github.com/aashnology/Woof); nothing of his is
in this repo. After a confirmed automation Hexi asks whether to call him in.
Yes starts a local copy (set `ASPEN_HOME` in `.env`); no, or no reply, leaves him
out, and with `ASPEN_HOME` unset Hexi says he isn't set up and carries on.
Hexi only starts and stops him. Break length, quiet behaviour and barking are
Aspen's own settings. "Send Aspen away" stops him.

**Hands-free mode (simulated Alexa+).** The "Hey Alexa" toggle turns the laptop
microphone into a stand-in for an Echo. Say "Alexa, ask Hexi what's costing me
time"; Hexi answers aloud through the same MCP path as typed input. Speech
without the wake word is dropped, and for a few seconds after Hexi speaks you
can reply ("yes") without repeating it. Wake-word matching is text matching on
the browser's transcript, not acoustic detection, and this has not been run on
a real Echo device. The wake logic is in `web/static/alexa.js` and is covered by
`tests/test_alexa_wake.py` (needs node).

**Bring your own data**, from the "My data" tab: an ActivityWatch or Toggl
export, a pasted list of steps, a public GitHub repo, or a public Google
Sheet/Drive link. Every path only ever reads and parses — nothing pasted
in is ever executed.

### Chrome extension (side panel)

`extension/` is a Manifest V3 side panel that sends the same requests to
`/api/agent` from any tab, showing each stage (heard, routed, request, MCP
tool, reply) as it runs.

1. Start both services.
2. Open `chrome://extensions`, enable Developer mode, choose **Load
   unpacked**, and select the `extension/` folder.
3. Click the Hexi toolbar icon. Type, use a chip, or press **Speak**.

It talks only to `localhost` / `127.0.0.1` (default `http://localhost:5000`;
use **Server** in the panel for another port). It carries its own copy of
`intents.js`; run `extension/sync.sh` after changing the original, and a
test fails if they differ. Tested: manifest, file references, and the
request logic in node, including against both live servers. Not tested:
loading it into Chrome, and microphone capture in the side panel, where
Chrome may require the one-time **Grant microphone** step.

**Said plainly, because it matters:** a website cannot see your other
browser tabs or other sites — that's a hard security boundary, not a
limitation of this build. Hexi "watches" a sandboxed workspace built into
this one page, not your real tabs, and the extension does not read page
content either. Real cross-tab visibility would need broad permissions and
a real consent design, which is a different, bigger product than this
hackathon build attempts.

### Hexi's advisor (optional)

Diagnoses come from a built-in template unless a model is configured. Set
`ANTHROPIC_API_KEY`, or `LLM_BASE_URL` and `LLM_API_KEY` for an
OpenAI-compatible endpoint, in `.env` (see `.env.example`). The MCP server
makes the call, so put the variables where it can read them; with Docker
Compose both services read the same `.env`.

### Tests

![Tests](docs/assets/panels/06-tests.png)

## License

![License](docs/assets/panels/07-license.png)
