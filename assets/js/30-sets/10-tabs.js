
/* === Hyperbridge: sets - tab strip, open-set header and navigation === */
function settingsOpen() {
  return $("#library").hasAttribute("data-settings");
}

function announce(name, detail) {
  document.dispatchEvent(new CustomEvent(name, { detail: detail }));
}

function markTab(button, active) {
  button.classList.toggle("content-card-active", active);
  if (active) button.setAttribute("aria-current", "true");
  else button.removeAttribute("aria-current");
}

// Redraws the set cards below the fixed ones (every set until one is pinned, plus the open set when it is not pinned) and marks the active tab.
function renderTabs() {
  var open = selectedSet();
  var shown = pinnedSets();
  if (!shown.length) shown = sets.slice();
  if (open && shown.indexOf(open) < 0) shown = shown.concat([open]);
  $("#sets-list").innerHTML = shown.map(function (item) {
    var active = !browsing && item.id === selectedId;
    return '<button class="content-card sets-tab sets-tab-set' + (active ? " content-card-active" : "") + '" type="button" data-set="' + item.id + '"' +
      (active ? ' aria-current="true"' : "") + ">" + '<span class="sets-tab-head"><span class="sets-tab-name">' + esc(item.name) + '</span><span class="sets-tab-count">' + item.count + "</span></span>" +
      (item.description ? '<span class="sets-tab-desc">' + esc(item.description) + "</span>" : "") + "</button>";
  }).join("");
  markTab($("#sets-discover"), feedOpen === "discover" && !browsing);
  markTab($("#sets-latest"), feedOpen === "latest" && !browsing);
  markTab($("#sets-all"), selectedId === null && !feedOpen && !unsortedOpen && !browsing);
  markTab($("#sets-unsorted"), unsortedOpen && !browsing);
  markTab($("#sets-browse"), browsing);
  $("#sets-count").textContent = sets.length;
}

// Shows the open set's title, description, size, tags and pin at the top of the library.
function renderHead() {
  var current = selectedSet();
  var head = $("#set-head");
  head.hidden = !current;
  if (!current) return;
  var desc = $("#set-head-desc");
  var ago = agoLabel(daysSince(current));
  $("#set-head-title").textContent = current.name;
  desc.textContent = current.description || "";
  desc.hidden = headEditing || !current.description;
  $("#set-head-meta").textContent = entriesLabel(current.count) + (ago ? " - UPDATED " + ago.toUpperCase() : "");
  var tags = $("#set-head-tags");
  tags.innerHTML = (current.tags || []).map(function (tag) {
    return '<li class="status-chip status-chip-outlined-muted">' + esc(tag) + "</li>";
  }).join("");
  tags.hidden = headEditing || !tags.children.length;
  $("#set-head-title").hidden = headEditing;
  $("#set-head-meta").hidden = headEditing;
  $("#set-head-form").hidden = !headEditing;
  $("#set-head-edit").hidden = headEditing;
  var pin = $("#set-head-pin");
  var label = current.pinned ? "Unpin from tabs" : "Pin to tabs";
  pin.setAttribute("aria-pressed", current.pinned ? "true" : "false");
  pin.setAttribute("aria-label", label);
  pin.setAttribute("data-tooltip", label);
}

// Collapses the sidebar into an auto-hide drawer, or restores it.
function setCollapsed(value) {
  tabsCollapsed = value;
  var label = value ? "Keep sidebar visible" : "Auto-hide sidebar";
  var button = $("#sets-collapse");
  $("#sets-rail").toggleAttribute("data-collapsed", value);
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
  if (value) headEditing = false;
  $("#library").toggleAttribute("data-sets-view", value);
  $("#sets-view").hidden = !value;
  if (value && !wasBrowsing) $("#library").scrollTop = 0;
  renderAll();
  if (value && !wasBrowsing) cascadeSets();
}

// Fades the bar and set cards in one after another when the Sets view opens, like the library grid.
function cascadeSets() {
  var items = [$("#sets-view .sets-bar")].concat(Array.prototype.slice.call(cardsEl.children));
  items.forEach(function (el, index) {
    if (!el) return;
    el.style.setProperty("--cascade-index", Math.min(index, SETS_CASCADE_MAX));
    el.classList.add("library-cascade");
  });
}

function openBrowse() {
  navigateIf(!browsing || settingsOpen(), function () {
    if (!browsing || settingsOpen()) announce("hyperbridge:sets");
    setBrowsing(true);
  });
}

// Opens a set (null for All) in the library, telling the grid when the filter changed.
function select(id) {
  navigateIf(id !== selectedId || feedOpen || unsortedOpen || browsing || settingsOpen(), function () {
    var changed = id !== selectedId || feedOpen || unsortedOpen || settingsOpen();
    if (id !== selectedId) headEditing = false;
    feedOpen = false;
    unsortedOpen = false;
    selectedId = id;
    setBrowsing(false);
    if (changed) announce("hyperbridge:filter", { setId: id });
  });
}

// Opens the library filtered to entries in no set, a queue for sorting new captures.
function openUnsorted() {
  navigateIf(!unsortedOpen || browsing || settingsOpen(), function () {
    var changed = !unsortedOpen || settingsOpen();
    headEditing = false;
    feedOpen = false;
    unsortedOpen = true;
    selectedId = null;
    setBrowsing(false);
    if (changed) announce("hyperbridge:filter", { setId: null, unsorted: true });
  });
}

// Opens a feed view in the library: "discover" for the shuffled pull, "latest" for newest posts first.
function openFeedView(view) {
  navigate(function () {
    var changed = feedOpen !== view || settingsOpen();
    headEditing = false;
    feedOpen = view;
    unsortedOpen = false;
    selectedId = null;
    setBrowsing(false);
    if (view === "latest") paintLatestCount(0);
    if (changed) announce(view === "latest" ? "hyperbridge:latest" : "hyperbridge:feed");
  });
}

function openDiscover() { openFeedView("discover"); }

function openLatest() { openFeedView("latest"); }

// Shows how many Latest images are new since the last visit on its tab; nothing when there are none.
function paintLatestCount(count) {
  var badge = $("#latest-count");
  badge.textContent = count > 0 ? (count > 99 ? "99+" : String(count)) : "";
  badge.hidden = !(count > 0);
}

// Checks the next batch of followed sources for new posts, then updates the Latest tab's count.
function pollLatest() {
  var bridge = api();
  if (!bridge || !bridge.refresh_latest) return;
  Promise.resolve(bridge.refresh_latest()).then(function () { return bridge.latest_status(); }).then(function (status) {
    paintLatestCount(feedOpen === "latest" ? 0 : (status && status.fresh) || 0);
  }).catch(function () {});
}

function startLatestPolling() {
  var bridge = api();
  if (bridge && bridge.latest_status) {
    Promise.resolve(bridge.latest_status()).then(function (status) { paintLatestCount((status && status.fresh) || 0); }).catch(function () {});
  }
  setTimeout(pollLatest, LATEST_FIRST_POLL_MS);
  setInterval(pollLatest, LATEST_POLL_MS);
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
