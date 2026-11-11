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
    if (restored && restored !== document.activeElement) restored.focus({ preventScroll: true });
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
