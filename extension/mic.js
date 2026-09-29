document.getElementById("go").addEventListener("click", function () {
  var msg = document.getElementById("msg");
  navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
    stream.getTracks().forEach(function (t) { t.stop(); });
    msg.textContent = "Microphone allowed. Close this tab and use Speak in the Hexi panel.";
  }).catch(function () {
    msg.textContent = "Microphone was blocked. Allow it from the lock icon in the address bar, then try again.";
  });
});
