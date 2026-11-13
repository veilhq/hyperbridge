  var PAGE_SIZE = 60;
  var MAX_REFRESH = 200;
  var POLL_MS = 2000;
  var CASCADE_MAX = 12;
  var SEARCH_DEBOUNCE_MS = 250;

  var state = { query: "", tag: "", color: "", setId: null, group: "", order: "color", years: [], entries: [], total: 0, loading: false, ticket: 0, signature: "", pendingIds: {}, cascade: false, refreshQueued: false };
  var grid, emptyEl, sentinel, searchInput, urlInput, submitBtn, errorEl;
  var setsCache = [];
  var tagsCache = [];
  var selected = new Set();
  var anchorId = null;
  var searchTimer = null;
  var pollTimer = null;
var candidates = null;
  var finding = false;
  var feedObserver = null;
  var findTicket = 0;
  var SKELETON_RATIOS = ["4 / 5", "1 / 1", "3 / 4", "5 / 4", "2 / 3", "1 / 1", "4 / 3", "3 / 4"];

  function api() { return window.pywebview && window.pywebview.api; }

  function makeEl(tag, className, text) {
    var el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  }
