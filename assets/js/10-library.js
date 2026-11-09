/* === Hyperbridge: library grid === */
(function () {
  "use strict";

  var PAGE_SIZE = 60;
  var POLL_MS = 2000;
  var SEARCH_DEBOUNCE_MS = 250;

  var state = { query: "", setId: null, entries: [], total: 0, loading: false, ticket: 0, signature: "" };
  var grid, emptyEl, sentinel, searchInput, urlInput, submitBtn, errorEl;
  var searchTimer = null;
  var pollTimer = null;

  function api() { return window.pywebview && window.pywebview.api; }

  function makeEl(tag, className, text) {
    var el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
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
    } else {
      card.appendChild(makeEl("span", "library-thumb-empty"));
    }

    if (entry.state === "pending") {
      card.appendChild(makeEl("span", "library-card-flag status-chip status-chip-outlined-muted", "Pending"));
    } else if (entry.state === "failed") {
      card.appendChild(makeEl("span", "library-card-flag library-failed status-chip status-chip-outlined-accent", "Failed"));
    }

    var body = makeEl("span", "library-card-details");
    body.appendChild(makeEl("span", "library-card-title", entry.title || entry.domain || "Untitled"));
    if (entry.domain) body.appendChild(makeEl("span", "library-card-domain", entry.domain));
    card.appendChild(body);

    card.addEventListener("click", function () {
      document.dispatchEvent(new CustomEvent("hyperbridge:open", { detail: { id: entry.id } }));
    });
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
    document.addEventListener("hyperbridge:filter", function (event) {
      state.setId = event.detail.setId || null;
      load(true);
    });
    document.addEventListener("hyperbridge:changed", function () {
      refresh();
      refreshStats();
    });

    if (api()) load(true);
    else window.addEventListener("pywebviewready", function () { load(true); });
  }

  init();
})();
