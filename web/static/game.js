// Progress, sound and result panels. Pure presentation: every number shown
// here comes from the server's report, and everything dynamic goes in through
// textContent so imported step names can never become markup.
(function (root) {
  var KEY = "hexiGame.v1";
  var TROPHIES = [
    { id: "first", title: "First automation", test: function (s) { return s.automations >= 1; } },
    { id: "explorer", title: "Data explorer", test: function (s) { return s.imported; } },
    { id: "doctor", title: "Diagnostician", test: function (s) { return s.diagnosed.length >= 1; } },
    { id: "trusted", title: "Trusted bot", test: function (s) { return s.bestGrade === "A" || s.bestGrade === "B"; } },
    { id: "hour", title: "Hour hero", test: function (s) { return s.weeklyHours >= 1; } },
    { id: "lord", title: "Time lord", test: function (s) { return s.weeklyHours >= 5; } },
  ];

  function fresh() { return { xp: 0, automations: 0, weeklyHours: 0, imported: false, diagnosed: [], bestGrade: null, trophies: [] }; }
  var state = fresh();
  try { var saved = JSON.parse(localStorage.getItem(KEY)); if (saved && typeof saved.xp === "number") state = Object.assign(fresh(), saved); } catch (e) {}
  function persist() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} }

  function level(xp) { return Math.floor((1 + Math.sqrt(1 + 8 * xp / 100)) / 2); }
  function floorXp(l) { return 100 * l * (l - 1) / 2; }

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) { var n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; }

  // ---- 8-bit sound: square-wave blips, no audio files ----------------------
  var sfxOn = true, ctx = null;
  try { sfxOn = localStorage.getItem("hexiSfx") !== "off"; } catch (e) {}
  var SONGS = { select: [[660, .05]], confirm: [[523, .07], [659, .07], [784, .12]], level: [[523, .08], [659, .08], [784, .08], [1047, .2]], error: [[196, .12], [147, .18]], ping: [[880, .06]] };
  function sfx(name) {
    if (!sfxOn) return;
    try {
      ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
      var t = ctx.currentTime;
      (SONGS[name] || []).forEach(function (n) {
        var o = ctx.createOscillator(), g = ctx.createGain();
        o.type = "square"; o.frequency.value = n[0]; g.gain.setValueAtTime(.04, t); g.gain.exponentialRampToValueAtTime(.001, t + n[1]);
        o.connect(g); g.connect(ctx.destination); o.start(t); o.stop(t + n[1]); t += n[1];
      });
    } catch (e) {}
  }
  function toggleSfx() { sfxOn = !sfxOn; try { localStorage.setItem("hexiSfx", sfxOn ? "on" : "off"); } catch (e) {} refreshSfx(); sfx("select"); }
  function refreshSfx() { var b = $("sfxBtn"); if (b) b.textContent = "SFX: " + (sfxOn ? "on" : "off"); }

  // ---- HUD, XP, trophies ---------------------------------------------------
  function toast(title, detail) {
    var host = $("toasts"); if (!host) return;
    var t = el("div", "toast", title); if (detail) t.appendChild(el("small", "", detail));
    host.appendChild(t); setTimeout(function () { t.remove(); }, 4200);
  }
  function renderHud() {
    var l = level(state.xp), lo = floorXp(l), hi = floorXp(l + 1);
    if ($("hudLevel")) $("hudLevel").textContent = "LV " + l;
    if ($("hudXpText")) $("hudXpText").textContent = "XP " + state.xp + " / " + hi;
    if ($("hudXpBar")) $("hudXpBar").style.setProperty("--pct", Math.round(100 * (state.xp - lo) / (hi - lo)));
    if ($("hudHours")) $("hudHours").textContent = state.weeklyHours.toFixed(1);
    if ($("hudTrophies")) $("hudTrophies").textContent = state.trophies.length + " / " + TROPHIES.length;
  }
  function gain(points, why) {
    var before = level(state.xp); state.xp += points;
    toast("+" + points + " XP", why);
    if (level(state.xp) > before) { toast("Level up!", "You reached level " + level(state.xp)); sfx("level"); }
    checkTrophies(); persist(); renderHud();
  }
  function checkTrophies() {
    TROPHIES.forEach(function (t) {
      if (state.trophies.indexOf(t.id) === -1 && t.test(state)) { state.trophies.push(t.id); toast("Trophy unlocked", t.title); sfx("level"); }
    });
  }
  var rank = { A: 4, B: 3, C: 2, D: 1 };
  function onAutomated(report) {
    var saved = report && report.time_saved, rel = report && report.reliability;
    state.automations += 1;
    if (saved) state.weeklyHours = Math.round((state.weeklyHours + saved.hours_saved_per_week) * 100) / 100;
    if (rel && (!state.bestGrade || rank[rel.grade] > rank[state.bestGrade])) state.bestGrade = rel.grade;
    gain(50 + Math.round(((saved && saved.hours_saved_per_week) || 0) * 100), "Automation confirmed");
    sfx("confirm");
  }
  function onImported() { if (!state.imported) { state.imported = true; gain(25, "Brought your own data"); } else { sfx("ping"); } }
  function onDiagnosed(key) { if (state.diagnosed.indexOf(key) === -1) { state.diagnosed.push(key); gain(15, "Diagnosis read"); } }
  function reset() { state = fresh(); persist(); renderHud(); }

  // ---- Result panels -------------------------------------------------------
  function stat(label, value) { var b = el("div", "stat-box"); b.appendChild(el("small", "", label)); b.appendChild(el("b", "", value)); return b; }
  function bar(pct, cls) { var b = el("div", "bar " + (cls || "")); var i = el("i"); i.style.setProperty("--pct", Math.max(0, Math.min(100, Math.round(pct)))); b.appendChild(i); return b; }
  function pretty(s) { return String(s).replace(/_/g, " "); }
  var COMP_LABEL = { evidence: "Runs seen", stability: "Steady times", coverage: "Steps present", cohesion: "Same shape", holdout: "Holdout test", outcome: "Outcome data" };

  function renderReport(host, report, workflow) {
    if (!report || report.error) return;
    var s = report.time_saved, r = report.reliability, spec = report.automation_spec;
    var card = el("div", "card");
    card.appendChild(el("h3", "", "Battle report: " + pretty(workflow)));

    var g = el("div", "grid4");
    g.appendChild(stat("Saved per run", s.minutes_saved_per_run + " min"));
    g.appendChild(stat("Per week (est.)", s.hours_saved_per_week + " h"));
    g.appendChild(stat("Per month (est.)", s.hours_saved_per_month + " h"));
    g.appendChild(stat("80% range / wk", s.weekly_hours_interval_80[0] + " to " + s.weekly_hours_interval_80[1] + " h"));
    card.appendChild(g);

    var gr = el("div", "grade");
    gr.appendChild(el("div", "letter " + r.grade, r.grade));
    var meta = el("div", "meta"); meta.appendChild(el("b", "", "Reliability " + r.score + " / 100: " + r.label));
    meta.appendChild(bar(r.score, r.score >= 65 ? "green" : r.score >= 50 ? "" : "red"));
    gr.appendChild(meta); card.appendChild(gr);

    Object.keys(r.components).forEach(function (k) {
      var row = el("div", "comp"); row.appendChild(el("span", "", COMP_LABEL[k] || k));
      row.appendChild(bar(r.components[k] * 100, "blue")); row.appendChild(el("span", "", Math.round(r.components[k] * 100) + "%"));
      card.appendChild(row);
    });
    if (s.holdout) card.appendChild(el("p", "fine", "Holdout test: fitted on the first " + s.holdout.train_runs + " runs, it predicted " + s.holdout.predicted_minutes_per_run + " min saved per run; the last " + s.holdout.test_runs + " runs actually showed " + s.holdout.actual_minutes_per_run + "."));

    if (r.caveats.length) {
      card.appendChild(el("h3", "", "Watch out"));
      var ul = el("ul", "plain"); r.caveats.forEach(function (c) { ul.appendChild(el("li", "", c)); }); card.appendChild(ul);
    }
    if (spec && spec.steps) {
      card.appendChild(el("h3", "", "Automation spec"));
      spec.steps.forEach(function (st) {
        var row = el("div", "row"); var left = el("div", "grow"); left.appendChild(el("div", "", pretty(st.step))); left.appendChild(el("div", "fine", st.guardrail));
        row.appendChild(left); row.appendChild(el("span", "tag " + (st.mode === "automate" ? "auto" : "human"), st.mode === "automate" ? "auto" : "human")); card.appendChild(row);
      });
      if (spec.stop_condition_minutes) card.appendChild(el("p", "fine", "Stop and alert a person if a run passes " + spec.stop_condition_minutes + " minutes."));
    }
    card.appendChild(el("p", "fine", "Shadow mode: your recorded history was replayed with these steps automated, keeping " + Math.round(s.supervision_overhead * 100) + "% of their time for supervision. Nothing ran against your live apps."));
    host.appendChild(card);
    card.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function renderAdvice(host, payload) {
    var card = el("div", "card");
    if (!payload || payload.error) { card.appendChild(el("p", "status", (payload && payload.error) || "No diagnosis available.")); host.appendChild(card); return card; }
    var a = payload.advice;
    var badge = el("span", "badge" + (a.source === "template" ? " tpl" : ""), a.source === "template" ? "Rule-based" : "AI model");
    var h = el("h3", "", "Hexi's diagnosis "); h.appendChild(badge); card.appendChild(h);
    card.appendChild(el("p", "", a.headline));
    card.appendChild(el("p", "", a.diagnosis));
    card.appendChild(el("h3", "", "Prescription"));
    var ol = el("ol", "rx");
    a.prescription.forEach(function (p) {
      var li = el("li"); li.appendChild(el("b", "", p.action));
      if (p.why) li.appendChild(el("small", "", p.why));
      if (p.expected_effect) li.appendChild(el("small", "", "Expected: " + p.expected_effect));
      ol.appendChild(li);
    });
    card.appendChild(ol);
    var seen = host.textContent;
    var risks = (a.risks || []).filter(function (r) { return seen.indexOf(r) === -1; });  // the report already lists its own caveats
    if (risks.length) { var ul = el("ul", "plain"); risks.forEach(function (r) { ul.appendChild(el("li", "", r)); }); card.appendChild(el("h3", "", "Risks")); card.appendChild(ul); }
    if (a.confidence_note) card.appendChild(el("p", "fine", a.confidence_note));
    host.appendChild(card);
    return card;
  }

  function loading(host, text) { var p = el("p", "loading", text || "Hexi is thinking..."); host.appendChild(p); return p; }

  root.HexiGame = { sfx: sfx, toggleSfx: toggleSfx, refreshSfx: refreshSfx, renderHud: renderHud, onAutomated: onAutomated,
    onImported: onImported, onDiagnosed: onDiagnosed, reset: reset, renderReport: renderReport, renderAdvice: renderAdvice,
    loading: loading, toast: toast, level: level, _state: function () { return state; } };
  renderHud(); refreshSfx();
  var b = document.getElementById("sfxBtn"); if (b) b.addEventListener("click", toggleSfx);
})(window);
