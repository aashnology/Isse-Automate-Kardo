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

  function matchWorkflow(text) {
    var lower = String(text).toLowerCase();
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

  function classifyIntent(text) {
    var lower = String(text).toLowerCase();
    var workflow = matchWorkflow(lower);
    for (var i = 0; i < RULES.length; i++) {
      if (RULES[i][1].test(lower)) return { intent: RULES[i][0], workflow: workflow };
    }
    return { intent: "unknown", workflow: workflow };
  }

  var api = { classifyIntent: classifyIntent, matchWorkflow: matchWorkflow };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.HexiIntents = api;
})(typeof window !== "undefined" ? window : globalThis);
