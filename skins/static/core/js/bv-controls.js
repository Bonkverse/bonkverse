// core/js/bv-controls.js
//
// Behaviour for the shared controls in css/controls.css:
// - .bv-num steppers: <button data-step="1"> / <button data-step="-1"> next to
//   an <input type="number"> step it and fire "input", like typing would.
// - .bv-range: keeps --fill (the coloured part of the track) in step with
//   the value, for browsers without a native filled track.

(function () {
  "use strict";

  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".bv-num__step[data-step]");
    if (!btn) return;
    const input = btn.closest(".bv-num").querySelector("input");
    if (!input) return;
    const dir = Number(btn.dataset.step);
    const step = Number(input.step) || 1;
    const min = input.min === "" ? -Infinity : Number(input.min);
    const max = input.max === "" ? Infinity : Number(input.max);
    const current = Number(input.value) || (dir > 0 ? min - step : 0);
    input.value = String(Math.min(max, Math.max(isFinite(min) ? min : 0, current + dir * step)));
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });

  function fill(range) {
    const min = Number(range.min) || 0, max = Number(range.max) || 100;
    range.style.setProperty("--fill", `${((Number(range.value) - min) / (max - min || 1)) * 100}%`);
  }
  document.addEventListener("input", (e) => {
    if (e.target.classList && e.target.classList.contains("bv-range")) fill(e.target);
  });
  window.BVControls = { fill };
  document.querySelectorAll(".bv-range").forEach(fill);
})();
