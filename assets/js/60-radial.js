/* === Hyperbridge: radial actions === */
(function () {
  "use strict";

  function byId(id) { return document.getElementById(id); }

  // Reuses a toolbar button's icon so the ring and the buttons always match.
  function iconOf(id) {
    var svg = byId(id) && byId(id).querySelector("svg");
    return svg ? svg.outerHTML : "";
  }

  function press(id) {
    var button = byId(id);
    if (button && !button.hidden) button.click();
  }

  // Opens the capture overlay with its input focused.
  function focusInput() {
    document.dispatchEvent(new CustomEvent("hyperbridge:capture-open"));
  }

  var GLYPHS = {
    compass: '<circle cx="12" cy="12" r="10"/><path d="m16.24 7.76-1.804 5.411a2 2 0 0 1-1.265 1.265L7.76 16.24l1.804-5.411a2 2 0 0 1 1.265-1.265z"/>',
    palette: '<circle cx="13.5" cy="6.5" r=".5"/><circle cx="17.5" cy="10.5" r=".5"/><circle cx="8.5" cy="7.5" r=".5"/><circle cx="6.5" cy="12.5" r=".5"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z"/>',
    calendar: '<path d="M8 2v4"/><path d="M16 2v4"/><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18"/>',
    link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    none: '<circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/>',
    layers: '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
    sort: '<path d="m21 16-4 4-4-4"/><path d="M17 20V4"/><path d="m3 8 4-4 4 4"/><path d="M7 4v16"/>',
    down: '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
    up: '<path d="m5 12 7-7 7 7"/><path d="M12 19V5"/>',
    title: '<path d="M12 4v16"/><path d="M4 7V5a1 1 0 0 1 1-1h14a1 1 0 0 1 1 1v2"/><path d="M9 20h6"/>'
  };

  // Inline Lucide-style glyph, so every tile in the ring is an icon.
  function glyph(name) {
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + GLYPHS[name] + "</svg>";
  }

  var CHOICE_GLYPHS = {
    group: { "": "none", color: "palette", year: "calendar", source: "link" },
    order: { color: "palette", newest: "down", oldest: "up", title: "title", source: "link" }
  };

  // Builds the View sub-rings: Group by and Order, each listing its choices with the current one marked.
  function viewRing() {
    var view = window.HyperbridgeView;
    if (!view) return [];
    function leaves(field, choices) {
      return choices.map(function (choice) {
        return {
          label: choice[1],
          svg: glyph(CHOICE_GLYPHS[field][choice[0]]),
          active: view.current(field) === choice[0],
          action: function () { view.choose(field, choice[0]); }
        };
      });
    }
    return [
      { label: "Group by", svg: glyph("layers"), children: leaves("group", view.groups) },
      { label: "Order", svg: glyph("sort"), children: leaves("order", view.orders) }
    ];
  }

  function actions() {
    var items = [
      { label: "Add or search", svg: iconOf("capture-submit"), action: focusInput },
      { label: "Discover", svg: glyph("compass"), action: function () { press("sets-discover"); } },
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
