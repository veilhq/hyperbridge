/* === Hyperbridge: sets sidebar === */
(function () {
  "use strict";

  var sets = [];
  var selectedId = null;
  var renamingId = null;
  var moreEl, formEl, nameEl, errorEl, allEl;

  function api() { return window.pywebview && window.pywebview.api; }

  function toast(variant, message) {
    if (window.HvToast) window.HvToast.show({ variant: variant, message: message });
  }

  function selectedSet() {
    return sets.find(function (item) { return item.id === selectedId; }) || null;
  }

  function showError(message) {
    errorEl.textContent = message || "";
    errorEl.hidden = !message;
  }

  // Hides the name field and clears any rename or error state.
  function stopRename() {
    renamingId = null;
    formEl.hidden = true;
    nameEl.value = "";
    showError("");
  }

  function openForm(value) {
    formEl.hidden = false;
    nameEl.value = value || "";
    nameEl.focus();
    nameEl.select();
  }

  function render() {
    var current = selectedSet();
    if (selectedId !== null && !current) selectedId = null;
    moreEl.textContent = "";
    sets.forEach(function (item) {
      var row = document.createElement("button");
      row.type = "button";
      row.className = "sets-item";
      row.setAttribute("data-set", item.id);
      if (item.id === selectedId) row.setAttribute("aria-current", "true");
      var label = document.createElement("span");
      label.className = "sets-name";
      label.textContent = item.name;
      var count = document.createElement("span");
      count.className = "sets-count";
      count.textContent = item.count;
      row.appendChild(label);
      row.appendChild(count);
      moreEl.appendChild(row);
    });
    if (selectedId === null) allEl.setAttribute("aria-current", "true");
    else allEl.removeAttribute("aria-current");
  }

  function refresh() {
    var bridge = api();
    if (!bridge || !bridge.list_sets) return Promise.resolve();
    return Promise.resolve(bridge.list_sets()).then(function (result) {
      sets = result || [];
      render();
    }).catch(function () {});
  }

  function select(id) {
    var changed = id !== selectedId;
    selectedId = id;
    stopRename();
    render();
    if (changed) document.dispatchEvent(new CustomEvent("hyperbridge:filter", { detail: { setId: id } }));
  }

  function onSubmit(event) {
    event.preventDefault();
    var bridge = api();
    var name = nameEl.value.trim();
    if (!bridge || !name) return;
    var call = renamingId !== null
      ? bridge.rename_set(renamingId, name)
      : bridge.create_set(name);
    Promise.resolve(call).then(function (result) {
      if (!result || !result.ok) {
        showError(result && result.error ? result.error : "Could not save.");
        return;
      }
      var wasRenaming = renamingId !== null;
      stopRename();
      toast("success", wasRenaming ? "Updated." : "Created.");
      return refresh().then(function () {
        if (!wasRenaming) select(result.set.id);
      });
    }).catch(function () { showError("Could not save."); });
  }

  function onRename(item) {
    renamingId = item.id;
    openForm(item.name);
  }

  // Deletes a set; its entries stay in the library.
  function onDelete(item) {
    var bridge = api();
    if (!bridge) return;
    Promise.resolve(bridge.delete_set(item.id)).then(function (ok) {
      if (!ok) {
        toast("error", "Could not delete.");
        return;
      }
      toast("success", "Deleted " + item.name + ".");
      if (selectedId === item.id) select(null);
      return refresh();
    }).catch(function () { toast("error", "Could not delete."); });
  }

  function onNew() {
    renamingId = null;
    openForm("");
  }

  // Right-click menu: Rename and Delete on a set row, New set anywhere in the rail.
  function setupMenu() {
    if (!window.HvContextMenu) return;
    var fresh = { label: "New set", action: onNew };
    window.HvContextMenu.register(".sets-item[data-set]", function (row) {
      var item = sets.find(function (entry) { return entry.id === Number(row.getAttribute("data-set")); });
      if (!item) return [];
      return [
        { label: "Rename", action: function () { onRename(item); } },
        { label: "Delete", action: function () { onDelete(item); } },
        { separator: true },
        fresh,
      ];
    });
    window.HvContextMenu.register("#sets-rail", function () { return [fresh]; });
  }

  // Ctrl+\ shows or hides the rail; the choice persists between sessions.
  function setupRailToggle() {
    var rail = $("#sets-rail");
    function apply(hidden) {
      rail.setAttribute("data-hidden", hidden ? "true" : "false");
      rail.inert = hidden;
    }
    var saved = false;
    try { saved = localStorage.getItem("hyperbridge-sets") === "hidden"; } catch (err) { saved = false; }
    apply(saved);
    document.addEventListener("keydown", function (event) {
      if (!event.ctrlKey || event.key !== "\\" || event.altKey || event.metaKey) return;
      if ($("#app").inert) return;
      event.preventDefault();
      var hidden = rail.getAttribute("data-hidden") !== "true";
      apply(hidden);
      try { localStorage.setItem("hyperbridge-sets", hidden ? "hidden" : "shown"); } catch (err) { /* ignore */ }
    });
  }

  function init() {
    moreEl = $("#sets-more");
    if (!moreEl) return;
    setupRailToggle();
    setupMenu();
    formEl = $("#sets-form");
    nameEl = $("#sets-name");
    errorEl = $("#sets-error");
    allEl = $("#sets-all");

    allEl.addEventListener("click", function () { select(null); });
    moreEl.addEventListener("click", function (event) {
      var row = event.target.closest(".sets-item");
      if (row) select(Number(row.getAttribute("data-set")));
    });
    formEl.addEventListener("submit", onSubmit);
    nameEl.addEventListener("input", function () { showError(""); });
    nameEl.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        stopRename();
        event.preventDefault();
      }
    });
    nameEl.addEventListener("blur", function () {
      if (!nameEl.value.trim()) stopRename();
    });
    document.addEventListener("hyperbridge:changed", refresh);

    if (api()) refresh();
    else window.addEventListener("pywebviewready", refresh);
  }

  init();
})();
