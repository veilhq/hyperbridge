/* === Hyperbridge: sets - shared state and helpers === */
var SETS_VIEW_KEY = "hyperbridge-sets-view";
var ARM_MS = 2500;
var METER_CELLS = 10;
var MS_PER_DAY = 86400000;
var SORTS = ["recent", "name", "size"];

var ICONS = {
  compass: '<circle cx="12" cy="12" r="10"/><path d="m16.24 7.76-1.804 5.411a2 2 0 0 1-1.265 1.265L7.76 16.24l1.804-5.411a2 2 0 0 1 1.265-1.265z"/>',
  layers: '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',
  plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
  pin: '<path d="M12 17v5"/><path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"/>',
  edit: '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/>',
  trash: '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>',
  back: '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>'
};

var sets = [];
var selectedId = null;
var feedOpen = false;
var browsing = false;
var editing = null;
var armedId = null;
var armTimer = null;
var query = "";
var sortKey = "recent";
var cardsEl;
var tabsCollapsed = true;

function api() { return window.pywebview && window.pywebview.api; }

function toast(variant, message) {
  if (window.HvToast) window.HvToast.show({ variant: variant, message: message });
}

// Returns the inline SVG for a named glyph.
function icon(name) {
  return '<svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + ICONS[name] + '</svg>';
}

function esc(text) {
  return String(text === null || text === undefined ? "" : text).replace(/[&<>"']/g, function (char) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
  });
}

function setById(id) {
  return sets.find(function (item) { return item.id === id; }) || null;
}

function selectedSet() { return setById(selectedId); }

function pinnedSets() {
  return sets.filter(function (item) { return item.pinned; });
}

// Whole days since a set last changed, or null when it has no change time.
function daysSince(item) {
  var stamp = Date.parse(item.updated);
  if (isNaN(stamp)) return null;
  return Math.max(0, Math.floor((Date.now() - stamp) / MS_PER_DAY));
}

function agoLabel(days) {
  if (days === null) return "";
  if (days <= 1) return "today";
  if (days < 7) return days + "d ago";
  if (days < 31) return Math.round(days / 7) + "w ago";
  return Math.round(days / 30) + "mo ago";
}

function entriesLabel(count) { return count + (count === 1 ? " ENTRY" : " ENTRIES"); }

function loadViewPrefs() {
  try {
    var saved = JSON.parse(localStorage.getItem(SETS_VIEW_KEY) || "{}");
    if (SORTS.indexOf(saved.sort) >= 0) sortKey = saved.sort;
    if (typeof saved.collapsed === "boolean") tabsCollapsed = saved.collapsed;
  } catch (err) { /* ignore */ }
}

function saveViewPrefs() {
  try { localStorage.setItem(SETS_VIEW_KEY, JSON.stringify({ sort: sortKey, collapsed: tabsCollapsed })); } catch (err) { /* ignore */ }
}
