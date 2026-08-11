// skins/static/js/toast.js
//
// Centralized toast system for Bonkverse. Use BVToast.show(...) anywhere
// on the site instead of writing a page-local toast() helper.
//
// Usage:
//   BVToast.show("Applied to your active slot.", { type: "success" });
//   BVToast.show("Failed to apply skin.", { type: "error" });
//   const handle = BVToast.show("Syncing your friends…", { type: "info", spinner: true, sticky: true });
//   handle.update("Synced 1132 friends (3 new)", { type: "success", spinner: false });
//   handle.dismiss();

(function (window) {
  var ICONS = {
    success: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>',
    error:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>',
    warning: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>',
    info:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>'
  };

  function getStack() {
    var stack = document.getElementById("bv-toast-stack");
    if (!stack) {
      stack = document.createElement("div");
      stack.id = "bv-toast-stack";
      document.body.appendChild(stack);
    }
    return stack;
  }

  function show(text, opts) {
    opts = opts || {};
    var type = opts.type || "info";
    var duration = opts.sticky ? null : (opts.duration || 3200);

    var el = document.createElement("div");
    el.className = "bv-toast bv-toast-" + type;

    var iconHTML = opts.spinner
      ? '<span class="bv-toast-spinner"></span>'
      : '<span class="bv-toast-icon">' + (ICONS[type] || ICONS.info) + '</span>';

    el.innerHTML = iconHTML + '<span class="bv-toast-text"></span>';
    el.querySelector(".bv-toast-text").textContent = text;

    getStack().appendChild(el);
    requestAnimationFrame(function () {
      el.classList.add("bv-toast-visible");
    });

    var dismissTimer = null;

    function dismiss() {
      if (dismissTimer) clearTimeout(dismissTimer);
      el.classList.remove("bv-toast-visible");
      setTimeout(function () { el.remove(); }, 300);
    }

    function scheduleDismiss(ms) {
      if (dismissTimer) clearTimeout(dismissTimer);
      if (ms !== null) dismissTimer = setTimeout(dismiss, ms);
    }

    scheduleDismiss(duration);

    function update(newText, newOpts) {
      newOpts = newOpts || {};
      var newType = newOpts.type || type;

      el.className = "bv-toast bv-toast-" + newType + " bv-toast-visible";
      var newIconHTML = newOpts.spinner
        ? '<span class="bv-toast-spinner"></span>'
        : '<span class="bv-toast-icon">' + (ICONS[newType] || ICONS.info) + '</span>';
      el.innerHTML = newIconHTML + '<span class="bv-toast-text"></span>';
      el.querySelector(".bv-toast-text").textContent = newText;

      scheduleDismiss(newOpts.sticky ? null : (newOpts.duration || 3200));
    }

    return { dismiss: dismiss, update: update, element: el };
  }

  window.BVToast = { show: show };
})(window);