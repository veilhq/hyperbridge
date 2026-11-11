  var FEED_PRELOAD_MS = 10000;
  var COLUMN_MIN_REM = 18;
  var COLUMN_LIMIT = 12;
  var resizeTimer = null;
  var columnShift = 0;
  var zoomAnchor = null;
  try { columnShift = parseInt(localStorage.getItem("hyperbridge-columns"), 10) || 0; } catch (err) { columnShift = 0; }

  // Columns that fit the width, moved by the zoom step the Operator chose with + and -.
  function fitColumns() {
    var gap = parseFloat(getComputedStyle(grid).columnGap) || 0;
    var min = COLUMN_MIN_REM * parseFloat(getComputedStyle(document.documentElement).fontSize);
    return Math.max(1, Math.floor((grid.clientWidth + gap) / (min + gap)));
  }

  function columnCount() {
    return Math.min(COLUMN_LIMIT, Math.max(1, fitColumns() + columnShift));
  }

  // Adds or removes columns (+ shows more, smaller cards; - fewer, larger) and remembers the choice.
  function zoomColumns(step) {
    var fit = fitColumns();
    var next = Math.min(COLUMN_LIMIT, Math.max(1, columnCount() + step));
    if (next === columnCount()) return;
    columnShift = next - fit;
    try { localStorage.setItem("hyperbridge-columns", String(columnShift)); } catch (err) { /* ignore */ }
    zoomAnchor = pickAnchor();
    document.dispatchEvent(new CustomEvent("hyperbridge:relayout"));
    if (state.group) flip(function () { grid.style.columns = String(next); holdAnchor(); });
    else relayoutColumns();
    zoomAnchor = null;
  }

  // Remembers the card nearest the middle of the view and where it sits, so a zoom can keep it there.
  function pickAnchor() {
    var scroller = $("#library");
    var box = scroller.getBoundingClientRect();
    var middle = box.top + box.height / 2;
    var best = null, bestGap = Infinity;
    Array.prototype.forEach.call(grid.querySelectorAll(".library-card[data-id]"), function (card) {
      var rect = card.getBoundingClientRect();
      var gap = rect.top <= middle && rect.bottom >= middle ? 0 : Math.min(Math.abs(rect.top - middle), Math.abs(rect.bottom - middle));
      if (gap < bestGap) { best = card; bestGap = gap; }
    });
    return best ? { id: best.getAttribute("data-id"), top: best.getBoundingClientRect().top - box.top } : null;
  }

  // Scrolls so the remembered card is back at the same height in the view.
  function holdAnchor() {
    if (!zoomAnchor) return;
    var scroller = $("#library");
    var card = grid.querySelector('.library-card[data-id="' + zoomAnchor.id + '"]');
    if (card) scroller.scrollTop += card.getBoundingClientRect().top - scroller.getBoundingClientRect().top - zoomAnchor.top;
    zoomAnchor = null;
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
      var sx = now.width ? item.rect.width / now.width : 1, sy = now.height ? item.rect.height / now.height : 1;
      var resized = Math.abs(sx - 1) > 0.01 || Math.abs(sy - 1) > 0.01;
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1 && !resized) return;
      if ((item.rect.bottom < 0 || item.rect.top > view) && (now.bottom < 0 || now.top > view)) return;
      // A card that changed size also scales from its old size, so a zoom morphs instead of popping.
      var from = "translate(" + dx + "px, " + dy + "px)" + (resized ? " scale(" + sx + ", " + sy + ")" : "");
      item.card.animate([{ transformOrigin: "0 0", transform: from }, { transformOrigin: "0 0", transform: "none" }], { duration: duration, easing: easing });
    });
  }

  // Re-deals the cards into the right number of columns after the window changes width.
  function relayoutColumns() {
    if (!grid.hasAttribute("data-columns") || grid.querySelector(".loading-skeleton")) return;
    if (candidates && (!candidates.feed || candidates.busy)) return;
    if (columnCount() === grid.querySelectorAll(".library-grid-column").length) return;
    document.dispatchEvent(new CustomEvent("hyperbridge:relayout"));
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
      holdAnchor();
    });
  }
