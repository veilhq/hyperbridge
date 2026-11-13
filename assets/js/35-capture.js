/* === Hyperbridge: capture shortcuts === */
(function () {
  "use strict";

  var input = document.getElementById("dock-input");
  if (!input) return;

  function isLink(text) { return /^https?:\/\//i.test(text); }

  // Ctrl+L focuses the capture input, which raises the bar.
  document.addEventListener("keydown", function (event) {
    var key = String(event.key).toLowerCase();
    if (key !== "l" || !(event.ctrlKey || event.metaKey) || event.altKey || event.repeat || document.getElementById("app").inert) return;
    event.preventDefault();
    input.focus();
    input.select();
  }, true);

  // A link pasted anywhere outside a field lands in the capture input and raises the bar.
  document.addEventListener("paste", function (event) {
    var target = event.target;
    if (target && target.closest && target.closest("input, textarea, select, [contenteditable]")) return;
    if (document.getElementById("app").inert || !event.clipboardData) return;
    var text = (event.clipboardData.getData("text") || "").trim();
    if (!isLink(text)) return;
    event.preventDefault();
    input.value = text;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.focus();
  });
})();
