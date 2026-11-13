  // Reads one pasted image file as base64 and creates an entry from it.
  function addPastedImage(file) {
    var bridge = api();
    if (!bridge || !bridge.add_image_data) return;
    var reader = new FileReader();
    reader.onload = function () {
      Promise.resolve(bridge.add_image_data(reader.result, file.name || "")).then(function (result) {
        if (!result || !result.ok) {
          toast("error", result && result.error ? result.error : "Could not add that image.");
          return;
        }
        toast("success", "Added image.");
        load(true);
        refreshStats();
      }).catch(function () { toast("error", "Could not add that image."); });
    };
    reader.readAsDataURL(file);
  }

  // Pasting an image from the clipboard adds it to the library; pasted text is left alone.
  function onPaste(event) {
    var lightbox = $("#lightbox");
    if (lightbox && lightbox.open) return;
    var items = event.clipboardData ? Array.prototype.slice.call(event.clipboardData.items) : [];
    var images = items.filter(function (item) { return item.kind === "file" && item.type.indexOf("image/") === 0; });
    if (!images.length) return;
    event.preventDefault();
    images.forEach(function (item) {
      var file = item.getAsFile();
      if (file) addPastedImage(file);
    });
  }

  function onSubmit(event) {
    event.preventDefault();
    var bridge = api();
    var url = urlInput.value.trim();
    if (!isLink(url)) {
      document.dispatchEvent(new CustomEvent("hyperbridge:capture-close"));
      return;
    }
    if (!bridge || !bridge.add_link || submitBtn.disabled) return;
    showError("");
    if (finding && bridge.discover_images) {
      discoverPage(url);
      return;
    }
    submitBtn.disabled = true;
    bridge.add_link(url).then(function (result) {
      if (!result || !result.ok) {
        showError(result && result.error ? result.error : "Capture failed.");
        return;
      }
      urlInput.value = "";
      document.dispatchEvent(new CustomEvent("hyperbridge:capture-close"));
      toast(result.already_captured ? "info" : "success", result.already_captured ? "Already captured." : "Captured.");
      if (!result.already_captured) {
        load(true);
        refreshStats();
      }
    }).catch(function () {
      showError("Capture failed.");
    }).then(function () {
      submitBtn.disabled = false;
    });
  }

  // A pasted link is a capture; any other text filters the library.
  function isLink(text) { return /^https?:\/\//i.test(text); }

  function onDockInput() {
    showError("");
    $("#capture-form").setAttribute("data-mode", isLink(searchInput.value.trim()) ? "link" : "search");
    clearTimeout(searchTimer);
    searchTimer = setTimeout(function () {
      var query = isLink(searchInput.value.trim()) ? "" : searchInput.value.trim();
      if (query === state.query) return;
      state.query = query;
      state.cascade = true;
      clearSelection();
      load(true);
    }, SEARCH_DEBOUNCE_MS);
  }

  function watchSentinel() {
    if (!("IntersectionObserver" in window)) return;
    var observer = new IntersectionObserver(function (observed) {
      if (!observed[0].isIntersecting) return;
      if (candidates) loadMoreFeed();
      else if (state.entries.length < state.total) load(false);
    }, { root: $("#library"), rootMargin: "400px" });
    feedObserver = observer;
    observer.observe(sentinel);
  }
