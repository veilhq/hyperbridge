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

  // Runs a library export or import through the bridge, disabling both buttons while it works.
  function transfer(method, working, done) {
    var bridge = api();
    if (!bridge || !bridge[method]) return;
    var buttons = [$("#library-export"), $("#library-import")];
    buttons.forEach(function (button) { button.disabled = true; });
    Promise.resolve(bridge[method]()).then(function (result) {
      if (!result || result.status === "failed") toast("error", (result && result.error) || "Something went wrong.");
      else if (result.status !== "cancelled") done(result);
    }).catch(function () { toast("error", "Something went wrong."); }).then(function () {
      buttons.forEach(function (button) { button.disabled = false; });
    });
    toast("info", working);
  }

  function entries(count) { return count + (count === 1 ? " entry" : " entries"); }

  // Wires the local-network Share and Fetch controls in the Library section.
  function initShare() {
    var start = $("#share-start"), stop = $("#share-stop"), info = $("#share-info");
    var timer = null;
    function show(sharing, text) {
      start.hidden = sharing;
      stop.hidden = !sharing;
      info.hidden = !sharing;
      info.textContent = text || "";
    }
    function clear() { if (timer) { clearInterval(timer); timer = null; } }
    function halt() { clear(); show(false); }
    start.addEventListener("click", function () {
      var bridge = api();
      if (!bridge || !bridge.start_share) return;
      Promise.resolve(bridge.start_share()).then(function (result) {
        if (!result || result.status !== "sharing") { toast("error", (result && result.error) || "Could not start sharing."); return; }
        var left = result.seconds;
        function paint() {
          var minutes = Math.floor(left / 60), seconds = left % 60;
          show(true, "Sharing at " + result.address + " with code " + result.code + ". Closes in " + minutes + ":" + (seconds < 10 ? "0" : "") + seconds + ".");
        }
        clear();
        paint();
        timer = setInterval(function () { left -= 1; if (left <= 0) halt(); else paint(); }, 1000);
      }).catch(function () { toast("error", "Could not start sharing."); });
    });
    stop.addEventListener("click", function () {
      var bridge = api();
      halt();
      if (bridge && bridge.stop_share) bridge.stop_share();
    });
    $("#fetch-form").addEventListener("submit", function (event) {
      event.preventDefault();
      var bridge = api();
      var go = $("#fetch-go");
      var address = $("#fetch-address").value.trim(), code = $("#fetch-code").value.trim();
      if (!bridge || !bridge.fetch_from_share || !address || !code) return;
      go.disabled = true;
      toast("info", "Fetching new entries.");
      Promise.resolve(bridge.fetch_from_share(address, code)).then(function (result) {
        if (!result || result.status === "failed") { toast("error", (result && result.error) || "Something went wrong."); return; }
        toast("success", "Fetched " + entries(result.added) + (result.skipped ? ", " + result.skipped + " already here." : "."));
        if (result.added) document.dispatchEvent(new CustomEvent("hyperbridge:changed"));
      }).catch(function () { toast("error", "Something went wrong."); }).then(function () { go.disabled = false; });
    });
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
    $("#library-export").addEventListener("click", function () {
      transfer("export_library", "Choose where to save the library.", function (result) {
        toast("success", "Exported " + entries(result.entries) + ".");
      });
    });
    $("#library-import").addEventListener("click", function () {
      transfer("import_library", "Choose a library file to import.", function (result) {
        toast("success", "Imported " + entries(result.added) + (result.skipped ? ", skipped " + result.skipped + " already here." : "."));
        document.dispatchEvent(new CustomEvent("hyperbridge:changed"));
      });
    });
    initShare();
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
