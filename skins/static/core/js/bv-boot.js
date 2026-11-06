// core/js/bv-boot.js
//
// What base.html does on every page once the body is in place. Loaded at the
// end of <body>, before the page's own scripts, so the order is the one the
// inline scripts had:
//
//   1. Django messages (#bv-messages, rendered by base.html) become toasts.
//   2. The particle background (#particles-js).
//   3. Lucide turns <i data-lucide="..."> into icons.
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

  function startParticles() {
    if (typeof window.particlesJS !== "function" || !document.getElementById("particles-js")) return;
    window.particlesJS("particles-js", {
      particles: {
        number: { value: 120, density: { enable: true, value_area: 1000 } },
        color: { value: ["#ffffff", "#00c3ff", "#ff99ff", "#ffcc00"] },
        shape: { type: "circle" },
        opacity: { value: 0.9, random: true },
        size: { value: 2.5, random: true },
        line_linked: { enable: false },
        move: { enable: true, speed: 0.8, direction: "none", random: true, straight: false, out_mode: "out" },
      },
      interactivity: {
        detect_on: "canvas",
        events: { onhover: { enable: false }, onclick: { enable: false } },
      },
      retina_detect: true,
    });
  }

  function drawIcons() {
    if (window.lucide) window.lucide.createIcons();
  }

  showMessages();
  startParticles();
  drawIcons();
})(window, document);
