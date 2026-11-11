  var GROUP_CHOICES = [["", "None"], ["color", "Color"], ["year", "Year"], ["source", "Source"]];
  var ORDER_CHOICES = [["color", "Color"], ["newest", "Newest"], ["oldest", "Oldest"], ["title", "Title"], ["source", "Source"]];
  var DEFAULT_ORDER = "color";

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
      state.signature = ""; state.signatureParts = [];
      state.cascade = true;
      load(true);
    }

    state.group = read("hyperbridge-group", GROUP_CHOICES, "");
    state.order = read("hyperbridge-order", ORDER_CHOICES, DEFAULT_ORDER);
    window.HyperbridgeView = {
      groups: GROUP_CHOICES,
      orders: ORDER_CHOICES,
      current: function (field) { return state[field]; },
      choose: choose
    };
  }
