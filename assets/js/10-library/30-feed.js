  var FEED_SOURCE_NAMES = { commons: "Wikimedia Commons", met: "The Met", arena: "Are.na", tumblr: "Tumblr", pinterest: "Pinterest" };

  // Names the discover view's exit icon for screen readers and hover.
  function setExitLabel(text) {
    var exit = $("#find-exit");
    exit.setAttribute("aria-label", text);
    exit.setAttribute("data-tooltip", text);
  }

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
    if (!pulled.enabled.length || !pulled.jobs) return "Discover pulls from the Are.na channels, Pinterest boards and Tumblr blogs on your followed list. Add one with the sliders icon.";
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
      setExitLabel("Back to library");
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
    var cardIds = selectedIds();
    Promise.resolve(bridge.accept_feed(ids, setId || null)).then(function (result) {
      if (!result || !result.ok) { toast("error", "Could not save those images."); return; }
      toast("success", "Saved " + ids.length + (ids.length === 1 ? " image." : " images."));
      refreshStats();
      changed();
      return playDiscard(cardIds, true).then(reloadFeed);
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
        flip(function () {
          showFeed({ items: items, total: result.total, loaded: result.items.length }, "", true);
          host.scrollTop = top;
        });
      });
    }).catch(function () {});
  }

  function leaveCandidates() {
    if (!candidates) return;
    candidates = null;
    syncMore();
    findTicket++;
    $("#find-refresh").hidden = true;
    setExitLabel("Back to set");
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
    var chosen = selectedIds().sort(function (a, b) { return a - b; }).map(function (index) { return candidates.candidates[index]; });
    var urls = chosen.map(function (item) { return item.url; });
    var details = {};
    chosen.forEach(function (item) {
      if (item.source_service || item.title) details[item.url] = { page_url: item.page_url, source_service: item.source_service, source_ref: item.source_ref, collection: item.collection, title: item.title, creator: item.creator };
    });
    Promise.resolve(bridge.add_discovered(urls, candidates.page_url, state.setId, details)).then(function (result) {
      if (!result || !result.ok) { toast("error", "Could not add those images."); return; }
      toast("success", "Added " + result.placed + (result.placed === 1 ? " image." : " images."));
      leaveCandidates();
      load(true);
      refreshStats();
      changed();
    }).catch(function () { toast("error", "Could not add those images."); });
  }
