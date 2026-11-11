/* === Hyperbridge: image unloading === */
(function () {
  "use strict";

  var MARGIN = "1500px 0px";
  var sources = new WeakMap();
  var observer = null;

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

  function watch(node) {
    if (node.nodeType !== 1) return;
    var images = node.matches(".library-card-image") ? [node] : node.querySelectorAll(".library-card-image");
    for (var i = 0; i < images.length; i++) observer.observe(images[i]);
  }

  function forget(node) {
    if (node.nodeType !== 1) return;
    var images = node.matches(".library-card-image") ? [node] : node.querySelectorAll(".library-card-image");
    for (var i = 0; i < images.length; i++) observer.unobserve(images[i]);
  }

  function init() {
    var grid = document.getElementById("library-grid");
    var scroller = document.getElementById("library");
    if (!grid || !scroller || !("IntersectionObserver" in window) || !("MutationObserver" in window)) return;
    observer = new IntersectionObserver(function (changes) {
      changes.forEach(function (change) {
        if (change.isIntersecting) restore(change.target);
        else unload(change.target);
      });
    }, { root: scroller, rootMargin: MARGIN });
    new MutationObserver(function (records) {
      records.forEach(function (record) {
        record.removedNodes.forEach(forget);
        record.addedNodes.forEach(watch);
      });
    }).observe(grid, { childList: true, subtree: true });
    watch(grid);
  }

  init();
})();
