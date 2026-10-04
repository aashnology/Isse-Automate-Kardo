const API = "";
const tabPositions = { bug_triage: 0, weekly_reporting: 130, onboarding_new_partner: 260, import: 390 };
let visited = new Set();
let currentTarget = null;
let currentProposalId = null;
let backendUp = false;

const FACES = {
  asleep: `<polygon points="24,4 42,15 42,33 24,44 6,33 6,15" fill="#D3D1C7" stroke="#5F5E5A" stroke-width="2" class="hexi-bob"/>
    <path d="M13 22 Q17 25 21 22" stroke="#2C2C2A" stroke-width="2.5" fill="none" stroke-linecap="round"/>
    <path d="M27 22 Q31 25 35 22" stroke="#2C2C2A" stroke-width="2.5" fill="none" stroke-linecap="round"/>
    <ellipse cx="24" cy="32" rx="3" ry="2" fill="#2C2C2A"/>
    <text class="hexi-z" x="34" y="10" font-size="7" fill="#5F5E5A">z</text>
    <text class="hexi-z z2" x="39" y="5" font-size="9" fill="#5F5E5A">z</text>`,
  idle: `<polygon points="24,4 42,15 42,33 24,44 6,33 6,15" fill="#B5D4F4" stroke="#185FA5" stroke-width="2" class="hexi-pulse"/>
    <rect class="hexi-blink" x="14" y="19" width="6" height="7" rx="1" fill="#042C53"/>
    <rect class="hexi-blink" x="28" y="19" width="6" height="7" rx="1" fill="#042C53"/>
    <path d="M17 31 Q24 34 31 31" stroke="#042C53" stroke-width="2.5" fill="none" stroke-linecap="round"/>`,
  watching: `<polygon points="24,4 42,15 42,33 24,44 6,33 6,15" fill="#B5D4F4" stroke="#185FA5" stroke-width="2" class="hexi-scan"/>
    <rect x="12" y="15" width="8" height="2.5" fill="#042C53" transform="rotate(-14 16 16)"/>
    <rect x="14" y="20" width="6" height="6" fill="#042C53"/>
    <rect x="28" y="21" width="6" height="4" fill="#042C53"/>
    <path d="M17 31 Q24 30 31 31" stroke="#042C53" stroke-width="2.5" fill="none" stroke-linecap="round"/>`,
  curious: `<polygon points="24,4 42,15 42,33 24,44 6,33 6,15" fill="#F0997B" stroke="#993C1D" stroke-width="2" class="hexi-pop"/>
    <circle cx="17" cy="22" r="4.5" fill="#4A1B0C"/><circle cx="31" cy="22" r="4.5" fill="#4A1B0C"/>
    <circle cx="24" cy="33" r="3.5" fill="none" stroke="#4A1B0C" stroke-width="2.5"/>`,
  suggesting: `<polygon points="24,4 42,15 42,33 24,44 6,33 6,15" fill="#FAC775" stroke="#854F0B" stroke-width="2" class="hexi-think"/>
    <path d="M12 17 Q16 13 20 16" stroke="#412402" stroke-width="2.2" fill="none" stroke-linecap="round"/>
    <circle cx="17" cy="21" r="3" fill="#412402"/><circle cx="31" cy="20" r="3" fill="#412402"/>
    <path d="M20 33 Q24 31 28 32" stroke="#412402" stroke-width="2.5" fill="none" stroke-linecap="round"/>`,
  confirmed: `<polygon points="24,4 42,15 42,33 24,44 6,33 6,15" fill="#97C459" stroke="#3B6D11" stroke-width="2" class="hexi-wiggle"/>
    <circle cx="16" cy="21" r="5" fill="#173404"/><path d="M27 23 L35 20" stroke="#173404" stroke-width="2.5" stroke-linecap="round"/>
    <path d="M13 31 Q24 40 35 29 Q28 34 24 30 Q20 34 13 31" fill="#173404"/>
    <polygon points="6,10 9,4 11,10" fill="#639922"/><polygon points="38,8 41,3 42,9" fill="#639922"/>`,
};

