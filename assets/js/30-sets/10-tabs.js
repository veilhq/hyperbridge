
/* === Hyperbridge: sets - tab strip, open-set header and navigation === */
function settingsOpen() {
  return $("#library").hasAttribute("data-settings");
}

function announce(name, detail) {
  document.dispatchEvent(new CustomEvent(name, { detail: detail }));
}

function markTab(button, active) {
  button.classList.toggle("nav-tab-active", active);
  if (active) button.setAttribute("aria-current", "true");
  else button.removeAttribute("aria-current");
}

// Redraws the pinned tabs (every set until one is pinned, plus the open set when it is not pinned) and marks the active tab.
function renderTabs() {
  var open = selectedSet();
  var shown = pinnedSets();
  if (!shown.length) shown = sets.slice();
  if (open && shown.indexOf(open) < 0) shown = shown.concat([open]);
  $("#sets-pinned").innerHTML = shown.map(function (item) {
    var active = !browsing && item.id === selectedId;
    return '<button class="nav-tab nav-tab-folder sets-tab' + (active ? " nav-tab-active" : "") + '" type="button" data-set="' + item.id + '"' +
      (active ? ' aria-current="true"' : "") + ">" + esc(item.name) + '<span class="sets-tab-count">' + item.count + "</span></button>";
  }).join("");
  markTab($("#sets-discover"), feedOpen && !browsing);
  markTab($("#sets-all"), selectedId === null && !feedOpen && !browsing);
  markTab($("#sets-browse"), browsing);
  $("#sets-count").textContent = sets.length;
}

// Shows the open set's title, description, size and pin at the top of the library.
function renderHead() {
  var current = selectedSet();
  var head = $("#set-head");
  head.hidden = !current;
  if (!current) return;
  var desc = $("#set-head-desc");
  var ago = agoLabel(daysSince(current));
  $("#set-head-title").textContent = current.name;
  desc.textContent = current.description || "";
  desc.hidden = !current.description;
  $("#set-head-meta").textContent = entriesLabel(current.count) + (ago ? " - UPDATED " + ago.toUpperCase() : "");
  var pin = $("#set-head-pin");
  var label = current.pinned ? "Unpin from tabs" : "Pin to tabs";
  pin.setAttribute("aria-pressed", current.pinned ? "true" : "false");
  pin.setAttribute("aria-label", label);
  pin.setAttribute("data-tooltip", label);
}

// Collapses the tab strip into an auto-hide bar, or restores it.
function setCollapsed(value) {
  tabsCollapsed = value;
  var label = value ? "Keep tabs visible" : "Auto-hide tabs";
  var button = $("#sets-collapse");
  $("#sets-tabs").toggleAttribute("data-collapsed", value);
  button.setAttribute("aria-pressed", value ? "true" : "false");
  button.setAttribute("aria-label", label);
  button.setAttribute("data-tooltip", label);
  saveViewPrefs();
}

// Redraws every sets surface; the cards are left alone while one is being edited.
function renderAll() {
  renderTabs();
  renderHead();
  if (editing === null) renderCards();
}

// Shows or hides the Sets view; the library grid underneath keeps its state.
function setBrowsing(value) {
  var wasBrowsing = browsing;
  browsing = value;
  if (!value) editing = null;
  $("#library").toggleAttribute("data-sets-view", value);
  $("#sets-view").hidden = !value;
  if (value && !wasBrowsing) $("#library").scrollTop = 0;
  renderAll();
}

function openBrowse() {
  if (!browsing || settingsOpen()) announce("hyperbridge:sets");
  setBrowsing(true);
}

// Opens a set (null for All) in the library, telling the grid when the filter changed.
function select(id) {
  var changed = id !== selectedId || feedOpen || settingsOpen();
  feedOpen = false;
  selectedId = id;
  setBrowsing(false);
  if (changed) announce("hyperbridge:filter", { setId: id });
}

function openDiscover() {
  var changed = !feedOpen || settingsOpen();
  feedOpen = true;
  selectedId = null;
  setBrowsing(false);
  if (changed) announce("hyperbridge:feed");
}

function refresh() {
  var bridge = api();
  if (!bridge || !bridge.list_sets) return Promise.resolve();
  return Promise.resolve(bridge.list_sets()).then(function (result) {
    sets = result || [];
    if (selectedId !== null && !selectedSet()) select(null);
    else renderAll();
  }).catch(function () {});
}
