/* === Hyperbridge: core === */
(function () {
  "use strict";

  var $ = function (selector) { return document.querySelector(selector); };
  window.$ = $;

  // Re-tints the HyperKit cursors: SVG data URIs cannot reference CSS variables.
  function syncCursors(hex) {
    var ec = encodeURIComponent(hex);
    var root = document.documentElement.style;
    root.setProperty("--cursor-default", "url(\"data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='" + ec + "' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'><path d='M4.037 4.688a.495.495 0 0 1 .651-.651l16 6.5a.5.5 0 0 1-.063.947l-6.124 1.58a2 2 0 0 0-1.438 1.435l-1.579 6.126a.5.5 0 0 1-.947.063z'/></svg>\") 2 2, auto");
    root.setProperty("--cursor-pointer", "url(\"data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='" + ec + "' stroke='" + ec + "' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'><path d='M4.037 4.688a.495.495 0 0 1 .651-.651l16 6.5a.5.5 0 0 1-.063.947l-6.124 1.58a2 2 0 0 0-1.438 1.435l-1.579 6.126a.5.5 0 0 1-.947.063z'/></svg>\") 2 2, pointer");
    root.setProperty("--cursor-text", "url(\"data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='" + ec + "' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M17 22h-1a4 4 0 0 1-4-4V6a4 4 0 0 1 4-4h1'/><path d='M7 22h1a4 4 0 0 0 4-4V6a4 4 0 0 0-4-4H7'/></svg>\") 10 10, text");
  }

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

    syncCursors(hex);

    if (typeof palette === "object") {
      if (palette.warm) root.setProperty("--warm", palette.warm);
      if (palette.cool) root.setProperty("--cool", palette.cool);
      if (palette.comp) root.setProperty("--comp", palette.comp);
    }
  }
  window.applyAccent = applyAccent;

  // Shows the entry total beside the All set.
  function renderStats(stats) {
    var count = stats && typeof stats.entries === "number" ? stats.entries : 0;
    var countEl = $("#all-count");
    if (countEl) countEl.textContent = count;
  }
  window.renderStats = renderStats;

  function onBridgeReady() {
    var api = window.pywebview && window.pywebview.api;
    if (!api) return;
    if (api.get_accent) api.get_accent().then(applyAccent);
    if (api.get_stats) api.get_stats().then(renderStats);
  }

  // Shared HyperKit cursor trail and companion box.
  if (window.HvCursorTrail) window.HvCursorTrail.start(document.body);
  if (window.HvCursorBox) window.HvCursorBox.start(document.body);

  if (window.pywebview && window.pywebview.api) {
    onBridgeReady();
  } else {
    window.addEventListener("pywebviewready", onBridgeReady);
  }
})();
