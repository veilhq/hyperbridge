/* === Hyperbridge: tag vocabulary picker shared by the lightbox and the library selection === */
(function () {
  "use strict";

  var pending = null;

  function api() { return window.pywebview && window.pywebview.api; }
  function byId(id) { return document.getElementById(id); }

  function toast(variant, message) {
    if (window.HvToast) window.HvToast.show({ variant: variant, message: message });
  }

  function esc(text) {
    return String(text).replace(/[&<>"']/g, function (c) { return "&#" + c.charCodeAt(0) + ";"; });
  }

  function mark(body) {
    return '<svg class="icon-glyph-sm tag-pick-mark" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"' +
      ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + body + "</svg>";
  }

  var ALL = mark('<path d="M20 6 9 17l-5-5"/>');
  var SOME = mark('<path d="M5 12h14"/>');
  var NONE = mark("");

  function plural(count) { return count + (count === 1 ? " entry" : " entries"); }

  // Tells the grid, sidebar and open lightbox that tags changed.
  function announce() {
    document.dispatchEvent(new CustomEvent("hyperbridge:changed"));
    document.dispatchEvent(new CustomEvent("hyperbridge:tags"));
  }

  // Puts a term on every entry, or takes it off when every one of them already has it.
  function toggle(name, ids, all, done) {
    var bridge = api();
    if (!bridge) return;
    var call = all ? bridge.remove_tags(ids, name) : bridge.add_tags(ids, name);
    Promise.resolve(call).then(function (count) {
      if (!count) { toast("error", all ? "Could not remove the tag." : "Could not tag."); return; }
      toast("success", all ? "Removed " + name + " from " + plural(count) + "." : "Tagged " + plural(count) + " " + name + ".");
      announce();
      if (done) done();
    }).catch(function () { toast("error", "Could not change tags."); });
  }

  // One row per vocabulary term marked with its state across the entries, then a row to make a new term.
  // counts maps a tag name to how many of the entries carry it.
  function items(terms, counts, ids, done) {
    var rows = (terms || []).map(function (term) {
      var held = counts[term.name] || 0;
      var all = held > 0 && held >= ids.length;
      return { label: (all ? ALL : held ? SOME : NONE) + esc(term.name), action: function () { toggle(term.name, ids, all, done); } };
    });
    if (rows.length) rows.push({ separator: true });
    rows.push({ label: NONE + "New tag...", action: function () { openNew(ids, done); } });
    return rows;
  }

  function showError(message) {
    byId("tag-new-error").textContent = message || "";
    byId("tag-new-error").hidden = !message;
  }

  // Opens the new-tag dialog; with ids the new term also goes onto those entries.
  function openNew(ids, done) {
    pending = { ids: ids || [], done: done };
    var count = pending.ids.length;
    byId("tag-new-hint").textContent = count
      ? "Adds a term to your tag vocabulary and puts it on " + (count === 1 ? "this entry." : count + " entries.")
      : "Adds a term to your tag vocabulary.";
    byId("tag-new-name").value = "";
    showError("");
    byId("tag-new-scrim").classList.add("visible");
    byId("tag-new").show();
    byId("tag-new-name").focus();
  }

  function closeNew() {
    if (!byId("tag-new").open) return;
    byId("tag-new").close();
    byId("tag-new-scrim").classList.remove("visible");
    pending = null;
  }

  function submitNew() {
    var bridge = api();
    var name = byId("tag-new-name").value.trim();
    if (!bridge || !pending) return;
    if (!name) { showError("Enter a tag name."); return; }
    var job = pending;
    Promise.resolve(bridge.create_tag(name)).then(function (made) {
      if (!made || !made.ok) { showError((made && made.error) || "Could not add the tag."); return; }
      closeNew();
      if (!job.ids.length) {
        toast(made.existed ? "info" : "success", made.existed ? made.name + " is already a tag." : "Added " + made.name + ".");
        announce();
        if (job.done) job.done(made.name);
        return;
      }
      return Promise.resolve(bridge.add_tags(job.ids, made.name)).then(function (count) {
        toast(count ? "success" : "error", count ? "Tagged " + plural(count) + " " + made.name + "." : "Could not tag.");
        announce();
        if (job.done) job.done(made.name);
      });
    }).catch(function () { showError("Could not add the tag."); });
  }

  function init() {
    if (!byId("tag-new")) return;
    byId("tag-new-form").addEventListener("submit", function (event) { event.preventDefault(); submitNew(); });
    byId("tag-new-cancel").addEventListener("click", closeNew);
    byId("tag-new-scrim").addEventListener("click", closeNew);
    byId("tag-new").addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      closeNew();
    });
  }

  init();
  window.HbTagPick = { items: items, openNew: openNew };
})();
