  // Placeholder for a capture in flight: a breathing glow and a label.
  function buildPending() {
    var panel = makeEl("span", "library-pending");
    var icon = makeEl("span", "library-pending-icon");
    icon.setAttribute("role", "img");
    icon.setAttribute("aria-label", "Capturing");
    icon.innerHTML = '<svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14"/><path d="M12 5v14"/></svg>';
    panel.appendChild(icon);
    return panel;
  }

  // Reserves an image's height before it loads so lazy images never resize the grid; an unknown size is corrected on load without moving the view.
  function reserveSpace(img, width, height) {
    if (width && height) { img.style.aspectRatio = width + " / " + height; return; }
    img.style.aspectRatio = "4 / 3";
    img.addEventListener("load", function () {
      if (!img.naturalWidth || !img.naturalHeight) return;
      var scroller = document.getElementById("library");
      var before = img.offsetHeight;
      var above = scroller && img.getBoundingClientRect().bottom < scroller.getBoundingClientRect().top;
      img.style.aspectRatio = img.naturalWidth + " / " + img.naturalHeight;
      if (above) scroller.scrollTop += img.offsetHeight - before;
    });
  }

  // Builds one entry card as a focusable button that announces its id on click.
  function buildCard(entry, reveal) {
    var card = makeEl("button", "library-card");
    card.type = "button";
    card.setAttribute("data-id", entry.id);
    card.setAttribute("aria-label", "Open " + (entry.title || entry.domain || "entry"));

    if (entry.thumb) {
      var img = document.createElement("img");
      img.className = "library-card-image";
      img.src = entry.thumb;
      img.alt = "";
      img.loading = "lazy";
      img.decoding = "async";
      reserveSpace(img, entry.width, entry.height);
      if (reveal) {
        // A capture that just finished fades its image in instead of popping.
        img.classList.add("library-card-reveal");
        var show = function () { img.classList.add("is-loaded"); };
        img.addEventListener("load", show);
        img.addEventListener("error", show);
        if (img.complete) requestAnimationFrame(show);
      }
      card.appendChild(img);
    } else if (entry.state === "pending") {
      card.appendChild(buildPending());
      card.setAttribute("data-pending", "true");
    } else {
      card.appendChild(makeEl("span", "library-thumb-empty"));
    }

    if (entry.state === "failed") {
      card.appendChild(makeEl("span", "library-card-flag library-failed status-chip status-chip-outlined-accent", "Failed"));
    }

    var body = makeEl("span", "library-card-details");
    body.appendChild(makeEl("span", "library-card-title", entry.title || "Untitled"));
    var caption = (entry.caption || []).join(" / ");
    if (caption) body.appendChild(makeEl("span", "library-card-caption", caption));
    else if (entry.domain) body.appendChild(makeEl("span", "library-card-domain", entry.domain));
    card.appendChild(body);

    if (selected.has(entry.id)) card.setAttribute("data-selected", "true");
    card.addEventListener("click", function (event) { onCardClick(event, entry.id); });
    return card;
  }

  // Builds a candidate card for a found, feed or trail image; clicking toggles its selection, except that a
  // library entry on a trail opens in the lightbox while nothing is selected.
  function buildCandidate(item, index) {
    var card = makeEl("button", "library-card");
    card.type = "button";
    card.setAttribute("data-id", index);
    if (item.feedId) card.setAttribute("data-key", "feed-" + item.feedId);
    if (item.entryId) card.setAttribute("data-entry", item.entryId);
    card.setAttribute("aria-label", item.entryId ? "Open " + (item.title || "entry")
      : "Select image " + (index + 1) + (item.fresh ? ", new" : "") + (item.fromCandidate ? ", from a new source" : ""));
    var img = document.createElement("img");
    img.className = "library-card-image";
    img.src = item.thumb;
    img.alt = "";
    reserveSpace(img, item.width, item.height);
    card.appendChild(img);
    if (item.known_entry_id || item.aiLabel || item.fresh || item.fromCandidate) {
      var flags = card.appendChild(makeEl("span", "library-card-flags"));
      if (item.fresh) {
        var fresh = flags.appendChild(makeEl("span", "status-chip status-chip-filled library-card-fresh"));
        fresh.setAttribute("data-tooltip", "New since your last visit");
        fresh.innerHTML = '<svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594-1.594z"/></svg>';
      }
      if (item.fromCandidate) {
        var sprout = flags.appendChild(makeEl("span", "status-chip status-chip-filled library-card-fresh"));
        sprout.setAttribute("data-tooltip", "New source: " + item.followLabel);
        sprout.innerHTML = '<svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 20h10"/><path d="M10 20c5.5-2.5.8-6.4 3-10"/><path d="M9.5 9.4c1.1.8 1.8 2.2 2.3 3.7-2 .4-3.5.4-4.8-.3-1.2-.6-2.3-1.9-3-4.2 2.8-.5 4.4 0 5.5.8z"/><path d="M14.1 6a7 7 0 0 0-1.1 4c1.9-.1 3.3-.6 4.3-1.4 1-1 1.6-2.3 1.7-4.6-2.7.1-4 1-4.9 2z"/></svg>';
      }
      if (item.known_entry_id) flags.appendChild(makeEl("span", "status-chip status-chip-outlined-accent", "Captured")).setAttribute("data-tooltip", "Already in the library");
      if (item.aiLabel) flags.appendChild(makeEl("span", "status-chip status-chip-outlined-accent", "AI label")).setAttribute("data-tooltip", item.aiLabel);
    }
    // A blurred AI-labeled image clears for good once it is selected.
    if (item.veiled) card.setAttribute("data-veiled", "true");
    var details = card.appendChild(makeEl("span", "library-card-details"));
    if (item.feedId || item.entryId) {
      if (item.title) details.appendChild(makeEl("span", "library-card-title", item.title));
      details.appendChild(makeEl("span", "library-card-domain", item.creator || item.source));
      if (item.matched && item.matched.length) details.appendChild(makeEl("span", "library-card-domain", "Like: " + item.matched.join(", ")));
    } else {
      details.appendChild(makeEl("span", "library-card-domain", item.section || (item.width + " x " + item.height)));
    }
    if (selected.has(index)) card.setAttribute("data-selected", "true");
    card.addEventListener("click", function (event) {
      if (item.veiled) { item.veiled = false; card.removeAttribute("data-veiled"); }
      if (item.entryId && !selected.size && !event.shiftKey && !event.ctrlKey && !event.metaKey) {
        document.dispatchEvent(new CustomEvent("hyperbridge:open", { detail: { id: item.entryId } }));
      } else if (event.shiftKey && anchorId !== null) selectRange(index);
      else toggleSelected(index);
    });
    return card;
  }

  function hostOf(pageUrl) {
    try { return new URL(pageUrl).hostname.replace(/^www\./, ""); } catch (err) { return pageUrl; }
  }

  // Opens the find view straight away with placeholder tiles while the page is read.
  function showFinding(pageUrl) {
    clearTrail();
    candidates = { page_url: pageUrl, candidates: [] };
    clearSelection();
    emptyEl.hidden = true;
    $("#library-meta").hidden = true;
    grid.removeAttribute("data-columns");
    grid.style.columns = "";
    grid.textContent = "";
    var fragment = document.createDocumentFragment();
    for (var i = 0; i < 12; i++) {
      var tile = makeEl("div", "library-card loading-skeleton");
      tile.style.aspectRatio = SKELETON_RATIOS[i % SKELETON_RATIOS.length];
      fragment.appendChild(tile);
    }
    grid.appendChild(fragment);
    grid.setAttribute("aria-busy", "true");
    $("#library").setAttribute("data-finding", "true");
    $("#find-head").hidden = false;
    $("#find-head-title").textContent = hostOf(pageUrl);
    $("#find-head-desc").textContent = "Finding images...";
  }

  // Replaces the placeholder tiles with the images found on the page, for choosing which join the open set.
  function showCandidates(result) {
    candidates = result;
    grid.removeAttribute("aria-busy");
    clearSelection();
    emptyEl.hidden = true;
    grid.textContent = "";
    var fragment = document.createDocumentFragment();
    result.candidates.forEach(function (item, index) { fragment.appendChild(buildCandidate(item, index)); });
    grid.appendChild(fragment);
    cascadeIn();
    var host = hostOf(result.page_url);
    var count = result.candidates.length;
    $("#find-head-title").textContent = result.title || host;
    $("#find-head-desc").textContent = count + (count === 1 ? " image" : " images") + " found on " + host + ". Select the ones to add to this set.";
    if (!result.candidates.length) {
      emptyEl.textContent = "No usable images found. Pages that load images with scripts are not readable yet; public Pinterest board links are the exception.";
      emptyEl.hidden = false;
    }
  }
