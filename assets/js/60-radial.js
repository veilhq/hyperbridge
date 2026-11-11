/* === Hyperbridge: radial actions === */
(function () {
  "use strict";

  function byId(id) { return document.getElementById(id); }

  // Reuses a dock button's icon so the ring and the dock always match.
  function iconOf(id) {
    var svg = byId(id) && byId(id).querySelector("svg");
    return svg ? svg.outerHTML : "";
  }

  function press(id) {
    var button = byId(id);
    if (button && !button.hidden) button.click();
  }

  // Focuses the dock input, opening the dock first when it is collapsed.
  function focusInput() {
    var dock = byId("dock");
    if (dock && dock.getAttribute("data-collapsed") === "true") press("dock-toggle");
    var input = byId("dock-input");
    if (input) input.focus();
  }

  function actions() {
    var items = [
      { label: "Add or search", svg: iconOf("capture-submit"), action: focusInput },
      { label: "Discover", svg: iconOf("dock-find"), action: function () { press("sets-discover"); } },
      { label: "View", svg: iconOf("group-toggle"), action: function () { press("group-toggle"); } },
      { label: "Settings", svg: iconOf("dock-settings"), action: function () { press("dock-settings"); } }
    ];
    var find = byId("dock-find");
    if (find && !find.hidden) items.splice(2, 0, { label: "Find more", svg: iconOf("dock-find"), action: function () { press("dock-find"); } });
    return items;
  }

  if (!window.HvRadialMenu) return;
  // Shift + right-click opens the ring from anywhere except over an open dialog.
  window.HvRadialMenu.register("body", function (body, event) {
    return event.target.closest("dialog[open]") ? null : actions();
  }, { shift: true });
})();
