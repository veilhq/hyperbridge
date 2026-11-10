/* === Hyperbridge: settings view === */
(function () {
  "use strict";

  var ACCESS_LABELS = { open: "Open", none: "Unavailable" };
  var sources = [];
  var view, list, library, opener, followList, followInput, followError;
  var followed = [];

  function api() { return window.pywebview && window.pywebview.api; }

  function toast(variant, message) {
    if (window.HvToast) window.HvToast.show({ variant: variant, message: message });
  }

  function makeEl(tag, className, text) {
    var el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  }

  function buildRow(source) {
    var row = makeEl("div", "settings-source");
    if (!source.available) row.setAttribute("data-unavailable", "true");
    var text = makeEl("span", "settings-source-text");
    text.appendChild(makeEl("span", "settings-source-name", source.name));
    text.appendChild(makeEl("span", "settings-source-desc", source.description));
    var chip = makeEl("span", "status-chip status-chip-outlined-muted", ACCESS_LABELS[source.access] || "");
    row.appendChild(text);
    row.appendChild(chip);
    return row;
  }

  function render() {
    list.textContent = "";
    sources.forEach(function (source) { list.appendChild(buildRow(source)); });
  }

  function showFollowError(message) {
    followError.textContent = message || "";
    followError.hidden = !message;
  }

  function renderFollowed() {
    followList.textContent = "";
    followed.forEach(function (item) {
      var row = makeEl("div", "settings-source");
      var text = makeEl("span", "settings-source-text");
      text.appendChild(makeEl("span", "settings-source-name", item.label || item.url));
      text.appendChild(makeEl("span", "settings-source-desc", item.url));
      var remove = makeEl("button", "action-button action-button-ghost", "Remove");
      remove.type = "button";
      remove.setAttribute("aria-label", "Stop following " + (item.label || item.url));
      remove.addEventListener("click", function () {
        var bridge = api();
        Promise.resolve(bridge.unfollow_source(item.id)).then(function () {
          followed = followed.filter(function (other) { return other.id !== item.id; });
          renderFollowed();
        }).catch(function () { toast("error", "Could not remove."); });
      });
      row.appendChild(text);
      row.appendChild(makeEl("span", "status-chip status-chip-outlined-muted", item.kind === "user" ? "User" : "Channel"));
      row.appendChild(remove);
      followList.appendChild(row);
    });
  }

  function follow(event) {
    event.preventDefault();
    var bridge = api();
    var url = followInput.value.trim();
    if (!bridge || !url) return;
    showFollowError("");
    var button = $("#follow-add");
    button.disabled = true;
    Promise.resolve(bridge.follow_source(url)).then(function (result) {
      if (!result || !result.ok) { showFollowError(result && result.error ? result.error : "Could not follow that link."); return; }
      followInput.value = "";
      if (!followed.some(function (item) { return item.id === result.item.id; })) followed.push(result.item);
      renderFollowed();
    }).catch(function () { showFollowError("Could not follow that link."); }).then(function () { button.disabled = false; });
  }

  function loadFollowed() {
    var bridge = api();
    if (!bridge || !bridge.list_followed) return;
    Promise.resolve(bridge.list_followed()).then(function (result) {
      followed = result || [];
      renderFollowed();
    }).catch(function () {});
  }

  function load() {
    loadFollowed();
    var bridge = api();
    if (!bridge || !bridge.list_feed_sources) return Promise.resolve();
    return Promise.resolve(bridge.list_feed_sources()).then(function (result) {
      sources = result || [];
      render();
    }).catch(function () {});
  }

  function isOpen() { return library.hasAttribute("data-settings"); }

  function setOpen(open) {
    if (open === isOpen()) return;
    if (open) library.setAttribute("data-settings", "true");
    else library.removeAttribute("data-settings");
    view.hidden = !open;
    opener.setAttribute("aria-pressed", open ? "true" : "false");
    opener.toggleAttribute("data-active", open);
    if (open) load();
  }

  function init() {
    view = $("#settings-view");
    if (!view) return;
    list = $("#settings-list");
    followList = $("#follow-list");
    followInput = $("#follow-input");
    followError = $("#follow-error");
    $("#follow-form").addEventListener("submit", follow);
    followInput.addEventListener("input", function () { showFollowError(""); });
    library = $("#library");
    opener = $("#dock-settings");
    opener.addEventListener("click", function () { setOpen(!isOpen()); });
    $("#settings-close").addEventListener("click", function () { setOpen(false); });
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape" || !isOpen() || $("#app").inert) return;
      var tag = event.target && event.target.tagName;
      if (tag === "INPUT") { event.target.blur(); return; }
      setOpen(false);
    });
    document.addEventListener("hyperbridge:filter", function () { setOpen(false); });
    document.addEventListener("hyperbridge:feed", function () { setOpen(false); });
  }

  init();
})();
