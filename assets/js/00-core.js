/* === Hyperbridge: core === */
(function () {
  "use strict";

  var $ = function (selector) { return document.querySelector(selector); };
  window.$ = $;

  // Reads the view defaults the app was launched with; a missing key returns the fallback.
  var launchDefaults = {};
  try { launchDefaults = JSON.parse(($("#hb-defaults") || {}).textContent || "{}") || {}; } catch (err) { launchDefaults = {}; }
  window.hbDefault = function (key, fallback) {
    return Object.prototype.hasOwnProperty.call(launchDefaults, key) ? launchDefaults[key] : fallback;
  };

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

  // Shows the entry total beside the All tab and the count of entries in no set beside Unsorted.
  function renderStats(stats) {
    var count = stats && typeof stats.entries === "number" ? stats.entries : 0;
    var countEl = $("#all-count");
    if (countEl) countEl.textContent = count;
    var unsortedEl = $("#unsorted-count");
    if (unsortedEl) unsortedEl.textContent = stats && typeof stats.unsorted === "number" ? stats.unsorted : 0;
  }
  window.renderStats = renderStats;

  var NAV_WAIT_MS = 250;
  var navWaits = null;

  function reducedMotion() {
    return document.documentElement.classList.contains("a11y-reduce-motion") ||
      (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  // Runs a change of view as a view transition: the old view fades and drifts down, then the new one rises in.
  // Navigations started inside it join the same transition; without support or with reduced motion it just runs.
  function navigate(update) {
    if (navWaits || !document.startViewTransition || reducedMotion()) { update(); return; }
    document.startViewTransition(function () {
      navWaits = [];
      try { update(); } finally {
        var waits = navWaits;
        navWaits = null;
      }
      var cap = new Promise(function (resolve) { setTimeout(resolve, NAV_WAIT_MS); });
      return Promise.race([Promise.all(waits).catch(function () {}), cap]);
    });
  }

  // Holds the incoming snapshot until the promise settles (briefly), so a reloading grid arrives with its new cards.
  navigate.wait = function (promise) {
    if (navWaits && promise && promise.then) navWaits.push(promise);
    return promise;
  };
  window.hbNavigate = navigate;

  function onBridgeReady() {
    var api = window.pywebview && window.pywebview.api;
    if (!api) return;
    if (api.get_accent) api.get_accent().then(applyAccent);
    if (api.get_stats) api.get_stats().then(renderStats);
  }

  // Shared HyperKit cursor trail and companion box; the trail's WebGL setup waits until the first frame is up.
  if (window.HvCursorTrail) {
    (window.requestIdleCallback || setTimeout)(function () { window.HvCursorTrail.start(document.body); }, { timeout: 1000 });
  }
  if (window.HvCursorBox) window.HvCursorBox.start(document.body);

  if (window.pywebview && window.pywebview.api) {
    onBridgeReady();
  } else {
    window.addEventListener("pywebviewready", onBridgeReady);
  }
})();
