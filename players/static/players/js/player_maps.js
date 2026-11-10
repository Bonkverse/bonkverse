// player_maps.js — the modes ring on a player's Maps & modes tab (players/maps.html)
//
// Pointing at a slice, or its legend row, puts that mode in the middle of
// the ring. The legend rows are buttons, so this works by keyboard and touch.

(function () {
  "use strict";

  const ring = document.querySelector("[data-ring]");
  if (!ring) return;
  const pct = ring.querySelector("[data-ring-pct]");
  const name = ring.querySelector("[data-ring-name]");
  const items = [...ring.querySelectorAll(".pv-legend__item")];
  const slices = [...ring.querySelectorAll(".pv-ring__slice")];

  function focus(i) {
    const item = items[i];
    if (!item) return;
    pct.textContent = `${item.dataset.share}%`;
    name.textContent = item.dataset.label;
    items.forEach((b, k) => b.setAttribute("aria-pressed", String(k === i)));
    slices.forEach((s, k) => s.classList.toggle("is-active", k === i));
  }

  slices.forEach((s) => {
    const i = Number(s.dataset.slice);
    s.addEventListener("pointerenter", () => focus(i));
    s.addEventListener("click", () => focus(i));
  });
  items.forEach((b) => {
    const i = Number(b.dataset.slice);
    b.addEventListener("click", () => focus(i));
    b.addEventListener("pointerenter", () => focus(i));
    b.addEventListener("focus", () => focus(i));
  });
  focus(0);
})();
