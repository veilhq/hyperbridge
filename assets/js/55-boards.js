/* === Hyperbridge: scratch boards - freeform canvases kept on this machine === */
(function () {
  "use strict";

  var DEF_W = 240;
  var DOT = 24;
  var ROW = 160;
  var NOTE_SIZE = 180;
  var SWATCH = 44;
  var SWATCH_STRIDE = 56;
  var SAVE_MS = 400;
  var ARM_MS = 2500;
  var DAY_MS = 86400000;
  var STALE_DAYS = 7;
  var TRAY_LIMIT = 120;
  var KEY_VIEW = "hyperbridge-board-view-";
  var KEY_SNAP = "hyperbridge-board-snap";
  var KEY_TRAY = "hyperbridge-board-tray";
  var KEY_ACTIVE = "hyperbridge-board-active";

  var ICONS = {
    "pointer": '<path d="M4.037 4.688a.495.495 0 0 1 .651-.651l16 6.5a.5.5 0 0 1-.063.947l-6.124 1.58a2 2 0 0 0-1.438 1.435l-1.579 6.126a.5.5 0 0 1-.947.063z"/>',
    "note": '<path d="M16 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V8Z"/><path d="M15 3v4a2 2 0 0 0 2 2h4"/>',
    "type": '<polyline points="4 7 4 4 20 4 20 7"/><line x1="9" x2="15" y1="20" y2="20"/><line x1="12" x2="12" y1="4" y2="20"/>',
    "frame": '<line x1="22" x2="2" y1="6" y2="6"/><line x1="22" x2="2" y1="18" y2="18"/><line x1="6" x2="6" y1="2" y2="22"/><line x1="18" x2="18" y1="2" y2="22"/>',
    "image-plus": '<path d="M16 5h6"/><path d="M19 2v6"/><path d="M21 11.5V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7.5"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/><circle cx="9" cy="9" r="2"/>',
    "images": '<path d="M18 22H4a2 2 0 0 1-2-2V6"/><path d="m22 13-1.296-1.296a2.41 2.41 0 0 0-3.408 0L11 18"/><circle cx="12" cy="8" r="2"/><rect width="16" height="16" x="6" y="2" rx="2"/>',
    "zoom-in": '<circle cx="11" cy="11" r="8"/><line x1="21" x2="16.65" y1="21" y2="16.65"/><line x1="11" x2="11" y1="8" y2="14"/><line x1="8" x2="14" y1="11" y2="11"/>',
    "zoom-out": '<circle cx="11" cy="11" r="8"/><line x1="21" x2="16.65" y1="21" y2="16.65"/><line x1="8" x2="14" y1="11" y2="11"/>',
    "grip": '<circle cx="12" cy="5" r="1"/><circle cx="19" cy="5" r="1"/><circle cx="5" cy="5" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/><circle cx="12" cy="19" r="1"/><circle cx="19" cy="19" r="1"/><circle cx="5" cy="19" r="1"/>',
    "scan": '<path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/>',
    "list-ordered": '<line x1="10" x2="21" y1="6" y2="6"/><line x1="10" x2="21" y1="12" y2="12"/><line x1="10" x2="21" y1="18" y2="18"/><path d="M4 6h1v4"/><path d="M4 10h2"/><path d="M6 18H4c0-1 2-2 2-3s-1-1.5-2-1"/>',
    "bookmark-plus": '<path d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z"/><line x1="12" x2="12" y1="7" y2="13"/><line x1="15" x2="9" y1="10" y2="10"/>',
    "plus": '<path d="M5 12h14"/><path d="M12 5v14"/>',
    "move-diagonal-2": '<polyline points="5 11 5 5 11 5"/><polyline points="19 13 19 19 13 19"/><line x1="5" x2="19" y1="5" y2="19"/>',
    "trash": '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>',
    "palette": '<circle cx="13.5" cy="6.5" r=".5" fill="currentColor"/><circle cx="17.5" cy="10.5" r=".5" fill="currentColor"/><circle cx="8.5" cy="7.5" r=".5" fill="currentColor"/><circle cx="6.5" cy="12.5" r=".5" fill="currentColor"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z"/>',
    "filter": '<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>',
    "bring-front": '<rect x="8" y="8" width="8" height="8" rx="2"/><path d="M4 10a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2"/><path d="M14 20a2 2 0 0 0 2 2h4a2 2 0 0 0 2-2v-4a2 2 0 0 0-2-2"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>'
  };

  function icon(name) {
    return '<svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
      'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (ICONS[name] || "") + "</svg>";
  }

  function byId(id) { return document.getElementById(id); }
  function api() { return window.pywebview && window.pywebview.api; }
  function toast(variant, message) { if (window.HvToast) window.HvToast.show({ variant: variant, message: message }); }
  function announce(name, detail) { document.dispatchEvent(new CustomEvent(name, { detail: detail })); }
  function pad2(n) { return n < 10 ? "0" + n : String(n); }
  function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;" }[c];
    });
  }
  function readStore(key) { try { return localStorage.getItem(key); } catch (err) { return null; } }
  function writeStore(key, value) { try { localStorage.setItem(key, value); } catch (err) { /* storage full or blocked */ } }

  var uidSeed = Math.floor(Math.random() * 1e6);
  function uid() { return "n" + (uidSeed++).toString(36); }

  // ---- State ----
  var library, viewEl, canvas, world, ctxBar, tray;
  var isOpen = false;
  var boards = [];
  var board = null;
  var tiles = {};
  var view = { x: 0, y: 0, z: 1 };
  var tool = "select";
  var selected = {};
  var drag = null;
  var editing = null;
  var spaceDown = false;
  var altDown = false;
  var snap = readStore(KEY_SNAP) === "1";
  var showOrder = false;
  var orderBeforeDialog = false;
  var filter = null;
  var colorFor = null;
  var dragEntry = null;
  var ghostEl = null;
  var trayEntries = [];
  var trayTotal = 0;
  var saveTimer = 0;
  var dirty = false;
  var saving = Promise.resolve();
  var armTimer = 0;
  var loadToken = 0;

  function selectedIds() { return Object.keys(selected); }
  function selectedCount() { return selectedIds().length; }
  function clearSelection() { selected = {}; }
  function selectOnly(id) { selected = {}; selected[id] = true; }
  function nodeById(id) {
    for (var i = 0; i < board.nodes.length; i += 1) if (board.nodes[i].id === id) return board.nodes[i];
    return null;
  }
  function visible(n) { return n.type !== "raw" && (n.type !== "image" || !!tiles[n.entry]); }
  function shownNodes() { return board ? board.nodes.filter(visible) : []; }
  function selectedNodes() { return shownNodes().filter(function (n) { return selected[n.id]; }); }

  // ---- JSON Canvas conversion: images are file nodes, frames are groups, the rest are tagged text nodes ----
  function presetIndex(color) {
    var i = ["1", "2", "3"].indexOf(String(color));
    return i < 0 ? null : i;
  }

  function fromDoc(doc) {
    return (doc.nodes || []).map(function (raw) {
      var base = { id: String(raw.id || uid()), x: Number(raw.x) || 0, y: Number(raw.y) || 0, w: Number(raw.width) || DEF_W, h: Number(raw.height) || DEF_W };
      if (raw.type === "file" && typeof raw.entry === "number") {
        base.type = "image";
        base.entry = raw.entry;
      } else if (raw.type === "group") {
        base.type = "frame";
        base.text = raw.label || "Frame";
      } else if (raw.type === "text" && raw.hb === "note") {
        base.type = "note";
        base.text = raw.text || "";
        var preset = presetIndex(raw.color);
        base.color = preset === null ? (parseHex(raw.color) || 0) : preset;
      } else if (raw.type === "text" && raw.hb === "label") {
        base.type = "label";
        base.text = raw.text || "Label";
      } else if (raw.type === "text" && raw.hb === "swatch" && parseHex(raw.color)) {
        base.type = "swatch";
        base.hex = parseHex(raw.color);
      } else {
        base.type = "raw";
        base.raw = raw;
      }
      return base;
    });
  }

  function toDoc() {
    var nodes = board.nodes.map(function (n) {
      if (n.type === "raw") return n.raw;
      var r = rectOf(n);
      var out = { id: n.id, x: Math.round(n.x), y: Math.round(n.y), width: Math.round(r.w), height: Math.round(r.h) };
      if (n.type === "image") { out.type = "file"; out.file = "hyperbridge:entry/" + n.entry; out.entry = n.entry; }
      else if (n.type === "frame") { out.type = "group"; out.label = n.text; }
      else if (n.type === "note") { out.type = "text"; out.hb = "note"; out.text = n.text; out.color = typeof n.color === "string" ? n.color : String(n.color + 1); }
      else if (n.type === "label") { out.type = "text"; out.hb = "label"; out.text = n.text; }
      else if (n.type === "swatch") { out.type = "text"; out.hb = "swatch"; out.text = n.hex; out.color = n.hex; }
      return out;
    });
    return { nodes: nodes, edges: board.edges || [] };
  }

  // ---- Saving: the document is written after a short pause, and before any switch, clear or promote ----
  function changed() {
    dirty = true;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(flush, SAVE_MS);
  }

  function flush() {
    clearTimeout(saveTimer);
    if (!dirty || !board || !api()) return saving;
    dirty = false;
    var id = board.id;
    var text = JSON.stringify(toDoc());
    saving = saving.then(function () {
      return Promise.resolve(api().save_board(id, text)).then(function (result) {
        if (!result || !result.ok) { toast("error", (result && result.error) || "That board could not be saved."); return; }
        mergeSummary(result.board);
      });
    }).catch(function () { toast("error", "That board could not be saved."); });
    return saving;
  }

  function mergeSummary(summary) {
    if (!summary) return;
    boards = boards.map(function (item) { return item.id === summary.id ? summary : item; });
    if (board && board.id === summary.id) { board.name = summary.name; board.updated_at = summary.updated_at; }
    renderTabs();
    renderReadout();
  }

  // ---- Grid snap: the step is the dot spacing, coarsened 4x below 50% zoom ----
  function gridStep() { return DOT * (view.z < 0.5 ? 4 : 1); }
  function snapOn() { return snap && !altDown; }
  function snapV(v) { return snapOn() ? Math.round(v / gridStep()) * gridStep() : Math.round(v); }

  // ---- Geometry ----
  function nodeEl(id) { return world.querySelector('[data-id="' + id + '"]'); }
  function rectOf(n) {
    if (n.type === "label") {
      var el = nodeEl(n.id);
      return { x: n.x, y: n.y, w: el ? el.offsetWidth : n.w, h: el ? el.offsetHeight : n.h };
    }
    return { x: n.x, y: n.y, w: n.w, h: n.h };
  }
  function boundsOf(nodes) {
    var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    nodes.forEach(function (n) {
      var r = rectOf(n);
      x0 = Math.min(x0, r.x); y0 = Math.min(y0, r.y);
      x1 = Math.max(x1, r.x + r.w); y1 = Math.max(y1, r.y + r.h);
    });
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }
  function inside(n, f) {
    var r = rectOf(n), cx = r.x + r.w / 2, cy = r.y + r.h / 2;
    return cx > f.x && cx < f.x + f.w && cy > f.y && cy < f.y + f.h;
  }
  function rowSort(list) {
    return list.slice().sort(function (a, b) { return (Math.floor(a.y / ROW) - Math.floor(b.y / ROW)) || (a.x - b.x); });
  }

  // Reading order: frame by frame, then loose images, each top-left to bottom-right.
  function readingOrder() {
    var images = shownNodes().filter(function (n) { return n.type === "image"; });
    var used = {}, groups = [];
    rowSort(shownNodes().filter(function (n) { return n.type === "frame"; })).forEach(function (f) {
      var members = images.filter(function (n) { return !used[n.id] && inside(n, f); });
      members.forEach(function (m) { used[m.id] = true; });
      if (members.length) groups.push({ x: f.x, y: f.y, items: rowSort(members) });
    });
    images.forEach(function (n) { if (!used[n.id]) groups.push({ x: n.x, y: n.y, items: [n] }); });
    return rowSort(groups).reduce(function (all, g) { return all.concat(g.items); }, []);
  }

  function toWorld(event) {
    var r = canvas.getBoundingClientRect();
    return { x: (event.clientX - r.left - view.x) / view.z, y: (event.clientY - r.top - view.y) / view.z };
  }
  function viewCenter() {
    var r = canvas.getBoundingClientRect();
    return { x: (r.width / 2 - view.x) / view.z, y: (r.height / 2 - view.y) / view.z };
  }

  // ---- View transform: pan and zoom are kept per board on this machine ----
  function applyView() {
    world.style.transform = "translate(" + view.x + "px, " + view.y + "px) scale(" + view.z + ")";
    world.style.setProperty("--canvas-inv", String(1 / view.z));
    var step = DOT * view.z * (view.z < 0.5 ? 4 : 1);
    canvas.style.backgroundSize = step + "px " + step + "px";
    canvas.style.backgroundPosition = (view.x - step / 2) + "px " + (view.y - step / 2) + "px";
    byId("board-zoom").textContent = Math.round(view.z * 100) + "%";
    updateCtx();
  }
  function storeView() { if (board) writeStore(KEY_VIEW + board.id, JSON.stringify(view)); }
  function zoomAt(sx, sy, factor) {
    var nz = clamp(view.z * factor, 0.15, 4);
    var wx = (sx - view.x) / view.z, wy = (sy - view.y) / view.z;
    view = { z: nz, x: sx - wx * nz, y: sy - wy * nz };
    applyView();
    storeView();
  }
  function zoomCenter(factor) {
    var r = canvas.getBoundingClientRect();
    zoomAt(r.width / 2, r.height / 2, factor);
  }
  function fit() {
    var r = canvas.getBoundingClientRect(), nodes = shownNodes();
    if (!nodes.length) {
      view = { x: r.width / 2, y: r.height / 2, z: 1 };
    } else {
      var bb = boundsOf(nodes), pad = 64, availH = r.height - 96;
      bb.y -= 32; bb.h += 32;
      var z = clamp(Math.min((r.width - pad * 2) / bb.w, (availH - pad) / bb.h), 0.15, 1.5);
      view = { z: z, x: (r.width - bb.w * z) / 2 - bb.x * z, y: (availH - bb.h * z) / 2 - bb.y * z + pad / 4 };
    }
    applyView();
    storeView();
  }

  // ---- Note color: three preset hues plus free hex entry ----
  function parseHex(value) {
    var m = String(value == null ? "" : value).trim().match(/^#?([0-9a-f]{3}|[0-9a-f]{6})$/i);
    if (!m) return null;
    var h = m[1].length === 3 ? m[1].replace(/(.)/g, "$1$1") : m[1];
    return "#" + h.toUpperCase();
  }
  function presetHex(i) {
    var probe = document.createElement("i");
    probe.style.color = "var(--note-color-" + (i + 1) + ")";
    document.body.appendChild(probe);
    var rgb = (getComputedStyle(probe).color.match(/\d+/g) || [0, 0, 0]).slice(0, 3);
    probe.parentNode.removeChild(probe);
    return "#" + rgb.map(function (c) { var h = (+c).toString(16); return h.length < 2 ? "0" + h : h; }).join("").toUpperCase();
  }
  function noteHex(n) { return typeof n.color === "string" ? n.color : presetHex(n.color % 3); }

  // ---- Render ----
  function gripHTML() {
    return '<button class="resize-grip" type="button" tabindex="-1" data-grip aria-label="Resize" data-tooltip="Resize">' + icon("move-diagonal-2") + "</button>";
  }

  function frameCount(f) {
    return shownNodes().filter(function (o) { return o.type !== "frame" && o.type !== "label" && inside(o, f); }).length;
  }

  function buildNode(n) {
    var el = document.createElement("div");
    el.className = "board-node select-ring board-" + n.type + (selected[n.id] ? " is-selected" : "");
    el.setAttribute("data-id", n.id);
    el.style.left = n.x + "px";
    el.style.top = n.y + "px";
    if (n.type !== "label") { el.style.width = n.w + "px"; el.style.height = n.h + "px"; }
    if (n.type === "image") {
      var tile = tiles[n.entry];
      el.innerHTML = '<img alt="" draggable="false" src="' + esc(tile.thumb) + '">' +
        '<span class="board-caption"><span>' + esc(tile.title || "Untitled") + "</span>" + (tile.creator ? "<span>" + esc(tile.creator) + "</span>" : "") + "</span>" +
        '<span class="board-badge"></span>';
    } else if (n.type === "note") {
      if (typeof n.color === "string") el.style.setProperty("--note-card-color", n.color);
      else el.classList.add("note-c" + (n.color % 3));
      el.innerHTML = '<div class="board-note-text">' + esc(n.text) + "</div>";
    } else if (n.type === "label") {
      el.innerHTML = '<div class="board-label-text">' + esc(n.text) + "</div>";
    } else if (n.type === "frame") {
      el.innerHTML = '<div class="board-frame-label"><span class="board-frame-name">' + esc(n.text) + '</span><span class="board-frame-count">' + pad2(frameCount(n)) + "</span></div>";
    } else if (n.type === "swatch") {
      if (filter === n.hex) el.classList.add("is-filter");
      el.innerHTML = '<div class="board-swatch-fill" style="--swatch:' + n.hex + '"></div><span class="board-swatch-hex">' + icon("filter") + n.hex + "</span>";
    }
    if (n.type !== "label") el.insertAdjacentHTML("beforeend", gripHTML());
    return el;
  }

  function renderWorld() {
    if (!board) return;
    world.innerHTML = "";
    var nodes = shownNodes();
    nodes.filter(function (n) { return n.type === "frame"; }).concat(nodes.filter(function (n) { return n.type !== "frame"; }))
      .forEach(function (n) { world.appendChild(buildNode(n)); });
    world.classList.toggle("is-single", selectedCount() === 1);
    canvas.classList.toggle("show-order", showOrder);
    byId("board-order").setAttribute("aria-pressed", showOrder ? "true" : "false");
    byId("board-order").classList.toggle("is-active", showOrder);
    if (showOrder) {
      var order = readingOrder();
      order.forEach(function (n, i) {
        var badge = world.querySelector('[data-id="' + n.id + '"] .board-badge');
        if (badge) badge.textContent = pad2(i + 1);
      });
      var points = order.map(function (n) { return (n.x + n.w / 2) + "," + (n.y + n.h / 2); }).join(" ");
      world.insertAdjacentHTML("afterbegin", '<svg class="board-order-path" aria-hidden="true"><polyline points="' + points + '"/></svg>');
    }
    ghostEl = document.createElement("div");
    ghostEl.className = "board-ghost";
    ghostEl.hidden = true;
    world.appendChild(ghostEl);
    byId("board-empty").hidden = nodes.length > 0;
    updateCtx();
  }

  function renderTabs() {
    var tabs = byId("boards-tabs");
    if (tabs.querySelector("input")) return;
    tabs.innerHTML = boards.map(function (item) {
      var active = board && item.id === board.id;
      return '<button class="board-tab" type="button" role="tab" data-board="' + item.id + '" aria-selected="' + (active ? "true" : "false") + '"' +
        (active ? ' data-tooltip="Double-click to rename"' : "") + ">" + esc(item.name) + "</button>";
    }).join("");
    byId("boards-count").textContent = boards.length || "";
  }

  function staleDays(stamp) {
    var at = Date.parse(stamp || "");
    return isNaN(at) ? 0 : Math.max(0, Math.floor((Date.now() - at) / DAY_MS));
  }

  // Item count plus the staleness meter: one cell per untouched day, warning once a week has passed.
  function renderReadout() {
    var out = byId("boards-readout");
    if (!board) { out.innerHTML = ""; return; }
    var count = shownNodes().filter(function (n) { return n.type === "image"; }).length;
    var days = staleDays(board.updated_at);
    var cells = "";
    for (var i = 0; i < STALE_DAYS; i += 1) cells += '<i class="board-stale-cell' + (i < Math.min(days, STALE_DAYS) ? " is-on" : "") + '"></i>';
    var tip = days === 0 ? "Touched today" : "Untouched for " + days + (days === 1 ? " day" : " days");
    out.innerHTML = '<span class="board-stat board-legend"><b>' + pad2(count) + "</b>Items</span>" +
      '<span class="board-stale' + (days >= STALE_DAYS ? " is-stale" : "") + '" data-tooltip="' + tip + '">' +
      '<span class="board-stale-cells">' + cells + '</span><span class="board-legend">' + pad2(days) + "D</span></span>";
  }

  function onBoardIds() {
    var ids = {};
    shownNodes().forEach(function (n) { if (n.type === "image") ids[n.entry] = true; });
    return ids;
  }

  function renderTray() {
    var toggle = byId("board-tray-toggle");
    toggle.classList.toggle("is-active", !tray.hidden);
    toggle.setAttribute("aria-pressed", tray.hidden ? "false" : "true");
    if (tray.hidden) return;
    var on = onBoardIds();
    byId("board-tray-count").textContent = pad2(trayTotal);
    var chip = byId("board-tray-filter");
    chip.hidden = !filter;
    chip.innerHTML = filter ? '<span class="board-filter-chip board-legend"><i style="--swatch:' + filter + '"></i>' + filter +
      '<button type="button" data-clear-filter aria-label="Clear color filter" data-tooltip="Clear color filter">' + icon("x") + "</button></span>" : "";
    byId("board-tray-grid").innerHTML = trayEntries.length ? trayEntries.map(function (entry) {
      return '<div class="board-tray-item' + (on[entry.id] ? " is-on-board" : "") + '" draggable="true" data-entry="' + entry.id + '" data-tooltip="' + esc(entry.title || "Untitled") + '">' +
        '<img alt="" src="' + esc(entry.thumb) + '"><span class="board-tray-mark">' + icon("check") + "</span></div>";
    }).join("") : '<p class="board-tray-empty">' + (filter ? "No saves near this color." : "No images in the library yet.") + "</p>";
  }

  function loadTray() {
    if (tray.hidden || !api()) { renderTray(); return; }
    Promise.resolve(api().list_entries("", 0, TRAY_LIMIT, null, "", "", filter || "")).then(function (result) {
      trayEntries = ((result && result.entries) || []).filter(function (entry) { return entry.thumb; });
      trayTotal = (result && result.total) || 0;
      renderTray();
    }).catch(function () { renderTray(); });
  }

  function render() { renderTabs(); renderReadout(); renderWorld(); renderTray(); }

  function refreshSelection() {
    Array.prototype.forEach.call(world.querySelectorAll(".board-node"), function (el) {
      el.classList.toggle("is-selected", !!selected[el.getAttribute("data-id")]);
    });
    world.classList.toggle("is-single", selectedCount() === 1);
    updateCtx();
  }

  // ---- Context bar: actions for the current selection, floated above it ----
  function hueRow(n) {
    var dots = [0, 1, 2].map(function (i) {
      return '<button class="board-hue" type="button" style="--hue:var(--note-color-' + (i + 1) + ')" data-act="hue" data-i="' + i + '" aria-pressed="' +
        (n.color === i ? "true" : "false") + '" aria-label="Hue ' + (i + 1) + '" data-tooltip="' + presetHex(i) + '"></button>';
    }).join("");
    var hex = noteHex(n);
    return '<span class="board-hues">' + dots + '<label class="board-hex" style="--hue:' + hex + '"><i></i><input id="board-note-hex" value="' + hex.slice(1) +
      '" maxlength="7" spellcheck="false" autocomplete="off" aria-label="Hex color"></label></span>';
  }

  function updateCtx() {
    if (!board) { ctxBar.hidden = true; return; }
    var sel = selectedNodes();
    if (!sel.length || editing || (drag && drag.kind !== "pan")) { ctxBar.hidden = true; return; }
    if (ctxBar.contains(document.activeElement) && document.activeElement.id === "board-note-hex") return;
    var buttons = [];
    if (sel.length === 1) {
      var n = sel[0];
      if (n.type === "image") buttons.push(["palette", "Pull palette", "pull"]);
      if (n.type === "swatch") buttons.push(["filter", filter === n.hex ? "Clear color filter" : "Filter library by color", "filter", false, filter === n.hex]);
      if (n.type === "note") buttons.push(["palette", "Note color", "recolor", false, colorFor === n.id]);
      if (n.type !== "frame") buttons.push(["bring-front", "Bring to front", "front"]);
    } else {
      buttons.push(["frame", "Group in a frame", "wrap"]);
    }
    var frameOnly = sel.length === 1 && sel[0].type === "frame";
    buttons.push(["trash", frameOnly ? "Remove frame (keeps items)" : "Delete", "delete", true]);
    var html = buttons.map(function (b) {
      return '<button class="action-icon' + (b[3] ? " action-icon-danger" : "") + (b[4] ? " is-active" : "") + '" type="button" data-act="' + b[2] +
        '" aria-label="' + b[1] + '" data-tooltip="' + b[1] + '">' + icon(b[0]) + "</button>";
    });
    if (sel.length === 1 && sel[0].type === "note" && colorFor === sel[0].id) html.splice(1, 0, hueRow(sel[0]));
    ctxBar.innerHTML = (sel.length > 1 ? '<span class="select-count">' + pad2(sel.length) + "</span>" : "") + html.join("");
    var bb = boundsOf(sel);
    ctxBar.style.left = (view.x + (bb.x + bb.w / 2) * view.z) + "px";
    ctxBar.style.top = (view.y + bb.y * view.z) + "px";
    ctxBar.hidden = false;
  }

  // ---- Actions ----
  function setTool(name) {
    tool = name;
    canvas.className = canvas.className.replace(/\btool-\w+/g, "").trim() + " tool-" + name;
    Array.prototype.forEach.call(document.querySelectorAll("#board-dock [data-tool]"), function (b) {
      b.classList.toggle("is-active", b.getAttribute("data-tool") === name);
    });
  }

  function placeSwatches(n, hexes) {
    var y = n.y + n.h + 40, ids = {};
    hexes.forEach(function (hex, i) {
      var id = uid();
      ids[id] = true;
      board.nodes.push({ id: id, type: "swatch", hex: hex, x: n.x + i * SWATCH_STRIDE, y: y, w: SWATCH, h: SWATCH });
    });
    selected = ids;
    changed();
    render();
    toast("success", "Pulled " + pad2(hexes.length) + " swatches.");
  }

  function pullPalette(n) {
    var tile = tiles[n.entry] || {};
    var hexes = (tile.swatches || []).map(parseHex).filter(Boolean).slice(0, 5);
    if (hexes.length) { placeSwatches(n, hexes); return; }
    Promise.resolve(api().board_tiles([n.entry])).then(function (found) {
      var fresh = (found || [])[0];
      if (fresh) tiles[n.entry] = fresh;
      var got = ((fresh && fresh.swatches) || []).map(parseHex).filter(Boolean).slice(0, 5);
      if (got.length) placeSwatches(n, got);
      else toast("info", "No palette for this image yet.");
    }).catch(function () { toast("error", "Could not read that palette."); });
  }

  function toggleFilter(hex) {
    filter = filter === hex ? null : hex;
    if (filter && tray.hidden) setTray(true);
    else loadTray();
    renderWorld();
  }

  function wrapInFrame(sel) {
    var bb = boundsOf(sel), pad = 24;
    var n = { id: uid(), type: "frame", x: bb.x - pad, y: bb.y - pad, w: bb.w + pad * 2, h: bb.h + pad * 2, text: "Group" };
    board.nodes.unshift(n);
    selectOnly(n.id);
    changed();
    render();
  }

  function deleteSelected() {
    if (!selectedCount()) return;
    if (board.nodes.some(function (n) { return selected[n.id] && n.type === "swatch" && n.hex === filter; })) { filter = null; loadTray(); }
    board.nodes = board.nodes.filter(function (n) { return !selected[n.id]; });
    clearSelection();
    changed();
    render();
  }

  function selectAll() {
    selected = {};
    shownNodes().forEach(function (n) { selected[n.id] = true; });
    refreshSelection();
  }

  function placeEntry(tile, cx, cy) {
    tiles[tile.id] = tile;
    var ratio = tile.width && tile.height ? tile.height / tile.width : 0.75;
    var w = DEF_W, h = Math.round(w * ratio);
    var n = { id: uid(), type: "image", entry: tile.id, x: snapV(cx - w / 2), y: snapV(cy - h / 2), w: w, h: h };
    board.nodes.push(n);
    selectOnly(n.id);
    changed();
    render();
  }

  // A tray entry becomes a tile straight away; its palette is fetched when first pulled.
  function tileFromEntry(entry) {
    return { type: "entry", id: entry.id, title: entry.title, creator: entry.domain || "", thumb: entry.thumb, width: entry.width, height: entry.height, swatches: [] };
  }

  // Pasted or dropped image files are saved to the library first, then placed on the board.
  function addFiles(files, at) {
    var images = files.filter(function (f) { return f && f.type && f.type.indexOf("image/") === 0; });
    if (!images.length) { toast("info", "Only images can go on a board."); return; }
    images.forEach(function (file, i) {
      var reader = new FileReader();
      reader.onload = function () {
        Promise.resolve(api().add_image_data(reader.result, file.name || "")).then(function (result) {
          if (!result || !result.ok) throw new Error((result && result.error) || "Could not add that image.");
          return Promise.resolve(api().board_tiles([result.entry_id]));
        }).then(function (found) {
          var tile = (found || [])[0];
          if (!tile || !board) return;
          placeEntry(tile, at.x + i * 32, at.y + i * 32);
          announce("hyperbridge:changed");
          toast("success", "Saved to library and placed.");
        }).catch(function (err) { toast("error", (err && err.message) || "Could not add that image."); });
      };
      reader.readAsDataURL(file);
    });
  }

  // ---- Text editing: notes, labels and frame legends edit in place ----
  function beginEdit(n) {
    var host = nodeEl(n.id);
    if (!host) return;
    var el = host.querySelector(n.type === "note" ? ".board-note-text" : n.type === "label" ? ".board-label-text" : ".board-frame-name");
    if (!el) return;
    editing = n.id;
    updateCtx();
    try { el.contentEditable = "plaintext-only"; } catch (err) { el.contentEditable = "true"; }
    if (!el.isContentEditable) el.contentEditable = "true";
    el.focus();
    var range = document.createRange();
    range.selectNodeContents(el);
    var s = window.getSelection();
    s.removeAllRanges();
    s.addRange(range);
    el.addEventListener("blur", commitEdit);
    el.addEventListener("keydown", function (event) {
      if (event.key === "Escape" || (event.key === "Enter" && !event.shiftKey && n.type !== "note")) { event.preventDefault(); el.blur(); }
    });
  }

  function commitEdit() {
    if (!editing) return;
    var n = nodeById(editing), el = world.querySelector("[contenteditable]:not([contenteditable='false'])");
    editing = null;
    if (n && el) {
      var text = el.innerText.replace(/\n+$/, "").trim();
      var next = text || (n.type === "note" ? "" : n.type === "frame" ? "Frame" : "Label");
      if (next !== n.text) { n.text = next; changed(); }
    }
    renderWorld();
  }

  // ---- Boards: list, switch, create, rename, clear ----
  function restoreView(id) {
    try {
      var saved = JSON.parse(readStore(KEY_VIEW + id) || "null");
      if (saved && isFinite(saved.x) && isFinite(saved.y) && saved.z > 0) { view = { x: saved.x, y: saved.y, z: clamp(saved.z, 0.15, 4) }; return true; }
    } catch (err) { /* fall through to fit */ }
    return false;
  }

  function showBoard(data) {
    board = { id: data.id, name: data.name, updated_at: data.updated_at, nodes: fromDoc(data.doc || {}), edges: (data.doc && data.doc.edges) || [] };
    tiles = {};
    (data.tiles || []).forEach(function (tile) { tiles[tile.id] = tile; });
    clearSelection();
    colorFor = null;
    dirty = false;
    writeStore(KEY_ACTIVE, String(board.id));
    setTool("select");
    var restored = restoreView(board.id);
    render();
    if (restored) applyView(); else fit();
  }

  function switchBoard(id) {
    if (!api()) return Promise.resolve();
    commitEdit();
    var token = loadToken += 1;
    return flush().then(function () { return api().get_board(id); }).then(function (data) {
      if (token !== loadToken) return;
      if (!data) { boards = boards.filter(function (item) { return item.id !== id; }); return pickBoard(); }
      showBoard(data);
    }).catch(function () { toast("error", "Could not open that board."); });
  }

  function newBoard() {
    return Promise.resolve(api().create_board("")).then(function (result) {
      if (!result || !result.ok) { toast("error", "Could not make a board."); return; }
      boards.unshift(result.board);
      return switchBoard(result.board.id);
    });
  }

  // Opens the last board used here, else the latest touched; makes one when there are none.
  function pickBoard() {
    if (!boards.length) return newBoard();
    var stored = Number(readStore(KEY_ACTIVE));
    var target = boards.filter(function (item) { return item.id === stored; })[0] || boards[0];
    return switchBoard(target.id);
  }

  function loadBoards() {
    if (!api() || !api().list_boards) return;
    Promise.resolve(api().list_boards()).then(function (list) {
      boards = list || [];
      renderTabs();
      return board && boards.some(function (item) { return item.id === board.id; }) ? switchBoard(board.id) : pickBoard();
    }).catch(function () { toast("error", "Could not load boards."); });
  }

  function forgetBoard(id) {
    boards = boards.filter(function (item) { return item.id !== id; });
    try { localStorage.removeItem(KEY_VIEW + id); } catch (err) { /* blocked storage */ }
    board = null;
    dirty = false;
    clearTimeout(saveTimer);
    filter = null;
    showOrder = false;
    return pickBoard();
  }

  function startRename(tab) {
    if (!board || Number(tab.getAttribute("data-board")) !== board.id) return;
    var input = document.createElement("input");
    input.className = "form-input board-tab-input";
    input.value = board.name;
    input.maxLength = 100;
    input.setAttribute("aria-label", "Board name");
    tab.replaceWith(input);
    input.focus();
    input.select();
    var done = false;
    function finish(save) {
      if (done) return;
      done = true;
      var name = input.value.trim();
      input.remove();
      renderTabs();
      if (!save || !name || name === board.name) return;
      Promise.resolve(api().rename_board(board.id, name)).then(function (result) {
        if (result && result.ok) mergeSummary(result.board);
        else toast("error", (result && result.error) || "Could not rename that board.");
      });
    }
    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter") { event.preventDefault(); finish(true); }
      else if (event.key === "Escape") { event.preventDefault(); finish(false); }
    });
    input.addEventListener("blur", function () { finish(true); });
  }

  function disarmClear() {
    clearTimeout(armTimer);
    byId("boards-clear").removeAttribute("data-armed");
  }

  // Clearing asks for a second click; the board's images stay in the library.
  function clearBoard() {
    if (!board) return;
    var button = byId("boards-clear");
    if (!button.hasAttribute("data-armed")) {
      button.setAttribute("data-armed", "");
      toast("info", "Click again to clear this board.");
      armTimer = setTimeout(disarmClear, ARM_MS);
      return;
    }
    disarmClear();
    var id = board.id;
    dirty = false;
    clearTimeout(saveTimer);
    saving.then(function () { return api().delete_board(id); }).then(function () {
      toast("success", "Board cleared. Its images stay in the library.");
      return forgetBoard(id);
    }).catch(function () { toast("error", "Could not clear that board."); });
  }

  // ---- Promote: the board's images become a set in reading order, then the board is cleared ----
  function promoteOpen() { return byId("board-promote").open; }

  function openPromote() {
    if (!board) return;
    commitEdit();
    var order = readingOrder();
    if (!order.length) { toast("info", "Add images before promoting."); return; }
    orderBeforeDialog = showOrder;
    showOrder = true;
    renderWorld();
    byId("board-promote-name").value = board.name;
    byId("board-promote-count").textContent = pad2(order.length) + " Items";
    byId("board-promote-strip").innerHTML = order.map(function (n, i) {
      return '<div class="board-order-thumb"><img alt="" src="' + esc(tiles[n.entry].thumb) + '"><span class="board-badge">' + pad2(i + 1) + "</span></div>";
    }).join("");
    byId("board-scrim").classList.add("visible");
    byId("app").inert = true;
    byId("board-promote").show();
    byId("board-promote-name").focus();
    byId("board-promote-name").select();
  }

  function closePromote() {
    if (!promoteOpen()) return;
    byId("board-promote").close();
    byId("board-scrim").classList.remove("visible");
    byId("app").inert = false;
    showOrder = orderBeforeDialog;
    if (board) renderWorld();
  }

  function confirmPromote() {
    if (!board || !promoteOpen()) return;
    var id = board.id;
    var name = byId("board-promote-name").value.trim() || board.name;
    var ids = readingOrder().map(function (n) { return n.entry; });
    var button = byId("board-promote-confirm");
    button.disabled = true;
    flush().then(function () { return api().promote_board(id, name, ids); }).then(function (result) {
      button.disabled = false;
      if (!result || !result.ok) { toast("error", (result && result.error) || "Could not promote that board."); return; }
      closePromote();
      toast("success", "Saved " + pad2(result.count) + " images to \"" + result.set.name + "\".");
      announce("hyperbridge:changed");
      return forgetBoard(id);
    }).catch(function () {
      button.disabled = false;
      toast("error", "Could not promote that board.");
    });
  }

  // ---- Tray and toggles ----
  function setTray(value) {
    tray.hidden = !value;
    writeStore(KEY_TRAY, value ? "1" : "0");
    loadTray();
    applyView();
  }

  function renderSnap() {
    var button = byId("board-snap");
    button.classList.toggle("is-active", snap);
    button.setAttribute("aria-pressed", snap ? "true" : "false");
    canvas.classList.toggle("is-snap", snapOn());
  }

  function toggleSnap() {
    snap = !snap;
    writeStore(KEY_SNAP, snap ? "1" : "0");
    renderSnap();
    toast("info", snap ? "Snap to grid on." : "Snap to grid off.");
  }

  function toggleOrder() { showOrder = !showOrder; renderWorld(); }

  // ---- Open and close: the boards view takes over the library pane ----
  function settingsOpen() { return library.hasAttribute("data-settings"); }

  function setOpen(value) {
    if (value === isOpen) return;
    if (!value) { commitEdit(); flush(); closePromote(); disarmClear(); drag = null; }
    isOpen = value;
    library.toggleAttribute("data-boards-view", value);
    viewEl.hidden = !value;
    byId("sets-boards").classList.toggle("content-card-active", value);
    if (value) byId("sets-boards").setAttribute("aria-current", "true");
    else byId("sets-boards").removeAttribute("aria-current");
    announce("hyperbridge:boards", { open: value });
    if (value) {
      library.scrollTop = 0;
      tray.hidden = readStore(KEY_TRAY) !== "1";
      renderSnap();
      loadBoards();
    }
  }

  function openBoards() {
    if (isOpen) return;
    if (settingsOpen()) byId("sets-settings").click();
    window.hbNavigate(function () { setOpen(true); });
  }

  function closeBoards() { setOpen(false); }

  function isEditable(target) {
    return !!(target && (target.isContentEditable || (target.closest && target.closest("input, textarea, select"))));
  }

  function canHandleKeys() {
    return isOpen && board && !byId("app").inert && !document.querySelector("dialog[open]");
  }

  // Board shortcuts win over the library's while the board is open; modified keys other than Ctrl+A pass through.
  function onKeyDown(event) {
    if (event.key === "Alt") { altDown = true; if (isOpen) renderSnap(); }
    if (!canHandleKeys() || isEditable(event.target) || event.key === "F11") return;
    var key = String(event.key).toLowerCase();
    if (event.ctrlKey || event.metaKey || event.altKey) {
      if ((event.ctrlKey || event.metaKey) && !event.altKey && key === "a") {
        event.preventDefault();
        event.stopPropagation();
        selectAll();
      }
      return;
    }
    event.stopPropagation();
    if (event.code === "Space") { event.preventDefault(); spaceDown = true; canvas.classList.add("is-space"); return; }
    if (key === "v") setTool("select");
    else if (key === "n") setTool("note");
    else if (key === "t") setTool("label");
    else if (key === "f") setTool("frame");
    else if (key === "l") setTray(tray.hidden);
    else if (key === "o") toggleOrder();
    else if (key === "g") toggleSnap();
    else if (key === "0") fit();
    else if (key === "=" || key === "+") zoomCenter(1.2);
    else if (key === "-") zoomCenter(1 / 1.2);
    else if (key === "delete" || key === "backspace") { event.preventDefault(); deleteSelected(); }
    else if (key === "escape") { event.preventDefault(); colorFor = null; clearSelection(); setTool("select"); refreshSelection(); }
    else if (key === "enter" && selectedCount() === 1) {
      var n = nodeById(selectedIds()[0]);
      if (n && (n.type === "note" || n.type === "label")) { event.preventDefault(); beginEdit(n); }
    }
  }

  function onKeyUp(event) {
    if (event.key === "Alt") { altDown = false; if (isOpen) renderSnap(); }
    if (event.code === "Space" && spaceDown) {
      spaceDown = false;
      canvas.classList.remove("is-space");
      if (isOpen) event.stopPropagation();
    }
  }

  // Pasted images land on the board; text pastes into fields are left to the field.
  function onPaste(event) {
    if (!isOpen || !board || byId("app").inert) return;
    event.stopPropagation();
    if (isEditable(event.target)) return;
    var items = event.clipboardData ? Array.prototype.slice.call(event.clipboardData.items) : [];
    var files = items.filter(function (item) { return item.kind === "file" && item.type.indexOf("image/") === 0; })
      .map(function (item) { return item.getAsFile(); }).filter(Boolean);
    if (!files.length) return;
    event.preventDefault();
    addFiles(files, viewCenter());
  }

  // ---- Pointer: pan, move (frames carry their contents), resize, marquee and frame drawing ----
  function onPointerDown(event) {
    if (!board || event.target.closest(".board-dock, .board-ctx, [contenteditable='true'], [contenteditable='plaintext-only']")) return;
    if (editing) commitEdit();
    if (colorFor) { colorFor = null; }
    var p = toWorld(event);
    if (event.button === 1 || spaceDown) {
      event.preventDefault();
      drag = { kind: "pan", lx: event.clientX, ly: event.clientY };
      canvas.classList.add("is-panning");
      return;
    }
    if (event.button !== 0) return;
    if (tool === "note" || tool === "label") {
      var made = tool === "note"
        ? { id: uid(), type: "note", x: snapV(p.x - NOTE_SIZE / 2), y: snapV(p.y - NOTE_SIZE / 2), w: NOTE_SIZE, h: NOTE_SIZE, color: shownNodes().filter(function (o) { return o.type === "note"; }).length % 3, text: "" }
        : { id: uid(), type: "label", x: snapV(p.x), y: snapV(p.y - 20), w: 200, h: 30, text: "Label" };
      board.nodes.push(made);
      selectOnly(made.id);
      setTool("select");
      changed();
      render();
      beginEdit(made);
      event.preventDefault();
      return;
    }
    if (tool === "frame") {
      var draft = document.createElement("div");
      draft.className = "board-frame-draft";
      world.appendChild(draft);
      drag = { kind: "frame", start: { x: snapV(p.x), y: snapV(p.y) }, draft: draft };
      return;
    }
    var hit = event.target.closest(".board-node");
    if (!hit) {
      if (!event.shiftKey) { clearSelection(); refreshSelection(); }
      var box = document.createElement("div");
      box.className = "marquee";
      box.hidden = true;
      world.appendChild(box);
      var base = {};
      selectedIds().forEach(function (id) { base[id] = true; });
      drag = { kind: "marquee", start: p, box: box, base: base };
      return;
    }
    var id = hit.getAttribute("data-id"), n = nodeById(id);
    if (!n) return;
    if (event.target.closest("[data-grip]")) {
      event.preventDefault();
      drag = { kind: "resize", id: id, start: p, ow: n.w, oh: n.h, ratio: n.h / n.w, keep: n.type === "image" || n.type === "swatch" };
      return;
    }
    if (event.shiftKey) { if (selected[id]) delete selected[id]; else selected[id] = true; }
    else if (!selected[id]) selectOnly(id);
    refreshSelection();
    var moving = {};
    selectedIds().forEach(function (sid) { moving[sid] = true; });
    shownNodes().forEach(function (f) {
      if (f.type !== "frame" || !selected[f.id]) return;
      shownNodes().forEach(function (o) { if (o.type !== "frame" && inside(o, f)) moving[o.id] = true; });
    });
    var origins = {};
    Object.keys(moving).forEach(function (mid) { var m = nodeById(mid); if (m) origins[mid] = { x: m.x, y: m.y }; });
    drag = { kind: "move", start: p, origins: origins, moved: false, anchor: id };
  }

  function onPointerMove(event) {
    if (!drag) return;
    if (drag.kind === "pan") {
      view.x += event.clientX - drag.lx;
      view.y += event.clientY - drag.ly;
      drag.lx = event.clientX;
      drag.ly = event.clientY;
      applyView();
      return;
    }
    var p = toWorld(event);
    if (drag.kind === "move") {
      var dx = p.x - drag.start.x, dy = p.y - drag.start.y;
      if (!drag.moved && Math.sqrt(dx * dx + dy * dy) * view.z < 3) return;
      if (!drag.moved) { drag.moved = true; ctxBar.hidden = true; }
      var a = drag.origins[drag.anchor];
      var sdx = snapV(a.x + dx) - a.x, sdy = snapV(a.y + dy) - a.y;
      Object.keys(drag.origins).forEach(function (id) {
        var n = nodeById(id), o = drag.origins[id];
        n.x = Math.round(o.x + sdx);
        n.y = Math.round(o.y + sdy);
        var el = nodeEl(id);
        if (el) { el.style.left = n.x + "px"; el.style.top = n.y + "px"; }
      });
    } else if (drag.kind === "resize") {
      var r = nodeById(drag.id), min = r.type === "swatch" ? 24 : 60;
      r.w = Math.max(min, snapV(r.x + drag.ow + p.x - drag.start.x) - r.x);
      r.h = drag.keep ? Math.round(r.w * drag.ratio) : Math.max(min, snapV(r.y + drag.oh + p.y - drag.start.y) - r.y);
      var rel = nodeEl(drag.id);
      if (rel) { rel.style.width = r.w + "px"; rel.style.height = r.h + "px"; }
      drag.moved = true;
      ctxBar.hidden = true;
    } else if (drag.kind === "marquee") {
      var m = { x: Math.min(p.x, drag.start.x), y: Math.min(p.y, drag.start.y), w: Math.abs(p.x - drag.start.x), h: Math.abs(p.y - drag.start.y) };
      drag.box.hidden = false;
      drag.box.style.left = m.x + "px";
      drag.box.style.top = m.y + "px";
      drag.box.style.width = m.w + "px";
      drag.box.style.height = m.h + "px";
      selected = {};
      Object.keys(drag.base).forEach(function (id) { selected[id] = true; });
      shownNodes().forEach(function (n) {
        var b = rectOf(n);
        if (b.x < m.x + m.w && b.x + b.w > m.x && b.y < m.y + m.h && b.y + b.h > m.y) selected[n.id] = true;
      });
      refreshSelection();
    } else if (drag.kind === "frame") {
      p.x = snapV(p.x);
      p.y = snapV(p.y);
      drag.draft.style.left = Math.min(p.x, drag.start.x) + "px";
      drag.draft.style.top = Math.min(p.y, drag.start.y) + "px";
      drag.draft.style.width = Math.abs(p.x - drag.start.x) + "px";
      drag.draft.style.height = Math.abs(p.y - drag.start.y) + "px";
      drag.end = p;
    }
  }

  function onPointerUp() {
    if (!drag) return;
    var d = drag;
    drag = null;
    canvas.classList.remove("is-panning");
    if (d.kind === "pan") { storeView(); updateCtx(); return; }
    if (d.kind === "marquee") { d.box.remove(); updateCtx(); return; }
    if ((d.kind === "move" || d.kind === "resize") && !d.moved) { updateCtx(); return; }
    if (d.kind === "frame") {
      d.draft.remove();
      var e2 = d.end || d.start, w = Math.abs(e2.x - d.start.x), h = Math.abs(e2.y - d.start.y);
      var count = board.nodes.filter(function (n) { return n.type === "frame"; }).length + 1;
      var n = w < 40 || h < 40
        ? { id: uid(), type: "frame", x: Math.round(d.start.x), y: Math.round(d.start.y), w: 480, h: 320, text: "Frame " + pad2(count) }
        : { id: uid(), type: "frame", x: Math.round(Math.min(e2.x, d.start.x)), y: Math.round(Math.min(e2.y, d.start.y)), w: Math.round(w), h: Math.round(h), text: "Frame " + pad2(count) };
      board.nodes.unshift(n);
      selectOnly(n.id);
      setTool("select");
    }
    changed();
    render();
  }

  // ---- Drag in from the tray or the desktop ----
  function showGhost(p, w, h, label) {
    if (!ghostEl) return;
    ghostEl.style.left = snapV(p.x - w / 2) + "px";
    ghostEl.style.top = snapV(p.y - h / 2) + "px";
    ghostEl.style.width = w + "px";
    ghostEl.style.height = h + "px";
    ghostEl.textContent = label;
    ghostEl.hidden = false;
  }
  function hideGhost() { if (ghostEl) ghostEl.hidden = true; }

  function onDragOver(event) {
    if (!board) return;
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = "copy";
    var p = toWorld(event);
    if (dragEntry) showGhost(p, DEF_W, dragEntry.width && dragEntry.height ? DEF_W * dragEntry.height / dragEntry.width : DEF_W * 0.75, "");
    else showGhost(p, DEF_W, DEF_W * 0.75, "Drop image");
  }

  // The drop stops here so the window's own file-drop import does not add the files a second time.
  function onDrop(event) {
    if (!board) return;
    event.preventDefault();
    event.stopPropagation();
    hideGhost();
    var p = toWorld(event);
    if (dragEntry) { placeEntry(tileFromEntry(dragEntry), p.x, p.y); dragEntry = null; return; }
    var files = Array.prototype.slice.call((event.dataTransfer && event.dataTransfer.files) || []);
    if (files.length) addFiles(files, p);
  }

  // ---- Wiring ----
  function onCtxClick(event) {
    var button = event.target.closest("[data-act]");
    if (!button) return;
    var sel = selectedNodes(), act = button.getAttribute("data-act"), first = sel[0];
    if (!first) return;
    if (act === "pull") pullPalette(first);
    else if (act === "filter") toggleFilter(first.hex);
    else if (act === "recolor") { colorFor = colorFor === first.id ? null : first.id; updateCtx(); }
    else if (act === "hue") { first.color = Number(button.getAttribute("data-i")); changed(); renderWorld(); }
    else if (act === "front") { board.nodes = board.nodes.filter(function (n) { return n !== first; }).concat([first]); changed(); renderWorld(); }
    else if (act === "wrap") wrapInFrame(sel);
    else if (act === "delete") deleteSelected();
  }

  function onCtxInput(event) {
    if (event.target.id !== "board-note-hex") return;
    var n = nodeById(colorFor), hex = parseHex(event.target.value), field = event.target.closest(".board-hex");
    field.classList.toggle("is-invalid", !hex && event.target.value.trim() !== "");
    if (!n || !hex) return;
    n.color = hex;
    changed();
    field.style.setProperty("--hue", hex);
    Array.prototype.forEach.call(ctxBar.querySelectorAll(".board-hue"), function (dot) { dot.setAttribute("aria-pressed", "false"); });
    var el = nodeEl(n.id);
    if (el) { el.classList.remove("note-c0", "note-c1", "note-c2"); el.style.setProperty("--note-card-color", hex); }
  }

  function wire() {
    Array.prototype.forEach.call(document.querySelectorAll("#boards-view [data-icon], #board-promote [data-icon]"), function (el) {
      el.insertAdjacentHTML("afterbegin", icon(el.getAttribute("data-icon")));
    });

    byId("sets-boards").addEventListener("click", openBoards);
    // Any other rail destination leaves the board first.
    byId("sets-rail").addEventListener("click", function (event) {
      if (!isOpen) return;
      var target = event.target.closest(".sets-tab, #sets-settings, #sets-new");
      if (target && target.id !== "sets-boards") closeBoards();
    }, true);
    ["hyperbridge:filter", "hyperbridge:sets", "hyperbridge:feed", "hyperbridge:latest", "hyperbridge:similar", "hyperbridge:tag"].forEach(function (name) {
      document.addEventListener(name, closeBoards);
    });
    new MutationObserver(function () { if (isOpen && settingsOpen()) closeBoards(); })
      .observe(library, { attributes: true, attributeFilter: ["data-settings"] });

    window.addEventListener("keydown", onKeyDown, true);
    window.addEventListener("keyup", onKeyUp, true);
    window.addEventListener("paste", onPaste, true);
    window.addEventListener("blur", function () { altDown = false; spaceDown = false; if (isOpen) { canvas.classList.remove("is-space"); renderSnap(); } });
    window.addEventListener("resize", function () { if (isOpen) updateCtx(); });
    // Keys typed into the board's own fields stay with those fields.
    viewEl.addEventListener("keydown", function (event) { if (isEditable(event.target)) event.stopPropagation(); });

    canvas.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("pointercancel", onPointerUp);
    canvas.addEventListener("dblclick", function (event) {
      var host = event.target.closest(".board-node");
      var n = host && nodeById(host.getAttribute("data-id"));
      if (!n) return;
      if (n.type === "note" || n.type === "label") beginEdit(n);
      else if (n.type === "frame" && event.target.closest(".board-frame-label")) beginEdit(n);
      else if (n.type === "swatch") toggleFilter(n.hex);
    });
    canvas.addEventListener("wheel", function (event) {
      if (!board) return;
      event.preventDefault();
      var r = canvas.getBoundingClientRect();
      zoomAt(event.clientX - r.left, event.clientY - r.top, Math.exp(-event.deltaY * 0.0015));
    }, { passive: false });
    canvas.addEventListener("dragover", onDragOver);
    canvas.addEventListener("dragleave", function (event) { if (!canvas.contains(event.relatedTarget)) hideGhost(); });
    canvas.addEventListener("drop", onDrop);

    ctxBar.addEventListener("pointerdown", function (event) { event.stopPropagation(); });
    ctxBar.addEventListener("click", onCtxClick);
    ctxBar.addEventListener("input", onCtxInput);
    ctxBar.addEventListener("keydown", function (event) {
      if (event.target.id === "board-note-hex" && (event.key === "Enter" || event.key === "Escape")) { event.preventDefault(); event.target.blur(); }
    });
    ctxBar.addEventListener("focusout", function (event) {
      if (event.target.id === "board-note-hex") setTimeout(updateCtx, 0);
    });

    Array.prototype.forEach.call(document.querySelectorAll("#board-dock [data-tool]"), function (b) {
      b.addEventListener("click", function () { setTool(b.getAttribute("data-tool")); });
    });
    byId("board-add-image").addEventListener("click", function () { byId("board-file").click(); });
    byId("board-file").addEventListener("change", function (event) {
      addFiles(Array.prototype.slice.call(event.target.files || []), viewCenter());
      event.target.value = "";
    });
    byId("board-tray-toggle").addEventListener("click", function () { setTray(tray.hidden); });
    byId("board-zoom-in").addEventListener("click", function () { zoomCenter(1.2); });
    byId("board-zoom-out").addEventListener("click", function () { zoomCenter(1 / 1.2); });
    byId("board-fit").addEventListener("click", fit);
    byId("board-snap").addEventListener("click", toggleSnap);
    byId("board-order").addEventListener("click", toggleOrder);

    byId("board-tray-grid").addEventListener("dragstart", function (event) {
      var item = event.target.closest("[data-entry]");
      if (!item) return;
      var id = Number(item.getAttribute("data-entry"));
      dragEntry = trayEntries.filter(function (entry) { return entry.id === id; })[0] || null;
      event.dataTransfer.setData("text/plain", "hyperbridge:entry/" + id);
      event.dataTransfer.effectAllowed = "copy";
    });
    byId("board-tray-grid").addEventListener("dragend", function () { dragEntry = null; hideGhost(); });
    byId("board-tray-filter").addEventListener("click", function (event) {
      if (!event.target.closest("[data-clear-filter]")) return;
      filter = null;
      loadTray();
      renderWorld();
    });

    var tabs = byId("boards-tabs");
    tabs.addEventListener("click", function (event) {
      var tab = event.target.closest("[data-board]");
      if (tab && (!board || Number(tab.getAttribute("data-board")) !== board.id)) switchBoard(Number(tab.getAttribute("data-board")));
    });
    tabs.addEventListener("dblclick", function (event) {
      var tab = event.target.closest("[data-board]");
      if (tab) startRename(tab);
    });
    byId("boards-new").addEventListener("click", function () { if (api()) commitEdit(); newBoard(); });
    byId("boards-promote").addEventListener("click", openPromote);
    byId("boards-clear").addEventListener("click", clearBoard);

    var dialog = byId("board-promote");
    byId("board-promote-form").addEventListener("submit", function (event) { event.preventDefault(); confirmPromote(); });
    byId("board-promote-cancel").addEventListener("click", closePromote);
    byId("board-scrim").addEventListener("click", closePromote);
    dialog.addEventListener("keydown", function (event) {
      event.stopPropagation();
      if (event.key === "Escape") { event.preventDefault(); closePromote(); }
    });
  }

  function refreshCount() {
    if (!api() || !api().list_boards) return;
    Promise.resolve(api().list_boards()).then(function (list) {
      if (!isOpen) boards = list || [];
      byId("boards-count").textContent = (list || []).length || "";
    }).catch(function () {});
  }

  function init() {
    library = byId("library");
    viewEl = byId("boards-view");
    if (!library || !viewEl) return;
    canvas = byId("board-canvas");
    world = byId("board-world");
    ctxBar = byId("board-ctx");
    tray = byId("board-tray");
    wire();
    if (api()) refreshCount();
    else window.addEventListener("pywebviewready", refreshCount);
  }

  init();
})();