// Any string that can originate from imported data (a CSV cell, a pasted
// step name, a GitHub/Google error message) is untrusted and must be
// escaped before it goes into innerHTML -- it can otherwise carry a script
// tag or an event handler straight into the page. Values placed via
// textContent elsewhere in this file don't need this; the browser already
// treats textContent as plain text.
function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function setMood(mood) { document.getElementById("hexiSvg").innerHTML = FACES[mood]; }
function setStatus(text) { document.getElementById("statusText").textContent = text; }

async function api(path, opts) {
  const res = await fetch(API + path, opts);
  if (res.ok) return res.json();
  // The server writes its 400 messages for the user ("that sheet looks
  // private"), so pass them through rather than a generic failure.
  let body = null;
  try { body = await res.json(); } catch (e) {}
  if (body && body.error) return body;
  throw new Error("request failed");
}

async function checkBackend() {
  try {
    await api("/api/friction-points?top_k=1");
    backendUp = true;
    setMood("idle");
    setStatus("Hexi is watching this workspace.");
  } catch (e) {
    backendUp = false;
    setMood("asleep");
    setStatus("Backend not running — start web/server.py, then reset.");
  }
}

async function selectTab(workflowName, btn) {
  document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  btn.classList.add("active");
  document.getElementById("hexiWrap").style.left = tabPositions[workflowName] + "px";

  if (workflowName === "import") {
    renderImportPanel();
    return;
  }
  visited.add(workflowName);

  if (!backendUp) return;

  const debug = await api("/api/debug/" + workflowName);
  const panel = document.getElementById("panel");
  if (debug.error) {
    panel.innerHTML = `<p class="status">${escapeHtml(debug.error)}</p>`;
    return;
  }
  panel.innerHTML = debug.step_breakdown.map(s =>
    `<div class="row"><span>${escapeHtml(s.step)}</span><span>${Math.round(s.share_of_total * 100)}% of time</span></div>`
  ).join("");

  const anomalyData = await api("/api/anomalies/" + workflowName);
  const anomalyNote = document.createElement("p");
  anomalyNote.className = "status";
  anomalyNote.style.marginTop = "10px";
  if (anomalyData.error) {
    anomalyNote.textContent = "";
  } else if (anomalyData.anomalies && anomalyData.anomalies.length) {
    const a = anomalyData.anomalies[0];
    anomalyNote.textContent = `One run ran unusually long — mainly '${a.likely_cause_step}'.`;
  } else {
    anomalyNote.textContent = anomalyData.note || "No anomalous runs in this workflow's history.";
  }
  panel.appendChild(anomalyNote);

  const dismissedResp = await api("/api/dismissed");
  const dismissedNames = dismissedResp.dismissed_workflows.map(w => w.workflow_name);

  if (visited.size >= 3 && !currentTarget) {
    const top = await api("/api/friction-points?top_k=1");
    if (top.friction_points.length && !dismissedNames.includes(top.friction_points[0].workflow_name)) {
      const fp = top.friction_points[0];
      currentTarget = fp.workflow_name;
      setMood("curious");
      setStatus("Hexi noticed a pattern across your tabs.");

      const track = document.getElementById("progressTrack");
      const fill = document.getElementById("progressFill");
      track.style.display = "block";
      fill.style.width = "0%";
      requestAnimationFrame(() => { fill.style.width = "100%"; });

      setTimeout(() => {
        setMood("suggesting");
        track.style.display = "none";
        fill.style.width = "0%";
        document.getElementById("bubbleText").textContent =
          `'${fp.workflow_name}' costs ${Math.round(fp.total_time_cost_minutes / 60 * 10) / 10}h and is rated ${fp.automation_tier}. Want me to handle it?`;
        document.getElementById("bubble").style.display = "block";
        speak(document.getElementById("bubbleText").textContent);
        setStatus("Hexi thinks this can be automated.");
      }, 1300);
    }
  }
}

