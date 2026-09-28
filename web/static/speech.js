// Turns Orbi's on-screen text into something that sounds natural when read
// aloud. On-screen text is written for the eye ("'bug_triage' costs 1.2h"),
// and a speech engine reads it literally ("bug underscore triage ... 1.2 h"),
// so this is a small cleanup pass, kept pure so it can be tested in node
// without a browser.
(function (root) {
  function speakable(text) {
    return String(text)
      .replace(/_/g, " ")
      .replace(/→/g, " then ")
      .replace(/(\d+(?:\.\d+)?)h\b/g, function (_, n) {
        return n + (parseFloat(n) === 1 ? " hour" : " hours");
      })
      .replace(/(\d+(?:\.\d+)?)%/g, "$1 percent")
      .replace(/['"“”‘’]/g, "")
      .replace(/\s+/g, " ")
      .trim();
  }

  var api = { speakable: speakable };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.OrbiSpeech = api;
})(typeof window !== "undefined" ? window : globalThis);
