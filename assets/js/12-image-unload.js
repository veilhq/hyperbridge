/* === Hyperbridge: image unloading and card parking === */
(function () {
  "use strict";

  var MARGIN = "1500px 0px";
  var REPARK_MS = 250;
  var sources = new WeakMap();
  var observer = null;
  var reparkTimer = null;

  // Drops the image data of a card that has scrolled far away, pinning its exact fractional height so the grid does not shift.
  function unload(img) {
    var height = img.getBoundingClientRect().height;
    if (!img.getAttribute("src") || !img.complete || !height) return;
    sources.set(img, img.getAttribute("src"));
    img.style.height = height + "px";
    img.removeAttribute("src");
  }

  // Puts the image back when its card scrolls near the viewport again; the held height is released once it has loaded.
  function restore(img) {
    var src = sources.get(img);
    if (src === undefined) return;
    sources.delete(img);
    var release = function () { img.style.height = ""; };
    img.addEventListener("load", release, { once: true });
    img.addEventListener("error", release, { once: true });
    img.src = src;
  }

  // A far-off card keeps its layout height but skips style, layout and paint for everything inside it.
  function park(card) {
    if (card.hasAttribute("data-parked")) return;
    var height = getComputedStyle(card).height;
    if (!parseFloat(height)) return;
    card.style.setProperty("--parked-height", height);
    card.setAttribute("data-parked", "true");
  }

  function unpark(card) {
    if (!card.hasAttribute("data-parked")) return;
    card.removeAttribute("data-parked");
    card.style.removeProperty("--parked-height");
  }

  function imagesOf(card) {
    return card.querySelectorAll(".library-card-image");
  }

  function cardsIn(node) {
    if (node.nodeType !== 1) return [];
    if (node.matches(".library-card")) return node.matches(".loading-skeleton") ? [] : [node];
    return node.querySelectorAll(".library-card:not(.loading-skeleton)");
  }

  function watch(node) {
    var cards = cardsIn(node);
    for (var i = 0; i < cards.length; i++) observer.observe(cards[i]);
  }

  function forget(node) {
    var cards = cardsIn(node);
    for (var i = 0; i < cards.length; i++) observer.unobserve(cards[i]);
  }

  // After the columns change width, every held height is stale: unpark all cards now and let the observer park them again once sizes settle.
  function releasePins(grid) {
    var images = grid.querySelectorAll(".library-card-image");
    for (var i = 0; i < images.length; i++) {
      if (!images[i].getAttribute("src") && sources.has(images[i])) images[i].style.height = "";
    }
    var parked = grid.querySelectorAll(".library-card[data-parked]");
    for (var j = 0; j < parked.length; j++) unpark(parked[j]);
    clearTimeout(reparkTimer);
    reparkTimer = setTimeout(function () {
      var cards = cardsIn(grid);
      for (var k = 0; k < cards.length; k++) { observer.unobserve(cards[k]); observer.observe(cards[k]); }
    }, REPARK_MS);
  }

  function init() {
    var grid = document.getElementById("library-grid");
    var scroller = document.getElementById("library");
    if (!grid || !scroller || !("IntersectionObserver" in window) || !("MutationObserver" in window)) return;
    observer = new IntersectionObserver(function (changes) {
      changes.forEach(function (change) {
        var card = change.target;
        var images = imagesOf(card);
        if (change.isIntersecting) {
          unpark(card);
          for (var i = 0; i < images.length; i++) restore(images[i]);
        } else {
          for (var j = 0; j < images.length; j++) unload(images[j]);
          park(card);
        }
      });
    }, { root: scroller, rootMargin: MARGIN });
    new MutationObserver(function (records) {
      records.forEach(function (record) {
        record.removedNodes.forEach(forget);
        record.addedNodes.forEach(watch);
      });
    }).observe(grid, { childList: true, subtree: true });
    watch(grid);
    document.addEventListener("hyperbridge:relayout", function () { releasePins(grid); });
    window.addEventListener("resize", function () { releasePins(grid); });
  }

  init();
})();
