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

  // Builds a candidate card for an image found on a pasted page; clicking always toggles its selection.
  function buildCandidate(item, index) {
    var card = makeEl("button", "library-card");
    card.type = "button";
    card.setAttribute("data-id", index);
    if (item.feedId) card.setAttribute("data-key", "feed-" + item.feedId);
    card.setAttribute("aria-label", "Select image " + (index + 1));
    var img = document.createElement("img");
    img.className = "library-card-image";
    img.src = item.thumb;
    img.alt = "";
    reserveSpace(img, item.width, item.height);
    card.appendChild(img);
    if (item.known_entry_id) card.appendChild(makeEl("span", "library-card-flag status-chip status-chip-outlined-accent", "Saved"));
    var details = card.appendChild(makeEl("span", "library-card-details"));
    if (item.feedId) {
      if (item.title) details.appendChild(makeEl("span", "library-card-title", item.title));
      details.appendChild(makeEl("span", "library-card-domain", item.creator || item.source));
    } else {
      details.appendChild(makeEl("span", "library-card-domain", item.section || (item.width + " x " + item.height)));
    }
    if (selected.has(index)) card.setAttribute("data-selected", "true");
    card.addEventListener("click", function (event) {
      if (event.shiftKey && anchorId !== null) selectRange(index);
      else toggleSelected(index);
    });
    return card;
  }

  function hostOf(pageUrl) {
    try { return new URL(pageUrl).hostname.replace(/^www\./, ""); } catch (err) { return pageUrl; }
  }

  // Opens the find view straight away with placeholder tiles while the page is read.
  function showFinding(pageUrl) {
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
