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

  // Builds the View sub-rings: Group by and Order, each listing its choices with the current one marked.
  function viewRing() {
    var view = window.HyperbridgeView;
    if (!view) return [];
    function leaves(field, choices) {
      return choices.map(function (choice) {
        return { label: choice[1], active: view.current(field) === choice[0], action: function () { view.choose(field, choice[0]); } };
      });
    }
    return [
      { label: "Group by", children: leaves("group", view.groups) },
      { label: "Order", children: leaves("order", view.orders) }
    ];
  }

  function actions() {
    var items = [
      { label: "Add or search", svg: iconOf("capture-submit"), action: focusInput },
      { label: "Discover", icon: "compass", action: function () { press("sets-discover"); } },
      { label: "View", svg: iconOf("group-toggle"), children: viewRing() },
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
