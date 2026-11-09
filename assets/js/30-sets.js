/* === Hyperbridge: sets sidebar === */
(function () {
  "use strict";

  var sets = [];
  var selectedId = null;
  var renaming = false;
  var confirmTimer = null;
  var listEl, moreEl, formEl, nameEl, errorEl, allEl, newEl, renameEl, deleteEl;

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

  function resetConfirm() {
    clearTimeout(confirmTimer);
    deleteEl.textContent = "Delete";
    deleteEl.removeAttribute("data-confirm");
  }

  // Hides the name field and clears any rename or error state.
  function stopRename() {
    renaming = false;
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
    renameEl.hidden = selectedId === null;
    deleteEl.hidden = selectedId === null;
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
    resetConfirm();
    stopRename();
    render();
    if (changed) document.dispatchEvent(new CustomEvent("hyperbridge:filter", { detail: { setId: id } }));
  }

  function onSubmit(event) {
    event.preventDefault();
    var bridge = api();
    var name = nameEl.value.trim();
    if (!bridge || !name) return;
    var call = renaming
      ? bridge.rename_set(selectedId, name)
      : bridge.create_set(name);
    Promise.resolve(call).then(function (result) {
      if (!result || !result.ok) {
        showError(result && result.error ? result.error : "Could not save.");
        return;
      }
      var wasRenaming = renaming;
      stopRename();
      toast("success", wasRenaming ? "Updated." : "Created.");
      return refresh().then(function () {
        if (!wasRenaming) select(result.set.id);
      });
    }).catch(function () { showError("Could not save."); });
  }

  function onRename() {
    var current = selectedSet();
    if (!current) return;
    renaming = true;
    openForm(current.name);
  }

  // First click arms the button; a second click within a few seconds deletes the set.
  function onDelete() {
    var bridge = api();
    var current = selectedSet();
    if (!bridge || !current) return;
    if (!deleteEl.getAttribute("data-confirm")) {
      deleteEl.setAttribute("data-confirm", "true");
      deleteEl.textContent = "Confirm";
      confirmTimer = setTimeout(resetConfirm, 3000);
      return;
    }
    resetConfirm();
    Promise.resolve(bridge.delete_set(current.id)).then(function (ok) {
      if (!ok) {
        toast("error", "Could not delete.");
        return;
      }
      toast("success", "Deleted " + current.name + ".");
      select(null);
      return refresh();
    }).catch(function () { toast("error", "Could not delete."); });
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
    listEl = $("#sets-list");
    if (!listEl) return;
    moreEl = $("#sets-more");
    setupRailToggle();
    newEl = $("#sets-new");
    formEl = $("#sets-form");
    nameEl = $("#sets-name");
    errorEl = $("#sets-error");
    allEl = $("#sets-all");
    renameEl = $("#sets-rename");
    deleteEl = $("#sets-delete");

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
    newEl.addEventListener("click", function () {
      renaming = false;
      openForm("");
    });
    renameEl.addEventListener("click", onRename);
    deleteEl.addEventListener("click", onDelete);
    document.addEventListener("hyperbridge:changed", refresh);

    if (api()) refresh();
    else window.addEventListener("pywebviewready", refresh);
  }

  init();
})();
