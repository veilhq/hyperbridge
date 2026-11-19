
/* === Hyperbridge: sets - wiring === */
function setupViewEvents() {
  var searchEl = $("#sets-search");
  searchEl.addEventListener("input", function () {
    query = searchEl.value;
    editing = null;
    renderCards();
  });
  $("#sets-sort").addEventListener("click", function (event) {
    var button = event.target.closest("[data-sort]");
    if (!button) return;
    sortKey = button.getAttribute("data-sort");
    saveViewPrefs();
    renderAll();
  });
  cardsEl.addEventListener("click", function (event) {
    var button = event.target.closest("button");
    if (!button) return;
    if (button.hasAttribute("data-new")) startNew();
    else if (button.hasAttribute("data-pin")) togglePin(Number(button.getAttribute("data-pin")));
    else if (button.hasAttribute("data-edit")) startEdit(Number(button.getAttribute("data-edit")));
    else if (button.hasAttribute("data-del")) confirmDelete(Number(button.getAttribute("data-del")));
    else if (button.hasAttribute("data-open")) select(Number(button.getAttribute("data-open")));
  });
  cardsEl.addEventListener("submit", function (event) {
    event.preventDefault();
    saveForm(event.target);
  });
  cardsEl.addEventListener("keydown", function (event) {
    if (event.key !== "Escape" || editing === null) return;
    event.preventDefault();
    event.stopPropagation();
    stopEditing();
  });
  // Escape clears the search, then leaves the Sets view, before the library's own Escape handling runs.
  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape" || !browsing || editing !== null || $("#app").inert) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (query) {
      query = "";
      $("#sets-search").value = "";
      renderCards();
    } else {
      navigate(function () { setBrowsing(false); });
    }
  }, true);
}

function initSets() {
  cardsEl = $("#sets-cards");
  if (!cardsEl) return;
  loadViewPrefs();
  setupMenus();
  setupViewEvents();
  $("#sets-discover").addEventListener("click", openDiscover);
  $("#sets-latest").addEventListener("click", openLatest);
  $("#sets-all").addEventListener("click", function () { select(null); });
  $("#sets-unsorted").addEventListener("click", openUnsorted);
  $("#sets-browse").addEventListener("click", openBrowse);
  $("#sets-new").addEventListener("click", startNew);
  $("#sets-collapse").addEventListener("click", function () { setCollapsed(!tabsCollapsed); });
  document.addEventListener("keydown", function (event) {
    var backslash = event.key === "\\" || event.code === "Backslash";
    if (!backslash || !(event.ctrlKey || event.metaKey) || event.repeat || $("#app").inert) return;
    event.preventDefault();
    setCollapsed(!tabsCollapsed);
  }, true);
  setCollapsed(tabsCollapsed);
  $("#sets-stack").addEventListener("click", function (event) {
    var tab = event.target.closest("[data-set]");
    if (tab) select(Number(tab.getAttribute("data-set")));
  });
  $("#set-head-back").addEventListener("click", openBrowse);
  $("#set-head-similar").addEventListener("click", function () {
    if (selectedId !== null) findSimilar(selectedId);
  });
  $("#set-head-pin").addEventListener("click", function () {
    if (selectedId !== null) togglePin(selectedId);
  });
  $("#set-head-edit").addEventListener("click", function () {
    if (selectedId !== null) startHeadEdit(selectedId);
  });
  $("#set-head-form").addEventListener("submit", function (event) {
    event.preventDefault();
    saveForm(event.target);
  });
  $("#set-head-form").addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    stopHeadEdit();
  });
  document.addEventListener("hyperbridge:changed", refresh);
  // Opening settings leaves the Sets view so the panel is not hidden behind it.
  new MutationObserver(function () {
    if (browsing && settingsOpen()) setBrowsing(false);
  }).observe($("#library"), { attributes: true, attributeFilter: ["data-settings"] });
  renderAll();
  paintLatestCount(0);
  if (api()) { refresh(); startLatestPolling(); }
  else window.addEventListener("pywebviewready", function () { refresh(); startLatestPolling(); });
}

initSets();
