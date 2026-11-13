
/* === Hyperbridge: sets - create, edit, pin, delete and menus === */
function stopEditing() {
  editing = null;
  renderAll();
}

function startNew() {
  openBrowse();
  editing = "new";
  renderCards();
  var form = cardsEl.querySelector("form");
  if (form) form.scrollIntoView({ block: "nearest" });
}

function startEdit(id) {
  openBrowse();
  editing = id;
  renderCards();
}

// Saves the open card form as a new set or as an edit of the one it belongs to.
function saveForm(form) {
  var bridge = api();
  var name = form.elements.name.value.trim();
  var description = form.elements.description.value.trim();
  if (!bridge || !name) {
    toast("error", "Name the set.");
    return;
  }
  var target = form.getAttribute("data-form");
  var creating = target === "new";
  var call = creating ? bridge.create_set(name, description) : bridge.rename_set(Number(target), name, description);
  Promise.resolve(call).then(function (result) {
    if (!result || !result.ok) {
      toast("error", result && result.error ? result.error : "Could not save.");
      return;
    }
    editing = null;
    toast("success", creating ? "Created." : "Updated.");
    return refresh();
  }).catch(function () { toast("error", "Could not save."); });
}

function togglePin(id) {
  var bridge = api();
  var item = setById(id);
  if (!bridge || !item) return;
  Promise.resolve(bridge.pin_set(id, !item.pinned)).then(function (ok) {
    if (!ok) return;
    toast("success", item.pinned ? "Unpinned." : "Pinned to tabs.");
    return refresh();
  }).catch(function () { toast("error", "Could not pin."); });
}

// Deletes a set; its entries stay in the library.
function deleteSet(item) {
  var bridge = api();
  if (!bridge) return;
  armedId = null;
  Promise.resolve(bridge.delete_set(item.id)).then(function (ok) {
    if (!ok) {
      toast("error", "Could not delete.");
      return;
    }
    toast("success", "Deleted " + item.name + ".");
    return refresh();
  }).catch(function () { toast("error", "Could not delete."); });
}

// The card's delete button asks twice: the first click arms it for a moment.
function confirmDelete(id) {
  var item = setById(id);
  if (!item) return;
  if (armedId === id) {
    clearTimeout(armTimer);
    deleteSet(item);
    return;
  }
  armedId = id;
  clearTimeout(armTimer);
  armTimer = setTimeout(function () {
    armedId = null;
    if (editing === null) renderCards();
  }, ARM_MS);
  renderCards();
  toast("info", "Click again to delete.");
}

// Right-click menus: card and tab actions, and New set anywhere in the strip or the view.
function setupMenus() {
  if (!window.HvContextMenu) return;
  var fresh = { label: "New set", action: startNew };
  function itemFor(element) {
    return setById(Number(element.getAttribute("data-set")));
  }
  window.HvContextMenu.register(".poster-card[data-set]", function (card) {
    var item = itemFor(card);
    if (!item) return [];
    return [
      { label: "Open", action: function () { select(item.id); } },
      { label: item.pinned ? "Unpin from tabs" : "Pin to tabs", action: function () { togglePin(item.id); } },
      { label: "Edit", action: function () { startEdit(item.id); } },
      { label: "Delete", action: function () { deleteSet(item); } },
      { separator: true },
      fresh,
    ];
  });
  window.HvContextMenu.register(".sets-tab[data-set]", function (tab) {
    var item = itemFor(tab);
    if (!item) return [];
    return [
      { label: item.pinned ? "Unpin from tabs" : "Pin to tabs", action: function () { togglePin(item.id); } },
      { label: "Edit", action: function () { startEdit(item.id); } },
      { label: "Delete", action: function () { deleteSet(item); } },
      { separator: true },
      fresh,
    ];
  });
  window.HvContextMenu.register("#sets-tabs", function () { return [fresh]; });
  window.HvContextMenu.register("#sets-view", function () { return [fresh]; });
}
