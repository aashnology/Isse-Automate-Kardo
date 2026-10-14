// Wake-word and conversation-window logic for the simulated Alexa+ voice loop.
// Pure and DOM-free so it can be tested in node. The browser microphone stands
// in for an Echo: a final transcript comes in, and this decides whether it was
// addressed to Hexi and what the command part is.
(function (root) {
  var FOLLOWUP_MS = 8000;     // after Hexi speaks, plain commands are accepted
  var CONFIRM_MS = 20000;     // longer window while a proposal awaits a yes/no

  var WAKE = /^(?:hey |ok |okay )?(?:alexa|alexia|alexis)\b[\s,.:!?-]*/;
  var INVOKE = /^(?:(?:ask|tell|open|launch|start|talk to|speak to)\s+)?(?:hexi|hexy|hexie|hex e)\b[\s,.:!?-]*(?:to |about |for |if |whether )?/;
  var DIRECT = /^(?:hexi|hexy|hexie)\b[\s,.:!?-]*/;

  function clean(t) {
    return String(t == null ? "" : t).toLowerCase().replace(/\s+/g, " ").trim().slice(0, 300).replace(/[\s.?!,]+$/, "");
  }

  function initialState() { return { awakeUntil: 0, awaitingConfirm: false }; }

  // Returns {action: "ignore" | "wake_only" | "command", utterance, via, state}.
  // via is "wake" (Alexa, ask Hexi ...), "direct" (Hexi, ...) or "followup".
  function route(transcript, state, now) {
    var s = { awakeUntil: state.awakeUntil, awaitingConfirm: state.awaitingConfirm };
    var text = clean(transcript);
    if (!text) return { action: "ignore", utterance: "", via: null, state: s };

    var m = WAKE.exec(text);
    if (m) {
      var rest = text.slice(m[0].length);
      var inv = INVOKE.exec(rest);
      var utterance = (inv ? rest.slice(inv[0].length) : rest).trim();
      if (!utterance) return { action: "wake_only", utterance: "", via: "wake", state: s };
      return { action: "command", utterance: utterance, via: "wake", state: s };
    }
    var d = DIRECT.exec(text);
    if (d) {
      var u = text.slice(d[0].length).trim();
      return { action: u ? "command" : "wake_only", utterance: u, via: "direct", state: s };
    }
    if (now < s.awakeUntil) return { action: "command", utterance: text, via: "followup", state: s };
    return { action: "ignore", utterance: "", via: null, state: s };
  }

  // Call when Hexi finishes speaking (or a wake word alone was heard).
  function openWindow(state, now, awaitingConfirm) {
    return {
      awakeUntil: now + (awaitingConfirm ? CONFIRM_MS : FOLLOWUP_MS),
      awaitingConfirm: !!awaitingConfirm,
    };
  }

  var api = { route: route, openWindow: openWindow, initialState: initialState,
              FOLLOWUP_MS: FOLLOWUP_MS, CONFIRM_MS: CONFIRM_MS };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.HexiAlexa = api;
})(typeof window !== "undefined" ? window : globalThis);
