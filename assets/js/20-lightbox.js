/* === Hyperbridge: lightbox and detail form === */
(function () {
  "use strict";

  var FIELDS = ["creator", "publisher", "title", "type", "year"];
  var imageCache = {};
  var current = null;
  var allSets = [];
  var assetIndex = 0;
  var returnFocus = null;
  var ticket = 0;
  var lb;

  function api() { return window.pywebview && window.pywebview.api; }
  function byId(id) { return document.getElementById(id); }

  function makeEl(tag, className, text) {
    var el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  }

  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function toast(variant, message) {
    if (window.HvToast) window.HvToast.show({ variant: variant, message: message });
  }

  function changed() { document.dispatchEvent(new CustomEvent("hyperbridge:changed")); }

  function displayTitle(entry) { return entry.title || entry.domain || "Untitled"; }

  // Fills the caption line in fixed field order; edited fields get a dashed underline.
  function renderCaption(entry) {
    var box = byId("lb-caption");
    box.textContent = "";
    var count = 0;
    FIELDS.forEach(function (name) {
      if (!entry[name]) return;
      if (count) box.appendChild(makeEl("span", "lightbox-caption-sep", " / "));
      var part = makeEl("span", "", entry[name]);
      if (entry.manual.indexOf(name) >= 0) {
        part.className = "lightbox-caption-manual";
        part.title = "Edited manually";
      }
      box.appendChild(part);
      count++;
    });
    if (!count) box.appendChild(makeEl("span", "lightbox-none", "No fields."));
  }

  function renderChips(box, names, className, emptyText) {
    box.textContent = "";
    if (!names.length) {
      box.appendChild(makeEl("span", "lightbox-none", emptyText));
      return;
    }
    names.forEach(function (name) { box.appendChild(makeEl("span", "status-chip " + className, name)); });
  }

  // Shows the entry's sets with a remove control, and a picker for the sets it is not in.
  function renderSets(entry) {
    var box = byId("lb-sets");
    box.textContent = "";
    if (!entry.sets.length) box.appendChild(makeEl("span", "lightbox-none", "No sets."));
    entry.sets.forEach(function (item) {
      var chip = makeEl("span", "status-chip status-chip-outlined-accent", item.name);
      var drop = makeEl("button", "lightbox-chip-remove");
      drop.innerHTML = '<svg class="icon-glyph-sm" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>';
      drop.setAttribute("data-tooltip", "Remove from " + item.name);
      drop.type = "button";
      drop.setAttribute("data-set", item.id);
      drop.setAttribute("aria-label", "Remove from " + item.name);
      chip.appendChild(drop);
      box.appendChild(chip);
    });
    var placed = entry.sets.map(function (item) { return item.id; });
    var open = allSets.filter(function (item) { return placed.indexOf(item.id) < 0; });
    if (!open.length) return;
    var add = makeEl("button", "action-icon lightbox-set-add");
    add.type = "button";
    add.id = "lb-place";
    add.setAttribute("aria-label", "Add to set");
    add.setAttribute("data-tooltip", "Add to set");
    add.innerHTML = '<svg class="icon-glyph-sm" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14"/><path d="M12 5v14"/></svg>';
    box.appendChild(add);
  }

  function renderSource(entry) {
    var box = byId("lb-source");
    box.textContent = "";
    if (!entry.source_url) {
      box.appendChild(makeEl("span", "lightbox-none", "No source."));
      return;
    }
    var link = makeEl("a", "", entry.source_url.replace(/^https?:\/\//, ""));
    link.href = entry.source_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    box.appendChild(link);
  }

  function renderStatus(entry) {
    var box = byId("lb-status");
    box.textContent = "";
    if (entry.state === "pending") {
      box.appendChild(makeEl("span", "status-chip status-chip-outlined-muted", "Pending"));
    } else if (entry.state === "failed") {
      box.appendChild(makeEl("span", "status-chip status-chip-outlined-accent lightbox-failed", "Failed"));
      box.appendChild(makeEl("span", "lightbox-none", "Could not read the page. Fill in the fields."));
    }
  }

  // Loads one asset image through the bridge, remembering it for the session.
  function loadImage(asset) {
    if (imageCache[asset.id]) return Promise.resolve(imageCache[asset.id]);
    var bridge = api();
    if (!bridge || !bridge.get_asset) return Promise.resolve(null);
    return Promise.resolve(bridge.get_asset(asset.id)).then(function (uri) {
      if (uri) imageCache[asset.id] = uri;
      return uri;
    }).catch(function () { return null; });
  }

  function renderImage() {
    var entry = current;
    var image = byId("lb-image");
    var asset = entry.assets[assetIndex];
    var multi = entry.assets.length > 1;
    lb.setAttribute("data-single", multi ? "false" : "true");
    var strip = byId("lb-strip");
    strip.textContent = "";
    entry.assets.forEach(function (_, i) {
      var dot = makeEl("button", "lightbox-dot");
      dot.type = "button";
      dot.setAttribute("data-asset", i);
      dot.setAttribute("aria-label", "Asset " + (i + 1));
      if (i === assetIndex) dot.setAttribute("aria-current", "true");
      strip.appendChild(dot);
    });
    image.alt = displayTitle(entry) + (multi ? ", asset " + (assetIndex + 1) + " of " + entry.assets.length : "");
    if (!asset) {
      image.removeAttribute("src");
      return;
    }
    var mine = ticket;
    if (imageCache[asset.id]) {
      image.src = imageCache[asset.id];
      return;
    }
    image.removeAttribute("src");
    loadImage(asset).then(function (uri) {
      if (mine === ticket && current && current.assets[assetIndex] === asset && uri) image.src = uri;
    });
  }

  function render() {
    var entry = current;
    byId("lb-title").textContent = displayTitle(entry);
    renderCaption(entry);
    renderStatus(entry);
    renderSource(entry);
    renderChips(byId("lb-tags"), entry.tags, "status-chip-outlined-muted", "No tags.");
    renderSets(entry);
    byId("act-save").hidden = !entry.assets.length;
    byId("act-save-all").hidden = entry.assets.length < 2;
    var editLabel = entry.state === "failed" ? "Fill in" : "Edit";
    byId("act-edit").setAttribute("aria-label", editLabel);
    byId("act-edit").setAttribute("data-tooltip", editLabel);
    renderImage();
  }

  // Opens non-modally over a HyperKit scrim so the cursor effects stay above it.
  function openDialog() {
    lb.show();
    byId("lb-scrim").classList.add("visible");
    byId("app").inert = true;
  }

  function closeForm() {
    byId("lb-form").hidden = true;
    byId("lb-view").hidden = false;
    byId("lb-actions").hidden = false;
  }

  function openForm() {
    if (!current) return;
    FIELDS.forEach(function (name) { byId("f-" + name).value = current[name] || ""; });
    byId("lb-view").hidden = true;
    byId("lb-form").hidden = false;
    byId("lb-actions").hidden = true;
    byId("f-creator").focus();
  }

  // Fetches an entry and shows it in the dialog.
  function openEntry(id, trigger) {
    var bridge = api();
    if (!bridge || !bridge.get_entry) return;
    var mine = ++ticket;
    if (trigger) returnFocus = trigger;
    var sets = bridge.list_sets ? Promise.resolve(bridge.list_sets()).catch(function () { return []; }) : Promise.resolve([]);
    Promise.all([bridge.get_entry(id), sets]).then(function (loaded) {
      var entry = loaded[0];
      allSets = loaded[1] || [];
      if (mine !== ticket) return;
      if (!entry) {
        toast("error", "Entry not found.");
        changed();
        return;
      }
      current = entry;
      assetIndex = 0;
      closeForm();
      render();
      if (!lb.open) openDialog();
      lb.focus();
    }).catch(function () { toast("error", "Could not open entry."); });
  }

  function cycleAsset(step) {
    if (!current || current.assets.length < 2) return;
    assetIndex = (assetIndex + step + current.assets.length) % current.assets.length;
    renderImage();
  }

  // Moves to the neighbouring card in the grid; stops at either end.
  function moveEntry(step) {
    if (!current) return;
    var cards = Array.prototype.slice.call(document.querySelectorAll("#library-grid [data-id]"));
    var index = cards.findIndex(function (card) { return Number(card.getAttribute("data-id")) === current.id; });
    var next = cards[index + step];
    if (index < 0 || !next) return;
    returnFocus = next;
    openEntry(Number(next.getAttribute("data-id")));
  }

  function onSubmit(event) {
    event.preventDefault();
    var bridge = api();
    if (!bridge || !bridge.update_entry || !current) return;
    var values = {};
    FIELDS.forEach(function (name) { values[name] = byId("f-" + name).value; });
    Promise.resolve(bridge.update_entry(current.id, values)).then(function (entry) {
      if (!entry) {
        toast("error", "Could not save.");
        return;
      }
      current = entry;
      closeForm();
      render();
      toast("success", "Updated.");
      changed();
    }).catch(function () { toast("error", "Could not save."); });
  }

  // Re-reads the open entry after a set change and tells the grid and sidebar.
  function reloadEntry(message) {
    var bridge = api();
    Promise.resolve(bridge.get_entry(current.id)).then(function (entry) {
      if (!entry || !current) return;
      current = entry;
      render();
      toast("success", message);
      changed();
    });
  }

  function placeInSet(setId) {
    var bridge = api();
    if (!bridge || !bridge.place_entry || !current || !setId) return;
    Promise.resolve(bridge.place_entry(current.id, setId)).then(function (ok) {
      if (!ok) toast("error", "Could not place.");
      else reloadEntry("Placed.");
    }).catch(function () { toast("error", "Could not place."); });
  }

  // Opens the shared menu of sets the entry is not yet in, anchored under the add button.
  function onPlaceMenu(event) {
    var add = event.target.closest("#lb-place");
    if (!add || !window.HvContextMenu || !current) return;
    event.stopPropagation();
    var rect = add.getBoundingClientRect();
    add.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: rect.left, clientY: rect.bottom + 4 }));
  }

  function placeItems() {
    var placed = current.sets.map(function (item) { return item.id; });
    return allSets.filter(function (item) { return placed.indexOf(item.id) < 0; }).map(function (item) {
      return { label: escapeHtml(item.name), action: function () { placeInSet(item.id); } };
    });
  }

  function onSetRemove(event) {
    var drop = event.target.closest(".lightbox-chip-remove");
    var bridge = api();
    if (!drop || !bridge || !bridge.remove_entry || !current) return;
    Promise.resolve(bridge.remove_entry(current.id, Number(drop.getAttribute("data-set")))).then(function (ok) {
      if (!ok) toast("error", "Could not remove.");
      else reloadEntry("Removed.");
    }).catch(function () { toast("error", "Could not remove."); });
  }

  function reportSave(result, noun) {
    var status = result && result.status ? result.status : result;
    if (status === "saved") toast("success", result.count > 1 ? "Saved " + result.count + " files." : "Saved.");
    else if (status === "cancelled") toast("info", "Cancelled.");
    else toast("error", "Could not save " + noun + ".");
  }

  function onSaveAsset() {
    var bridge = api();
    var asset = current && current.assets[assetIndex];
    if (!bridge || !bridge.save_asset || !asset) return;
    Promise.resolve(bridge.save_asset(asset.id)).then(function (result) { reportSave(result, "image"); })
      .catch(function () { toast("error", "Could not save image."); });
  }

  function onSaveAll() {
    var bridge = api();
    if (!bridge || !bridge.save_entry_assets || !current) return;
    Promise.resolve(bridge.save_entry_assets(current.id)).then(function (result) { reportSave(result, "images"); })
      .catch(function () { toast("error", "Could not save images."); });
  }

  function onDiscard() {
    var bridge = api();
    if (!bridge || !bridge.discard_entry || !current) return;
    var title = displayTitle(current);
    Promise.resolve(bridge.discard_entry(current.id)).then(function (ok) {
      if (!ok) {
        toast("error", "Could not discard.");
        return;
      }
      returnFocus = null;
      lb.close();
      toast("success", "Discarded " + title + ".");
      changed();
    }).catch(function () { toast("error", "Could not discard."); });
  }

  function onKey(event) {
    if (event.key === "Escape") { lb.close(); event.preventDefault(); return; }
    var tag = (event.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") return;
    if (event.key === "ArrowLeft") { cycleAsset(-1); event.preventDefault(); }
    else if (event.key === "ArrowRight") { cycleAsset(1); event.preventDefault(); }
    else if (event.key === "ArrowUp") { moveEntry(-1); event.preventDefault(); }
    else if (event.key === "ArrowDown") { moveEntry(1); event.preventDefault(); }
    else if ((event.key === "e" || event.key === "E") && byId("lb-form").hidden) { openForm(); event.preventDefault(); }
  }

  function onClosed() {
    byId("lb-scrim").classList.remove("visible");
    byId("app").inert = false;
    current = null;
    ticket++;
    if (!returnFocus) return;
    var id = returnFocus.getAttribute("data-id");
    var card = document.querySelector('#library-grid [data-id="' + id + '"]');
    if (card) card.focus();
  }

  function init() {
    lb = byId("lightbox");
    if (!lb) return;
    document.addEventListener("hyperbridge:open", function (event) {
      var id = event.detail.id;
      openEntry(id, document.querySelector('#library-grid [data-id="' + id + '"]'));
    });
    byId("lb-prev").addEventListener("click", function () { cycleAsset(-1); });
    byId("lb-next").addEventListener("click", function () { cycleAsset(1); });
    byId("lb-strip").addEventListener("click", function (event) {
      var dot = event.target.closest(".lightbox-dot");
      if (!dot) return;
      assetIndex = Number(dot.getAttribute("data-asset"));
      renderImage();
    });
    byId("lb-scrim").addEventListener("click", function () { lb.close(); });
    lb.addEventListener("close", onClosed);
    lb.addEventListener("keydown", onKey);
    byId("act-edit").addEventListener("click", openForm);
    byId("act-discard").addEventListener("click", onDiscard);
    byId("act-save").addEventListener("click", onSaveAsset);
    byId("act-save-all").addEventListener("click", onSaveAll);
    byId("lb-sets").addEventListener("click", onPlaceMenu);
    if (window.HvContextMenu) window.HvContextMenu.register("#lb-place", function () { return current ? placeItems() : []; });
    byId("lb-sets").addEventListener("click", onSetRemove);
    byId("f-cancel").addEventListener("click", function () {
      closeForm();
      render();
      toast("info", "Cancelled.");
    });
    byId("lb-form").addEventListener("submit", onSubmit);
  }

  init();
})();
