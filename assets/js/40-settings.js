/* === Hyperbridge: settings view === */
(function () {
  "use strict";

  var ACCESS_LABELS = { open: "Open", none: "Unavailable" };
  var sources = [];
  var view, list, library, opener, followList, followInput, followError;
  var followed = [];
  var FOLLOW_PAGE = 48;
  var KIND_LABELS = { channel: "Channels", user: "Users", pinterest: "Boards", tumblr: "Blogs" };
  var followKind = "";
  var followShown = FOLLOW_PAGE;

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

  function kindOf(item) { return KIND_LABELS[item.kind] ? item.kind : "channel"; }

  // Returns the followed sources matching the type chips and filter box, grouped by type then label.
  function visibleFollowed() {
    var needle = $("#follow-filter").value.trim().toLowerCase();
    return followed.filter(function (item) {
      if (followKind && kindOf(item) !== followKind) return false;
      return !needle || (item.label || "").toLowerCase().indexOf(needle) !== -1 || (item.url || "").toLowerCase().indexOf(needle) !== -1;
    }).sort(function (a, b) {
      var order = Object.keys(KIND_LABELS);
      return order.indexOf(kindOf(a)) - order.indexOf(kindOf(b)) || (a.label || a.url).toLowerCase().localeCompare((b.label || b.url).toLowerCase());
    });
  }

  // Paints the type chips with counts; hidden until a second type exists.
  function renderFollowKinds() {
    var box = $("#follow-kinds");
    box.textContent = "";
    var counts = {};
    followed.forEach(function (item) { counts[kindOf(item)] = (counts[kindOf(item)] || 0) + 1; });
    var kinds = Object.keys(KIND_LABELS).filter(function (kind) { return counts[kind]; });
    if (followKind && !counts[followKind]) followKind = "";
    [["", "All", followed.length]].concat(kinds.map(function (kind) { return [kind, KIND_LABELS[kind], counts[kind]]; })).forEach(function (entry) {
      var chip = makeEl("button", "nav-tab", entry[1] + " " + entry[2]);
      chip.type = "button";
      chip.setAttribute("aria-pressed", entry[0] === followKind ? "true" : "false");
      chip.classList.toggle("nav-tab-active", entry[0] === followKind);
      chip.addEventListener("click", function () { followKind = entry[0]; followShown = FOLLOW_PAGE; renderFollowed(); });
      box.appendChild(chip);
    });
  }

  function renderFollowed() {
    followList.textContent = "";
    $("#follow-tools").hidden = followed.length < 2;
    renderFollowKinds();
    var found = visibleFollowed();
    var more = $("#follow-more");
    more.hidden = found.length <= followShown;
    more.textContent = "Show more (" + (found.length - followShown) + " left)";
    if (followed.length && !found.length) followList.appendChild(makeEl("span", "settings-source-desc", "No followed sources match."));
    found.slice(0, followShown).forEach(function (item) {
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
      row.appendChild(makeEl("span", "status-chip status-chip-outlined-muted", item.kind === "user" ? "User" : item.kind === "pinterest" ? "Board" : item.kind === "tumblr" ? "Blog" : "Channel"));
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
          show(true, "Address " + (result.addresses || [result.address]).join(" or ") + ", code " + result.code + ". Closes in " + minutes + ":" + (seconds < 10 ? "0" : "") + seconds + ".");
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

  var MACHINE_ICONS = {
    laptop: '<path d="M18 5a2 2 0 0 1 2 2v8.526a2 2 0 0 0 .212.897l1.068 2.127a1 1 0 0 1-.9 1.45H3.62a1 1 0 0 1-.9-1.45l1.068-2.127A2 2 0 0 0 4 15.526V7a2 2 0 0 1 2-2z"/><path d="M20.054 15.987H3.946"/>',
    desktop: '<rect width="20" height="14" x="2" y="3" rx="2"/><line x1="8" x2="16" y1="21" y2="21"/><line x1="12" x2="12" y1="17" y2="21"/>'
  };
  MACHINE_ICONS.computer = MACHINE_ICONS.desktop;
  var MACHINE_LABELS = { laptop: "Laptop", desktop: "Desktop", computer: "Computer" };

  // Lists the machines found on the network and lets the Operator pair, sync or unpair; polls while Settings is open.
  function initSync() {
    var list = $("#sync-list"), info = $("#sync-info"), pairStart = $("#sync-pair-start"), pairStop = $("#sync-pair-stop");
    var timer = null, lastReceived = null, busy = false;
    var codes = {};

    function pad(value) { return (value < 10 ? "0" : "") + value; }

    function row(machine) {
      var item = document.createElement("div");
      item.className = "settings-source";
      item.setAttribute("data-machine", machine.id);
      item.classList.add("settings-machine");
      var kind = MACHINE_ICONS[machine.kind] ? machine.kind : "computer";
      var icon = document.createElement("span");
      icon.className = "settings-machine-icon";
      icon.setAttribute("role", "img");
      icon.setAttribute("aria-label", MACHINE_LABELS[kind]);
      icon.setAttribute("data-online", machine.online ? "true" : "false");
      icon.innerHTML = '<svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + MACHINE_ICONS[kind] + "</svg>";
      item.appendChild(icon);
      var text = document.createElement("span");
      text.className = "settings-source-text";
      var name = document.createElement("span");
      name.className = "settings-source-name";
      name.textContent = machine.name;
      var desc = document.createElement("span");
      desc.className = "settings-source-desc";
      desc.textContent = machine.paired ? (machine.online ? "Paired, on the network." : "Paired, not seen right now.") : "Showing a pairing code. Enter it to pair.";
      text.appendChild(name);
      text.appendChild(desc);
      item.appendChild(text);
      if (machine.paired) {
        var sync = document.createElement("button");
        sync.className = "action-button action-button-ghost";
        sync.type = "button";
        sync.textContent = "Sync";
        sync.disabled = !machine.online || busy;
        sync.addEventListener("click", function () { runSync(machine, sync); });
        var unpair = document.createElement("button");
        unpair.className = "action-button action-button-ghost";
        unpair.type = "button";
        unpair.textContent = "Unpair";
        unpair.addEventListener("click", function () {
          var bridge = api();
          if (bridge && bridge.unpair) Promise.resolve(bridge.unpair(machine.id)).then(poll);
        });
        item.appendChild(sync);
        item.appendChild(unpair);
      } else {
        var form = document.createElement("form");
        form.className = "settings-follow-form";
        form.autocomplete = "off";
        var input = document.createElement("input");
        input.className = "form-input settings-code";
        input.type = "text";
        input.inputMode = "numeric";
        input.maxLength = 6;
        input.placeholder = "Code";
        input.setAttribute("aria-label", "Pairing code shown on " + machine.name);
        input.value = codes[machine.id] || "";
        input.addEventListener("input", function () { codes[machine.id] = input.value; });
        var go = document.createElement("button");
        go.className = "action-button action-button-ghost";
        go.type = "submit";
        go.textContent = "Pair";
        form.appendChild(input);
        form.appendChild(go);
        form.addEventListener("submit", function (event) {
          event.preventDefault();
          var bridge = api();
          if (!bridge || !bridge.pair_with || !input.value.trim()) return;
          go.disabled = true;
          Promise.resolve(bridge.pair_with(machine.id, input.value.trim())).then(function (result) {
            if (!result || result.status === "failed") { toast("error", (result && result.error) || "Could not pair."); return; }
            delete codes[machine.id];
            toast("success", "Paired with " + result.name + ".");
            poll();
          }).catch(function () { toast("error", "Could not pair."); }).then(function () { go.disabled = false; });
        });
        item.appendChild(form);
      }
      return item;
    }

    function runSync(machine, button) {
      var bridge = api();
      if (!bridge || !bridge.sync_with || busy) return;
      busy = true;
      button.disabled = true;
      toast("info", "Syncing with " + machine.name + ".");
      syncOverlay.local = true;
      paintSyncOverlay();
      Promise.resolve(bridge.sync_with(machine.id)).then(function (result) {
        if (!result || result.status === "failed") { toast("error", (result && result.error) || "Could not sync."); return; }
        var got = result.pulled ? result.pulled.added : 0;
        var sent = result.pushed ? result.pushed.added : 0;
        var edits = (result.pulled ? result.pulled.updated : 0) + (result.pushed ? result.pushed.updated : 0);
        var removed = (result.pulled ? result.pulled.deleted : 0) + (result.pushed ? result.pushed.deleted : 0);
        toast(result.push_error ? "error" : "success", "Received " + entries(got) + ", sent " + entries(sent) + (edits ? ", synced " + edits + (edits === 1 ? " edit" : " edits") : "") + (removed ? ", removed " + removed : "") + "." + (result.push_error ? " " + result.push_error : ""));
        if (got || (result.pulled && (result.pulled.updated || result.pulled.deleted || result.pulled.sets))) document.dispatchEvent(new CustomEvent("hyperbridge:changed"));
      }).catch(function () { toast("error", "Could not sync."); }).then(function () { busy = false; syncOverlay.local = false; paintSyncOverlay(); poll(); });
    }

    var phoneInfo = $("#phone-info"), phoneCreate = $("#phone-create"), phoneOff = $("#phone-off");
    var phoneToken = "";

    // Shows the phone capture state: the address to send links to, and the token once after it is created.
    function paintPhone(phone) {
      var enabled = !!(phone && phone.enabled);
      phoneCreate.textContent = enabled ? "New token" : "Create phone token";
      phoneOff.hidden = !enabled;
      phoneInfo.hidden = !enabled;
      if (!enabled) { phoneToken = ""; phoneInfo.textContent = ""; return; }
      var urls = phone.addresses.map(function (address) { return "http://" + address + ":" + phone.port + "/capture"; });
      phoneInfo.textContent = "Send to " + urls.join(" or ") + (phoneToken ? ". Token: " + phoneToken + " (shown once; header X-Token)." : ". The token is set; make a new one to see it again.");
    }

    function paint(status) {
      paintPhone(status.phone);
      var pairing = status.pairing_seconds > 0;
      pairStart.hidden = pairing;
      pairStop.hidden = !pairing;
      info.hidden = !pairing;
      info.textContent = pairing ? "Enter code " + status.code + " on the other machine. Closes in " + Math.floor(status.pairing_seconds / 60) + ":" + pad(status.pairing_seconds % 60) + "." : "";
      var active = document.activeElement;
      if (active && list.contains(active) && active.tagName === "INPUT") return;
      list.textContent = "";
      status.machines.forEach(function (machine) { list.appendChild(row(machine)); });
    }

    function poll() {
      var bridge = api();
      if (!bridge || !bridge.sync_status) return;
      Promise.resolve(bridge.sync_status()).then(function (status) {
        if (!status || status.status !== "ok") return;
        if (lastReceived !== null && status.received > lastReceived) document.dispatchEvent(new CustomEvent("hyperbridge:changed"));
        lastReceived = status.received;
        paint(status);
      }).catch(function () {});
    }

    pairStart.addEventListener("click", function () {
      var bridge = api();
      if (!bridge || !bridge.start_pairing) return;
      Promise.resolve(bridge.start_pairing()).then(function (result) {
        if (!result || result.status !== "ok") toast("error", (result && result.error) || "Could not open pairing.");
        poll();
      });
    });
    phoneCreate.addEventListener("click", function () {
      var bridge = api();
      if (!bridge || !bridge.new_phone_token) return;
      Promise.resolve(bridge.new_phone_token()).then(function (result) {
        if (!result || result.status !== "ok") { toast("error", (result && result.error) || "Could not create the phone token."); return; }
        phoneToken = result.token;
        poll();
      });
    });
    phoneOff.addEventListener("click", function () {
      var bridge = api();
      if (bridge && bridge.clear_phone_token) Promise.resolve(bridge.clear_phone_token()).then(function () { phoneToken = ""; poll(); });
    });
    pairStop.addEventListener("click", function () {
      var bridge = api();
      if (bridge && bridge.stop_pairing) Promise.resolve(bridge.stop_pairing()).then(poll);
    });

    return {
      start: function () { if (timer) return; poll(); timer = setInterval(poll, 3000); },
      stop: function () { if (timer) { clearInterval(timer); timer = null; } }
    };
  }

  var syncPoller = null;
  var syncOverlay = { local: false, remote: false };

  // Shows the full-screen sync overlay while this machine starts a sync or another machine is syncing with it.
  function paintSyncOverlay() {
    var overlay = $("#sync-overlay");
    if (overlay) overlay.hidden = !(syncOverlay.local || syncOverlay.remote);
  }

  function watchSyncActivity() {
    setInterval(function () {
      var bridge = api();
      if (!bridge || !bridge.sync_busy) return;
      Promise.resolve(bridge.sync_busy()).then(function (state) {
        syncOverlay.remote = !!(state && state.syncing);
        paintSyncOverlay();
      }).catch(function () {});
    }, 1500);
  }

  function isOpen() { return library.hasAttribute("data-settings"); }

  // Shows one settings section at a time, remembers the choice, and moves between tabs with the arrow keys.
  function initTabs() {
    var tabs = Array.prototype.slice.call(view.querySelectorAll(".settings-tab"));
    if (!tabs.length) return;
    function show(name, focus) {
      var known = tabs.some(function (tab) { return tab.getAttribute("data-tab") === name; });
      if (!known) name = tabs[0].getAttribute("data-tab");
      tabs.forEach(function (tab) {
        var on = tab.getAttribute("data-tab") === name;
        tab.classList.toggle("nav-tab-active", on);
        tab.setAttribute("aria-selected", on ? "true" : "false");
        tab.tabIndex = on ? 0 : -1;
        $("#settings-tab-" + tab.getAttribute("data-tab")).hidden = !on;
        if (on && focus) tab.focus();
      });
      try { localStorage.setItem("hyperbridge-settings-tab", name); } catch (err) { /* ignore */ }
    }
    tabs.forEach(function (tab, index) {
      tab.addEventListener("click", function () { show(tab.getAttribute("data-tab")); });
      tab.addEventListener("keydown", function (event) {
        var step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
        if (!step) return;
        event.preventDefault();
        show(tabs[(index + step + tabs.length) % tabs.length].getAttribute("data-tab"), true);
      });
    });
    var saved = "";
    try { saved = localStorage.getItem("hyperbridge-settings-tab") || ""; } catch (err) { saved = ""; }
    show(saved);
  }

  function setOpen(open) {
    if (open === isOpen()) return;
    if (open) library.setAttribute("data-settings", "true");
    else library.removeAttribute("data-settings");
    view.hidden = !open;
    opener.setAttribute("aria-pressed", open ? "true" : "false");
    opener.toggleAttribute("data-active", open);
    if (open) load();
    if (syncPoller) { if (open) syncPoller.start(); else syncPoller.stop(); }
  }

  function init() {
    view = $("#settings-view");
    if (!view) return;
    list = $("#settings-list");
    initTabs();
    followList = $("#follow-list");
    followInput = $("#follow-input");
    $("#follow-filter").addEventListener("input", function () { followShown = FOLLOW_PAGE; renderFollowed(); });
    $("#follow-more").addEventListener("click", function () { followShown += FOLLOW_PAGE; renderFollowed(); });
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
    syncPoller = initSync();
    watchSyncActivity();
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
