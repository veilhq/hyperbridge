/* === Hyperbridge: lightbox and detail form === */
(function () {
  "use strict";

  var FIELDS = ["creator", "publisher", "title", "type", "year"];
  var FORM_FIELDS = FIELDS.concat(["description"]);
  var imageCache = {};
  var current = null;
  var allSets = [];
  var assetIndex = 0;
  var returnFocus = null;
  var ticket = 0;
  var lb;
  var swapToken = 0;

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

  function displayTitle(entry) { return entry.title || "Untitled"; }

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

  // Shows the description under its label, hidden when the entry has none.
  function renderDescription(entry) {
    var value = byId("lb-description");
    var text = entry.description || "";
    value.textContent = text;
    value.hidden = !text;
    byId("lb-description-label").hidden = !text;
    value.classList.toggle("lightbox-caption-manual", entry.manual.indexOf("description") >= 0 && !!text);
  }

  function renderChips(box, names, className, emptyText, clickable) {
    box.textContent = "";
    if (!names.length) {
      box.appendChild(makeEl("span", "lightbox-none", emptyText));
      return;
    }
    names.forEach(function (name) {
      var chip = makeEl(clickable ? "button" : "span", "status-chip " + className + (clickable ? " lightbox-tag" : ""), name);
      if (clickable) {
        chip.type = "button";
        chip.setAttribute("data-tag", name);
        chip.setAttribute("data-tooltip", "Show entries tagged " + name);
      }
      box.appendChild(chip);
    });
  }

  // Shows the entry's sets with a remove control, and a picker for the sets it is not in.
  function renderSets(entry) {
    var box = byId("lb-sets");
    box.textContent = "";
    if (!entry.sets.length) box.appendChild(makeEl("span", "lightbox-none", "No sets."));
    entry.sets.forEach(function (item) {
      var chip = makeEl("span", "status-chip status-chip-outlined-accent", item.name);
      var known = allSets.filter(function (set) { return set.id === item.id; })[0];
      var isCover = Boolean(known && known.cover_entry_id === entry.id);
      var coverLabel = isCover ? "Cover of " + item.name + " - use the newest image instead" : "Make cover of " + item.name;
      var cover = makeEl("button", "lightbox-chip-cover");
      cover.innerHTML = '<svg class="icon-glyph-sm" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/></svg>';
      cover.type = "button";
      cover.setAttribute("data-set", item.id);
      cover.setAttribute("aria-pressed", isCover ? "true" : "false");
      cover.setAttribute("aria-label", coverLabel);
      cover.setAttribute("data-tooltip", coverLabel);
      chip.appendChild(cover);
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

  // Lists other entries holding the same or a visually near image; each chip opens that entry.
  function renderDuplicates(entry) {
    var box = byId("lb-duplicates");
    var items = entry.duplicates || [];
    box.textContent = "";
    box.hidden = !items.length;
    byId("lb-duplicates-label").hidden = !items.length;
    items.forEach(function (item) {
      var title = displayTitle(item);
      var chip = makeEl("button", "status-chip status-chip-outlined-muted lightbox-tag", title);
      chip.type = "button";
      chip.setAttribute("data-entry", item.id);
      chip.setAttribute("data-tooltip", "Open " + title);
      box.appendChild(chip);
    });
  }

  // Shows the source link with its service chip, plus the collection and posted date when known.
  function renderSource(entry) {
    var box = byId("lb-source");
    var origin = entry.source || {};
    box.textContent = "";
    if (!entry.source_url) {
      box.appendChild(makeEl("span", "lightbox-none", "No source."));
    } else {
      var link = makeEl("a", "", entry.source_url.replace(/^https?:\/\//, ""));
      link.href = entry.source_url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      box.appendChild(link);
    }
    if (origin.source_service) {
      var service = origin.source_service;
      box.appendChild(makeEl("span", "status-chip status-chip-outlined-muted lightbox-service", service.charAt(0).toUpperCase() + service.slice(1)));
    }
    var extras = { collection: origin.collection, posted: (origin.posted_at || "").slice(0, 10) };
    Object.keys(extras).forEach(function (name) {
      var value = byId("lb-" + name);
      value.textContent = extras[name] || "";
      value.hidden = !extras[name];
      byId("lb-" + name + "-label").hidden = !extras[name];
    });
  }

  // The image's dominant swatches, shown as a thin color bar under the title.
  function renderSwatches(entry) {
    var box = byId("lb-swatches");
    box.textContent = "";
    var empty = !entry.swatches || !entry.swatches.length;
    box.hidden = empty;
    if (!empty) replay(box);
    (entry.swatches || []).forEach(function (hex) {
      var chip = makeEl("button", "lightbox-swatch");
      chip.type = "button";
      chip.style.backgroundColor = hex;
      chip.setAttribute("data-color", hex);
      chip.setAttribute("aria-label", "Show entries with a color like " + hex);
      chip.setAttribute("data-tooltip", hex + " - show similar");
      box.appendChild(chip);
    });
  }

  function renderStatus(entry) {
    var box = byId("lb-status");
    box.textContent = "";
    if (entry.state === "pending") {
      box.appendChild(makeEl("span", "status-chip status-chip-outlined-muted", "Pending"));
    } else if (entry.state === "failed") {
      box.appendChild(makeEl("span", "status-chip status-chip-outlined-accent lightbox-failed", "Failed"));
      box.appendChild(makeEl("span", "lightbox-none", (entry.failure || "Could not read the page.") + (entry.source_url ? " Try again, or fill in the fields." : " Fill in the fields.")));
      if (entry.source_url) {
        var retry = makeEl("button", "action-button action-button-ghost lightbox-retry", "Try again");
        retry.type = "button";
        box.appendChild(retry);
      }
    }
  }

  // Queues the open failed entry for another capture; it shows as pending until done.
  function onRetry(event) {
    var bridge = api();
    if (!event.target.closest(".lightbox-retry") || !bridge || !bridge.recapture_entries || !current) return;
    event.target.disabled = true;
    Promise.resolve(bridge.recapture_entries([current.id])).then(function (count) {
      if (!count) { toast("error", "Could not retry."); event.target.disabled = false; return; }
      reloadEntry("Trying again.");
    }).catch(function () { toast("error", "Could not retry."); event.target.disabled = false; });
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

  // Fades the image out, swaps its source, then fades the new one in.
  function swapImage(image, uri) {
    var mySwap = ++swapToken;
    if (image.getAttribute("src") === uri) { image.classList.remove("is-swapping"); return; }
    var apply = function () {
      if (mySwap !== swapToken) return;
      image.addEventListener("load", function done() { image.removeEventListener("load", done); image.classList.remove("is-swapping"); });
      image.src = uri;
    };
    if (!image.getAttribute("src") || image.classList.contains("is-swapping") || parseFloat(getComputedStyle(image).transitionDuration) === 0) { apply(); return; }
    image.classList.add("is-swapping");
    image.addEventListener("transitionend", function done(event) {
      if (event.propertyName !== "opacity") return;
      image.removeEventListener("transitionend", done);
      apply();
    });
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
      image.classList.remove("is-swapping");
      return;
    }
    var mine = ticket;
    if (!lb.open) {
      image.removeAttribute("src");
      image.classList.add("is-swapping");
    }
    if (imageCache[asset.id]) {
      swapImage(image, imageCache[asset.id]);
      return;
    }
    loadImage(asset).then(function (uri) {
      if (mine === ticket && current && current.assets[assetIndex] === asset && uri) swapImage(image, uri);
    });
  }

  // Restarts the fade-in on an element so a content change reads as a transition.
  function replay(el) {
    el.classList.remove("lightbox-swap");
    void el.offsetWidth;
    el.classList.add("lightbox-swap");
  }

  function render() {
    var entry = current;
    if (lb.open) replay(document.querySelector(".lightbox-rail"));
    byId("lb-title").textContent = displayTitle(entry);
    renderCaption(entry);
    renderDescription(entry);
    renderStatus(entry);
    renderSwatches(entry);
    renderSource(entry);
    renderChips(byId("lb-tags"), entry.tags, "status-chip-outlined-muted", "No tags.", true);
    renderSets(entry);
    renderDuplicates(entry);
    byId("act-save").hidden = !entry.assets.length;
    byId("act-save-all").hidden = entry.assets.length < 2;
    var blank = !entry.source_url && !FORM_FIELDS.some(function (name) { return entry[name]; });
    var editLabel = entry.state === "failed" || blank ? "Fill in" : "Edit";
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

  // Plays the exit animation, then closes the dialog; the scrim fades out alongside.
  function closeDialog() {
    if (!lb.open || lb.hasAttribute("data-closing")) return;
    lb.setAttribute("data-closing", "true");
    byId("lb-scrim").classList.remove("visible");
    var finish = function () { lb.removeAttribute("data-closing"); lb.close(); };
    if (getComputedStyle(lb).animationName === "lightboxOut") {
      lb.addEventListener("animationend", function done(event) {
        if (event.target !== lb) return;
        lb.removeEventListener("animationend", done);
        finish();
      });
    } else {
      finish();
    }
  }

  function closeForm() {
    byId("lb-form").hidden = true;
    byId("lb-view").hidden = false;
    byId("lb-actions").hidden = false;
    if (lb.open) { replay(byId("lb-view")); replay(byId("lb-actions")); }
  }

  function openForm() {
    if (!current) return;
    FORM_FIELDS.forEach(function (name) { byId("f-" + name).value = current[name] || ""; });
    byId("f-tags").value = (current.tags || []).join(", ");
    byId("lb-view").hidden = true;
    byId("lb-form").hidden = false;
    byId("lb-actions").hidden = true;
    replay(byId("lb-form"));
    byId("f-creator").focus();
  }

  // Fetches an entry and shows it in the dialog; resolves true once it is shown.
  function openEntry(id, trigger) {
    var bridge = api();
    if (!bridge || !bridge.get_entry) return Promise.resolve(false);
    var mine = ++ticket;
    if (trigger) returnFocus = trigger;
    var sets = bridge.list_sets ? Promise.resolve(bridge.list_sets()).catch(function () { return []; }) : Promise.resolve([]);
    return Promise.all([bridge.get_entry(id), sets]).then(function (loaded) {
      var entry = loaded[0];
      allSets = loaded[1] || [];
      if (mine !== ticket) return false;
      if (!entry) {
        toast("error", "Entry not found.");
        changed();
        return false;
      }
      current = entry;
      assetIndex = 0;
      closeForm();
      render();
      if (!lb.open) openDialog();
      lb.focus();
      return true;
    }).catch(function () { toast("error", "Could not open entry."); return false; });
  }

  function cycleAsset(step) {
    if (!current || current.assets.length < 2) return;
    assetIndex = (assetIndex + step + current.assets.length) % current.assets.length;
    renderImage();
  }

  // Moves to the neighboring entry card in the grid; stops at either end. On a trail only library tiles count.
  function moveEntry(step) {
    if (!current) return;
    var key = entryKey();
    var cards = Array.prototype.slice.call(document.querySelectorAll("#library-grid [" + key + "]"));
    var index = cards.findIndex(function (card) { return Number(card.getAttribute(key)) === current.id; });
    var next = cards[index + step];
    if (index < 0 || !next) return;
    returnFocus = next;
    openEntry(Number(next.getAttribute(key)));
  }

  // Grid cards name their entry in data-id, except in a find view (a trail), where data-entry does.
  function entryKey() {
    return document.querySelector("#library[data-finding]") ? "data-entry" : "data-id";
  }

  function onSubmit(event) {
    event.preventDefault();
    var bridge = api();
    if (!bridge || !bridge.update_entry || !current) return;
    var values = {};
    FORM_FIELDS.forEach(function (name) { values[name] = byId("f-" + name).value; });
    values.tags = byId("f-tags").value;
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

  // Opens the shared menu of sets the entry is not yet in, anchored to the add button.
  function onPlaceMenu(event) {
    var add = event.target.closest("#lb-place");
    if (!add || !window.HvContextMenu || !current) return;
    event.stopPropagation();
    window.HvContextMenu.openFor(add, placeItems());
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

  // Makes the open entry its set's cover, or with the cover pressed hands it back to the newest image.
  function onSetCover(event) {
    var button = event.target.closest(".lightbox-chip-cover");
    var bridge = api();
    if (!button || !bridge || !bridge.set_cover || !current) return;
    var setId = Number(button.getAttribute("data-set"));
    var making = button.getAttribute("aria-pressed") !== "true";
    Promise.resolve(bridge.set_cover(setId, making ? current.id : null)).then(function (ok) {
      if (!ok) { toast("error", "Could not change the cover."); return; }
      allSets.forEach(function (item) { if (item.id === setId) item.cover_entry_id = making ? current.id : null; });
      render();
      toast("success", making ? "Set as cover." : "Cover set back to the newest image.");
      changed();
    }).catch(function () { toast("error", "Could not change the cover."); });
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
      var discardedId = current.id;
      closeDialog();
      toast("success", "Discarded " + title + ".");
      document.dispatchEvent(new CustomEvent("hyperbridge:discarded", { detail: { id: discardedId } }));
    }).catch(function () { toast("error", "Could not discard."); });
  }

  function onKey(event) {
    if (event.key === "Escape") { closeDialog(); event.preventDefault(); return; }
    var tag = (event.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") return;
    if (!current) return;
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
    document.dispatchEvent(new CustomEvent("hyperbridge:lightbox-closed"));
    if (!returnFocus) return;
    var key = entryKey();
    var id = returnFocus.getAttribute(key);
    var card = document.querySelector("#library-grid [" + key + '="' + id + '"]');
    if (card) card.focus();
  }

  // Toggles the stage between filling the space (default) and showing the whole image with margins; persists.
  function setupFit() {
    var button = byId("lb-fit");
    function apply(mode) {
      lb.setAttribute("data-fit", mode);
      var label = mode === "fit" ? "Fill the space" : "Show full image";
      button.setAttribute("aria-label", label);
      button.setAttribute("data-tooltip", label);
      try { localStorage.setItem("hyperbridge-fit", mode); } catch (err) { /* ignore */ }
    }
    var fallback = window.hbDefault && window.hbDefault("lightbox_fit", "fill") === "fit" ? "fit" : "fill";
    var saved = fallback;
    try {
      var stored = localStorage.getItem("hyperbridge-fit");
      saved = stored === "fit" || stored === "fill" ? stored : fallback;
    } catch (err) { saved = fallback; }
    apply(saved);
    button.addEventListener("click", function () { apply(lb.getAttribute("data-fit") === "fit" ? "fill" : "fit"); });
  }

  // Opens the current asset at its native pixel size in a scrollable full-window view.
  function openFull() {
    var asset = current && current.assets[assetIndex];
    var view = byId("full-view");
    if (!asset || !view) return;
    loadImage(asset).then(function (uri) {
      if (!uri) { toast("error", "Could not load the image."); return; }
      byId("full-view-image").src = uri;
      if (!view.open) view.showModal();
      byId("full-view-scroll").scrollTo(0, 0);
    });
  }

  function setupFull() {
    var view = byId("full-view");
    byId("lb-full").addEventListener("click", openFull);
    byId("full-view-close").addEventListener("click", function () { view.close(); });
    byId("full-view-image").addEventListener("click", function () { view.close(); });
    // Drops the image once the fade-out ends, unless the viewer reopened meanwhile.
    var clear = function () { if (!view.open) byId("full-view-image").removeAttribute("src"); };
    view.addEventListener("close", function () {
      if (parseFloat(getComputedStyle(view).transitionDuration) === 0) clear();
    });
    view.addEventListener("transitionend", function (event) {
      if (event.target === view && event.propertyName === "opacity") clear();
    });
  }

  function init() {
    lb = byId("lightbox");
    if (!lb) return;
    setupFull();
    document.addEventListener("hyperbridge:open", function (event) {
      var id = event.detail.id;
      openEntry(id, document.querySelector("#library-grid [" + entryKey() + '="' + id + '"]'));
    });
    setupFit();
    byId("lb-prev").addEventListener("click", function () { cycleAsset(-1); });
    byId("lb-next").addEventListener("click", function () { cycleAsset(1); });
    byId("lb-strip").addEventListener("click", function (event) {
      var dot = event.target.closest(".lightbox-dot");
      if (!dot) return;
      assetIndex = Number(dot.getAttribute("data-asset"));
      renderImage();
    });
    byId("lb-scrim").addEventListener("click", closeDialog);
    lb.addEventListener("close", onClosed);
    lb.addEventListener("keydown", onKey);
    byId("act-edit").addEventListener("click", openForm);
    byId("act-trail").addEventListener("click", function () {
      if (current) document.dispatchEvent(new CustomEvent("hyperbridge:trail", { detail: { entry: current.id } }));
    });
    byId("act-discard").addEventListener("click", onDiscard);
    byId("act-save").addEventListener("click", onSaveAsset);
    byId("act-save-all").addEventListener("click", onSaveAll);
    byId("lb-sets").addEventListener("click", onPlaceMenu);
    byId("lb-sets").addEventListener("click", onSetRemove);
    byId("lb-sets").addEventListener("click", onSetCover);
    byId("lb-status").addEventListener("click", onRetry);
    byId("f-cancel").addEventListener("click", function () {
      closeForm();
      render();
      toast("info", "Cancelled.");
    });
    byId("lb-form").addEventListener("submit", onSubmit);
    byId("lb-swatches").addEventListener("click", function (event) {
      var chip = event.target.closest("[data-color]");
      if (!chip) return;
      document.dispatchEvent(new CustomEvent("hyperbridge:color", { detail: { color: chip.getAttribute("data-color") } }));
      closeDialog();
    });
    byId("lb-tags").addEventListener("click", function (event) {
      var chip = event.target.closest("[data-tag]");
      if (!chip) return;
      document.dispatchEvent(new CustomEvent("hyperbridge:tag", { detail: { tag: chip.getAttribute("data-tag") } }));
      closeDialog();
    });
    byId("lb-duplicates").addEventListener("click", function (event) {
      var chip = event.target.closest("[data-entry]");
      if (!chip) return;
      openEntry(Number(chip.getAttribute("data-entry")));
    });
  }

  init();
  window.HbLightbox = {
    openEntry: function (id) { return openEntry(id); },
    close: closeDialog,
    isOpen: function () { return Boolean(lb && lb.open); },
  };
})();
