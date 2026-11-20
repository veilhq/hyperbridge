  var FEED_PRELOAD_MS = 10000;
  var COLUMN_MIN_REM = 18;
  var COLUMN_LIMIT = 12;
  var resizeTimer = null;
  var columnShift = 0;
  var zoomAnchor = null;
  var defaultShift = window.hbDefault ? Number(window.hbDefault("library_columns", 0)) || 0 : 0;
  try {
    var savedShift = parseInt(localStorage.getItem("hyperbridge-columns"), 10);
    columnShift = isNaN(savedShift) ? defaultShift : savedShift;
  } catch (err) { columnShift = defaultShift; }

  // Columns that fit the width, moved by the zoom step the Operator chose with + and -.
  function fitColumns() {
    var gap = parseFloat(getComputedStyle(grid).columnGap) || 0;
    var min = COLUMN_MIN_REM * parseFloat(getComputedStyle(document.documentElement).fontSize);
    return Math.max(1, Math.floor((grid.clientWidth + gap) / (min + gap)));
  }

  function columnCount() {
    return Math.min(COLUMN_LIMIT, Math.max(1, fitColumns() + columnShift));
  }

  // Columns on screen now, which can differ from columnCount() when the width changed without a window resize.
  function shownColumns() {
    if (grid.hasAttribute("data-columns")) return grid.querySelectorAll(".library-grid-column").length || columnCount();
    return parseInt(grid.style.columns, 10) || columnCount();
  }

  // Adds or removes columns (+ shows more, smaller cards; - fewer, larger) and remembers the choice.
  function zoomColumns(step) {
    var fit = fitColumns();
    var shown = shownColumns();
    var next = Math.min(COLUMN_LIMIT, Math.max(1, shown + step));
    if (next === shown) return;
    columnShift = next - fit;
    try { localStorage.setItem("hyperbridge-columns", String(columnShift)); } catch (err) { /* ignore */ }
    zoomAnchor = pickAnchor();
    if (state.group) {
      document.dispatchEvent(new CustomEvent("hyperbridge:relayout"));
      flip(function () { grid.style.columns = String(next); holdAnchor(); });
    } else {
      relayoutColumns(next);
    }
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

  // Empties the grid and sets up fixed columns, the given count or what fits now.
  function resetColumns(count) {
    placement = null;
    grid.textContent = "";
    grid.setAttribute("data-columns", "true");
    for (var i = 0, total = count || columnCount(); i < total; i++) grid.appendChild(makeEl("div", "library-grid-column"));
  }

  // Column heights measured once per synchronous run of placements, then advanced by each card's predicted height.
  var placement = null;

  function startPlacement() {
    var columns = Array.prototype.slice.call(grid.querySelectorAll(".library-grid-column"));
    placement = { columns: columns, heights: columns.map(function (column) { return column.offsetHeight; }), width: columns.length ? columns[0].clientWidth : 0, chrome: null };
    queueMicrotask(function () { placement = null; });
  }

  // Border and bottom margin a card adds around its reserved image box, read once per run.
  function cardChrome(el) {
    var style = getComputedStyle(el);
    return { border: (parseFloat(style.borderTopWidth) || 0) + (parseFloat(style.borderBottomWidth) || 0), margin: parseFloat(style.marginBottom) || 0 };
  }

  function parseRatio(value) {
    var parts = String(value || "").split("/");
    var ratio = parseFloat(parts[0]) / (parts.length > 1 ? parseFloat(parts[1]) : 1);
    return ratio > 0 && isFinite(ratio) ? ratio : 0;
  }

  // Height an element takes in a column, from the aspect ratio it reserves (inline, or 4 / 3 for pending and empty cards); null when unknown.
  function predictedHeight(el) {
    var own = parseRatio(el.style.aspectRatio);
    var box = own ? el : el.querySelector(".library-card-image, .library-pending, .library-thumb-empty");
    var ratio = own || (box && (parseRatio(box.style.aspectRatio) || (box.classList.contains("library-card-image") ? 0 : 4 / 3)));
    if (!ratio || !placement.width) return null;
    if (!placement.chrome) placement.chrome = cardChrome(el);
    var border = placement.chrome.border;
    return (own ? placement.width / ratio : (placement.width - border) / ratio + border) + placement.chrome.margin;
  }

  // Adds an element to the shortest column, at its top when asked.
  function placeInColumn(el, top) {
    if (!placement || !placement.columns[0] || !placement.columns[0].isConnected) startPlacement();
    var heights = placement.heights;
    var index = 0;
    for (var i = 1; i < heights.length; i++) if (heights[i] < heights[index]) index = i;
    var best = placement.columns[index];
    if (top && best.firstChild) best.insertBefore(el, best.firstChild);
    else best.appendChild(el);
    var grown = predictedHeight(el);
    // Anything without a reserved ratio is measured, and the run measures fresh from then on.
    if (grown === null) placement = null;
    else heights[index] += grown;
  }

  function motionSeconds(name) {
    var value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return parseFloat(value) / (value.slice(-2) === "ms" ? 1000 : 1);
  }

  function reducedMotion() {
    return document.documentElement.classList.contains("a11y-reduce-motion") || (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  // A card's identity across a rebuild: the saved feed id when it has one, else its entry id.
  function cardKey(card) {
    return card.getAttribute("data-key") || card.getAttribute("data-id");
  }

  // Finds the card now standing in for one that was replaced during a rebuild.
  function successorOf(item) {
    if (item.card.isConnected) return item.card;
    if (!item.key) return null;
    return grid.querySelector('.library-card[data-key="' + item.key + '"]') || grid.querySelector('.library-card[data-id="' + item.key + '"]');
  }

  // Runs a grid change and glides every card that moved (or was rebuilt) from where it was to where it landed.
  function flip(mutate) {
    var before = Array.prototype.slice.call(grid.querySelectorAll(".library-card")).map(function (card) {
      return { card: card, key: cardKey(card), rect: card.getBoundingClientRect() };
    });
    mutate();
    if (reducedMotion()) return;
    var view = window.innerHeight;
    var duration = motionSeconds("--motion-enter") * 1000 || 400;
    var easing = getComputedStyle(document.documentElement).getPropertyValue("--ease").trim() || "ease";
    before.forEach(function (item) {
      item.card = successorOf(item);
      if (!item.card || !item.card.animate) return;
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

  // Re-deals the cards into the given number of columns, or what fits after the window changes width.
  // A zoom passes its count so a layout shift during the re-deal cannot cancel it.
  function relayoutColumns(count) {
    if (!grid.hasAttribute("data-columns") || grid.querySelector(".loading-skeleton")) return;
    if (candidates && (!(candidates.feed || candidates.trail) || candidates.busy)) return;
    var want = typeof count === "number" ? count : columnCount();
    if (want === grid.querySelectorAll(".library-grid-column").length) return;
    document.dispatchEvent(new CustomEvent("hyperbridge:relayout"));
    var cards = Array.prototype.slice.call(grid.querySelectorAll(".library-card"));
    var order = {};
    state.entries.forEach(function (entry, index) { order[entry.id] = index; });
    cards.sort(function (a, b) {
      var first = a.getAttribute("data-id"), second = b.getAttribute("data-id");
      return candidates ? Number(first) - Number(second) : order[first] - order[second];
    });
    flip(function () {
      resetColumns(want);
      cards.forEach(function (card) { placeInColumn(card); });
      holdAnchor();
    });
  }
