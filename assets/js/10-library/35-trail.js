  // Trails: following where an image leads, one place at a time, as a grid. Each step starts from an image and shows
  // one of the places it leads to; right-clicking a tile starts the next step from that tile.
  var TRAIL_ICONS = {
    channel: '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
    user: '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    creator: '<path d="m16 11 2 2 4-4"/><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>',
    blog: '<path d="M4 11a9 9 0 0 1 9 9"/><path d="M4 4a16 16 0 0 1 16 16"/><circle cx="5" cy="19" r="1"/>',
    site: '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>',
    tag: '<path d="M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z"/><circle cx="7.5" cy="7.5" r=".5" fill="currentColor"/>',
    color: '<circle cx="13.5" cy="6.5" r=".5" fill="currentColor"/><circle cx="17.5" cy="10.5" r=".5" fill="currentColor"/><circle cx="8.5" cy="7.5" r=".5" fill="currentColor"/><circle cx="6.5" cy="12.5" r=".5" fill="currentColor"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z"/>',
    cooling: '<path d="M5 22h14"/><path d="M5 2h14"/><path d="M17 22v-4.172a2 2 0 0 0-.586-1.414L12 12l-4.414 4.414A2 2 0 0 0 7 17.828V22"/><path d="M7 2v4.172a2 2 0 0 0 .586 1.414L12 12l4.414-4.414A2 2 0 0 0 17 6.172V2"/>',
    follow: '<path d="M5 12h14"/><path d="M12 5v14"/>',
    followed: '<path d="M20 6 9 17l-5-5"/>',
    yes: '<path d="M20 6 9 17l-5-5"/>',
    no: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  };
  var TRAIL_KIND_NAMES = { channel: "Are.na channel", user: "Are.na profile", blog: "Tumblr blog", site: "site", creator: "creator",
    tag: "tag", color: "color", credit: "credit" };
  var LIBRARY_PLACES = ["creator", "credit", "tag", "color"];
  var RABBIT_ICON = '<svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13 16a3 3 0 0 1 2.24 5"/><path d="M18 12h.01"/><path d="M18 21h-8a4 4 0 0 1-4-4 7 7 0 0 1 7-7h.2L9.6 6.4a1 1 0 1 1 2.8-2.8L15.8 7h.2c3.3 0 6 2.7 6 6v1a2 2 0 0 1-2 2h-1a3 3 0 0 0-3 3"/><path d="M20 8.54V4a2 2 0 1 0-4 0v3"/><path d="M7.612 12.524a3 3 0 1 0-1.6 4.3"/></svg>';
  // The open trail: {id, back, left, steps: [{origin, hops, active, images, more, checking, loading, places}]}.
  var trail = null;

  function trailGlyph(name) {
    return '<svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + TRAIL_ICONS[name] + "</svg>";
  }

  function trailStep() { return trail.steps[trail.steps.length - 1]; }
  function trailEntryOf(item) { return item.type === "entry" ? item.id : item.known_entry_id || null; }
  function trailRef(item) { return trailEntryOf(item) ? { entry: trailEntryOf(item) } : { feed: item.id }; }
  function trailKey(item) { return trailEntryOf(item) ? "e" + trailEntryOf(item) : "f" + item.id; }
  function trailPlace(hop) { return { kind: hop.kind, url: hop.url, label: hop.label, feed_url: hop.feed_url || "" }; }
  function inLibrary(hop) { return LIBRARY_PLACES.indexOf(hop.url.split(":")[0]) >= 0; }
  function hopIcon(hop) { return hop.kind === "creator" && hop.url.indexOf("creator:") === 0 ? "creator" : TRAIL_ICONS[hop.kind] ? hop.kind : "user"; }

  // A grid tile for a trail image: library entries open in the lightbox, other images are picked to save.
  function trailCandidate(item) {
    var entry = item.type === "entry";
    return { raw: item, feedId: entry ? null : item.id, entryId: entry ? item.id : null, url: item.url, thumb: item.thumb || item.url,
      width: item.width, height: item.height, title: item.title, creator: item.creator,
      source: entry ? "In the library" : FEED_SOURCE_NAMES[item.source_id] || item.source_id || "", known_entry_id: item.known_entry_id || null };
  }

  // Starts a trail from a library entry ({entry}) or a Discover image ({feed, item}); the view shown before is returned to on exit.
  function startTrail(detail) {
    var origin = detail.entry ? { type: "entry", id: detail.entry } : Object.assign({ type: "feed" }, detail.item || {}, { id: detail.feed });
    if (window.HbLightbox && window.HbLightbox.isOpen()) window.HbLightbox.close();
    if (trail) { navigate(function () { pushStep(origin); }); return; }
    var back = candidates && candidates.feed ? { set: feedSet, latest: feedLatest } : null;
    trail = { id: Date.now().toString(36) + Math.random().toString(36).slice(2, 8), back: back, left: null, steps: [] };
    navigate(function () {
      findTicket++;
      state.ticket++;
      feedSet = null;
      feedLatest = false;
      setFinding(false);
      $("#dock-find").hidden = true;
      $("#find-refresh").hidden = true;
      $("#find-flagged").hidden = true;
      $("#find-offer").hidden = true;
      setExitLabel(back ? "Back to Discover" : "Back to library");
      $("#library").setAttribute("data-finding", "true");
      $("#find-head").hidden = false;
      $("#find-trail").hidden = false;
      pushStep(origin);
    });
  }

  // Leaves the trail for the view it started from.
  function exitTrail() {
    if (!trail) return;
    var back = trail.back;
    trail = null;
    $("#find-trail").hidden = true;
    if (back) { openFeed(false, back.set, back.latest); return; }
    navigate(function () {
      leaveCandidates();
      navigate.wait(load(true));
    });
  }

  function clearTrail() {
    if (!trail) return;
    trail = null;
    $("#find-trail").hidden = true;
  }

  // Adds a step from an image: lists where it leads at no cost, checks other sites once, then opens the best place.
  function pushStep(origin) {
    var bridge = api();
    var step = { origin: origin, hops: [], active: -1, images: [], more: false, checking: false, loading: true, places: [] };
    trail.steps.push(step);
    var mine = trail;
    showTrailLoading();
    renderTrailHead();
    Promise.resolve(bridge.trail_hops(trailRef(origin))).then(function (result) {
      if (trail !== mine || trailStep() !== step) return null;
      step.hops = (result && result.hops) || [];
      var waiting = (result && result.pending) || step.hops.some(function (hop) { return hop.state === "unchecked"; });
      if (!waiting || trail.left === 0) return null;
      step.checking = true;
      renderTrailHead();
      return Promise.resolve(bridge.trail_check(trailRef(origin), trail.id)).then(function (checked) {
        if (trail !== mine) return;
        if (checked && checked.hops) step.hops = checked.hops;
        if (checked) trail.left = checked.left;
      }).catch(function () {});
    }).catch(function () {}).then(function () {
      if (trail !== mine || trailStep() !== step) return;
      step.checking = false;
      var first = firstPlace(step.hops);
      if (first < 0) {
        step.loading = false;
        showTrailGrid(step);
        return;
      }
      openHop(first);
    });
  }

  // Picks the place a step opens on: the first ready place on another site, else the first ready library place.
  function firstPlace(hops) {
    var ready = hops.map(function (hop, i) { return { hop: hop, i: i }; }).filter(function (item) { return item.hop.state === "ready" && item.hop.count; });
    var outside = ready.filter(function (item) { return !inLibrary(item.hop); });
    return outside.length ? outside[0].i : ready.length ? ready[0].i : -1;
  }

  // Shows one of the step's places in the grid; a place not checked yet costs one request now.
  function openHop(i) {
    var bridge = api();
    var step = trailStep();
    var hop = step.hops[i];
    if (!hop || !bridge) return;
    var mine = trail;
    step.active = i;
    step.loading = true;
    step.images = [];
    step.more = false;
    showTrailLoading();
    renderTrailHead();
    Promise.resolve(bridge.trail_images(trailPlace(hop), trail.id, false)).then(function (result) {
      if (trail !== mine || trailStep() !== step || step.active !== i) return null;
      if (result && result.state === "cooling") hop.state = "cooling";
      var skip = trailKey(step.origin);
      var images = ((result && result.images) || []).filter(function (item) { return trailKey(item) !== skip; });
      step.more = Boolean(result && result.more);
      step.places = (result && result.places) || [];
      if (result && result.state === "ready") { hop.state = "ready"; hop.count = result.count; }
      return preloadFeed(images);
    }).catch(function () { return []; }).then(function (images) {
      if (!images || trail !== mine || trailStep() !== step || step.active !== i) return;
      step.images = images;
      step.loading = false;
      showTrailGrid(step);
    });
  }

  // Reads the next page of the open place and adds its images after the ones shown.
  function trailMore() {
    var bridge = api();
    var step = trailStep();
    var hop = step.hops[step.active];
    if (!hop || !step.more || step.loading || !bridge) return;
    var mine = trail;
    step.loading = true;
    syncMore();
    Promise.resolve(bridge.trail_images(trailPlace(hop), trail.id, true)).then(function (result) {
      if (trail !== mine || trailStep() !== step) return null;
      var shown = {};
      step.images.forEach(function (item) { shown[trailKey(item)] = true; });
      shown[trailKey(step.origin)] = true;
      step.more = Boolean(result && result.more);
      if (result && result.state === "cooling") toast("info", hop.label + " is resting. Try again later.");
      return preloadFeed(((result && result.images) || []).filter(function (item) { return !shown[trailKey(item)]; }));
    }).catch(function () { return []; }).then(function (images) {
      if (!images || trail !== mine || trailStep() !== step) return;
      step.loading = false;
      images.forEach(function (item, position) {
        step.images.push(item);
        candidates.candidates.push(trailCandidate(item));
        var card = buildCandidate(candidates.candidates[candidates.candidates.length - 1], candidates.candidates.length - 1);
        card.style.setProperty("--cascade-index", Math.min(position, CASCADE_MAX));
        card.classList.add("library-cascade");
        placeInColumn(card);
      });
      renderTrailHead();
      syncMore();
    });
  }

  function showTrailLoading() {
    candidates = { trail: true, page_url: "", candidates: [] };
    clearSelection();
    syncMore();
    feedMessage("");
    $("#library-meta").hidden = true;
    resetColumns();
    for (var i = 0; i < 12; i++) {
      var tile = makeEl("div", "library-card loading-skeleton");
      tile.style.aspectRatio = SKELETON_RATIOS[i % SKELETON_RATIOS.length];
      placeInColumn(tile);
    }
    grid.setAttribute("aria-busy", "true");
  }

  // Paints the step's images in the grid; quiet redraws without the cascade.
  function showTrailGrid(step, quiet) {
    candidates = { trail: true, page_url: "", candidates: step.images.map(trailCandidate) };
    grid.removeAttribute("aria-busy");
    clearSelection();
    resetColumns();
    candidates.candidates.forEach(function (item, index) { placeInColumn(buildCandidate(item, index)); });
    if (!quiet) cascadeIn();
    renderTrailHead();
    syncMore();
    var hop = step.hops[step.active];
    var empty = !step.hops.length ? "This image does not lead anywhere yet. Images from Are.na, Tumblr and site feeds carry the most places."
      : !hop ? "None of the places this image leads to has images right now."
      : hop.state === "cooling" ? hop.label + " is resting after asking us to slow down. Try again later."
      : "Nothing more at " + hop.label + ".";
    feedMessage(step.images.length ? "" : empty);
  }

  function hopCountText(hop, step) {
    if (hop.state === "cooling") return "";
    if (hop.state === "unchecked") return step.checking ? "..." : "--";
    return HvUtils.pad2(hop.count || 0);
  }

  function renderCrumbs() {
    var box = $("#find-trail-path");
    box.textContent = "";
    trail.steps.forEach(function (step, i) {
      if (i) box.appendChild(makeEl("span", "find-trail-sep", "/"));
      var hop = step.hops[step.active];
      var last = i === trail.steps.length - 1;
      var crumb = makeEl(last ? "span" : "button", "find-trail-crumb", hop ? hop.label : "...");
      if (!last) {
        crumb.type = "button";
        crumb.setAttribute("data-step", i);
        crumb.setAttribute("data-tooltip", "Back to " + (hop ? hop.label : "this step"));
      }
      box.appendChild(crumb);
    });
  }

  function kindName(hop) { return TRAIL_KIND_NAMES[hop.url.split(":")[0]] || TRAIL_KIND_NAMES[hop.kind] || hop.kind; }

  // Lists where the step's image leads as branches of a path fork; the open branch carries the Follow action.
  function renderHops(step) {
    var box = $("#find-trail-hops");
    box.textContent = "";
    step.hops.forEach(function (hop, i) {
      var branch = makeEl("div", "path-fork-branch");
      if (hop.state === "unchecked") branch.setAttribute("data-state", "unknown");
      else if (hop.state === "cooling") branch.setAttribute("data-state", "resting");
      var take = branch.appendChild(makeEl("button", "path-fork-take"));
      take.type = "button";
      take.setAttribute("data-hop", i);
      take.setAttribute("aria-pressed", i === step.active ? "true" : "false");
      var kind = kindName(hop);
      take.setAttribute("data-tooltip", hop.state === "cooling" ? hop.label + " is resting: the site asked us to slow down"
        : hop.state === "unchecked" ? "Not checked yet; opening it checks"
        : "Open the " + kind + " " + hop.label + (hop.via ? ", found by searching Are.na for " + hop.via : ""));
      take.appendChild(makeEl("span", "path-fork-key", i < 9 ? String(i + 1) : ""));
      take.insertAdjacentHTML("beforeend", trailGlyph(hop.state === "cooling" ? "cooling" : hopIcon(hop)));
      take.appendChild(makeEl("span", "path-fork-label", hop.label));
      take.appendChild(makeEl("span", "path-fork-kind", kind));
      take.appendChild(makeEl("span", "path-fork-count", hopCountText(hop, step)));
      if (i === step.active && (hop.followable || (hop.kind === "creator" && step.places.length))) {
        var follow = branch.appendChild(makeEl("button", "action-icon find-hop-follow"));
        follow.type = "button";
        follow.innerHTML = trailGlyph(hop.followed ? "followed" : "follow");
        var label = hop.followed ? "Following " + hop.label : "Follow " + hop.label + " in Discover";
        follow.setAttribute("aria-label", label);
        follow.setAttribute("data-tooltip", label);
        follow.disabled = Boolean(hop.followed);
        follow.setAttribute("data-follow", i);
      }
      box.appendChild(branch);
    });
  }

  function renderAsk(step) {
    var hop = step.hops[step.active];
    var ask = $("#find-trail-ask");
    ask.hidden = !(hop && hop.suggest);
    if (ask.hidden) return;
    $("#find-trail-ask-text").textContent = "Is " + hop.label + " the same person as " + hop.suggest.name + "?";
  }

  // Redraws the head: the place shown, how many images it has, the path back, and where the step's image leads.
  function renderTrailHead() {
    if (!trail) return;
    var step = trailStep();
    var hop = step.hops[step.active];
    var title = $("#find-head-title");
    title.textContent = "";
    var mark = title.appendChild(makeEl("span", "find-head-mark"));
    mark.setAttribute("role", "img");
    mark.setAttribute("aria-label", "Trail");
    mark.innerHTML = RABBIT_ICON;
    var kind = hop ? kindName(hop) : "";
    var shown = step.images.length;
    var desc = step.checking ? "Checking where this image leads..."
      : step.loading ? (hop ? "Opening the " + kind + " " + hop.label + "..." : "Finding where this image leads...")
      : hop ? shown + (step.more ? "+" : "") + (shown === 1 ? " image" : " images") + " from the " + kind + " " + hop.label
        + ". Select to save; right-click one to follow its trail."
      : "Where this image leads.";
    if (trail.left !== null) desc += " " + trail.left + (trail.left === 1 ? " check" : " checks") + " left on this trail.";
    $("#find-head-desc").textContent = desc;
    renderCrumbs();
    renderHops(step);
    renderAsk(step);
  }

  function backTo(index) {
    if (!trail || index < 0 || index >= trail.steps.length - 1) return;
    trail.steps.length = index + 1;
    var step = trailStep();
    if (step.loading && step.active >= 0) openHop(step.active);
    else showTrailGrid(step);
  }

  // Starts the next step from a tile in the grid.
  function trailFrom(index) {
    var item = candidates && candidates.trail && candidates.candidates[index];
    if (!item || !trail) return;
    var origin = Object.assign({}, item.raw, item.known_entry_id ? { known_entry_id: item.known_entry_id } : {});
    navigate(function () { pushStep(origin); });
  }

  // Keeps the selected trail images in the library, optionally in a set; they stay in the grid and blur behind the captured mark.
  // With a set, selected images already in the library are placed in it too.
  function acceptTrail(setId) {
    var bridge = api();
    if (!candidates || !candidates.trail || !selected.size || !trail) return;
    var chosen = selectedIds().map(function (index) { return candidates.candidates[index]; }).filter(Boolean);
    var picked = chosen.filter(function (item) { return item.feedId && !item.known_entry_id; });
    var kept = setId ? chosen.map(function (item) { return item.entryId || item.known_entry_id; }).filter(Boolean) : [];
    if (!picked.length && !kept.length) { toast("info", "Those images are already in the library."); return; }
    var step = trailStep();
    var mine = trail;
    var saving = picked.length ? Promise.resolve(bridge.trail_save(picked.map(function (item) { return item.feedId; }), setId || null))
      : Promise.resolve({ ok: true, entry_ids: {} });
    var placing = kept.length ? Promise.resolve(bridge.place_entries(kept, setId)).catch(function () { return 0; }) : Promise.resolve(0);
    Promise.all([saving, placing]).then(function (done) {
      var result = done[0];
      if (!result || !result.ok) { toast("error", "Could not save those images."); return; }
      var count = picked.length + (done[1] || 0);
      toast("success", (setId ? "Saved " + count + " to the set." : "Saved " + count + (count === 1 ? " image." : " images.")));
      refreshStats();
      changed();
      if (trail !== mine || trailStep() !== step) return;
      var known = result.entry_ids || {};
      clearSelection();
      if (!candidates || !candidates.trail) return;
      candidates.candidates.forEach(function (item, index) {
        var entryId = item.feedId && known[String(item.feedId)];
        if (!entryId) return;
        item.known_entry_id = entryId;
        item.raw.known_entry_id = entryId;
        var card = grid.querySelector('[data-id="' + index + '"]');
        if (card) markCaptured(card, true);
      });
    }).catch(function () { toast("error", "Could not save those images."); });
  }

  // Follows the open place for Discover; a creator follows each of their places, one request at a time.
  function followHop(i) {
    var bridge = api();
    var step = trailStep();
    var hop = step.hops[i];
    if (!hop || !bridge || !bridge.follow_source) return;
    var urls = hop.kind === "creator"
      ? step.places.filter(function (place) { return !place.followed; }).map(function (place) { return place.url; })
      : [hop.url];
    if (!urls.length) { toast("info", "Already following every place."); return; }
    var added = 0;
    urls.reduce(function (chain, url) {
      return chain.then(function () {
        return Promise.resolve(bridge.follow_source(url)).then(function (result) { if (result && result.ok) added++; }).catch(function () {});
      });
    }, Promise.resolve()).then(function () {
      if (!added) { toast("error", "Could not follow " + hop.label + "."); return; }
      hop.followed = true;
      if (trail && trailStep() === step) renderTrailHead();
      toast("success", urls.length > 1 ? "Following " + added + " of " + urls.length + " places." : "Following " + hop.label + ".");
    });
  }

  // Answers whether the open place belongs to the suggested creator, then lists the step's places again.
  function answerSuggest(yes) {
    var bridge = api();
    var step = trailStep();
    var hop = step.hops[step.active];
    if (!hop || !hop.suggest || !bridge) return;
    var suggest = hop.suggest;
    var call = yes ? bridge.confirm_creator(suggest.name, hop.url, suggest.creator_id) : bridge.reject_creator(suggest.name, hop.url);
    Promise.resolve(call).then(function (result) {
      if (yes && !(result && result.ok)) { toast("error", "Could not link that creator."); return; }
      if (yes) toast("success", "Linked to " + suggest.name + ".");
      delete hop.suggest;
      if (!trail || trailStep() !== step) return;
      var activeUrl = hop.url;
      return Promise.resolve(bridge.trail_hops(trailRef(step.origin))).then(function (listed) {
        if (!trail || trailStep() !== step || !listed || !listed.hops) return;
        step.hops = listed.hops;
        step.active = step.hops.findIndex(function (item) { return item.url === activeUrl; });
        renderTrailHead();
      });
    }).catch(function () { toast("error", "Could not save that answer."); });
  }

  // Backspace goes back a step and 1-9 open the step's places, while no field or dialog has the keys.
  function onTrailKey(event) {
    if (!trail || $("#app").inert || event.ctrlKey || event.metaKey || event.altKey) return;
    var tag = event.target && event.target.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    if (event.key === "Backspace") { event.preventDefault(); backTo(trail.steps.length - 2); }
    else if (/^[1-9]$/.test(event.key) && trailStep().hops[Number(event.key) - 1]) { event.preventDefault(); openHop(Number(event.key) - 1); }
  }

  function setupTrail() {
    if (!$("#find-trail")) return;
    document.addEventListener("hyperbridge:trail", function (event) { startTrail(event.detail || {}); });
    document.addEventListener("keydown", onTrailKey);
    $("#find-trail-path").addEventListener("click", function (event) {
      var crumb = event.target.closest("[data-step]");
      if (crumb) backTo(Number(crumb.getAttribute("data-step")));
    });
    $("#find-trail-hops").addEventListener("click", function (event) {
      if (!trail) return;
      var target = event.target.closest("[data-hop], [data-follow]");
      if (!target) return;
      if (target.hasAttribute("data-follow")) followHop(Number(target.getAttribute("data-follow")));
      else if (Number(target.getAttribute("data-hop")) !== trailStep().active || !trailStep().images.length) openHop(Number(target.getAttribute("data-hop")));
    });
    document.addEventListener("hyperbridge:discarded", function (event) {
      if (!trail) return;
      var step = trailStep();
      step.images = step.images.filter(function (item) { return trailEntryOf(item) !== event.detail.id; });
      if (candidates && candidates.trail && !step.loading) showTrailGrid(step, true);
      refreshStats();
      changed();
    });
    $("#find-trail-yes").addEventListener("click", function () { answerSuggest(true); });
    $("#find-trail-no").addEventListener("click", function () { answerSuggest(false); });
  }
