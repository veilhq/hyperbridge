  var DISCARD_ICON = '<svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>';

  var SAVED_ICON = '<svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>';

  // Glows a card red with an x (or in the success color with a check when saved), then collapses it; resolves when the card is gone.
  function playDiscardCard(card, saved) {
    return new Promise(function (resolve) {
      var mark = makeEl("span", saved ? "library-discard-mark library-saved-mark" : "library-discard-mark");
      mark.innerHTML = saved ? SAVED_ICON : DISCARD_ICON;
      card.appendChild(mark);
      card.classList.add("library-card-discarding");
      if (getComputedStyle(mark).animationName === "none") { resolve(); return; }
      mark.addEventListener("animationend", function () {
        card.style.height = card.offsetHeight + "px";
        void card.offsetHeight;
        card.classList.add("library-card-collapse");
        card.style.height = "0px";
        if (parseFloat(getComputedStyle(card).transitionDuration) === 0) { resolve(); return; }
        card.addEventListener("transitionend", function (event) { if (event.propertyName === "height") resolve(); });
      });
    });
  }

  function playDiscard(ids, saved) {
    var cards = ids.map(function (id) { return grid.querySelector('[data-id="' + id + '"]'); }).filter(Boolean);
    return Promise.all(cards.map(function (card) { return playDiscardCard(card, saved); }));
  }

  function afterDiscard() {
    load(true);
    refreshStats();
    changed();
  }

  function discard(entry) {
    var bridge = api();
    Promise.resolve(bridge.discard_entry(entry.id)).then(function (ok) {
      if (ok) {
        toast("success", "Discarded " + (entry.title || entry.domain || "entry") + ".");
        playDiscard([entry.id]).then(afterDiscard);
      } else {
        toast("error", "Could not discard.");
      }
    }).catch(function () { toast("error", "Could not discard."); });
  }

  // Selection: Ctrl/Cmd-click toggles, Shift-click selects a range, and any click toggles while a selection exists.
  function paintSelection() {
    grid.querySelectorAll(".library-card").forEach(function (card) {
      if (selected.has(Number(card.getAttribute("data-id")))) card.setAttribute("data-selected", "true");
      else card.removeAttribute("data-selected");
    });
    $("#select-bar").hidden = !selected.size;
    $("#select-count").textContent = selected.size + " selected";
    var picking = !!candidates;
    $("#sel-accept").hidden = !picking;
    $("#sel-remove").hidden = picking || !state.setId;
    var feedMode = picking && candidates.feed;
    $("#sel-add").hidden = (picking && !feedMode) || !setsCache.length;
    $("#sel-tag").hidden = picking || !tagsCache.length;
    $("#sel-save").hidden = picking;
    $("#sel-recapture").hidden = picking;
    $("#sel-discard").hidden = picking && !feedMode;
  }

  function clearSelection() {
    if (!selected.size) return;
    selected.clear();
    anchorId = null;
    paintSelection();
  }

  function toggleSelected(id) {
    if (selected.has(id)) selected.delete(id);
    else selected.add(id);
    anchorId = id;
    paintSelection();
  }

  function visibleIds() {
    if (candidates) return candidates.candidates.map(function (item, index) { return index; });
    return state.entries.map(function (entry) { return entry.id; });
  }

  function selectRange(id) {
    var ids = visibleIds();
    var from = ids.indexOf(anchorId);
    var to = ids.indexOf(id);
    if (from < 0 || to < 0) {
      toggleSelected(id);
      return;
    }
    ids.slice(Math.min(from, to), Math.max(from, to) + 1).forEach(function (item) { selected.add(item); });
    paintSelection();
  }

  function onCardClick(event, id) {
    if (event.shiftKey && anchorId !== null) selectRange(id);
    else if (event.shiftKey || event.ctrlKey || event.metaKey || selected.size) toggleSelected(id);
    else document.dispatchEvent(new CustomEvent("hyperbridge:open", { detail: { id: id } }));
  }

  function selectedIds() { return Array.from(selected); }

  // Runs a bridge call per selected id and reports how many succeeded.
  function bulk(call, done) {
    var ids = selectedIds();
    return Promise.all(ids.map(function (id) {
      return Promise.resolve(call(id)).then(function (ok) { return !!ok; }).catch(function () { return false; });
    })).then(function (results) {
      done(results.filter(Boolean).length, ids.length);
    });
  }

  function bulkPlace(item) {
    var bridge = api();
    bulk(function (id) { return bridge.place_entry(id, item.id); }, function (ok, total) {
      toast(ok === total ? "success" : "error", ok === total ? "Placed " + ok + "." : "Placed " + ok + " of " + total + ".");
      changed();
    });
  }

  function bulkTag(item) {
    var bridge = api();
    Promise.resolve(bridge.add_tags(selectedIds(), item.name)).then(function (count) {
      toast(count ? "success" : "error", count ? "Tagged " + count + "." : "Could not tag.");
      loadTags();
      changed();
    }).catch(function () { toast("error", "Could not tag."); });
  }

  function bulkRemove() {
    var bridge = api();
    var setId = state.setId;
    if (!setId) return;
    bulk(function (id) { return bridge.remove_entry(id, setId); }, function (ok) {
      toast("success", "Removed " + ok + ".");
      clearSelection();
      load(true);
      changed();
    });
  }

  function bulkSave() {
    var bridge = api();
    Promise.resolve(bridge.save_entries_assets(selectedIds())).then(reportSave).catch(function () { toast("error", "Could not save images."); });
  }

  // Fetches the selected link entries again so their images are saved at full size; they show as capturing until done.
  function bulkRecapture() {
    var bridge = api();
    Promise.resolve(bridge.recapture_entries(selectedIds())).then(function (count) {
      toast(count ? "success" : "error", count ? "Re-capturing " + count + (count === 1 ? " entry." : " entries.") : "Nothing to re-capture. Pasted and dropped images have no source link.");
      clearSelection();
      load(true);
    }).catch(function () { toast("error", "Could not re-capture."); });
  }

  function bulkDiscard() {
    if (candidates && candidates.feed) { dismissFeed(); return; }
    var bridge = api();
    var ids = selectedIds();
    bulk(function (id) { return bridge.discard_entry(id); }, function (ok, total) {
      toast(ok === total ? "success" : "error", ok === total ? "Discarded " + ok + "." : "Discarded " + ok + " of " + total + ".");
      clearSelection();
      (ok === total ? playDiscard(ids) : Promise.resolve()).then(afterDiscard);
    });
  }

  function setMenuItems() {
    return setsCache.map(function (item) {
      return { label: escapeHtml(item.name), action: function () {
        if (candidates && candidates.feed) acceptFeed(item.id);
        else bulkPlace(item);
      } };
    });
  }

  function tagMenuItems() {
    return tagsCache.map(function (item) {
      return { label: escapeHtml(item.name), action: function () { bulkTag(item); } };
    });
  }

  function bulkMenuItems() {
    var items = [];
    if (setsCache.length) items.push({ label: "Add to set", children: setMenuItems() });
    if (tagsCache.length) items.push({ label: "Add tag", children: tagMenuItems() });
    if (state.setId) items.push({ label: "Remove from set", action: bulkRemove });
    items.push({ label: "Download", action: bulkSave });
    items.push({ label: "Re-capture at full size", action: bulkRecapture });
    items.push({ separator: true });
    items.push({ label: "Discard " + selected.size, action: bulkDiscard });
    return items;
  }

  // Opens the add-to-set or tag menu beside the button that was clicked.
  function openSetMenu(event) {
    event.stopPropagation();
    if (!window.HvContextMenu) return;
    var button = event.currentTarget;
    window.HvContextMenu.openFor(button, button.id === "sel-tag" ? tagMenuItems() : setMenuItems());
  }

  function setupSelection() {
    $("#sel-accept").addEventListener("click", acceptCandidates);
    $("#sel-add").addEventListener("click", openSetMenu);
    $("#sel-tag").addEventListener("click", openSetMenu);
    $("#sel-remove").addEventListener("click", bulkRemove);
    $("#sel-save").addEventListener("click", bulkSave);
    $("#sel-recapture").addEventListener("click", bulkRecapture);
    $("#sel-discard").addEventListener("click", bulkDiscard);
    $("#sel-clear").addEventListener("click", clearSelection);
    document.addEventListener("keydown", function (event) {
      if ($("#app").inert) return;
      var tag = event.target && event.target.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (!event.ctrlKey && !event.metaKey && !event.altKey && (event.key === "+" || event.key === "=")) {
        zoomColumns(1);
      } else if (!event.ctrlKey && !event.metaKey && !event.altKey && (event.key === "-" || event.key === "_")) {
        zoomColumns(-1);
      } else if (event.key === "Escape") {
        if (selected.size) clearSelection();
        else if (candidates && candidates.feed) $("#sets-all").click();
        else if (candidates) leaveCandidates();
        else if (finding) setFinding(false);
      } else if ((event.ctrlKey || event.metaKey) && (event.key === "a" || event.key === "A")) {
        event.preventDefault();
        visibleIds().forEach(function (id) { selected.add(id); });
        paintSelection();
      }
    });
  }

  // Right-click menu for a grid card.
  function setupMenu() {
    if (!window.HvContextMenu) return;
    window.HvContextMenu.register(".library-card[data-id]", function (card) {
      var id = Number(card.getAttribute("data-id"));
      var entry = state.entries.find(function (item) { return item.id === id; });
      var bridge = api();
      if (!entry || !bridge) return [];
      if (selected.size > 1 && selected.has(id)) return bulkMenuItems();
      var items = [
        { label: "Open", action: function () { document.dispatchEvent(new CustomEvent("hyperbridge:open", { detail: { id: id } })); } },
        { label: "Open source", action: function () { openSource(id); } },
        { label: "Download", action: function () {
          Promise.resolve(bridge.save_entry_assets(id)).then(reportSave).catch(function () { toast("error", "Could not save images."); });
        } },
      ];
      if (setsCache.length) {
        items.push({
          label: "Add to set",
          children: setsCache.map(function (item) {
            return { label: escapeHtml(item.name), action: function () { placeIn(id, item); } };
          }),
        });
      }
      if (state.setId) {
        items.push({ label: "Remove from set", action: function () {
          Promise.resolve(bridge.remove_entry(id, state.setId)).then(function () { load(true); changed(); });
        } });
      }
      items.push({ separator: true });
      items.push({ label: "Discard", action: function () { discard(entry); } });
      return items;
    });
  }