function renderImportPanel() {
  const panel = document.getElementById("panel");
  panel.innerHTML = `
    <p class="status" style="margin-bottom:8px;">Bring your own data — nothing here is executed, only read and parsed.</p>
    <div style="display:flex; flex-direction:column; gap:8px;">
      <div>
        <label class="status" style="display:block; margin-bottom:3px;">ActivityWatch (.json) or Toggl (.csv) export</label>
        <input type="file" id="importFile" accept=".json,.csv" style="font-size:12px;">
      </div>
      <div>
        <label class="status" style="display:block; margin-bottom:3px;">Or paste a step list (blank line = new run)</label>
        <textarea id="importText" rows="3" placeholder="download file, 2&#10;clean data, 10&#10;export, 3"
          style="width:100%; font-size:12px; padding:6px; border:1px solid var(--border); border-radius:6px; font-family:inherit;"></textarea>
      </div>
      <div>
        <label class="status" style="display:block; margin-bottom:3px;">Or a public GitHub repo, Google Sheet, or Drive file link (read-only)</label>
        <input type="text" id="importRepo" placeholder="owner/repo, a github.com URL, or a Google Sheet / Drive link shared as anyone-with-the-link"
          style="width:100%; font-size:12px; padding:6px; border:1px solid var(--border); border-radius:6px; font-family:inherit;">
      </div>
      <button class="btn" id="importBtn" style="align-self:flex-start;">Analyze this</button>
      <div id="importResults"></div>
    </div>`;

  document.getElementById("importBtn").addEventListener("click", runImport);
}

async function runImport() {
  const results = document.getElementById("importResults");
  results.innerHTML = '<p class="status">Analyzing...</p>';
  setMood("watching");

  const fileInput = document.getElementById("importFile");
  const text = document.getElementById("importText").value.trim();
  const repo = document.getElementById("importRepo").value.trim();

  try {
    let data;
    if (fileInput.files.length) {
      const form = new FormData();
      form.append("file", fileInput.files[0]);
      data = await api("/api/import", { method: "POST", body: form });
    } else if (repo) {
      const isGoogle = /(docs|drive)\.google\.com/.test(repo);
      data = await api("/api/import", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(isGoogle ? {google_link: repo} : {github_repo: repo}),
      });
    } else if (text) {
      data = await api("/api/import", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({pasted_text: text}),
      });
    } else {
      results.innerHTML = '<p class="status">Provide a file, some pasted steps, or a repo first.</p>';
      setMood("idle");
      return;
    }

    if (data.error) {
      results.innerHTML = `<p class="status">${escapeHtml(data.error)}</p>`;
      setMood("idle");
      return;
    }

    setMood("curious");
    let html = `<p class="status" style="margin-bottom:6px;">${data.events_imported} events → ${data.discovered_workflows.length} discovered pattern(s)</p>`;
    for (const c of data.discovered_workflows) {
      const sequence = c.canonical_sequence.map(escapeHtml).join(" → ");
      html += `<div class="row" style="flex-direction:column; align-items:flex-start; gap:2px;">
        <span>${sequence}</span>
        <span style="color:var(--muted); font-size:11px;">${c.run_count} run(s)</span>
      </div>`;
      const anomalies = (data.anomalies_by_cluster && data.anomalies_by_cluster[c.matched_label]) || [];
      if (anomalies.length) {
        html += `<p class="status" style="margin:4px 0 8px 4px;">⚠ ${anomalies.length} unusual run(s) — worst took ${Math.round(anomalies[0].total_minutes)} min, mainly '${escapeHtml(anomalies[0].likely_cause_step)}'.</p>`;
      }
    }
    results.innerHTML = html;
  } catch (e) {
    results.innerHTML = '<p class="status">Something went wrong reaching the backend.</p>';
    setMood("idle");
  }
}

