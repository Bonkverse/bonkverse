// profile.js — every player profile tab (players/_layout.html)
//
// The tab row scrolls sideways when it doesn't fit (phones). This keeps the
// current tab in view and fades the edge that has more tabs behind it, so
// people can tell the row scrolls (design review): data-more-start and
// data-more-end on [data-pv-tabs] switch the fades in players/css/profile.css.

(function () {
  "use strict";

  const wrap = document.querySelector("[data-pv-tabs]");
  const row = wrap && wrap.querySelector(".bv-tabs");
  if (!row) return;

  const current = row.querySelector('[aria-current="page"]');
  if (current && row.scrollWidth > row.clientWidth) {
    // Center the current tab without scrolling the page itself.
    row.scrollLeft = current.offsetLeft - (row.clientWidth - current.offsetWidth) / 2;
  }

  function update() {
    const max = row.scrollWidth - row.clientWidth;
    wrap.toggleAttribute("data-more-start", row.scrollLeft > 2);
    wrap.toggleAttribute("data-more-end", row.scrollLeft < max - 2);
  }
  row.addEventListener("scroll", update, { passive: true });
  window.addEventListener("resize", update);
  update();
})();
