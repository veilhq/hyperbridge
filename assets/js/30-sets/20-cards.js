
/* === Hyperbridge: sets - Sets view cards === */
var HEX_COLOR = /^#[0-9a-f]{6}$/i;

function visibleSets() {
  var needle = query.trim().toLowerCase();
  var list = sets.filter(function (item) {
    return !needle || (item.name + " " + item.description).toLowerCase().indexOf(needle) >= 0;
  });
  list.sort(function (first, second) {
    if (sortKey === "name") return first.name.localeCompare(second.name);
    if (sortKey === "size") return second.count - first.count;
    return (second.updated || "").localeCompare(first.updated || "") || first.name.localeCompare(second.name);
  });
  return list;
}

function paletteHtml(item) {
  var swatches = (item.palette || []).filter(function (color) { return HEX_COLOR.test(color); });
  if (!swatches.length) return "";
  return '<span class="poster-card-palette" aria-hidden="true">' + swatches.map(function (color) {
    return '<i style="background:' + color + '"></i>';
  }).join("") + "</span>";
}

// Ten cells showing a set's size relative to the largest set.
function meterHtml(count) {
  var largest = sets.reduce(function (most, item) { return Math.max(most, item.count); }, 1);
  var lit = count ? Math.max(1, Math.round(count / largest * METER_CELLS)) : 0;
  var cells = "";
  for (var i = 0; i < METER_CELLS; i++) cells += "<i" + (i < lit ? ' class="on"' : "") + "></i>";
  return '<span class="poster-card-meter" title="' + count + ' entries, relative to your largest set" aria-hidden="true">' + cells + "</span>";
}

function toolButton(action, id, glyph, label, pressed) {
  return '<button class="action-icon" type="button" data-' + action + '="' + id + '" aria-label="' + label + '" data-tooltip="' + label + '"' +
    (pressed === undefined ? "" : ' aria-pressed="' + pressed + '"') + (action === "del" && armedId === id ? " data-armed" : "") + ">" + icon(glyph) + "</button>";
}

function imageHtml(item) {
  if (!item.count) return '<div class="poster-card-image is-empty"><span class="poster-card-empty">EMPTY</span></div>';
  var cover = item.cover ? '<img src="' + esc(item.cover) + '" alt="" draggable="false">' : '<div class="poster-card-fill sets-card-fill"></div>';
  return '<div class="poster-card-image">' + cover + "</div>";
}

function formHtml(item) {
  var isNew = item === null;
  return '<div class="poster-card"' + (isNew ? "" : ' data-set="' + item.id + '"') + ">" +
    (isNew || !item.count ? '<div class="poster-card-image is-empty"><span class="poster-card-empty">' + (isNew ? "NEW" : "EMPTY") + "</span></div>" : imageHtml(item)) +
    '<form class="poster-card-form" data-form="' + (isNew ? "new" : item.id) + '" novalidate>' +
    '<input class="form-input" name="name" placeholder="Set name" maxlength="100" aria-label="Set name" autocomplete="off" value="' + esc(isNew ? "" : item.name) + '">' +
    '<input class="form-input" name="description" placeholder="Description (optional)" maxlength="200" aria-label="Set description" autocomplete="off" value="' + esc(isNew ? "" : item.description) + '">' +
    '<span class="sets-card-hint">ENTER SAVE - ESC CANCEL</span><button type="submit" hidden></button></form></div>';
}

function cardHtml(item) {
  if (editing === item.id) return formHtml(item);
  var days = daysSince(item);
  var age = days === null ? "" : days <= 1 ? '<span class="poster-card-fresh">TODAY</span>' : "<span>" + esc(agoLabel(days).toUpperCase()) + "</span>";
  var pinLabel = item.pinned ? "Unpin from tabs" : "Pin to tabs";
  return '<div class="poster-card" data-set="' + item.id + '">' + imageHtml(item) +
    '<span class="poster-card-count">' + entriesLabel(item.count) + "</span>" +
    '<button class="poster-card-open" type="button" data-open="' + item.id + '" aria-label="Open ' + esc(item.name) + '"></button>' +
    '<div class="poster-card-body"><div class="poster-card-title">' + esc(item.name) + "</div>" +
    '<div class="poster-card-desc"><span>' + esc(item.description || "No description.") + "</span></div>" + (item.count ? paletteHtml(item) : "") + "</div>" +
    '<div class="poster-card-meta">' + meterHtml(item.count) + age + "</div>" +
    '<span class="poster-card-tools' + (item.pinned ? " keep" : "") + '">' +
    toolButton("pin", item.id, "pin", pinLabel, item.pinned ? "true" : "false") + toolButton("edit", item.id, "edit", "Edit") +
    toolButton("del", item.id, "trash", armedId === item.id ? "Click again to delete" : "Delete") + "</span></div>";
}

function addTileHtml() {
  return '<button class="poster-card poster-card-add" type="button" data-new>' +
    '<div class="poster-card-image is-empty"><span class="poster-card-empty">' + icon("plus") + "</span></div>" +
    '<span class="poster-card-count">NEW</span>' +
    '<div class="poster-card-body"><div class="poster-card-title">New set</div>' +
    '<div class="poster-card-desc"><span>Name it, add a description, then fill it from the library.</span></div></div>' +
    '<div class="poster-card-meta">' + meterHtml(0) + "<span>0</span></div></button>";
}

// Redraws the Sets view: tally, sort buttons and the card grid (the edit form takes focus).
function renderCards() {
  var list = visibleSets();
  var searching = query.trim() !== "";
  var html = list.map(cardHtml).join("");
  if (editing === "new") html += formHtml(null);
  else if (!searching) html += addTileHtml();
  cardsEl.innerHTML = html;
  $("#sets-tally").textContent = list.length + " OF " + sets.length + " SETS";
  $("#sets-none").hidden = list.length > 0 || !searching;
  Array.prototype.forEach.call(document.querySelectorAll("#sets-sort [data-sort]"), function (button) {
    var active = button.getAttribute("data-sort") === sortKey;
    button.setAttribute("aria-pressed", active ? "true" : "false");
    if (active) $("#sets-sort").style.setProperty("--segment-index", SORTS.indexOf(sortKey));
  });
  var field = cardsEl.querySelector("form input");
  if (field) {
    field.focus();
    field.select();
  }
}
