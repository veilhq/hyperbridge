/* === Hyperbridge: saved colors - hex values kept on this machine for later === */
(function () {
  "use strict";

  var ICONS = {
    "copy": '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
    "image": '<rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/>',
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "plus": '<path d="M5 12h14"/><path d="M12 5v14"/>',
    "trash": '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>'
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
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;" }[c];
    });
  }
  function parseHex(value) {
    var m = String(value == null ? "" : value).trim().match(/^#?([0-9a-f]{3}|[0-9a-f]{6})$/i);
    if (!m) return null;
    var h = m[1].length === 3 ? m[1].replace(/(.)/g, "$1$1") : m[1];
    return "#" + h.toUpperCase();
  }

  var library, viewEl, grid;
  var isOpen = false;
  var colors = [];
  var renaming = null;

  function colorById(id) {
    for (var i = 0; i < colors.length; i += 1) if (colors[i].id === id) return colors[i];
    return null;
  }

  // ---- Shared: save, list and copy, used by the lightbox and boards too ----
  function save(hex, entryId, name) {
    var bridge = api();
    if (!bridge || !bridge.save_color) return Promise.resolve(null);
    return Promise.resolve(bridge.save_color(hex, name || "", entryId == null ? null : entryId)).then(function (result) {
      if (!result || !result.ok) { toast("error", (result && result.error) || "Could not save that color."); return null; }
      toast(result.created ? "success" : "info", result.created ? "Saved " + result.color.hex + " to colors." : result.color.hex + " is already saved.");
      announce("hyperbridge:colors-changed");
      return result.color;
    }).catch(function () { toast("error", "Could not save that color."); return null; });
  }

  function list() {
    var bridge = api();
    if (!bridge || !bridge.list_colors) return Promise.resolve([]);
    return Promise.resolve(bridge.list_colors()).then(function (found) { return found || []; }).catch(function () { return []; });
  }

  function copy(hex) {
    function done() { toast("success", "Copied " + hex + "."); }
    function fallback() {
      var field = document.createElement("textarea");
      field.value = hex;
      document.body.appendChild(field);
      field.select();
      try { document.execCommand("copy"); done(); } catch (err) { toast("error", "Could not copy " + hex + "."); }
      field.remove();
    }
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(hex).then(done, fallback);
    else fallback();
  }

  // ---- Render ----
  function cardHTML(item) {
    var name = item.name ? esc(item.name) : "Name";
    var source = item.source
      ? '<button class="action-icon" type="button" data-act="source" aria-label="Open source image" data-tooltip="' + esc(item.source.title || "Open source image") + '">' + icon("image") + "</button>"
      : "";
    return '<div class="colors-card" data-color-id="' + item.id + '" style="--swatch:' + item.hex + '">' +
      '<button class="colors-card-fill" type="button" data-act="copy" aria-label="Copy ' + item.hex + '"></button>' +
      '<div class="colors-card-details"><div class="colors-card-meta"><button class="colors-card-name' + (item.name ? "" : " is-blank") + '" type="button" data-act="rename" data-tooltip="Rename">' + name + "</button>" +
      '<span class="colors-card-hex">' + item.hex + "</span></div>" +
      '<div class="colors-card-actions">' + source +
      '<button class="action-icon" type="button" data-act="filter" aria-label="Show entries with a color like ' + item.hex + '" data-tooltip="Show similar">' + icon("search") + "</button>" +
      '<button class="action-icon" type="button" data-act="copy" aria-label="Copy hex" data-tooltip="Copy hex">' + icon("copy") + "</button>" +
      '<button class="action-icon action-icon-danger" type="button" data-act="delete" aria-label="Delete color" data-tooltip="Delete color">' + icon("trash") + "</button>" +
      "</div></div></div>";
  }

  function render() {
    grid.innerHTML = colors.map(cardHTML).join("");
    byId("colors-empty").hidden = colors.length > 0;
    byId("colors-tally").textContent = pad2(colors.length);
    byId("colors-count").textContent = colors.length || "";
  }

  function load() {
    return list().then(function (found) {
      colors = found;
      if (isOpen) render();
      else byId("colors-count").textContent = colors.length || "";
    });
  }

  // ---- Card actions ----
  function startRename(card, item) {
    var button = card.querySelector(".colors-card-name");
    var input = document.createElement("input");
    input.className = "form-input-inline colors-card-name-input";
    input.value = item.name;
    input.maxLength = 60;
    input.placeholder = "Name";
    input.setAttribute("aria-label", "Color name");
    button.replaceWith(input);
    renaming = item.id;
    input.focus();
    input.select();
    var finished = false;
    function finish(keep) {
      if (finished) return;
      finished = true;
      renaming = null;
      var name = input.value.trim();
      if (!keep || name === item.name) { render(); return; }
      Promise.resolve(api().rename_color(item.id, name)).then(function (result) {
        if (result && result.ok) item.name = result.color.name;
        else toast("error", (result && result.error) || "Could not rename that color.");
        render();
        announce("hyperbridge:colors-changed");
      });
    }
    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter") { event.preventDefault(); finish(true); }
      else if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); finish(false); }
    });
    input.addEventListener("blur", function () { finish(true); });
  }

  function remove(item) {
    Promise.resolve(api().delete_color(item.id)).then(function () {
      colors = colors.filter(function (other) { return other.id !== item.id; });
      render();
      toast("success", "Deleted " + item.hex + ".");
      announce("hyperbridge:colors-changed");
    }).catch(function () { toast("error", "Could not delete that color."); });
  }

  function onGridClick(event) {
    var button = event.target.closest("[data-act]");
    var card = event.target.closest("[data-color-id]");
    if (!button || !card) return;
    var item = colorById(Number(card.getAttribute("data-color-id")));
    if (!item) return;
    var act = button.getAttribute("data-act");
    if (act === "copy") copy(item.hex);
    else if (act === "rename") startRename(card, item);
    else if (act === "delete") remove(item);
    else if (act === "source" && item.entry_id) announce("hyperbridge:open", { id: item.entry_id });
    else if (act === "filter") { setOpen(false); announce("hyperbridge:color", { color: item.hex }); }
  }

  function onAddInput() {
    var field = byId("colors-add-field"), value = byId("colors-add-hex").value, hex = parseHex(value);
    field.classList.toggle("is-invalid", !hex && value.trim() !== "");
    field.style.setProperty("--hue", hex || "transparent");
  }

  function onAddSubmit(event) {
    event.preventDefault();
    var hexInput = byId("colors-add-hex"), nameInput = byId("colors-add-name");
    var hex = parseHex(hexInput.value);
    if (!hex) { byId("colors-add-field").classList.add("is-invalid"); hexInput.focus(); return; }
    save(hex, null, nameInput.value).then(function (color) {
      if (!color) return;
      hexInput.value = "";
      nameInput.value = "";
      onAddInput();
      hexInput.focus();
    });
  }

  // ---- Open and close: the colors view takes over the library pane ----
  function setOpen(value) {
    if (value === isOpen) return;
    isOpen = value;
    library.toggleAttribute("data-colors-view", value);
    viewEl.hidden = !value;
    var tab = byId("sets-colors");
    tab.classList.toggle("content-card-active", value);
    if (value) tab.setAttribute("aria-current", "true");
    else tab.removeAttribute("aria-current");
    announce("hyperbridge:colors", { open: value });
    if (value) { library.scrollTop = 0; render(); load(); }
  }

  function openColors() {
    if (isOpen) return;
    if (library.hasAttribute("data-settings")) byId("sets-settings").click();
    window.hbNavigate(function () { setOpen(true); });
  }

  function wire() {
    Array.prototype.forEach.call(viewEl.querySelectorAll("[data-icon]"), function (el) {
      el.insertAdjacentHTML("afterbegin", icon(el.getAttribute("data-icon")));
    });
    byId("sets-colors").addEventListener("click", openColors);
    // Any other rail destination leaves the colors view first.
    byId("sets-rail").addEventListener("click", function (event) {
      if (!isOpen) return;
      var target = event.target.closest(".sets-tab, #sets-settings, #sets-new");
      if (target && target.id !== "sets-colors") setOpen(false);
    }, true);
    ["hyperbridge:filter", "hyperbridge:sets", "hyperbridge:feed", "hyperbridge:latest", "hyperbridge:similar", "hyperbridge:tag", "hyperbridge:color"].forEach(function (name) {
      document.addEventListener(name, function () { setOpen(false); });
    });
    document.addEventListener("hyperbridge:boards", function (event) { if (event.detail && event.detail.open) setOpen(false); });
    document.addEventListener("hyperbridge:colors-changed", function () { if (renaming === null) load(); });
    new MutationObserver(function () { if (isOpen && library.hasAttribute("data-settings")) setOpen(false); })
      .observe(library, { attributes: true, attributeFilter: ["data-settings"] });
    // Keys typed into the view's own fields stay with those fields.
    viewEl.addEventListener("keydown", function (event) {
      if (event.target.closest && event.target.closest("input")) event.stopPropagation();
    });
    grid.addEventListener("click", onGridClick);
    byId("colors-add-hex").addEventListener("input", onAddInput);
    byId("colors-add").addEventListener("submit", onAddSubmit);
  }

  // Saves a color from anywhere in the app; entryId links it to the library image it came from.
  window.HbColors = { save: save, list: list };

  function init() {
    library = byId("library");
    viewEl = byId("colors-view");
    if (!library || !viewEl) return;
    grid = byId("colors-grid");
    wire();
    if (api()) load();
    else window.addEventListener("pywebviewready", load);
  }

  init();
})();