async function automateWorkflow(name) {
  const proposal = await api("/api/propose", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({workflow_name: name}),
  });
  if (!proposal.proposal_id) {
    setMood("watching");
    return {ok: false, message: proposal.summary};
  }
  await api("/api/confirm", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({proposal_id: proposal.proposal_id}),
  });
  setMood("confirmed");
  document.getElementById("bubble").style.display = "none";
  return {ok: true, message: `Done — automated: ${proposal.proposed_automation.join(", ")}.`};
}

async function dismissWorkflow(name) {
  await api("/api/dismiss", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({workflow_name: name, reason: "dismissed via Hexi demo"}),
  });
  setMood("idle");
  document.getElementById("bubble").style.display = "none";
  return {message: `Got it — won't suggest '${name}' again, even after a restart.`};
}

document.querySelectorAll(".tab").forEach(btn => {
  btn.addEventListener("click", () => selectTab(btn.dataset.workflow, btn));
});

document.getElementById("confirmBtn").addEventListener("click", async () => {
  const result = await automateWorkflow(currentTarget);
  if (!result.ok) document.getElementById("bubbleText").textContent = result.message;
  setStatus(result.ok
    ? "Automation confirmed — real propose/confirm calls, not a script."
    : "Nothing here was safe to automate — that's the real answer, not a bug.");
});

document.getElementById("dismissBtn").addEventListener("click", async () => {
  const result = await dismissWorkflow(currentTarget);
  setStatus(result.message);
});

document.getElementById("resetBtn").addEventListener("click", async () => {
  if (speechSupported) window.speechSynthesis.cancel();
  if (currentTarget) {
    await api("/api/restore", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({workflow_name: currentTarget}),
    }).catch(() => {});
  }
  visited = new Set();
  currentTarget = null;
  document.getElementById("bubble").style.display = "none";
  document.getElementById("progressTrack").style.display = "none";
  document.getElementById("progressFill").style.width = "0%";
  document.getElementById("panel").innerHTML = '<p class="status">Click a tab to load its real step breakdown.</p>';
  document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  document.getElementById("hexiWrap").style.left = "0px";
  checkBackend();
});

setMood("asleep");
checkBackend();

// ---------------------------- Spoken replies --------------------------------
// Browser-native speech synthesis: no API, no key, no cost. Speech only ever
// starts after a user gesture (sending a message, clicking a tab), which is
// also what browsers require before they'll allow audio at all.
const speechSupported = "speechSynthesis" in window;
let voiceOn = true;
try { voiceOn = localStorage.getItem("hexiVoice") !== "off"; } catch (e) {}

function refreshVoiceButton() {
  const btn = document.getElementById("voiceBtn");
  if (!speechSupported) { btn.style.display = "none"; return; }
  btn.textContent = voiceOn ? "Voice: on" : "Voice: off";
}

function speak(text) {
  if (!speechSupported || !voiceOn) return;
  window.speechSynthesis.cancel();  // never queue up stale replies
  const utterance = new SpeechSynthesisUtterance(HexiSpeech.speakable(text));
  const english = window.speechSynthesis.getVoices().find(v => v.lang && v.lang.startsWith("en"));
  if (english) utterance.voice = english;
  utterance.rate = 1.02;
  window.speechSynthesis.speak(utterance);
}

document.getElementById("voiceBtn").addEventListener("click", () => {
  voiceOn = !voiceOn;
  try { localStorage.setItem("hexiVoice", voiceOn ? "on" : "off"); } catch (e) {}
  if (!voiceOn && speechSupported) window.speechSynthesis.cancel();
  refreshVoiceButton();
});
refreshVoiceButton();

// ---------------------------- Chat / command interface ----------------------
function appendChat(who, text) {
  const log = document.getElementById("chatLog");
  const div = document.createElement("div");
  div.className = "chat-msg " + who;
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  if (who === "hexi") speak(text);
}

