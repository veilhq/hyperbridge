
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
      setBrowsing(false);
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
  $("#sets-all").addEventListener("click", function () { select(null); });
  $("#sets-browse").addEventListener("click", openBrowse);
  $("#sets-new").addEventListener("click", startNew);
  $("#sets-pinned").addEventListener("click", function (event) {
    var tab = event.target.closest("[data-set]");
    if (tab) select(Number(tab.getAttribute("data-set")));
  });
  $("#set-head-back").addEventListener("click", openBrowse);
  $("#set-head-pin").addEventListener("click", function () {
    if (selectedId !== null) togglePin(selectedId);
  });
  document.addEventListener("hyperbridge:changed", refresh);
  // Opening settings leaves the Sets view so the panel is not hidden behind it.
  new MutationObserver(function () {
    if (browsing && settingsOpen()) setBrowsing(false);
  }).observe($("#library"), { attributes: true, attributeFilter: ["data-settings"] });
  renderAll();
  if (api()) refresh();
  else window.addEventListener("pywebviewready", refresh);
}

initSets();
