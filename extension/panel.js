// Side-panel controller: text or voice in, staged execution steps out.
// All routing/request logic lives in agent_client.js (tested in node); this
// file is only DOM and browser APIs.
(function () {
  var $ = function (id) { return document.getElementById(id); };
  var state = { pendingProposal: null, lastWorkflow: null };
  var base = HexiAgent.DEFAULT_BASE;
  var busy = false;

  // Simplified faces (same hexagon language as the web demo).
  var FILL = { asleep: "#D3D1C7", idle: "#B5D4F4", watching: "#B5D4F4", curious: "#F0997B", suggesting: "#FAC775", confirmed: "#97C459" };
  function setMood(mood) {
    var fill = FILL[mood] || FILL.idle;
    $("face").innerHTML =
      '<polygon points="24,4 42,15 42,33 24,44 6,33 6,15" fill="' + fill + '" stroke="#2c2c2a" stroke-width="2"/>' +
      (mood === "asleep"
        ? '<path d="M13 22 Q17 25 21 22" stroke="#2c2c2a" stroke-width="2.5" fill="none"/><path d="M27 22 Q31 25 35 22" stroke="#2c2c2a" stroke-width="2.5" fill="none"/>'
        : '<rect x="14" y="19" width="6" height="7" rx="1" fill="#042C53"/><rect x="28" y="19" width="6" height="7" rx="1" fill="#042C53"/><path d="M17 31 Q24 34 31 31" stroke="#042C53" stroke-width="2.5" fill="none"/>');
  }

  function addMsg(who, text) {
    var d = document.createElement("div");
    d.className = "msg " + who;
    d.textContent = text;
    $("log").appendChild(d);
    $("log").scrollTop = $("log").scrollHeight;
  }

  // Steps render live: a step with the same id replaces the earlier one
  // ("running" -> "done"/"error"), so the list shows progress, not history.
  function renderStep(s) {
    var li = document.querySelector('#stepList li[data-id="' + s.id + '"]');
    if (!li) { li = document.createElement("li"); li.dataset.id = s.id; $("stepList").appendChild(li); }
    li.className = s.status;
    li.textContent = s.label;
    if (s.detail) {
      var d = document.createElement("span");
      d.className = "detail";
      d.textContent = s.detail;
      li.appendChild(d);
    }
    $("steps").open = true;
    $("status").textContent = s.status === "error" ? s.detail : s.label;
  }

  async function submit(text) {
    if (busy) return;
    busy = true;
    $("stepList").innerHTML = "";
    if (String(text).trim()) addMsg("you", text);
    try {
      var out = await HexiAgent.ask(text, state, {
        base: base,
        fetch: function (u, o) { return fetch(u, o); },
        classify: HexiIntents.classifyIntent,
        onStep: renderStep,
      });
      state = out.state;
      setMood(out.mood);
      addMsg("hexi", out.reply);
      if (window.speechSynthesis && out.reply) {
        window.speechSynthesis.cancel();
        window.speechSynthesis.speak(new SpeechSynthesisUtterance(out.reply.replace(/_/g, " ")));
      }
    } catch (e) {
      addMsg("hexi", "Something went wrong. Try: what's costing me time, or brief me.");
    } finally {
      busy = false;
    }
  }

  function send() { var v = $("input").value; $("input").value = ""; submit(v); }
  $("send").addEventListener("click", send);
  $("input").addEventListener("keydown", function (e) { if (e.key === "Enter") send(); });
  document.querySelectorAll(".chip").forEach(function (c) {
    c.addEventListener("click", function () { submit(c.textContent); });
  });

  // ---- voice input (browser SpeechRecognition; audio goes to the browser vendor)
  var Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
  var rec = null;
  if (!Rec) {
    $("mic").hidden = true;
    $("micNote").textContent = "Voice input isn't available in this browser; typing works.";
  } else {
    $("mic").addEventListener("click", function () {
      if (rec) { rec.stop(); return; }
      if (window.speechSynthesis) window.speechSynthesis.cancel();
      rec = new Rec();
      rec.lang = "en-US";
      rec.interimResults = false;
      var heard = false;
      rec.onresult = function (e) { heard = true; submit(e.results[0][0].transcript); };
      rec.onerror = function (e) {
        var blocked = e.error === "not-allowed" || e.error === "service-not-allowed";
        $("micNote").textContent = blocked ? "Microphone blocked for this panel." : "Speech recognition failed (" + e.error + ") — typing works.";
        $("grantMic").hidden = !blocked;
      };
      rec.onend = function () { rec = null; $("mic").textContent = "Speak"; if (!heard) setMood("idle"); };
      $("mic").textContent = "Listening…";
      setMood("watching");
      try { rec.start(); } catch (e) { rec = null; $("mic").textContent = "Speak"; }
    });
  }
  // Extension side panels can't always show Chrome's microphone prompt, so
  // this opens a normal extension tab that can, once.
  $("grantMic").addEventListener("click", function () { chrome.tabs.create({ url: chrome.runtime.getURL("mic.html") }); });

  // ---- server address (localhost / 127.0.0.1 only)
  $("settings").addEventListener("click", function () {
    var v = window.prompt("Hexi server address (this machine only)", base);
    if (v === null) return;
    base = HexiAgent.normalizeBase(v);
    chrome.storage.local.set({ base: base });
    $("status").textContent = "Server: " + base;
  });
  chrome.storage.local.get("base", function (r) { if (r && r.base) base = HexiAgent.normalizeBase(r.base); });

  setMood("idle");
})();
