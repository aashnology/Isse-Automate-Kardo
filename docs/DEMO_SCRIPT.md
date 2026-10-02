# Demo Video Script — Isse Automate Kardo

Target: **under 3:00**, since judges aren't required to watch past that
mark. Everything genuinely differentiating (root-cause debug, cross-session
memory) is front-loaded before 2:30.

**Recording setup:** `python web/server.py`, then screen-record the browser
at `localhost:5000`. Hexi's every expression change is a real call into the
same pipeline `mcp_server.py`'s tools use (`web/server.py` imports the exact
same functions) — this is not a scripted animation. Keep MCP Inspector
(`npx @modelcontextprotocol/inspector` against `python src/mcp_server.py`)
open in a second tab for the one beat that needs it (the double-confirm
rejection, §1:35 below) — that's a backend-only safety property with no
natural home in Hexi's UI, and Inspector proves it's the real MCP server,
which the submission needs shown regardless.

---

## 0:00–0:15 — Hook

**Voiceover:**
> "Alexa+ can watch how you actually work — but only if something turns
> raw activity into an answer. This is Isse Automate Kardo: it finds which
> workflow is wasting the most time, shows you exactly why, and only
> automates something after you say yes."

**On screen:** Title card, then straight to Hexi's page loading (idle →
breathing/blinking, establishing it's alive before anything happens).

---

## 0:15–0:35 — Where the time goes, per workflow

**Action:** Click through the three tabs (ticket queue, spreadsheet, inbox).
Hexi tracks across the dock as you go.

**Voiceover:**
> "Each tab shows where the time actually goes in that workflow — a real
> step-by-step breakdown pulled from the event log, not a guess. Bring
> your own data instead of these three built-in examples, and it finds
> the workflows themselves, with no labels at all."

**Accuracy note (why the wording is "each tab shows," not "finds with no
labels"):** these three tabs call `debug_workflow`, which groups by each
tab's own known `workflow_name` — real analysis, but not label-free. The
actual label-free sequence-clustering path (no `workflow_name` involved)
is what the fourth tab, "My data," runs on an imported file or pasted
text — see below for whether that's worth its own beat in this cut.

---

## 0:35–0:55 — Where the time actually goes, and the anomaly

**Action:** On the ticket queue tab, point out the anomaly note under the
step breakdown.

**Voiceover:**
> "And it's not just averages — this specific run ran way past normal, on
> this exact step. That's IQR outlier detection on real run durations, not
> a canned example."

---

## 0:55–1:15 — Hexi notices the pattern

**Action:** After the third tab, Hexi goes curious, then suggesting, with
the real speech bubble (workflow name, real hours, real automation tier).

**Voiceover:**
> "Once it's seen enough of the workspace, it surfaces the one thing
> actually worth automating — ranked by real time cost, not just
> 'this happens a lot.'"

---

## 1:15–1:35 — Human-in-the-loop, on camera

**Action:** Click "Automate it." Hexi goes confirmed.

**Voiceover:**
> "It proposes — it never just does it. Only clicking confirm executes
> anything, and only after a real propose call returned a real proposal id."

---

## 1:35–2:00 — Prove it isn't scripted, and prove the safety property

**Action (Hexi):** Switch to a workflow with no automatable steps (bug
triage) and click "Automate it" — Hexi honestly reports nothing was safe to
automate, not a fake success.

**Action (Inspector, quick cutaway):** Call `confirm_automation` with an
already-used proposal id.

**Voiceover:**
> "One workflow succeeds, another correctly refuses — that's proof this is
> calling the real backend, not playing a recording. And under the hood,
> a used proposal can't be replayed — confirming twice fails on purpose."

---

## 2:00–2:30 — The standout: it remembers, across sessions

**Action:** Click "Not now" on a suggestion (Hexi → idle, status confirms
it's saved to disk). **Kill and restart `web/server.py` on camera.** Reload
the page, revisit the same tabs — Hexi doesn't re-suggest it.

**Voiceover:**
> "Here's the part that isn't just a single-turn Q&A bot: I just told it to
> stop suggesting this — and restarted the server entirely. It still
> remembers. This is a standing preference, on disk, not something held in
> one conversation's memory."

**Show:** The restart itself, visibly, not cut around — this is the single
strongest 15 seconds of the video for the "orchestrates across services /
maintains context across sessions" judging bar, and it isn't provable to a
skeptical judge unless the restart is on screen.

---

## 2:30–2:50 — Brief me, and the voice moment

**Action:** Click the **Brief me** chip in Hexi. It calls the same
`build_briefing` function the MCP tool `narrate_briefing` uses, and Hexi
reads the result aloud. (Turn the browser's sound on and check the voice on
the recording machine beforehand — voices vary by browser and OS.)

**Voiceover:**
> "One tap pulls the same analysis into a single spoken answer — no
> separate step for the user, just the findings, said plainly."

**If you have room:** click **Speak**, say "what's costing me time", and let
Hexi answer. It's the most Alexa+-like moment in the whole demo. Chrome or
Edge only, and the transcription is done by the browser vendor's cloud
service, so don't describe it as running locally.

---

## 2:50–3:00 — Close

**Voiceover:**
> "Deterministic end to end, explainable at every step — that's Isse
> Automate Kardo."

**On screen:** Repo URL card.

---

## Cut list if you're running long

Priority order to trim, worst-to-keep-first (cut from the top of this
list first):
1. The Inspector double-confirm cutaway — nice but not essential.
2. The "Speak" voice moment — genuinely optional; "Brief me" alone covers the point.
3. The anomaly note — strong but the second-most-ownable point.

**Never cut:** the discovery-with-no-labels open, Hexi noticing the
pattern, and the restart-and-still-remembers sequence. Those three are what
separate this from "obvious" on the judging rubric.

**One honesty note for the room, not the video:** the bug-triage run this
demo shows as anomalous, and the whole "watches a workspace" framing, run
on this project's own synthetic dataset inside one page — not your real
browser tabs. See README's "Running it / Hexi" section for why
that's a hard boundary, not a shortcut, if a judge asks.

**Open question, worth deciding before recording:** this cut never shows
the "My data" tab, which is the one thing in this demo that actually runs
label-free discovery (no `workflow_name` anywhere) rather than grouping by
a known one. Two options: (A) record as scripted above — the claim still
stands in the text description and README, backed by real tests, just not
on camera; or (B) add a ~15s beat showing "My data" on a small pasted
example, trimming something from the cut list to make room. (A) is lower
effort and what this script currently assumes; (B) makes the headline
claim visibly provable to a judge who only watches the video. Defaulting
to (A) unless told otherwise.
