/* === Hyperbridge: library grid === */
(function () {
  "use strict";

  var PAGE_SIZE = 60;
  var MAX_REFRESH = 200;
  var POLL_MS = 2000;
  var CASCADE_MAX = 12;
  var SEARCH_DEBOUNCE_MS = 250;

  var state = { query: "", tag: "", color: "", setId: null, group: "", order: "", years: [], entries: [], total: 0, loading: false, ticket: 0, signature: "", pendingIds: {}, cascade: false };
  var grid, emptyEl, sentinel, searchInput, urlInput, submitBtn, errorEl;
  var setsCache = [];
  var tagsCache = [];
  var selected = new Set();
  var anchorId = null;
  var searchTimer = null;
  var pollTimer = null;
var candidates = null;
  var finding = false;
  var feedObserver = null;
  var findTicket = 0;
  var SKELETON_RATIOS = ["4 / 5", "1 / 1", "3 / 4", "5 / 4", "2 / 3", "1 / 1", "4 / 3", "3 / 4"];

  function api() { return window.pywebview && window.pywebview.api; }

  function makeEl(tag, className, text) {
    var el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  }

  // Placeholder for a capture in flight: a breathing glow and a label.
  function buildPending() {
    var panel = makeEl("span", "library-pending");
    var icon = makeEl("span", "library-pending-icon");
    icon.setAttribute("role", "img");
    icon.setAttribute("aria-label", "Capturing");
    icon.innerHTML = '<svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14"/><path d="M12 5v14"/></svg>';
    panel.appendChild(icon);
    return panel;
  }

  // Builds one entry card as a focusable button that announces its id on click.
  function buildCard(entry, reveal) {
    var card = makeEl("button", "library-card");
    card.type = "button";
    card.setAttribute("data-id", entry.id);
    card.setAttribute("aria-label", "Open " + (entry.title || entry.domain || "entry"));

    if (entry.thumb) {
      var img = document.createElement("img");
      img.className = "library-card-image";
      img.src = entry.thumb;
      img.alt = "";
      img.loading = "lazy";
      if (entry.width && entry.height) img.style.aspectRatio = entry.width + " / " + entry.height;
      if (reveal) {
        // A capture that just finished fades its image in instead of popping.
        img.classList.add("library-card-reveal");
        var show = function () { img.classList.add("is-loaded"); };
        img.addEventListener("load", show);
        img.addEventListener("error", show);
        if (img.complete) requestAnimationFrame(show);
      }
      card.appendChild(img);
    } else if (entry.state === "pending") {
      card.appendChild(buildPending());
      card.setAttribute("data-pending", "true");
    } else {
      card.appendChild(makeEl("span", "library-thumb-empty"));
    }

    if (entry.state === "failed") {
      card.appendChild(makeEl("span", "library-card-flag library-failed status-chip status-chip-outlined-accent", "Failed"));
    }

    var body = makeEl("span", "library-card-details");
    body.appendChild(makeEl("span", "library-card-title", entry.title || "Untitled"));
    var caption = (entry.caption || []).join(" / ");
    if (caption) body.appendChild(makeEl("span", "library-card-caption", caption));
    else if (entry.domain) body.appendChild(makeEl("span", "library-card-domain", entry.domain));
    card.appendChild(body);

    if (selected.has(entry.id)) card.setAttribute("data-selected", "true");
    card.addEventListener("click", function (event) { onCardClick(event, entry.id); });
    return card;
  }

  // Builds a candidate card for an image found on a pasted page; clicking always toggles its selection.
  function buildCandidate(item, index) {
    var card = makeEl("button", "library-card");
    card.type = "button";
    card.setAttribute("data-id", index);
    card.setAttribute("aria-label", "Select image " + (index + 1));
    var img = document.createElement("img");
    img.className = "library-card-image";
    img.src = item.thumb;
    img.alt = "";
    if (item.width && item.height) img.style.aspectRatio = item.width + " / " + item.height;
    card.appendChild(img);
    if (item.known_entry_id) card.appendChild(makeEl("span", "library-card-flag status-chip status-chip-outlined-accent", "Saved"));
    var details = card.appendChild(makeEl("span", "library-card-details"));
    if (item.feedId) {
      if (item.title) details.appendChild(makeEl("span", "library-card-title", item.title));
      details.appendChild(makeEl("span", "library-card-domain", item.creator || item.source));
    } else {
      details.appendChild(makeEl("span", "library-card-domain", item.width + " x " + item.height));
    }
    if (selected.has(index)) card.setAttribute("data-selected", "true");
    card.addEventListener("click", function (event) {
      if (event.shiftKey && anchorId !== null) selectRange(index);
      else toggleSelected(index);
    });
    return card;
  }

  function hostOf(pageUrl) {
    try { return new URL(pageUrl).hostname.replace(/^www\./, ""); } catch (err) { return pageUrl; }
  }

  // Opens the find view straight away with placeholder tiles while the page is read.
  function showFinding(pageUrl) {
    candidates = { page_url: pageUrl, candidates: [] };
    clearSelection();
    emptyEl.hidden = true;
    $("#library-meta").hidden = true;
    grid.textContent = "";
    var fragment = document.createDocumentFragment();
    for (var i = 0; i < 12; i++) {
      var tile = makeEl("div", "library-card loading-skeleton");
      tile.style.aspectRatio = SKELETON_RATIOS[i % SKELETON_RATIOS.length];
      fragment.appendChild(tile);
    }
    grid.appendChild(fragment);
    grid.setAttribute("aria-busy", "true");
    $("#library").setAttribute("data-finding", "true");
    $("#find-head").hidden = false;
    $("#find-head-title").textContent = hostOf(pageUrl);
    $("#find-head-desc").textContent = "Finding images...";
  }

  // Replaces the placeholder tiles with the images found on the page, for choosing which join the open set.
  function showCandidates(result) {
    candidates = result;
    grid.removeAttribute("aria-busy");
    clearSelection();
    emptyEl.hidden = true;
    grid.textContent = "";
    var fragment = document.createDocumentFragment();
    result.candidates.forEach(function (item, index) { fragment.appendChild(buildCandidate(item, index)); });
    grid.appendChild(fragment);
    cascadeIn();
    var host = hostOf(result.page_url);
    var count = result.candidates.length;
    $("#find-head-title").textContent = result.title || host;
    $("#find-head-desc").textContent = count + (count === 1 ? " image" : " images") + " found on " + host + ". Select the ones to add to this set.";
    if (!result.candidates.length) {
      emptyEl.textContent = "No usable images found. Pages that load images with scripts, such as Pinterest boards, are not readable yet.";
      emptyEl.hidden = false;
    }
  }

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
  var FEED_SOURCE_NAMES = { commons: "Wikimedia Commons", met: "The Met", arena: "Are.na", tumblr: "Tumblr" };

  function feedCandidate(item) {
    return { feedId: item.id, url: item.url, thumb: item.thumb || item.url, width: item.width, height: item.height,
      title: item.title, creator: item.creator, source: FEED_SOURCE_NAMES[item.source_id] || item.source_id, known_entry_id: null };
  }

  // Loads every thumbnail off-screen first so cards enter the grid at their final size; images that fail are dropped.
  function preloadFeed(items) {
    return Promise.all(items.map(function (item) {
      return new Promise(function (resolve) {
        var probe = new Image();
        var timer = setTimeout(function () { resolve(null); }, FEED_PRELOAD_MS);
        probe.onload = function () {
          clearTimeout(timer);
          item.width = probe.naturalWidth;
          item.height = probe.naturalHeight;
          resolve(item);
        };
        probe.onerror = function () { clearTimeout(timer); resolve(null); };
        probe.src = item.thumb || item.url;
      });
    })).then(function (list) { return list.filter(Boolean); });
  }

  function feedCount() {
    var count = candidates.total;
    $("#find-head-desc").textContent = count + (count === 1 ? " new image" : " new images") + " from your sources. Select the ones to save or dismiss.";
  }

  // Adds the next page of feed images when the grid end nears; at the end of the stored list it pulls from the sources first.
  function loadMoreFeed() {
    var bridge = api();
    if (!candidates || !candidates.feed || candidates.busy || candidates.finished || !candidates.candidates.length) return;
    var ticket = findTicket;
    var current = candidates;
    current.busy = true;
    syncMore();
    var tail = [];
    for (var i = 0; i < 8; i++) {
      var tile = makeEl("div", "library-card loading-skeleton");
      tile.style.aspectRatio = SKELETON_RATIOS[i % SKELETON_RATIOS.length];
      tail.push(tile);
      placeInColumn(tile);
    }
    var more = current.loaded < current.total
      ? Promise.resolve(bridge.list_feed(current.loaded, PAGE_SIZE))
      : Promise.resolve(bridge.refresh_feed()).then(function () { return bridge.list_feed(current.loaded, PAGE_SIZE); });
    more.then(function (result) {
      if (ticket !== findTicket || candidates !== current) return null;
      if (!result.items.length) current.finished = true;
      current.loaded += result.items.length;
      current.total = result.total;
      return preloadFeed(result.items);
    }).then(function (items) {
      if (!items || ticket !== findTicket || candidates !== current) return;
      // Each new card takes the place of a skeleton tile so the columns do not reflow.
      items.forEach(function (item, position) {
        current.candidates.push(feedCandidate(item));
        var card = buildCandidate(current.candidates[current.candidates.length - 1], current.candidates.length - 1);
        card.style.setProperty("--cascade-index", Math.min(position, CASCADE_MAX));
        card.classList.add("library-cascade");
        var slot = tail.shift();
        if (slot) slot.replaceWith(card);
        else placeInColumn(card);
      });
    }).catch(function () { current.finished = true; }).then(function () {
      tail.forEach(function (tile) { tile.remove(); });
      current.busy = false;
      if (candidates !== current) return;
      if (current.finished && current.manual) toast("info", "Nothing new from your sources right now.");
      current.manual = false;
      syncMore();
      if (!current.finished && feedObserver) { feedObserver.unobserve(sentinel); feedObserver.observe(sentinel); }
    });
  }

  // Shows the Discover more button once the feed has run out of images to add.
  function syncMore() {
    var button = $("#library-more");
    if (button) button.hidden = !(candidates && candidates.feed && candidates.finished && !candidates.busy && candidates.candidates.length);
  }

  function discoverMore() {
    if (!candidates || !candidates.feed || candidates.busy) return;
    candidates.finished = false;
    candidates.manual = true;
    syncMore();
    loadMoreFeed();
  }

  function feedMessage(text) {
    emptyEl.textContent = text;
    emptyEl.hidden = !text;
  }

  // Paints the feed's unseen images in the grid; choosing some saves or dismisses them.
  function showFeed(result, note, quiet) {
    candidates = { feed: true, page_url: "", total: result.total, loaded: result.loaded || result.items.length, busy: false, finished: false, candidates: result.items.map(feedCandidate) };
    grid.removeAttribute("aria-busy");
    clearSelection();
    resetColumns();
    candidates.candidates.forEach(function (item, index) { placeInColumn(buildCandidate(item, index)); });
    if (!quiet) cascadeIn();
    feedCount();
    var count = result.total;
    feedMessage(count ? "" : (note || "Nothing new yet. Tag or group some images to steer the feed, then refresh."));
  }

  // Names why a refresh brought nothing: no sources, nothing to pull from, or sources unreachable.
  function refreshNote(pulled) {
    if (!pulled || !pulled.ok) return "Could not refresh the feed.";
    if (!pulled.enabled.length || !pulled.jobs) return "Discover pulls from the Are.na channels and Tumblr blogs on your followed list. Add one with the sliders icon.";
    if (pulled.failed >= pulled.jobs) return "Could not reach the sources. Check the internet connection and refresh.";
    return "";
  }

  function showFeedLoading() {
    candidates = { feed: true, page_url: "", candidates: [] };
    syncMore();
    clearSelection();
    feedMessage("");
    $("#library-meta").hidden = true;
    resetColumns();
    for (var i = 0; i < 12; i++) {
      var tile = makeEl("div", "library-card loading-skeleton");
      tile.style.aspectRatio = SKELETON_RATIOS[i % SKELETON_RATIOS.length];
      placeInColumn(tile);
    }
    grid.setAttribute("aria-busy", "true");
    $("#find-head-desc").textContent = "Finding images...";
  }

  // Opens the Discover feed; it pulls from the sources first when it is empty or out of date.
  function openFeed(forceRefresh) {
    var bridge = api();
    if (!bridge || !bridge.list_feed) return;
    var ticket = ++findTicket;
    if (!candidates || !candidates.feed) {
      state.setId = null;
      setFinding(false);
      $("#dock-find").hidden = true;
      renderFilter();
      emptyEl.hidden = true;
      $("#library").setAttribute("data-finding", "true");
      $("#find-head").hidden = false;
      $("#find-head-title").textContent = "Discover";
      $("#find-exit").textContent = "Back to library";
      $("#find-refresh").hidden = false;
    }
    showFeedLoading();
    var sourcesOff = "";
    Promise.resolve(bridge.list_feed(0, PAGE_SIZE)).then(function (first) {
      if (ticket !== findTicket) return null;
      if (!forceRefresh && first.total && !first.stale) return first;
      return Promise.resolve(bridge.refresh_feed(true)).then(function (pulled) {
        if (ticket !== findTicket) return null;
        sourcesOff = refreshNote(pulled);
        return bridge.list_feed(0, PAGE_SIZE);
      });
    }).then(function (result) {
      if (!result || ticket !== findTicket) return null;
      return preloadFeed(result.items).then(function (items) {
        if (ticket !== findTicket) return;
        showFeed({ items: items, total: result.total, loaded: result.items.length },
          sourcesOff);
      });
    }).catch(function () {
      if (ticket !== findTicket) return;
      showFeed({ items: [], total: 0 }, "Could not load the feed.");
    });
  }

  function feedIdsOfSelection() {
    return selectedIds().sort(function (a, b) { return a - b; }).map(function (index) { return candidates.candidates[index].feedId; });
  }

  // Saves the selected feed images to the library, placing them in a set when one is given.
  function acceptFeed(setId) {
    var bridge = api();
    if (!candidates || !candidates.feed || !selected.size) return;
    var ids = feedIdsOfSelection();
    Promise.resolve(bridge.accept_feed(ids, setId || null)).then(function (result) {
      if (!result || !result.ok) { toast("error", "Could not save those images."); return; }
      toast("success", "Saved " + ids.length + (ids.length === 1 ? " image." : " images."));
      refreshStats();
      changed();
      reloadFeed();
    }).catch(function () { toast("error", "Could not save those images."); });
  }

  function dismissFeed() {
    var bridge = api();
    if (!candidates || !candidates.feed || !selected.size) return;
    var ids = feedIdsOfSelection();
    Promise.resolve(bridge.dismiss_feed(ids)).then(function () {
      toast("success", "Dismissed " + ids.length + ".");
      reloadFeed();
    }).catch(function () { toast("error", "Could not dismiss."); });
  }

  // Redraws the feed after a save or dismiss without a skeleton pass, keeping the scroll position.
  function reloadFeed() {
    var bridge = api();
    var ticket = ++findTicket;
    var shown = candidates ? Math.max(candidates.loaded, PAGE_SIZE) : PAGE_SIZE;
    var host = $("#library");
    var top = host.scrollTop;
    Promise.resolve(bridge.list_feed(0, shown)).then(function (result) {
      if (ticket !== findTicket || !candidates || !candidates.feed) return null;
      return preloadFeed(result.items).then(function (items) {
        if (ticket !== findTicket || !candidates || !candidates.feed) return;
        showFeed({ items: items, total: result.total, loaded: result.items.length }, "", true);
        host.scrollTop = top;
      });
    }).catch(function () {});
  }

  function leaveCandidates() {
    if (!candidates) return;
    candidates = null;
    syncMore();
    findTicket++;
    $("#find-refresh").hidden = true;
    $("#find-exit").textContent = "Back to set";
    grid.removeAttribute("data-columns");
    grid.textContent = "";
    grid.removeAttribute("aria-busy");
    $("#library").removeAttribute("data-finding");
    $("#find-head").hidden = true;
    clearSelection();
    state.signature = null;
    state.signatureParts = [];
    state.cascade = true;
    renderFilter();
    render();
  }

  function setFinding(on) {
    finding = on;
    $("#dock-find").setAttribute("aria-pressed", on ? "true" : "false");
    $("#dock-find").toggleAttribute("data-active", on);
    searchInput.placeholder = on ? "Paste a page link to browse its images" : "Paste a link or search";
    $("#capture-form").setAttribute("data-mode", on ? "link" : "search");
    if (on) searchInput.focus();
  }

  function discoverPage(url) {
    var bridge = api();
    submitBtn.disabled = true;
    var ticket = ++findTicket;
    urlInput.value = "";
    setFinding(false);
    showFinding(url);
    function fail(message) {
      if (ticket !== findTicket) return;
      grid.removeAttribute("aria-busy");
      grid.textContent = "";
      $("#find-head-desc").textContent = "Nothing to show.";
      emptyEl.textContent = message;
      emptyEl.hidden = false;
    }
    Promise.resolve(bridge.discover_images(url)).then(function (result) {
      if (ticket !== findTicket) return;
      if (!result || !result.ok) fail(result && result.error ? result.error : "Could not read that page.");
      else showCandidates(result);
    }).catch(function () { fail("Could not read that page."); }).then(function () { submitBtn.disabled = false; });
  }

  function acceptCandidates() {
    var bridge = api();
    if (candidates && candidates.feed) { acceptFeed(state.setId); return; }
    if (!candidates || !state.setId || !selected.size) return;
    var urls = selectedIds().sort(function (a, b) { return a - b; }).map(function (index) { return candidates.candidates[index].url; });
    Promise.resolve(bridge.add_discovered(urls, candidates.page_url, state.setId)).then(function (result) {
      if (!result || !result.ok) { toast("error", "Could not add those images."); return; }
      toast("success", "Added " + result.placed + (result.placed === 1 ? " image." : " images."));
      leaveCandidates();
      load(true);
      refreshStats();
      changed();
    }).catch(function () { toast("error", "Could not add those images."); });
  }

  function partOf(entry) {
    return [entry.id, entry.state, entry.title, entry.domain, entry.group, entry.thumb ? 1 : 0, (entry.caption || []).join("/")].join("|");
  }

  function renderEmpty() {
    if (state.entries.length) {
      emptyEl.hidden = true;
      return;
    }
    emptyEl.textContent = state.query || state.tag || state.color ? "No matches." : "No entries.";
    emptyEl.hidden = false;
  }

  // Shows the active tag and color as chips that clear their filter when clicked.
  function renderFilter() {
    var box = $("#library-filter");
    var chip = $("#library-filter-chip");
    var colorChip = $("#library-filter-color");
    if (!box || !chip || !colorChip) return;
    box.hidden = !state.tag && !state.color;
    chip.hidden = !state.tag;
    chip.textContent = state.tag ? "Tag: " + state.tag + " x" : "";
    colorChip.hidden = !state.color;
    colorChip.textContent = state.color ? "Color: " + state.color + " x" : "";
  }

  function setColor(color) {
    state.color = color || "";
    state.cascade = true;
    renderFilter();
    clearSelection();
    load(true);
  }

  function setTag(tag) {
    state.tag = tag || "";
    state.cascade = true;
    renderFilter();
    clearSelection();
    load(true);
  }

  // Right-aligned count and year range above the grid while a set is open.
  function renderMeta() {
    var meta = $("#library-meta");
    if (!meta) return;
    var show = state.setId !== null && state.total > 0;
    meta.hidden = !show;
    if (!show) return;
    var years = state.years;
    var span = years.length === 2 ? (years[0] === years[1] ? years[0] : years[0] + "-" + years[1]) : "";
    meta.textContent = state.total + (state.total === 1 ? " entry" : " entries") + (span ? " - " + span : "");
  }

  // Animates a finished card from the pending tile's height to its own, so the grid eases instead of jumping.
  function growCard(item) {
    var card = item.card;
    card.style.height = "auto";
    var target = card.offsetHeight;
    if (!item.from || item.from === target) { card.style.height = ""; return; }
    card.style.height = item.from + "px";
    void card.offsetHeight;
    card.classList.add("library-card-grow");
    card.style.height = target + "px";
    var done = function () { card.classList.remove("library-card-grow"); card.style.height = ""; };
    if (parseFloat(getComputedStyle(card).transitionDuration) === 0) { done(); return; }
    card.addEventListener("transitionend", function (event) { if (event.propertyName === "height") done(); });
  }

  // Fades the rebuilt grid in as a cascade, ordered by on-screen position (rows, then columns).
  function cascadeIn() {
    var nodes = grid.hasAttribute("data-columns") ? grid.querySelectorAll(".library-grid-column > *") : grid.children;
    var items = Array.prototype.slice.call(nodes).map(function (el) {
      var rect = el.getBoundingClientRect();
      return { el: el, top: Math.round(rect.top), left: Math.round(rect.left) };
    });
    items.sort(function (a, b) { return a.top - b.top || a.left - b.left; });
    items.forEach(function (item, index) {
      item.el.style.setProperty("--cascade-index", Math.min(index, CASCADE_MAX));
      item.el.classList.add("library-cascade");
    });
  }

  // Builds the card for an entry; a capture that just finished remembers the pending tile's height to grow from.
  function makeCard(entry, grown) {
    var reveal = !!state.pendingIds[entry.id] && !!entry.thumb;
    var card = buildCard(entry, reveal);
    if (reveal && entry.width && entry.height) {
      var old = grid.querySelector('[data-id="' + entry.id + '"]');
      if (old) grown.push({ card: card, from: old.offsetHeight });
    }
    return card;
  }

  function restoreFocus(focusedId) {
    var restored = focusedId ? grid.querySelector('[data-id="' + focusedId + '"]') : null;
    if (restored) restored.focus();
  }

  // Redraws every card: fixed columns normally, sectioned CSS columns while grouped.
  function rebuildGrid() {
    var active = document.activeElement;
    var focusedId = active && active.getAttribute ? active.getAttribute("data-id") : null;
    var grown = [];
    var cards = state.entries.map(function (entry) { return makeCard(entry, grown); });
    if (state.group) {
      var fragment = document.createDocumentFragment();
      var lastGroup = null;
      state.entries.forEach(function (entry, index) {
        if (entry.group !== lastGroup) {
          fragment.appendChild(makeEl("h2", "library-group", entry.group));
          lastGroup = entry.group;
        }
        fragment.appendChild(cards[index]);
      });
      grid.removeAttribute("data-columns");
      grid.textContent = "";
      grid.appendChild(fragment);
    } else {
      resetColumns();
      cards.forEach(function (card) { placeInColumn(card); });
    }
    grown.forEach(growCard);
    if (state.cascade) cascadeIn();
    restoreFocus(focusedId);
  }

  // Applies a list change to the cards already shown: removed ones leave, changed ones swap in place, new ones join a column. Nothing else changes column.
  function patchGrid() {
    var current = {};
    grid.querySelectorAll(".library-card[data-id]").forEach(function (card) { current[card.getAttribute("data-id")] = card; });
    var wanted = {};
    var lastKept = -1;
    state.entries.forEach(function (entry, index) {
      wanted[entry.id] = true;
      if (current[entry.id]) lastKept = index;
    });
    var active = document.activeElement;
    var focusedId = active && active.getAttribute ? active.getAttribute("data-id") : null;
    var grown = [];
    flip(function () {
      Object.keys(current).forEach(function (id) { if (!wanted[id]) current[id].remove(); });
      state.entries.forEach(function (entry, index) {
        var card = current[entry.id];
        if (card && state.partById[entry.id] === partOf(entry)) return;
        var fresh = makeCard(entry, grown);
        if (card) card.replaceWith(fresh);
        else placeInColumn(fresh, index < lastKept);
      });
      grown.forEach(growCard);
    });
    restoreFocus(focusedId);
  }

  function render() {
    if (candidates) return;
    var parts = state.entries.map(partOf);
    var signature = parts.join(";");
    if (signature !== state.signature) {
      var patchable = !state.group && !state.cascade && state.signatureParts && state.signatureParts.length > 0 && grid.hasAttribute("data-columns");
      if (patchable) patchGrid();
      else rebuildGrid();
      var nextPending = {};
      var partById = {};
      state.entries.forEach(function (entry, index) {
        if (entry.state === "pending") nextPending[entry.id] = true;
        partById[entry.id] = parts[index];
      });
      state.pendingIds = nextPending;
      state.partById = partById;
      state.signature = signature;
      state.signatureParts = parts;
    }
    state.cascade = false;
    renderEmpty();
    renderMeta();
    updatePolling();
  }

  // Fetches a page. reset replaces the list; otherwise the page is appended.
  function load(reset) {
    var bridge = api();
    if (!bridge || !bridge.list_entries || candidates) return Promise.resolve();
    if (state.loading && !reset) return Promise.resolve();
    var ticket = ++state.ticket;
    var offset = reset ? 0 : state.entries.length;
    state.loading = true;
    return bridge.list_entries(state.query, offset, PAGE_SIZE, state.setId, state.group, state.tag, state.color, state.order).then(function (result) {
      if (ticket !== state.ticket) return;
      state.total = result.total;
      state.years = result.years || [];
      state.entries = reset ? result.entries : state.entries.concat(result.entries);
      render();
    }).catch(function () {}).then(function () {
      if (ticket === state.ticket) state.loading = false;
    });
  }

  // Re-reads everything loaded so far so pending entries pick up their new state.
  function refresh() {
    var bridge = api();
    if (!bridge || !bridge.list_entries || state.loading || candidates) return;
    var ticket = ++state.ticket;
    var limit = Math.min(Math.max(state.entries.length, PAGE_SIZE), MAX_REFRESH);
    var tail = state.entries.slice(limit);
    var knownTotal = state.total;
    state.loading = true;
    bridge.list_entries(state.query, 0, limit, state.setId, state.group, state.tag, state.color, state.order).then(function (result) {
      if (ticket !== state.ticket) return;
      state.total = result.total;
      state.years = result.years || [];
      // Entries past the server page cap are kept as loaded unless the list changed size.
      state.entries = tail.length && result.total === knownTotal ? result.entries.concat(tail) : result.entries;
      render();
    }).catch(function () {}).then(function () {
      if (ticket === state.ticket) state.loading = false;
    });
  }

  function updatePolling() {
    var anyPending = state.entries.some(function (entry) { return entry.state === "pending"; });
    if (anyPending && !pollTimer) {
      pollTimer = setInterval(refresh, POLL_MS);
    } else if (!anyPending && pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function refreshStats() {
    var bridge = api();
    if (bridge && bridge.get_stats && window.renderStats) {
      Promise.resolve(bridge.get_stats()).then(window.renderStats);
    }
  }

  function showError(message) {
    errorEl.textContent = message || "";
    errorEl.hidden = !message;
  }

  function toast(variant, message) {
    if (window.HvToast) window.HvToast.show({ variant: variant, message: message });
  }

  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function reportSave(result) {
    var status = result && result.status;
    if (status === "saved") toast("success", result.count > 1 ? "Saved " + result.count + " files." : "Saved.");
    else if (status === "cancelled") toast("info", "Cancelled.");
    else toast("error", "Could not save images.");
  }

  function changed() {
    document.dispatchEvent(new CustomEvent("hyperbridge:changed"));
  }

  function loadTags() {
    var bridge = api();
    if (!bridge || !bridge.list_tags) return;
    Promise.resolve(bridge.list_tags()).then(function (list) { tagsCache = list || []; paintSelection(); }).catch(function () {});
  }

  function loadSets() {
    var bridge = api();
    if (!bridge || !bridge.list_sets) return;
    Promise.resolve(bridge.list_sets()).then(function (list) { setsCache = list || []; paintSelection(); }).catch(function () {});
  }

  function openSource(id) {
    var bridge = api();
    if (!bridge || !bridge.get_entry) return;
    Promise.resolve(bridge.get_entry(id)).then(function (entry) {
      if (!entry || !entry.source_url) return;
      var link = document.createElement("a");
      link.href = entry.source_url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.click();
    });
  }

  function placeIn(entryId, item) {
    var bridge = api();
    Promise.resolve(bridge.place_entry(entryId, item.id)).then(function (ok) {
      if (ok) {
        toast("success", "Placed.");
        changed();
      } else {
        toast("error", "Could not place.");
      }
    }).catch(function () { toast("error", "Could not place."); });
  }

  var DISCARD_ICON = '<svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>';

  // Glows a card red with an x, then collapses it to nothing; resolves when the card is gone.
  function playDiscardCard(card) {
    return new Promise(function (resolve) {
      var mark = makeEl("span", "library-discard-mark");
      mark.innerHTML = DISCARD_ICON;
      card.appendChild(mark);
      card.classList.add("library-card-discarding");
      if (getComputedStyle(mark).animationName === "none") { resolve(); return; }
      mark.addEventListener("animationend", function () {
        card.style.height = card.offsetHeight + "px";
        void card.offsetHeight;
        card.classList.add("library-card-collapse");
        card.style.height = "0px";
        if (parseFloat(getComputedStyle(card).transitionDuration) === 0) { resolve(); return; }
        card.addEventListener("transitionend", function (event) { if (event.propertyName === "height") resolve(); });
      });
    });
  }

  function playDiscard(ids) {
    var cards = ids.map(function (id) { return grid.querySelector('[data-id="' + id + '"]'); }).filter(Boolean);
    return Promise.all(cards.map(playDiscardCard));
  }

  function afterDiscard() {
    load(true);
    refreshStats();
    changed();
  }

  function discard(entry) {
    var bridge = api();
    Promise.resolve(bridge.discard_entry(entry.id)).then(function (ok) {
      if (ok) {
        toast("success", "Discarded " + (entry.title || entry.domain || "entry") + ".");
        playDiscard([entry.id]).then(afterDiscard);
      } else {
        toast("error", "Could not discard.");
      }
    }).catch(function () { toast("error", "Could not discard."); });
  }

  // Selection: Ctrl/Cmd-click toggles, Shift-click selects a range, and any click toggles while a selection exists.
  function paintSelection() {
    grid.querySelectorAll(".library-card").forEach(function (card) {
      if (selected.has(Number(card.getAttribute("data-id")))) card.setAttribute("data-selected", "true");
      else card.removeAttribute("data-selected");
    });
    $("#select-bar").hidden = !selected.size;
    $("#select-count").textContent = selected.size + " selected";
    var picking = !!candidates;
    $("#sel-accept").hidden = !picking;
    $("#sel-remove").hidden = picking || !state.setId;
    var feedMode = picking && candidates.feed;
    $("#sel-add").hidden = (picking && !feedMode) || !setsCache.length;
    $("#sel-tag").hidden = picking || !tagsCache.length;
    $("#sel-save").hidden = picking;
    $("#sel-discard").hidden = picking && !feedMode;
  }

  function clearSelection() {
    if (!selected.size) return;
    selected.clear();
    anchorId = null;
    paintSelection();
  }

  function toggleSelected(id) {
    if (selected.has(id)) selected.delete(id);
    else selected.add(id);
    anchorId = id;
    paintSelection();
  }

  function visibleIds() {
    if (candidates) return candidates.candidates.map(function (item, index) { return index; });
    return state.entries.map(function (entry) { return entry.id; });
  }

  function selectRange(id) {
    var ids = visibleIds();
    var from = ids.indexOf(anchorId);
    var to = ids.indexOf(id);
    if (from < 0 || to < 0) {
      toggleSelected(id);
      return;
    }
    ids.slice(Math.min(from, to), Math.max(from, to) + 1).forEach(function (item) { selected.add(item); });
    paintSelection();
  }

  function onCardClick(event, id) {
    if (event.shiftKey && anchorId !== null) selectRange(id);
    else if (event.shiftKey || event.ctrlKey || event.metaKey || selected.size) toggleSelected(id);
    else document.dispatchEvent(new CustomEvent("hyperbridge:open", { detail: { id: id } }));
  }

  function selectedIds() { return Array.from(selected); }

  // Runs a bridge call per selected id and reports how many succeeded.
  function bulk(call, done) {
    var ids = selectedIds();
    return Promise.all(ids.map(function (id) {
      return Promise.resolve(call(id)).then(function (ok) { return !!ok; }).catch(function () { return false; });
    })).then(function (results) {
      done(results.filter(Boolean).length, ids.length);
    });
  }

  function bulkPlace(item) {
    var bridge = api();
    bulk(function (id) { return bridge.place_entry(id, item.id); }, function (ok, total) {
      toast(ok === total ? "success" : "error", ok === total ? "Placed " + ok + "." : "Placed " + ok + " of " + total + ".");
      changed();
    });
  }

  function bulkTag(item) {
    var bridge = api();
    Promise.resolve(bridge.add_tags(selectedIds(), item.name)).then(function (count) {
      toast(count ? "success" : "error", count ? "Tagged " + count + "." : "Could not tag.");
      loadTags();
      changed();
    }).catch(function () { toast("error", "Could not tag."); });
  }

  function bulkRemove() {
    var bridge = api();
    var setId = state.setId;
    if (!setId) return;
    bulk(function (id) { return bridge.remove_entry(id, setId); }, function (ok) {
      toast("success", "Removed " + ok + ".");
      clearSelection();
      load(true);
      changed();
    });
  }

  function bulkSave() {
    var bridge = api();
    Promise.resolve(bridge.save_entries_assets(selectedIds())).then(reportSave).catch(function () { toast("error", "Could not save images."); });
  }

  function bulkDiscard() {
    if (candidates && candidates.feed) { dismissFeed(); return; }
    var bridge = api();
    var ids = selectedIds();
    bulk(function (id) { return bridge.discard_entry(id); }, function (ok, total) {
      toast(ok === total ? "success" : "error", ok === total ? "Discarded " + ok + "." : "Discarded " + ok + " of " + total + ".");
      clearSelection();
      (ok === total ? playDiscard(ids) : Promise.resolve()).then(afterDiscard);
    });
  }

  function setMenuItems() {
    return setsCache.map(function (item) {
      return { label: escapeHtml(item.name), action: function () {
        if (candidates && candidates.feed) acceptFeed(item.id);
        else bulkPlace(item);
      } };
    });
  }

  function tagMenuItems() {
    return tagsCache.map(function (item) {
      return { label: escapeHtml(item.name), action: function () { bulkTag(item); } };
    });
  }

  function bulkMenuItems() {
    var items = [];
    if (setsCache.length) items.push({ label: "Add to set", children: setMenuItems() });
    if (tagsCache.length) items.push({ label: "Add tag", children: tagMenuItems() });
    if (state.setId) items.push({ label: "Remove from set", action: bulkRemove });
    items.push({ label: "Download", action: bulkSave });
    items.push({ separator: true });
    items.push({ label: "Discard " + selected.size, action: bulkDiscard });
    return items;
  }

  // Opens the menu just above the selection bar; it flips upward when there is no room below.
  function openSetMenu(event) {
    event.stopPropagation();
    var rect = event.currentTarget.getBoundingClientRect();
    event.currentTarget.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: rect.left, clientY: $("#select-bar").getBoundingClientRect().top - 8 }));
  }

  function setupSelection() {
    $("#sel-accept").addEventListener("click", acceptCandidates);
    $("#sel-add").addEventListener("click", openSetMenu);
    $("#sel-tag").addEventListener("click", openSetMenu);
    $("#sel-remove").addEventListener("click", bulkRemove);
    $("#sel-save").addEventListener("click", bulkSave);
    $("#sel-discard").addEventListener("click", bulkDiscard);
    $("#sel-clear").addEventListener("click", clearSelection);
    if (window.HvContextMenu) {
      window.HvContextMenu.register("#sel-add", setMenuItems);
      window.HvContextMenu.register("#sel-tag", tagMenuItems);
    }
    document.addEventListener("keydown", function (event) {
      if ($("#app").inert) return;
      var tag = event.target && event.target.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (event.key === "Escape") {
        if (selected.size) clearSelection();
        else if (candidates && candidates.feed) $("#sets-all").click();
        else if (candidates) leaveCandidates();
        else if (finding) setFinding(false);
      } else if ((event.ctrlKey || event.metaKey) && (event.key === "a" || event.key === "A")) {
        event.preventDefault();
        visibleIds().forEach(function (id) { selected.add(id); });
        paintSelection();
      }
    });
  }

  // Right-click menu for a grid card.
  function setupMenu() {
    if (!window.HvContextMenu) return;
    window.HvContextMenu.register(".library-card[data-id]", function (card) {
      var id = Number(card.getAttribute("data-id"));
      var entry = state.entries.find(function (item) { return item.id === id; });
      var bridge = api();
      if (!entry || !bridge) return [];
      if (selected.size > 1 && selected.has(id)) return bulkMenuItems();
      var items = [
        { label: "Open", action: function () { document.dispatchEvent(new CustomEvent("hyperbridge:open", { detail: { id: id } })); } },
        { label: "Open source", action: function () { openSource(id); } },
        { label: "Download", action: function () {
          Promise.resolve(bridge.save_entry_assets(id)).then(reportSave).catch(function () { toast("error", "Could not save images."); });
        } },
      ];
      if (setsCache.length) {
        items.push({
          label: "Add to set",
          children: setsCache.map(function (item) {
            return { label: escapeHtml(item.name), action: function () { placeIn(id, item); } };
          }),
        });
      }
      if (state.setId) {
        items.push({ label: "Remove from set", action: function () {
          Promise.resolve(bridge.remove_entry(id, state.setId)).then(function () { load(true); changed(); });
        } });
      }
      items.push({ separator: true });
      items.push({ label: "Discard", action: function () { discard(entry); } });
      return items;
    });
  }

  // Reads one pasted image file as base64 and creates an entry from it.
  function addPastedImage(file) {
    var bridge = api();
    if (!bridge || !bridge.add_image_data) return;
    var reader = new FileReader();
    reader.onload = function () {
      Promise.resolve(bridge.add_image_data(reader.result, file.name || "")).then(function (result) {
        if (!result || !result.ok) {
          toast("error", result && result.error ? result.error : "Could not add that image.");
          return;
        }
        toast("success", "Added image.");
        load(true);
        refreshStats();
      }).catch(function () { toast("error", "Could not add that image."); });
    };
    reader.readAsDataURL(file);
  }

  // Pasting an image from the clipboard adds it to the library; pasted text is left alone.
  function onPaste(event) {
    var lightbox = $("#lightbox");
    if (lightbox && lightbox.open) return;
    var items = event.clipboardData ? Array.prototype.slice.call(event.clipboardData.items) : [];
    var images = items.filter(function (item) { return item.kind === "file" && item.type.indexOf("image/") === 0; });
    if (!images.length) return;
    event.preventDefault();
    images.forEach(function (item) {
      var file = item.getAsFile();
      if (file) addPastedImage(file);
    });
  }

  function onSubmit(event) {
    event.preventDefault();
    var bridge = api();
    var url = urlInput.value.trim();
    if (!bridge || !bridge.add_link || !isLink(url) || submitBtn.disabled) return;
    showError("");
    if (finding && bridge.discover_images) {
      discoverPage(url);
      return;
    }
    submitBtn.disabled = true;
    bridge.add_link(url).then(function (result) {
      if (!result || !result.ok) {
        showError(result && result.error ? result.error : "Capture failed.");
        return;
      }
      urlInput.value = "";
      toast(result.already_captured ? "info" : "success", result.already_captured ? "Already captured." : "Captured.");
      if (!result.already_captured) {
        load(true);
        refreshStats();
      }
    }).catch(function () {
      showError("Capture failed.");
    }).then(function () {
      submitBtn.disabled = false;
    });
  }

  // A pasted link is a capture; any other text filters the library.
  function isLink(text) { return /^https?:\/\//i.test(text); }

  function onDockInput() {
    showError("");
    $("#capture-form").setAttribute("data-mode", isLink(searchInput.value.trim()) ? "link" : "search");
    clearTimeout(searchTimer);
    searchTimer = setTimeout(function () {
      var query = isLink(searchInput.value.trim()) ? "" : searchInput.value.trim();
      if (query === state.query) return;
      state.query = query;
      state.cascade = true;
      clearSelection();
      load(true);
    }, SEARCH_DEBOUNCE_MS);
  }

  function watchSentinel() {
    if (!("IntersectionObserver" in window)) return;
    var observer = new IntersectionObserver(function (observed) {
      if (!observed[0].isIntersecting) return;
      if (candidates) loadMoreFeed();
      else if (state.entries.length < state.total) load(false);
    }, { root: $("#library"), rootMargin: "400px" });
    feedObserver = observer;
    observer.observe(sentinel);
  }

  var GROUP_CHOICES = [["", "None"], ["color", "Color"], ["year", "Year"], ["source", "Source"]];
  var ORDER_CHOICES = [["", "Newest"], ["oldest", "Oldest"], ["title", "Title"], ["source", "Source"]];

  // The view button opens a menu with a Group by section and an Order section; both choices persist.
  function setupGroup() {
    var button = $("#group-toggle");
    if (!button) return;
    var menu = makeEl("div", "view-menu floating-panel");
    menu.setAttribute("role", "menu");
    menu.hidden = true;
    document.body.appendChild(menu);

    function read(key, choices) {
      var saved = "";
      try { saved = localStorage.getItem(key) || ""; } catch (err) { saved = ""; }
      return choices.some(function (choice) { return choice[0] === saved; }) ? saved : "";
    }

    function labelOf(choices, value) {
      return choices.filter(function (choice) { return choice[0] === value; })[0][1];
    }

    function paintButton() {
      var label = "View: group " + labelOf(GROUP_CHOICES, state.group).toLowerCase() + ", order " + labelOf(ORDER_CHOICES, state.order).toLowerCase();
      button.setAttribute("aria-label", label);
      button.setAttribute("data-tooltip", label);
      button.setAttribute("data-group", state.group);
      button.setAttribute("data-order", state.order);
    }

    function close() {
      if (menu.hidden) return;
      menu.hidden = true;
      button.setAttribute("aria-expanded", "false");
    }

    function choose(key, field, value) {
      try { localStorage.setItem(key, value); } catch (err) { /* ignore */ }
      state[field] = value;
      paintButton();
      state.signature = ""; state.signatureParts = [];
      state.cascade = true;
      load(true);
      build();
    }

    function section(title, key, field, choices) {
      menu.appendChild(makeEl("span", "view-menu-label", title));
      choices.forEach(function (choice) {
        var row = makeEl("button", "menu-item" + (state[field] === choice[0] ? " active" : ""));
        row.type = "button";
        row.setAttribute("role", "menuitemradio");
        row.setAttribute("aria-checked", state[field] === choice[0] ? "true" : "false");
        row.appendChild(makeEl("span", "menu-item-label", choice[1]));
        row.addEventListener("click", function () { choose(key, field, choice[0]); });
        menu.appendChild(row);
      });
    }

    function build() {
      menu.textContent = "";
      section("Group by", "hyperbridge-group", "group", GROUP_CHOICES);
      menu.appendChild(makeEl("div", "menu-item-separator"));
      section("Order", "hyperbridge-order", "order", ORDER_CHOICES);
    }

    function open() {
      build();
      menu.hidden = false;
      var rect = button.getBoundingClientRect();
      menu.style.bottom = (window.innerHeight - rect.top) + "px";
      menu.style.right = Math.max(0, window.innerWidth - rect.right) + "px";
      button.setAttribute("aria-expanded", "true");
    }

    state.group = read("hyperbridge-group", GROUP_CHOICES);
    state.order = read("hyperbridge-order", ORDER_CHOICES);
    button.setAttribute("aria-haspopup", "menu");
    button.setAttribute("aria-expanded", "false");
    paintButton();
    button.addEventListener("click", function (event) {
      event.stopPropagation();
      if (menu.hidden) open(); else close();
    });
    document.addEventListener("click", function (event) {
      if (!menu.hidden && !menu.contains(event.target)) close();
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !menu.hidden) { close(); button.focus(); }
    });
  }

  function init() {
    grid = $("#library-grid");
    emptyEl = $("#library-empty");
    sentinel = $("#library-sentinel");
    searchInput = $("#dock-input");
    urlInput = searchInput;
    submitBtn = $("#capture-submit");
    errorEl = $("#capture-error");
    if (!grid) return;

    $("#capture-form").addEventListener("submit", onSubmit);
    $("#library-filter-chip").addEventListener("click", function () { setTag(""); });
    $("#library-filter-color").addEventListener("click", function () { setColor(""); });
    document.addEventListener("hyperbridge:color", function (event) { setColor(event.detail.color); });
    $("#find-exit").addEventListener("click", function () {
      if (candidates && candidates.feed) $("#sets-all").click();
      else leaveCandidates();
    });
    $("#find-refresh").addEventListener("click", function () { openFeed(true); });
    $("#feed-more").addEventListener("click", discoverMore);
    document.addEventListener("hyperbridge:feed", function () { openFeed(false); });
    window.addEventListener("resize", function () {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(relayoutColumns, 150);
    });
    $("#dock-find").addEventListener("click", function () { setFinding(!finding); });
    document.addEventListener("hyperbridge:tag", function (event) { setTag(event.detail.tag); });
    document.addEventListener("paste", onPaste);
    document.addEventListener("hyperbridge:dropped", function (event) {
      var result = event.detail || {};
      if (result.added) toast("success", result.added > 1 ? "Added " + result.added + " images." : "Added image.");
      if (result.skipped) toast("info", result.skipped + (result.skipped > 1 ? " files were" : " file was") + " not an image.");
      if (result.added) { load(true); refreshStats(); }
    });
    searchInput.addEventListener("input", onDockInput);
    searchInput.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && searchInput.value) {
        searchInput.value = "";
        onDockInput();
      }
    });
    watchSentinel();
    setupSelection();
    setupGroup();
    document.addEventListener("hyperbridge:filter", function (event) {
      state.setId = event.detail.setId || null;
      leaveCandidates();
      setFinding(false);
      $("#dock-find").hidden = !state.setId;
      renderFilter();
      state.cascade = true;
      clearSelection();
      load(true);
    });
    document.addEventListener("hyperbridge:discarded", function (event) { playDiscard([event.detail.id]).then(afterDiscard); });
    document.addEventListener("hyperbridge:changed", function () {
      refresh();
      refreshStats();
      loadSets(); loadTags();
    });
    setupMenu();

    state.cascade = true;
    if (api()) {
      load(true);
      loadSets(); loadTags();
    } else {
      window.addEventListener("pywebviewready", function () { load(true); loadSets(); loadTags(); });
    }
  }

  init();
})();
