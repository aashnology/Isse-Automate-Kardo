// Hexi's chat router: turns a typed or spoken sentence into {intent, workflow}.
// Deliberately plain keyword matching, not an LLM -- and deliberately pulled
// out of the page into a pure module so it can be tested. The first version
// lived inline, matched substrings instead of whole words, and so read
// "stop suggesting bug triage" as a question about what costs the most time
// (because "stop" contains "top"). Whole-word matching and the rule order
// below exist because of that bug.
(function (root) {
  var WORKFLOW_SYNONYMS = {
    bug_triage: ["bug", "bugs", "ticket", "tickets", "triage"],
    weekly_reporting: ["report", "reports", "reporting", "spreadsheet", "weekly"],
    onboarding_new_partner: ["onboarding", "partner", "partners", "inbox"],
  };

  var MAX_CHARS = 300;
  var MAX_TOKENS = 60;
  var EXAMPLES = [
    "what's costing me time",
    "why is reporting slow",
    "any unusual runs in the tickets",
    "automate it",
    "stop suggesting bug triage",
    "what have I dismissed",
    "brief me",
  ];

  // Anything can arrive here -- a null from a failed transcription, a pasted
  // paragraph, markup, control characters. Reduce it to plain lowercase text
  // of bounded length so nothing downstream has to defend itself.
  function sanitize(input) {
    if (typeof input !== "string") {
      input = input === null || input === undefined || typeof input === "object" ? "" : String(input);
    }
    return input
      .replace(/[\u2018\u2019\u02bc]/g, "'")
      .replace(/<[^>]*>/g, " ")
      .replace(/[\u0000-\u001f\u007f-\u009f]/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, MAX_CHARS)
      .toLowerCase();
  }

  // Words worth correcting toward. Fuzzy matching is deliberately narrow:
  // 5+ letter words only, one edit (two for 9+ letters), same first letter --
  // typos and mis-transcriptions rarely change the first letter, and this keeps
  // "grief" from becoming "brief" or "unbox" from becoming "inbox".
  var VOCAB = [
    "briefing", "summarize", "rundown", "restore", "dismissed", "dismiss",
    "automate", "anomalies", "anomaly", "unusual", "outliers", "explain",
    "breakdown", "bottleneck", "wasting", "costing", "friction", "biggest",
    "reporting", "spreadsheet", "onboarding", "partner", "partners",
    "tickets", "ticket", "triage", "weekly", "brief",
  ];

  function editDistance(a, b, limit) {
    if (Math.abs(a.length - b.length) > limit) return limit + 1;
    var prev = [], cur = [], i, j;
    for (j = 0; j <= b.length; j++) prev[j] = j;
    for (i = 1; i <= a.length; i++) {
      cur = [i];
      for (j = 1; j <= b.length; j++) {
        cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      }
      prev = cur;
    }
    return prev[b.length];
  }

  function correctToken(tok) {
    if (tok.length < 5 || VOCAB.indexOf(tok) !== -1) return tok;
    var limit = tok.length >= 9 ? 2 : 1, best = tok, bestD = limit + 1;
    for (var i = 0; i < VOCAB.length; i++) {
      var w = VOCAB[i];
      if (w.charAt(0) !== tok.charAt(0)) continue;
      var d = editDistance(tok, w, limit);
      if (d < bestD) { bestD = d; best = w; }
    }
    return best;
  }

  function correct(text) {
    return text.split(" ").slice(0, MAX_TOKENS).map(correctToken).join(" ");
  }

  function matchWorkflow(text) {
    var lower = sanitize(text);
    var names = Object.keys(WORKFLOW_SYNONYMS);
    for (var i = 0; i < names.length; i++) {
      var words = WORKFLOW_SYNONYMS[names[i]];
      for (var j = 0; j < words.length; j++) {
        if (new RegExp("\\b" + words[j] + "\\b").test(lower)) return names[i];
      }
    }
    return null;
  }

  // Order matters: more specific intents come first. "restore" and
  // "dismissed list" must beat "dismiss"; "dismiss" must beat "friction".
  var RULES = [
    ["brief", /\b(brief|briefing|summary|summarize|rundown|catch me up|update me)\b/],
    ["dismissed_list", /\b(what|which|list|show)\b.*\bdismissed\b/],
    ["restore", /\b(restore|bring back|undo|resume)\b/],
    ["dismiss", /\b(stop|dismiss|never ?mind|no thanks|don'?t (suggest|ask|show|bring))\b/],
    ["automate", /\b(automate|do it|handle it|go ahead|yes please|yes)\b/],
    ["anomalies", /\b(anomal\w*|unusual|weird|outliers?|spikes?)\b/],
    ["why", /\b(why|slow|debug|breakdown|bottleneck|explain)\b/],
    ["friction", /\b(waste|wasting|costing|cost|costs|most time|top|biggest|friction|time sink)\b/],
    ["help", /\b(help|what can you do)\b/],
  ];

  function firstRule(text) {
    for (var i = 0; i < RULES.length; i++) if (RULES[i][1].test(text)) return RULES[i][0];
    return null;
  }

  // Never throws, always returns {intent, workflow, corrected, examples?}.
  // intent is "empty" for nothing usable, "unknown" for text no rule matched
  // even after typo correction (examples then gives the caller something
  // concrete to show instead of an error).
  function classifyIntent(text) {
    var clean = sanitize(text);
    if (!clean) return { intent: "empty", workflow: null, corrected: false, examples: EXAMPLES };
    var intent = firstRule(clean), corrected = false, fixed = clean;
    if (!intent) {
      fixed = correct(clean);
      intent = firstRule(fixed);
      corrected = intent !== null;
    }
    var workflow = matchWorkflow(clean) || matchWorkflow(fixed);
    if (!intent) return { intent: "unknown", workflow: workflow, corrected: false, examples: EXAMPLES };
    return { intent: intent, workflow: workflow, corrected: corrected };
  }

  var api = { classifyIntent: classifyIntent, matchWorkflow: matchWorkflow, sanitize: sanitize, EXAMPLES: EXAMPLES };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.HexiIntents = api;
})(typeof window !== "undefined" ? window : globalThis);
