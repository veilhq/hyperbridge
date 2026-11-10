/* === Hyperbridge: window hotkeys === */
(function () {
  "use strict";

  function typing(target) {
    var tag = target && target.tagName;
    return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || !!(target && target.isContentEditable);
  }

  // F11 always toggles fullscreen; F does too unless a text field has focus.
  document.addEventListener("keydown", function (event) {
    if (event.ctrlKey || event.altKey || event.metaKey || event.repeat) return;
    var wanted = event.key === "F11" || ((event.key === "f" || event.key === "F") && !typing(event.target));
    if (!wanted) return;
    event.preventDefault();
    var bridge = window.pywebview && window.pywebview.api;
    if (bridge && bridge.toggle_fullscreen) bridge.toggle_fullscreen();
  });
})();
