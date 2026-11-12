/* === Hyperbridge: tag manager in settings === */
(function () {
  "use strict";

  var SHOWN = 100;
  var tags = [];
  var byName = false;
  var renaming = "";
  var confirming = "";
  var listEl, filterEl, sortEl, errorEl, view;

  function api() { return window.pywebview && window.pywebview.api; }

  function toast(variant, message) {
    if (window.HvToast) window.HvToast.show({ variant: variant, message: message });
  }

  function makeEl(tag, className, text) {
    var el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  }

  function showError(message) {
    errorEl.textContent = message || "";
    errorEl.hidden = !message;
  }

  function entries(count) { return count + (count === 1 ? " entry" : " entries"); }

  // Returns the tags matching the filter, in the chosen order.
  function visible() {
    var needle = filterEl.value.trim().toLowerCase();
    var found = tags.filter(function (item) { return !needle || item.name.toLowerCase().indexOf(needle) !== -1; });
    if (byName) found.sort(function (a, b) { return a.name.toLowerCase() < b.name.toLowerCase() ? -1 : 1; });
    return found;
  }

  function exists(name) {
    var lower = name.toLowerCase();
    return tags.some(function (item) { return item.name.toLowerCase() === lower; });
  }

  // Opens the library filtered to one tag.
  function open(name) {
    $("#settings-close").click();
    document.dispatchEvent(new CustomEvent("hyperbridge:tag", { detail: { tag: name } }));
  }

  function done(message) {
    renaming = "";
    confirming = "";
    toast("success", message);
    document.dispatchEvent(new CustomEvent("hyperbridge:changed"));
    return load();
  }

  function submitRename(item, input) {
    var bridge = api();
    var name = input.value.trim();
    if (!bridge || !name || name === item.name) { renaming = ""; render(); return; }
    showError("");
    Promise.resolve(bridge.rename_tag(item.name, name)).then(function (result) {
      if (!result || !result.ok) { showError((result && result.error) || "Could not rename."); return; }
      return done(result.merged ? "Merged into " + name + "." : "Renamed to " + name + ".");
    }).catch(function () { showError("Could not rename."); });
  }

  function remove(item) {
    var bridge = api();
    if (!bridge) return;
    Promise.resolve(bridge.delete_tag(item.name)).then(function (count) {
      return done("Deleted " + item.name + " from " + entries(count) + ".");
    }).catch(function () { toast("error", "Could not delete."); });
  }

  function buildRow(item) {
    var row = makeEl("div", "settings-source");
    if (renaming === item.name) {
      var input = makeEl("input", "form-input");
      input.value = item.name;
      input.maxLength = 40;
      input.setAttribute("aria-label", "New name for " + item.name);
      var save = makeEl("button", "action-button action-button-ghost", "Save");
      save.type = "button";
      var cancel = makeEl("button", "action-button action-button-ghost", "Cancel");
      cancel.type = "button";
      function sync() { save.textContent = input.value.trim() && input.value.trim().toLowerCase() !== item.name.toLowerCase() && exists(input.value.trim()) ? "Merge" : "Save"; }
      input.addEventListener("input", sync);
      input.addEventListener("keydown", function (event) {
        if (event.key === "Enter") { event.preventDefault(); submitRename(item, input); }
        if (event.key === "Escape") { event.preventDefault(); renaming = ""; render(); }
      });
      save.addEventListener("click", function () { submitRename(item, input); });
      cancel.addEventListener("click", function () { renaming = ""; render(); });
      row.appendChild(input);
      row.appendChild(makeEl("span", "status-chip status-chip-outlined-muted", String(item.count)));
      row.appendChild(save);
      row.appendChild(cancel);
      window.setTimeout(function () { input.focus(); input.select(); }, 0);
      return row;
    }
    var name = makeEl("button", "settings-tag-name", item.name);
    name.type = "button";
    name.setAttribute("data-tooltip", "Show " + entries(item.count));
    name.addEventListener("click", function () { open(item.name); });
    var rename = makeEl("button", "action-button action-button-ghost", "Rename");
    rename.type = "button";
    rename.setAttribute("aria-label", "Rename " + item.name);
    rename.addEventListener("click", function () { renaming = item.name; confirming = ""; render(); });
    var armed = confirming === item.name;
    var del = makeEl("button", "action-button action-button-ghost action-button-danger", armed ? "Confirm" : "Delete");
    del.type = "button";
    del.setAttribute("aria-label", (armed ? "Confirm deleting " : "Delete ") + item.name);
    del.addEventListener("click", function () {
      if (armed) { remove(item); return; }
      confirming = item.name;
      render();
    });
    row.appendChild(name);
    row.appendChild(makeEl("span", "status-chip status-chip-outlined-muted", String(item.count)));
    row.appendChild(rename);
    row.appendChild(del);
    return row;
  }

  function render() {
    listEl.textContent = "";
    var found = visible();
    found.slice(0, SHOWN).forEach(function (item) { listEl.appendChild(buildRow(item)); });
    var note = "";
    if (!tags.length) note = "No tags yet.";
    else if (!found.length) note = "No tags match.";
    else if (found.length > SHOWN) note = (found.length - SHOWN) + " more. Filter to narrow the list.";
    if (note) listEl.appendChild(makeEl("span", "settings-source-desc", note));
    sortEl.textContent = byName ? "A to Z" : "Most used";
    $("#tags-prune").disabled = !tags.some(function (item) { return item.count === 1; });
  }

  function load() {
    var bridge = api();
    if (!bridge || !bridge.list_tags) return Promise.resolve();
    return Promise.resolve(bridge.list_tags()).then(function (result) {
      tags = result || [];
      render();
    }).catch(function () {});
  }

  function prune() {
    var bridge = api();
    var single = tags.filter(function (item) { return item.count === 1; }).length;
    if (!bridge || !single) return;
    var button = $("#tags-prune");
    if (button.getAttribute("data-armed") !== "true") {
      button.setAttribute("data-armed", "true");
      button.textContent = "Confirm: delete " + single;
      window.setTimeout(function () { button.removeAttribute("data-armed"); button.textContent = "Delete single-use"; }, 4000);
      return;
    }
    button.removeAttribute("data-armed");
    button.textContent = "Delete single-use";
    Promise.resolve(bridge.delete_single_use_tags()).then(function (count) {
      return done("Deleted " + count + (count === 1 ? " tag." : " tags."));
    }).catch(function () { toast("error", "Could not delete."); });
  }

  function init() {
    view = $("#settings-view");
    listEl = $("#tags-list");
    if (!view || !listEl) return;
    filterEl = $("#tags-filter");
    sortEl = $("#tags-sort");
    errorEl = $("#tags-error");
    filterEl.addEventListener("input", render);
    sortEl.addEventListener("click", function () { byName = !byName; render(); });
    $("#tags-prune").addEventListener("click", prune);
    new MutationObserver(function () { if (!view.hidden) { renaming = ""; confirming = ""; load(); } })
      .observe(view, { attributes: true, attributeFilter: ["hidden"] });
  }

  init();
})();
