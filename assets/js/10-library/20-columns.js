  var FEED_PRELOAD_MS = 10000;
  var COLUMN_MIN_REM = 18;
  var resizeTimer = null;

  function columnCount() {
    var gap = parseFloat(getComputedStyle(grid).columnGap) || 0;
    var min = COLUMN_MIN_REM * parseFloat(getComputedStyle(document.documentElement).fontSize);
    return Math.max(1, Math.floor((grid.clientWidth + gap) / (min + gap)));
  }

  // Empties the grid and sets up fixed columns for the feed.
  function resetColumns() {
    grid.textContent = "";
    grid.setAttribute("data-columns", "true");
    for (var i = 0, count = columnCount(); i < count; i++) grid.appendChild(makeEl("div", "library-grid-column"));
  }

  // Adds an element to the shortest column, at its top when asked.
  function placeInColumn(el, top) {
    var columns = grid.querySelectorAll(".library-grid-column");
    var best = columns[0];
    for (var i = 1; i < columns.length; i++) if (columns[i].offsetHeight < best.offsetHeight) best = columns[i];
    if (top && best.firstChild) best.insertBefore(el, best.firstChild);
    else best.appendChild(el);
  }

  function motionSeconds(name) {
    var value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return parseFloat(value) / (value.slice(-2) === "ms" ? 1000 : 1);
  }

  function reducedMotion() {
    return document.documentElement.classList.contains("a11y-reduce-motion") || (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  // Runs a grid change and glides every card that moved from where it was to where it landed.
  function flip(mutate) {
    var before = Array.prototype.slice.call(grid.querySelectorAll(".library-card")).map(function (card) {
      return { card: card, rect: card.getBoundingClientRect() };
    });
    mutate();
    if (reducedMotion()) return;
    var view = window.innerHeight;
    var duration = motionSeconds("--motion-enter") * 1000 || 400;
    var easing = getComputedStyle(document.documentElement).getPropertyValue("--ease").trim() || "ease";
    before.forEach(function (item) {
      if (!item.card.isConnected || !item.card.animate) return;
      var now = item.card.getBoundingClientRect();
      var dx = item.rect.left - now.left, dy = item.rect.top - now.top;
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;
      if ((item.rect.bottom < 0 || item.rect.top > view) && (now.bottom < 0 || now.top > view)) return;
      item.card.animate([{ transform: "translate(" + dx + "px, " + dy + "px)" }, { transform: "none" }], { duration: duration, easing: easing });
    });
  }

  // Re-deals the cards into the right number of columns after the window changes width.
  function relayoutColumns() {
    if (!grid.hasAttribute("data-columns") || grid.querySelector(".loading-skeleton")) return;
    if (candidates && (!candidates.feed || candidates.busy)) return;
    if (columnCount() === grid.querySelectorAll(".library-grid-column").length) return;
    var cards = Array.prototype.slice.call(grid.querySelectorAll(".library-card"));
    var order = {};
    state.entries.forEach(function (entry, index) { order[entry.id] = index; });
    cards.sort(function (a, b) {
      var first = a.getAttribute("data-id"), second = b.getAttribute("data-id");
      return candidates ? Number(first) - Number(second) : order[first] - order[second];
    });
    flip(function () {
      resetColumns();
      cards.forEach(function (card) { placeInColumn(card); });
    });
  }
