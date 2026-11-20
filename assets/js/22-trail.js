/* === Hyperbridge: trails - following where an image leads, step by step, inside the lightbox === */
(function () {
  "use strict";

  var SETTLE_MS = 500;
  var ICON = {
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
  var trail = null;
  var settleTimer = null;
  var showToken = 0;

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
  function pad2(n) { return n < 10 ? "0" + n : String(n); }

  function glyph(name, small) {
    return '<svg class="' + (small ? "icon-glyph-sm" : "icon-glyph") + '" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + ICON[name] + "</svg>";
  }

  function iconButton(name, label, attr, value) {
    var button = makeEl("button", "action-icon lightbox-hop-action");
    button.type = "button";
    button.innerHTML = glyph(name);
    button.setAttribute("aria-label", label);
    button.setAttribute("data-tooltip", label);
    if (attr) button.setAttribute(attr, value);
    return button;
  }

  function step() { return trail.steps[trail.steps.length - 1]; }
  function image() { var current = step(); return current.images[current.index]; }
  function entryOf(item) { return item.type === "entry" ? item.id : item.known_entry_id || null; }
  function refOf(item) { return entryOf(item) ? { entry: entryOf(item) } : { feed: item.id }; }
  function keyOf(item) { return entryOf(item) ? "e" + entryOf(item) : "f" + item.id; }
  function placeOf(hop) { return { kind: hop.kind, url: hop.url, label: hop.label, feed_url: hop.feed_url || "" }; }

  // Starts a trail at a library entry ({entry}) or a Discover image ({feed, item}); the id scopes its request budget.
  function start(detail) {
    var root = detail.entry ? { type: "entry", id: detail.entry } : Object.assign({}, detail.item || {}, { type: "feed", id: detail.feed });
    trail = { id: Date.now().toString(36) + Math.random().toString(36).slice(2, 8), hops: [], left: null, checking: false,
      steps: [{ label: "Start", images: [root], index: 0, more: false, skip: "" }] };
    show();
  }

  function end() {
    trail = null;
    showToken++;
    clearTimeout(settleTimer);
    byId("lb-trail").hidden = true;
    byId("act-trail").hidden = false;
  }

  // Shows the step's current image, lists where it leads, and checks other sites once the Operator settles on it.
  function show() {
    var mine = ++showToken;
    clearTimeout(settleTimer);
    var item = image();
    trail.hops = [];
    trail.checking = false;
    var entry = entryOf(item);
    var shown = entry ? window.HbLightbox.openEntry(entry) : Promise.resolve(window.HbLightbox.showLoose(item));
    Promise.resolve(shown).then(function () {
      if (mine !== showToken || !trail) return;
      byId("lb-trail").hidden = false;
      byId("act-trail").hidden = true;
      renderTrail();
      loadHops(mine, true);
    });
  }

  function loadHops(mine, settle) {
    var bridge = api();
    if (!bridge || !bridge.trail_hops) return;
    Promise.resolve(bridge.trail_hops(refOf(image()))).then(function (result) {
      if (mine !== showToken || !trail) return;
      trail.hops = (result && result.hops) || [];
      renderTrail();
      if (settle) settleTimer = setTimeout(function () { check(mine); }, SETTLE_MS);
    }).catch(function () {});
  }

  function check(mine) {
    var bridge = api();
    if (!trail || mine !== showToken || !bridge || !bridge.trail_check || trail.left === 0) return;
    trail.checking = true;
    renderTrail();
    Promise.resolve(bridge.trail_check(refOf(image()), trail.id)).then(function (result) {
      if (mine !== showToken || !trail) return;
      if (result && result.hops && result.hops.length) trail.hops = result.hops;
      if (result) trail.left = result.left;
    }).catch(function () {}).then(function () {
      if (mine !== showToken || !trail) return;
      trail.checking = false;
      renderTrail();
    });
  }

  function renderCrumbs() {
    var box = byId("lb-trail-crumbs");
    box.textContent = "";
    trail.steps.forEach(function (item, i) {
      if (i) box.appendChild(makeEl("span", "lightbox-caption-sep", " / "));
      var last = i === trail.steps.length - 1;
      var crumb = makeEl(last ? "span" : "button", last ? "lightbox-trail-crumb" : "lightbox-trail-crumb lightbox-tag", item.label);
      if (!last) {
        crumb.type = "button";
        crumb.setAttribute("data-step", i);
        crumb.setAttribute("data-tooltip", "Back to " + item.label);
      }
      box.appendChild(crumb);
    });
    var current = step();
    byId("lb-trail-position").textContent = pad2(current.index + 1) + " / " + pad2(current.images.length) + (current.more ? "+" : "");
    byId("lb-trail-back").disabled = trail.steps.length < 2;
  }

  function hopCount(hop) {
    if (hop.state === "cooling") {
      var rest = makeEl("span", "lightbox-hop-count");
      rest.innerHTML = glyph("cooling", true);
      rest.setAttribute("data-tooltip", "Resting: the site asked us to slow down");
      return rest;
    }
    if (hop.state === "unchecked") {
      var open = makeEl("span", "lightbox-hop-count", "--");
      open.setAttribute("data-tooltip", trail.checking ? "Checking..." : "Not checked yet; opening it checks");
      return open;
    }
    return makeEl("span", "lightbox-hop-count", pad2(hop.count || 0));
  }

  function renderHop(box, hop, i) {
    var row = makeEl("div", "list-row lightbox-hop");
    var open = makeEl("button", "lightbox-hop-open");
    open.type = "button";
    open.setAttribute("data-hop", i);
    open.setAttribute("data-tooltip", "Open " + hop.label + (i < 9 ? " (" + (i + 1) + ")" : ""));
    open.appendChild(makeEl("span", "lightbox-hop-key", i < 9 ? String(i + 1) : ""));
    var kind = makeEl("span", "lightbox-hop-kind");
    kind.innerHTML = glyph(hop.kind === "creator" && hop.url.indexOf("creator:") === 0 ? "creator" : ICON[hop.kind] ? hop.kind : "user", true);
    open.appendChild(kind);
    open.appendChild(makeEl("span", "lightbox-hop-label", hop.label));
    open.appendChild(hopCount(hop));
    row.appendChild(open);
    var followable = hop.followable || (hop.kind === "creator" && hop.places);
    if (followable && hop.followed) {
      var done = iconButton("followed", "Following " + hop.label);
      done.disabled = true;
      row.appendChild(done);
    } else if (followable) {
      row.appendChild(iconButton("follow", "Follow " + hop.label, "data-follow", i));
    }
    box.appendChild(row);
    if (!hop.suggest) return;
    var ask = makeEl("div", "lightbox-hop-ask");
    ask.appendChild(makeEl("span", "lightbox-none", "Same person as " + hop.suggest.name + "?"));
    ask.appendChild(iconButton("yes", "Yes, link to " + hop.suggest.name, "data-confirm", i));
    ask.appendChild(iconButton("no", "No, not " + hop.suggest.name, "data-reject", i));
    box.appendChild(ask);
  }

  function renderTrail() {
    if (!trail) return;
    renderCrumbs();
    var item = image();
    byId("lb-trail-keep").hidden = Boolean(entryOf(item));
    byId("lb-trail-left").textContent = trail.checking ? "Checking..." : trail.left === null ? "" : pad2(trail.left) + " checks left";
    var box = byId("lb-trail-hops");
    box.textContent = "";
    if (!trail.hops.length) {
      box.appendChild(makeEl("span", "lightbox-none", trail.checking ? "Looking..." : "Nowhere yet."));
      return;
    }
    trail.hops.forEach(function (hop, i) { renderHop(box, hop, i); });
  }

  function visible(images, skip) { return images.filter(function (item) { return keyOf(item) !== skip; }); }

  // Steps into a place: library places come from the database, outside places from the day's check or one request now.
  function enter(i) {
    var hop = trail && trail.hops[i];
    var bridge = api();
    if (!hop || !bridge || !bridge.trail_images || trail.entering) return;
    trail.entering = true;
    var mine = trail;
    var skip = keyOf(image());
    Promise.resolve(bridge.trail_images(placeOf(hop), trail.id, false)).then(function (result) {
      mine.entering = false;
      if (trail !== mine) return;
      var images = visible((result && result.images) || [], skip);
      if (!images.length) {
        toast("info", result && result.state === "cooling" ? hop.label + " is resting. Try again later." : "Nothing more at " + hop.label + ".");
        return;
      }
      trail.steps.push({ label: hop.label, place: placeOf(hop), images: images, index: 0, more: Boolean(result.more), skip: skip });
      show();
    }).catch(function () { mine.entering = false; toast("error", "Could not open " + hop.label + "."); });
  }

  // Reads the step's next page when the Operator moves past its last image.
  function readMore(current) {
    var bridge = api();
    if (current.loading || !bridge) return;
    current.loading = true;
    Promise.resolve(bridge.trail_images(current.place, trail.id, true)).then(function (result) {
      current.loading = false;
      if (!trail || step() !== current) return;
      var had = current.images.length;
      current.images = visible((result && result.images) || [], current.skip);
      current.more = Boolean(result && result.more);
      if (current.images.length > had) { current.index = had; show(); } else renderTrail();
    }).catch(function () { current.loading = false; });
  }

  function move(delta) {
    var current = step();
    var next = current.index + delta;
    if (next < 0) return;
    if (next >= current.images.length) { if (current.more) readMore(current); return; }
    current.index = next;
    show();
  }

  function backTo(index) {
    if (index < 0 || index >= trail.steps.length - 1) return;
    trail.steps.length = index + 1;
    show();
  }

  // Keeps the shown trail image in the library, optionally in a set, then moves on.
  function keep(setId) {
    var bridge = api();
    var item = image();
    if (!bridge || !bridge.trail_save || entryOf(item)) return;
    var mine = trail;
    Promise.resolve(bridge.trail_save(item.id, setId || null)).then(function (result) {
      if (!result || !result.ok || !result.entry_id) { toast("error", "Could not keep that image."); return; }
      item.known_entry_id = result.entry_id;
      toast("success", setId ? "Kept in the set." : "Kept.");
      changed();
      if (trail !== mine) return;
      if (step().index < step().images.length - 1 || step().more) move(1);
      else show();
    }).catch(function () { toast("error", "Could not keep that image."); });
  }

  function keepInSet(button) {
    var bridge = api();
    if (!bridge || !bridge.list_sets || !window.HvContextMenu) return;
    Promise.resolve(bridge.list_sets()).then(function (sets) {
      if (!sets || !sets.length) { toast("info", "No sets yet."); return; }
      window.HvContextMenu.openFor(button, sets.map(function (set) {
        return { label: escapeHtml(set.name), action: function () { keep(set.id); } };
      }));
    }).catch(function () {});
  }

  // Follows a place for Discover; a creator follows each of their places, one request at a time.
  function follow(i) {
    var hop = trail.hops[i];
    var bridge = api();
    if (!hop || !bridge || !bridge.follow_source) return;
    var urls = hop.kind === "creator"
      ? Promise.resolve(bridge.trail_images(placeOf(hop), trail.id, false)).then(function (result) {
        return ((result && result.places) || []).filter(function (place) { return !place.followed; }).map(function (place) { return place.url; });
      })
      : Promise.resolve([hop.url]);
    urls.then(function (list) {
      var added = 0;
      return list.reduce(function (chain, url) {
        return chain.then(function () {
          return Promise.resolve(bridge.follow_source(url)).then(function (result) { if (result && result.ok) added++; }).catch(function () {});
        });
      }, Promise.resolve()).then(function () {
        if (!list.length) { toast("info", "Already following every place."); return; }
        if (!added) { toast("error", "Could not follow " + hop.label + "."); return; }
        hop.followed = true;
        renderTrail();
        toast("success", list.length > 1 ? "Following " + added + " of " + list.length + " places." : "Following " + hop.label + ".");
      });
    }).catch(function () { toast("error", "Could not follow " + hop.label + "."); });
  }

  function answer(i, yes) {
    var hop = trail.hops[i];
    var bridge = api();
    if (!hop || !hop.suggest || !bridge) return;
    var mine = showToken;
    var call = yes ? bridge.confirm_creator(hop.suggest.name, hop.url, hop.suggest.creator_id) : bridge.reject_creator(hop.suggest.name, hop.url);
    Promise.resolve(call).then(function (result) {
      if (yes && !(result && result.ok)) { toast("error", "Could not link that creator."); return; }
      if (yes) toast("success", "Linked to " + hop.suggest.name + ".");
      if (trail && mine === showToken) loadHops(mine, false);
    }).catch(function () { toast("error", "Could not save that answer."); });
  }

  // Up and Down move through the step's images, 1-9 open a place, Backspace goes back a step.
  function onKey(event) {
    if (!trail || event.ctrlKey || event.metaKey || event.altKey) return false;
    if (event.key === "ArrowDown") { move(1); return true; }
    if (event.key === "ArrowUp") { move(-1); return true; }
    if (event.key === "Backspace") { backTo(trail.steps.length - 2); return true; }
    if (/^[1-9]$/.test(event.key)) { enter(Number(event.key) - 1); return true; }
    return false;
  }

  function init() {
    if (!byId("lb-trail")) return;
    document.addEventListener("hyperbridge:trail", function (event) { start(event.detail || {}); });
    document.addEventListener("hyperbridge:lightbox-closed", end);
    byId("lb-trail-back").addEventListener("click", function () { if (trail) backTo(trail.steps.length - 2); });
    byId("lb-trail-crumbs").addEventListener("click", function (event) {
      var crumb = event.target.closest("[data-step]");
      if (crumb && trail) backTo(Number(crumb.getAttribute("data-step")));
    });
    byId("lb-trail-save").addEventListener("click", function () { keep(null); });
    byId("lb-trail-save-set").addEventListener("click", function (event) { event.stopPropagation(); keepInSet(event.currentTarget); });
    byId("lb-trail-skip").addEventListener("click", function () { if (trail) move(1); });
    byId("lb-trail-hops").addEventListener("click", function (event) {
      if (!trail) return;
      var target = event.target.closest("[data-hop], [data-follow], [data-confirm], [data-reject]");
      if (!target) return;
      if (target.hasAttribute("data-hop")) enter(Number(target.getAttribute("data-hop")));
      else if (target.hasAttribute("data-follow")) follow(Number(target.getAttribute("data-follow")));
      else if (target.hasAttribute("data-confirm")) answer(Number(target.getAttribute("data-confirm")), true);
      else answer(Number(target.getAttribute("data-reject")), false);
    });
  }

  init();
  window.HbTrail = { onKey: onKey, active: function () { return Boolean(trail); } };
})();
