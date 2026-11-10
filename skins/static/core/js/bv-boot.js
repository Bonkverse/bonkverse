// core/js/bv-boot.js
//
// What base.html does on every page once the body is in place. Loaded at the
// end of <body>, before the page's own scripts, so the order is the one the
// inline scripts had:
//
//   1. Django messages (#bv-messages, rendered by base.html) become toasts.
//   2. Lucide turns <i data-lucide="..."> into icons.
//
// Each step is skipped if its library didn't load (a CDN outage shouldn't
// stop the page's own scripts from running).

(function (window, document) {
  "use strict";

  function showMessages() {
    var list = document.getElementById("bv-messages");
    if (!list || !window.BVToast) return;
    list.querySelectorAll("li").forEach(function (li) {
      window.BVToast.show(li.textContent, { type: li.dataset.type || "info" });
    });
  }

  function drawIcons() {
    if (window.lucide) window.lucide.createIcons();
  }

  showMessages();
  drawIcons();
})(window, document);
