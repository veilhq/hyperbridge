/* === Hyperbridge: capture drawer === */
(function () {
  "use strict";

  var PREF_KEY = "hyperbridge-capture";
  var drawer = document.getElementById("capture-drawer");
  var handle = document.getElementById("capture-handle");
  var collapse = document.getElementById("capture-collapse");
  var input = document.getElementById("dock-input");
  if (!drawer || !handle || !collapse || !input) return;

  // Auto-hide is the default; the choice persists between sessions.
  function apply(collapsed, remember) {
    var label = collapsed ? "Keep capture bar visible" : "Auto-hide capture bar";
    drawer.toggleAttribute("data-collapsed", collapsed);
    collapse.setAttribute("aria-pressed", collapsed ? "true" : "false");
    collapse.setAttribute("aria-label", label);
    collapse.setAttribute("data-tooltip", label);
    if (!remember) return;
    try { localStorage.setItem(PREF_KEY, collapsed ? "auto-hide" : "pinned"); } catch (err) { /* ignore */ }
  }

  function isLink(text) { return /^https?:\/\//i.test(text); }

  function load() {
    try { return localStorage.getItem(PREF_KEY) !== "pinned"; } catch (err) { return true; }
  }

  apply(load(), false);
  handle.addEventListener("click", function () { input.focus(); });
  collapse.addEventListener("click", function () { apply(!drawer.hasAttribute("data-collapsed"), true); });
  document.addEventListener("hyperbridge:chrome", function (event) { apply(event.detail.collapsed, true); });

  // Ctrl+L opens the drawer with the input focused.
  document.addEventListener("keydown", function (event) {
    var key = String(event.key).toLowerCase();
    if (key !== "l" || !(event.ctrlKey || event.metaKey) || event.altKey || event.repeat || document.getElementById("app").inert) return;
    event.preventDefault();
    input.focus();
    input.select();
  }, true);

  // A link pasted anywhere outside a field lands in the capture input and raises the drawer.
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
