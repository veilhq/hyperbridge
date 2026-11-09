/* === Hyperbridge: core === */
(function () {
  "use strict";

  var $ = function (selector) { return document.querySelector(selector); };
  window.$ = $;

  // Applies the accent palette synced from Hypervisor's preferences.
  function applyAccent(palette) {
    var hex = typeof palette === "string" ? palette : palette.accent;
    var r = parseInt(hex.slice(1, 3), 16);
    var g = parseInt(hex.slice(3, 5), 16);
    var b = parseInt(hex.slice(5, 7), 16);
    var root = document.documentElement.style;

    root.setProperty("--accent", hex);
    root.setProperty("--accent-dim", hex + "cc");
    root.setProperty("--accent-glow", "rgba(" + r + "," + g + "," + b + ",0.06)");
    root.setProperty("--accent-border", "rgba(" + r + "," + g + "," + b + ",0.15)");

    if (typeof palette === "object") {
      if (palette.warm) root.setProperty("--warm", palette.warm);
      if (palette.cool) root.setProperty("--cool", palette.cool);
      if (palette.comp) root.setProperty("--comp", palette.comp);
    }
  }
  window.applyAccent = applyAccent;

  // Shows the entry total and hides the empty state once the library has entries.
  function renderStats(stats) {
    var count = stats && typeof stats.entries === "number" ? stats.entries : 0;
    var countEl = $("#entry-count");
    var emptyEl = $("#library-empty");
    if (countEl) countEl.textContent = count === 1 ? "1 entry" : count + " entries";
    if (emptyEl) emptyEl.hidden = count > 0;
  }
  window.renderStats = renderStats;

  function onBridgeReady() {
    var api = window.pywebview && window.pywebview.api;
    if (!api) return;
    if (api.get_accent) api.get_accent().then(applyAccent);
    if (api.get_stats) api.get_stats().then(renderStats);
  }

  if (window.pywebview && window.pywebview.api) {
    onBridgeReady();
  } else {
    window.addEventListener("pywebviewready", onBridgeReady);
  }
})();
