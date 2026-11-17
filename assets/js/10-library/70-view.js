  var GROUP_CHOICES = [["", "None"], ["color", "Color"], ["year", "Year"], ["source", "Source"]];
  var ORDER_CHOICES = [["color", "Color"], ["newest", "Newest"], ["oldest", "Oldest"], ["title", "Title"], ["source", "Source"], ["random", "Random"]];

  // A fresh seed for the random order; each launch and each re-pick of Random deals a new shuffle.
  function newSeed() {
    return Math.floor(Math.random() * 2147483647);
  }

  // The launch default for a view field when it is one of the choices, else the fallback.
  function launchDefault(key, choices, fallback) {
    var value = window.hbDefault ? window.hbDefault(key, fallback) : fallback;
    return choices.some(function (choice) { return choice[0] === value; }) ? value : fallback;
  }

  // Group and order choices persist; the radial menu reads and sets them through window.HyperbridgeView.
  function setupGroup() {
    function read(key, choices, fallback) {
      var saved = "";
      try { saved = localStorage.getItem(key) || ""; } catch (err) { saved = ""; }
      return choices.some(function (choice) { return choice[0] === saved; }) ? saved : fallback;
    }

    function choose(field, value) {
      try { localStorage.setItem("hyperbridge-" + field, value); } catch (err) { /* ignore */ }
      state[field] = value;
      if (field === "order" && value === "random") state.seed = newSeed();
      state.signature = ""; state.signatureParts = [];
      state.cascade = true;
      load(true);
    }

    state.group = read("hyperbridge-group", GROUP_CHOICES, launchDefault("library_group", GROUP_CHOICES, ""));
    state.order = read("hyperbridge-order", ORDER_CHOICES, launchDefault("library_order", ORDER_CHOICES, "newest"));
    state.seed = newSeed();
    window.HyperbridgeView = {
      groups: GROUP_CHOICES,
      orders: ORDER_CHOICES,
      current: function (field) { return state[field]; },
      choose: choose
    };
  }
