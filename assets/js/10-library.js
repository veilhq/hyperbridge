/* === Hyperbridge: library grid === */
(function () {
  "use strict";

  var PAGE_SIZE = 60;
  var POLL_MS = 2000;
  var SEARCH_DEBOUNCE_MS = 250;

  var state = { query: "", setId: null, entries: [], total: 0, loading: false, ticket: 0, signature: "" };
  var grid, emptyEl, sentinel, searchInput, urlInput, submitBtn, errorEl;
  var setsCache = [];
  var selected = new Set();
  var anchorId = null;
  var searchTimer = null;
  var pollTimer = null;

  function api() { return window.pywebview && window.pywebview.api; }

  function makeEl(tag, className, text) {
    var el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  }

  // Placeholder for a capture in flight: a morphing gradient, a label and the source domain.
  function buildPending(entry) {
    var panel = makeEl("span", "library-pending");
    panel.appendChild(makeEl("span", "library-pending-label", "Capturing"));
    if (entry.domain) panel.appendChild(makeEl("span", "library-pending-domain", entry.domain));
    return panel;
  }

  // Builds one entry card as a focusable button that announces its id on click.
  function buildCard(entry) {
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
      card.appendChild(img);
    } else if (entry.state === "pending") {
      card.appendChild(buildPending(entry));
      card.setAttribute("data-pending", "true");
    } else {
      card.appendChild(makeEl("span", "library-thumb-empty"));
    }

    if (entry.state === "failed") {
      card.appendChild(makeEl("span", "library-card-flag library-failed status-chip status-chip-outlined-accent", "Failed"));
    }

    var body = makeEl("span", "library-card-details");
    body.appendChild(makeEl("span", "library-card-title", entry.title || entry.domain || "Untitled"));
    if (entry.domain) body.appendChild(makeEl("span", "library-card-domain", entry.domain));
    card.appendChild(body);

    if (selected.has(entry.id)) card.setAttribute("data-selected", "true");
    card.addEventListener("click", function (event) { onCardClick(event, entry.id); });
    return card;
  }

  function signatureOf(entries) {
    return entries.map(function (entry) {
      return [entry.id, entry.state, entry.title, entry.domain, entry.thumb ? 1 : 0].join("|");
    }).join(";");
  }

  function renderEmpty() {
    if (state.entries.length) {
      emptyEl.hidden = true;
      return;
    }
    emptyEl.textContent = state.query ? "No matches." : "No entries.";
    emptyEl.hidden = false;
  }

  function render() {
    var signature = signatureOf(state.entries);
    if (signature !== state.signature) {
      state.signature = signature;
      var active = document.activeElement;
      var focusedId = active && active.getAttribute ? active.getAttribute("data-id") : null;
      var fragment = document.createDocumentFragment();
      state.entries.forEach(function (entry) { fragment.appendChild(buildCard(entry)); });
      grid.textContent = "";
      grid.appendChild(fragment);
      if (focusedId) {
        var restored = grid.querySelector('[data-id="' + focusedId + '"]');
        if (restored) restored.focus();
      }
    }
    renderEmpty();
    updatePolling();
  }

  // Fetches a page. reset replaces the list; otherwise the page is appended.
  function load(reset) {
    var bridge = api();
    if (!bridge || !bridge.list_entries) return Promise.resolve();
    if (state.loading && !reset) return Promise.resolve();
    var ticket = ++state.ticket;
    var offset = reset ? 0 : state.entries.length;
    state.loading = true;
    return bridge.list_entries(state.query, offset, PAGE_SIZE, state.setId).then(function (result) {
      if (ticket !== state.ticket) return;
      state.total = result.total;
      state.entries = reset ? result.entries : state.entries.concat(result.entries);
      render();
    }).catch(function () {}).then(function () {
      if (ticket === state.ticket) state.loading = false;
    });
  }

  // Re-reads everything loaded so far so pending entries pick up their new state.
  function refresh() {
    var bridge = api();
    if (!bridge || !bridge.list_entries || state.loading) return;
    var ticket = ++state.ticket;
    var limit = Math.max(state.entries.length, PAGE_SIZE);
    state.loading = true;
    bridge.list_entries(state.query, 0, limit, state.setId).then(function (result) {
      if (ticket !== state.ticket) return;
      state.total = result.total;
      state.entries = result.entries;
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

  function discard(entry) {
    var bridge = api();
    Promise.resolve(bridge.discard_entry(entry.id)).then(function (ok) {
      if (ok) {
        toast("success", "Discarded " + (entry.title || entry.domain || "entry") + ".");
        load(true);
        refreshStats();
        changed();
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
    $("#sel-remove").hidden = !state.setId;
    $("#sel-add").hidden = !setsCache.length;
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

  function selectRange(id) {
    var ids = state.entries.map(function (entry) { return entry.id; });
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
    var bridge = api();
    bulk(function (id) { return bridge.discard_entry(id); }, function (ok, total) {
      toast(ok === total ? "success" : "error", ok === total ? "Discarded " + ok + "." : "Discarded " + ok + " of " + total + ".");
      clearSelection();
      load(true);
      refreshStats();
      changed();
    });
  }

  function setMenuItems() {
    return setsCache.map(function (item) {
      return { label: escapeHtml(item.name), action: function () { bulkPlace(item); } };
    });
  }

  function bulkMenuItems() {
    var items = [];
    if (setsCache.length) items.push({ label: "Add to set", children: setMenuItems() });
    if (state.setId) items.push({ label: "Remove from set", action: bulkRemove });
    items.push({ label: "Download", action: bulkSave });
    items.push({ separator: true });
    items.push({ label: "Discard " + selected.size, action: bulkDiscard });
    return items;
  }

  // Opens the set menu above the bar's add button.
  function openSetMenu(event) {
    event.stopPropagation();
    var rect = event.currentTarget.getBoundingClientRect();
    event.currentTarget.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: rect.left, clientY: rect.bottom }));
  }

  function setupSelection() {
    $("#sel-add").addEventListener("click", openSetMenu);
    $("#sel-remove").addEventListener("click", bulkRemove);
    $("#sel-save").addEventListener("click", bulkSave);
    $("#sel-discard").addEventListener("click", bulkDiscard);
    $("#sel-clear").addEventListener("click", clearSelection);
    if (window.HvContextMenu) window.HvContextMenu.register("#sel-add", setMenuItems);
    document.addEventListener("keydown", function (event) {
      if ($("#app").inert) return;
      var tag = event.target && event.target.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (event.key === "Escape") {
        clearSelection();
      } else if ((event.ctrlKey || event.metaKey) && (event.key === "a" || event.key === "A")) {
        event.preventDefault();
        state.entries.forEach(function (entry) { selected.add(entry.id); });
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

  function onSubmit(event) {
    event.preventDefault();
    var bridge = api();
    var url = urlInput.value.trim();
    if (!bridge || !bridge.add_link || !url || submitBtn.disabled) return;
    showError("");
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

  function onSearchInput() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(function () {
      var query = searchInput.value.trim();
      if (query === state.query) return;
      state.query = query;
      clearSelection();
      load(true);
    }, SEARCH_DEBOUNCE_MS);
  }

  function watchSentinel() {
    if (!("IntersectionObserver" in window)) return;
    var observer = new IntersectionObserver(function (observed) {
      if (observed[0].isIntersecting && state.entries.length < state.total) load(false);
    }, { root: $("#library"), rootMargin: "400px" });
    observer.observe(sentinel);
  }

  function init() {
    grid = $("#library-grid");
    emptyEl = $("#library-empty");
    sentinel = $("#library-sentinel");
    searchInput = $("#library-search");
    urlInput = $("#capture-url");
    submitBtn = $("#capture-submit");
    errorEl = $("#capture-error");
    if (!grid) return;

    $("#capture-form").addEventListener("submit", onSubmit);
    urlInput.addEventListener("input", function () { showError(""); });
    searchInput.addEventListener("input", onSearchInput);
    watchSentinel();
    setupSelection();
    document.addEventListener("hyperbridge:filter", function (event) {
      state.setId = event.detail.setId || null;
      clearSelection();
      load(true);
    });
    document.addEventListener("hyperbridge:changed", function () {
      refresh();
      refreshStats();
      loadSets();
    });
    setupMenu();

    if (api()) {
      load(true);
      loadSets();
    } else {
      window.addEventListener("pywebviewready", function () { load(true); loadSets(); });
    }
  }

  init();
})();
