# Demo Video Script — Isse Automate Kardo

Target: **under 3:00**, since judges aren't required to watch past that
mark. Everything genuinely differentiating (root-cause debug, cross-session
memory) is front-loaded before 2:30; Bedrock/AWS is placed last on purpose —
it's a strong bonus, not the core Alexa+ story, and it's fine if a rushed
judge never gets there.

**Recording setup:** MCP Inspector (`npx @modelcontextprotocol/inspector`)
pointed at `python src/mcp_server.py` is the fastest path to a real,
unstaged recording — it's a genuine MCP client calling your actual server
over Streamable HTTP, which satisfies "show your MCP server in action"
directly. Screen-record the Inspector's tool-call panel + response JSON;
your voiceover carries the narrative so the JSON doesn't have to be
read live.

If you'd rather have an actual chat-style interface (closer to what a
judge imagines "Alexa+" looking like) instead of Inspector's raw panel, say
so and I'll build a minimal one — a text-input box that calls the server
and renders responses as a conversation. Not required, but it would look
more like a finished product on camera.

---

## 0:00–0:15 — Hook

**Voiceover:**
> "Alexa+ can watch how you actually work — but only if something turns
> raw activity into an answer. This is Isse Automate Kardo: it finds your
> real workflows with zero labels, tells you which one is wasting the most
> time and why, and only automates something after you say yes."

**On screen:** Title card / repo README open briefly, then straight to
Inspector.

---

## 0:15–0:35 — Discovery with no labels

**Action:** Call `discover_workflows`.

**Voiceover:**
> "No hardcoded workflow names here — this is pure sequence-similarity
> clustering over raw events. It's finding the structure itself."

**Show:** The returned clusters, pointing at `run_count` and
`matched_label` (note out loud that the label is only attached *after*
clustering, for readability — it's not what the clustering used).

---

## 0:35–0:55 — Where the time actually goes

**Action:** Call `get_top_friction_points`.

**Voiceover:**
> "Ranked by real time cost, with an automation-potential score — not just
> 'this happens a lot,' but 'this happens a lot, doesn't need much
> judgment, and costs real hours.'"

---

## 0:55–1:15 — Root cause, not just a total

**Action:** Call `debug_workflow` on the top result.

**Voiceover:**
> "It's not enough to know a workflow is slow — here's exactly which step
> is the bottleneck, broken down by share of total time."

---

## 1:15–1:35 — The anomaly, not just the average

**Action:** Call `detect_anomalous_runs`.

**Voiceover:**
> "And this isn't just averages — it catches the *specific* run that blew
> past normal, and names the step that caused it."

---

## 1:35–2:00 — Human-in-the-loop, on camera

**Action:** Call `propose_automation`, show the `proposal_id` and the
step list. Then call `confirm_automation` with that id. Then call
`confirm_automation` again with the *same* id.

**Voiceover:**
> "It proposes — it never just does it. Only a matching confirm executes
> anything. And it can't be replayed: confirming twice fails on purpose."

**Show:** The second confirm returning an error. This is a small moment
but it's a real safety property, worth 5 seconds on screen.

---

## 2:00–2:30 — The standout: it remembers, across sessions

**Action:** Call `dismiss_workflow_suggestions` on a workflow ("stop
suggesting automation for this one"). **Kill and restart the server
process on camera.** Call `propose_automation` on that same workflow
again.

**Voiceover:**
> "Here's the part that isn't just a single-turn Q&A bot: I just told it
> to stop suggesting this — and restarted the server entirely. It still
> remembers. This is a standing preference, on disk, not something held in
> one conversation's memory."

**Show:** The response explicitly saying it was previously dismissed. This
is the single strongest 15 seconds of the video for the "orchestrates
across services / maintains context across sessions" judging bar — make
sure the restart is visibly on screen, not cut around, or the claim isn't
provable to a skeptical judge.

---

## 2:30–2:50 — Bedrock, briefly (AWS Builder)

**Action:** Call `narrate_briefing`.

**Voiceover:**
> "And for the AWS Builder track: this same analysis gets composed into
> one spoken-ready sentence by Amazon Bedrock — it only phrases numbers
> already computed here, it never scores or ranks anything itself."

**If Bedrock isn't enabled/tested by recording time:** say so plainly on
camera instead of hiding it — *"this falls back to a template when Bedrock
isn't configured, which is exactly what's running right now"* is a fine,
honest line and matches this project's whole ethos. Do not imply Bedrock
ran if it didn't.

---

## 2:50–3:00 — Close

**Voiceover:**
> "Deterministic where it needs to be explainable, an LLM only where it's
> phrasing — not deciding. That's Isse Automate Kardo."

**On screen:** Repo URL card.

---

## Cut list if you're running long

Priority order to trim, worst-to-keep-first (cut from the top of this
list first):
1. The second (failing) `confirm_automation` call — nice but not essential.
2. Bedrock section — genuinely optional; the fallback line covers you if cut.
3. Anomaly detection — strong but the second-most-ownable point.

**Never cut:** the discovery-with-no-labels open, the root-cause debug,
and the restart-and-still-remembers sequence. Those three are what
separate this from "obvious" on the judging rubric.
