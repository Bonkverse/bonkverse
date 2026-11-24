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
//
// How long a toast stays:
//   - error and warning: until closed (×), so there's time to read what went
//     wrong (login errors give a reason and a time to retry). Pass
//     `duration` to time one out anyway.
//   - success and info: a few seconds, longer for long text; never while the
//     pointer is over it or it has focus.
//   - `sticky: true`: until closed or dismissed by code, for any type.

(function (window) {
  var ICONS = {
    success: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>',
    error:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>',
    warning: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>',
    info:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>'
  };

  function getStack() {
    var stack = document.getElementById("site-toast-stack");
    if (!stack) {
      stack = document.createElement("div");
      stack.id = "site-toast-stack";
      document.body.appendChild(stack);
    }
    return stack;
  }

  // Errors and warnings wait to be closed unless the caller times them.
  function durationFor(text, type, opts) {
    if (opts.sticky) return null;
    if (opts.duration) return opts.duration;
    if (type === "error" || type === "warning") return null;
    // About 60 ms a character, at least 3.2 s: time to read a longer one.
    return Math.max(3200, String(text || "").length * 60);
  }

  function show(text, opts) {
    opts = opts || {};
    var type = opts.type || "info";
    var duration = durationFor(text, type, opts);

    var el = document.createElement("div");
    el.className = "site-toast site-toast-" + type;
    // Errors interrupt a screen reader; the rest wait their turn.
    el.setAttribute("role", type === "error" ? "alert" : "status");

    var iconHTML = opts.spinner
      ? '<span class="site-toast-spinner"></span>'
      : '<span class="site-toast-icon">' + (ICONS[type] || ICONS.info) + '</span>';

    var closeHTML = '<button type="button" class="site-toast-close" aria-label="Dismiss">&times;</button>';

    el.innerHTML = iconHTML + '<span class="site-toast-text"></span>' + closeHTML;
    el.querySelector(".site-toast-text").textContent = text;

    getStack().appendChild(el);
    requestAnimationFrame(function () {
      el.classList.add("site-toast-visible");
    });

    var dismissTimer = null;

    function dismiss() {
      if (dismissTimer) clearTimeout(dismissTimer);
      el.classList.remove("site-toast-visible");
      setTimeout(function () { el.remove(); }, 300);
    }

    // Manual close button — the only way to dismiss a sticky (duration:
    // null) toast, since scheduleDismiss never fires one for it.
    el.querySelector(".site-toast-close").addEventListener("click", dismiss);

    // The time left is kept so hovering or focusing the toast pauses it.
    var remaining = duration;
    var startedAt = 0;
    var paused = false;

    function scheduleDismiss(ms) {
      if (dismissTimer) clearTimeout(dismissTimer);
      dismissTimer = null;
      remaining = ms;
      if (ms === null || paused) return;
      startedAt = Date.now();
      dismissTimer = setTimeout(dismiss, ms);
    }

    function pause() {
      if (paused) return;
      paused = true;
      if (dismissTimer) {
        clearTimeout(dismissTimer);
        dismissTimer = null;
        remaining = Math.max(1000, remaining - (Date.now() - startedAt));
      }
    }

    function resume() {
      if (!paused) return;
      paused = false;
      scheduleDismiss(remaining);
    }

    el.addEventListener("mouseenter", pause);
    el.addEventListener("mouseleave", resume);
    el.addEventListener("focusin", pause);
    el.addEventListener("focusout", resume);

    scheduleDismiss(duration);

    function update(newText, newOpts) {
      newOpts = newOpts || {};
      var newType = newOpts.type || type;

      el.className = "site-toast site-toast-" + newType + " site-toast-visible";
      el.setAttribute("role", newType === "error" ? "alert" : "status");
      var newIconHTML = newOpts.spinner
        ? '<span class="site-toast-spinner"></span>'
        : '<span class="site-toast-icon">' + (ICONS[newType] || ICONS.info) + '</span>';
      el.innerHTML = newIconHTML + '<span class="site-toast-text"></span>' + closeHTML;
      el.querySelector(".site-toast-text").textContent = newText;
      el.querySelector(".site-toast-close").addEventListener("click", dismiss);

      scheduleDismiss(durationFor(newText, newType, newOpts));
    }

    return { dismiss: dismiss, update: update, element: el };
  }

  window.BVToast = { show: show };
})(window);