const HELP_TEXT = "Try: what's costing me time, why is reporting slow, any unusual runs, automate it, stop suggesting bug triage, brief me, or what have I dismissed.";

async function handleChatMessageInner(raw) {
  appendChat("you", raw);
  if (!backendUp) { appendChat("hexi", "I'm asleep right now — start web/server.py, then reset."); return; }

  const { intent, workflow } = HexiIntents.classifyIntent(raw);
  const name = workflow || currentTarget;
  const needName = (question) => { appendChat("hexi", question); };

  switch (intent) {
    case "brief": {
      const b = await api("/api/brief");
      const points = b.based_on.top_friction_points;
      if (points.length) currentTarget = points[0].workflow_name;
      setMood(points.length ? "curious" : "idle");
      appendChat("hexi", b.narration);
      return;
    }
    case "friction": {
      const top = await api("/api/friction-points?top_k=1");
      if (!top.friction_points.length) { appendChat("hexi", "Nothing to report yet — every workflow is dismissed or empty."); return; }
      const fp = top.friction_points[0];
      currentTarget = fp.workflow_name;
      setMood("curious");
      appendChat("hexi", `'${fp.workflow_name}' costs ${Math.round(fp.total_time_cost_minutes / 60 * 10) / 10}h, rated ${fp.automation_tier}.`);
      return;
    }
    case "why": {
      if (!name) { needName("Which workflow? Try 'reporting', 'bug triage', or 'onboarding'."); return; }
      currentTarget = name;
      const debug = await api("/api/debug/" + name);
      if (debug.error) { appendChat("hexi", debug.error); return; }
      const top = debug.step_breakdown[0];
      appendChat("hexi", `In '${name}', '${top.step}' takes the biggest share — ${Math.round(top.share_of_total * 100)}% of the total time.`);
      return;
    }
    case "anomalies": {
      if (!name) { needName("Which workflow should I check for anomalies?"); return; }
      const a = await api("/api/anomalies/" + name);
      if (a.anomalies && a.anomalies.length) {
        appendChat("hexi", `One run of '${name}' ran unusually long — mainly '${a.anomalies[0].likely_cause_step}'.`);
      } else {
        appendChat("hexi", a.note || `No anomalous runs in '${name}'.`);
      }
      return;
    }
    case "automate": {
      if (!name) { needName("Automate what? Ask what's costing you time first."); return; }
      const result = await automateWorkflow(name);
      appendChat("hexi", result.message);
      return;
    }
    case "dismiss": {
      if (!name) { needName("Stop suggesting what?"); return; }
      const result = await dismissWorkflow(name);
      appendChat("hexi", result.message);
      return;
    }
    case "restore": {
      if (!workflow) { needName("Which one should I bring back?"); return; }
      await api("/api/restore", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({workflow_name: workflow}),
      });
      appendChat("hexi", `Restored — I'll suggest '${workflow}' again if it comes up.`);
      return;
    }
    case "dismissed_list": {
      const d = await api("/api/dismissed");
      const names = d.dismissed_workflows.map(w => w.workflow_name);
      appendChat("hexi", names.length ? `You've asked me to stop suggesting: ${names.join(", ")}.` : "You haven't dismissed anything.");
      return;
    }
    default:
      appendChat("hexi", HELP_TEXT);
  }
}

// Nothing a user types or says should surface as an uncaught error.
async function handleChatMessage(raw) {
  try {
    await handleChatMessageInner(raw);
  } catch (e) {
    appendChat("hexi", "Something went wrong reaching the backend. " + HELP_TEXT);
  }
}

// ---------------------------- Voice -> MCP ----------------------------------
// Spoken requests run through the MCP server (via /api/agent), not the
// in-process shortcuts typed chat uses. "Automate" is two utterances: the
// first proposes and stores the proposal id, the next "yes" confirms it.
let pendingProposal = null;

