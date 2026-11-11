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
