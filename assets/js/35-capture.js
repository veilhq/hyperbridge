/* === Hyperbridge: capture overlay === */
(function () {
  "use strict";

  var overlay = document.getElementById("capture-overlay");
  var input = document.getElementById("dock-input");
  var app = document.getElementById("app");
  if (!overlay || !input || !app) return;
  var returnTo = null;
  var holdingApp = false;

  function isOpen() { return overlay.classList.contains("visible"); }
  function isLink(text) { return /^https?:\/\//i.test(text); }

  // Raises the overlay over the blurred app with the input focused; text, when given, fills the input.
  function open(text) {
    if (text !== undefined && text !== null) {
      input.value = text;
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }
    if (isOpen()) {
      input.focus();
      return;
    }
    if (app.inert) return;
    returnTo = document.activeElement;
    holdingApp = true;
    app.inert = true;
    overlay.inert = false;
    overlay.classList.add("visible");
    input.focus();
    input.select();
  }

  // Lowers the overlay; Find more mode ends with it.
  function close() {
    if (!isOpen()) return;
    overlay.classList.remove("visible");
    overlay.inert = true;
    if (holdingApp) app.inert = false;
    holdingApp = false;
    var find = document.getElementById("dock-find");
    if (find && find.getAttribute("aria-pressed") === "true") find.click();
    if (returnTo && returnTo.focus && document.contains(returnTo)) returnTo.focus();
    returnTo = null;
  }

  overlay.addEventListener("mousedown", function (event) {
    if (event.target === overlay) close();
  });
  document.addEventListener("hyperbridge:capture-open", function () { open(); });
  document.addEventListener("hyperbridge:capture-close", close);

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && isOpen()) {
      event.preventDefault();
      event.stopImmediatePropagation();
      close();
      return;
    }
    var key = String(event.key).toLowerCase();
    if (key !== "l" || !(event.ctrlKey || event.metaKey) || event.altKey || event.repeat) return;
    event.preventDefault();
    open();
  }, true);

  // A link pasted anywhere outside a field opens the overlay with the link in the input.
  document.addEventListener("paste", function (event) {
    var target = event.target;
    if (isOpen() || app.inert || !event.clipboardData) return;
    if (target && target.closest && target.closest("input, textarea, select, [contenteditable]")) return;
    var text = (event.clipboardData.getData("text") || "").trim();
    if (!isLink(text)) return;
    event.preventDefault();
    open(text);
  });
})();