async function handleVoice(said) {
  const { intent, workflow } = HexiIntents.classifyIntent(said);
  const agentIntents = ["brief", "friction", "why", "anomalies", "automate", "dismiss", "restore", "dismissed_list"];
  if (!backendUp || !agentIntents.includes(intent)) { handleChatMessage(said); return; }
  appendChat("you", said);
  const name = workflow || currentTarget;
  let res = null;
  try { res = await fetch(API + "/api/agent", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({intent, workflow: name, proposal_id: intent === "automate" ? pendingProposal : null}),
  }); } catch (e) { res = null; }
  const data = res ? await res.json().catch(() => ({})) : {};
  if (res && !res.ok && res.status !== 503) { appendChat("hexi", data.reply || HELP_TEXT); return; }
  if (!res || !res.ok) {
    setStatus("MCP server not reachable — start src/mcp_server.py. Using the direct path instead.");
    document.getElementById("chatLog").lastChild.remove();
    handleChatMessage(said);
    return;
  }
  if (name) currentTarget = name;
  pendingProposal = data.pending_proposal_id || null;
  setMood(data.mood);
  setStatus(`Answered through MCP (${(data.tools || []).join(", ")}, protocol ${data.protocol}).`);
  appendChat("hexi", data.reply);
}

// ---------------------------- Voice input -----------------------------------
// Uses the browser's SpeechRecognition (Chrome, Edge, Safari). Worth knowing:
// in Chrome and Edge the audio is sent to the browser vendor's cloud service
// to be transcribed -- unlike the spoken replies above, which stay on the
// device -- so the button's tooltip says so. Not available in Firefox, where
// the button is hidden rather than left to fail.
const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognizer = null;

function setListening(on, resetFace = true) {
  const btn = document.getElementById("micBtn");
  btn.textContent = on ? "Listening..." : "Speak";
  if (on) { setMood("watching"); setStatus("Listening — say something."); }
  else if (backendUp && resetFace) { setMood("idle"); }
}

function startListening() {
  if (recognizer) { recognizer.stop(); return; }   // second click cancels
  if (speechSupported) window.speechSynthesis.cancel();  // don't transcribe Hexi's own voice
  recognizer = new Recognition();
  recognizer.lang = "en-US";
  recognizer.interimResults = false;
  recognizer.maxAlternatives = 1;
  let heard = false;
  recognizer.onresult = (e) => {
    heard = true;
    const said = e.results[0][0].transcript;
    document.getElementById("chatInput").value = "";
    handleVoice(said);
  };
  recognizer.onerror = (e) => {
    const reasons = {
      "not-allowed": "Microphone access was blocked — allow it in the address bar and try again.",
      "service-not-allowed": "Microphone access was blocked — allow it in the address bar and try again.",
      "no-speech": "I didn't catch anything — try again.",
      "audio-capture": "I can't find a microphone.",
      "network": "Speech recognition needs an internet connection in this browser.",
    };
    setStatus(reasons[e.error] || "Speech recognition failed — you can still type.");
  };
  recognizer.onend = () => {
    recognizer = null;
    // If something was heard, the reply sets Hexi's face; only reset it
    // when nothing was, so the two can't fight over the expression.
    setListening(false, !heard);
  };
  setListening(true);
  try { recognizer.start(); } catch (err) { recognizer = null; setListening(false); }
}

if (!Recognition) {
  document.getElementById("micBtn").style.display = "none";
} else {
  document.getElementById("micBtn").addEventListener("click", startListening);
}

document.querySelectorAll("#chips .chip").forEach(chip => {
  chip.addEventListener("click", () => handleChatMessage(chip.textContent));
});

document.getElementById("chatSend").addEventListener("click", () => {
  const input = document.getElementById("chatInput");
  const msg = input.value.trim();
  if (!msg) return;
  input.value = "";
  handleChatMessage(msg);
});
document.getElementById("chatInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") document.getElementById("chatSend").click();
});
