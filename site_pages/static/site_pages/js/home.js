// home.js: the home page (site_pages/home.html).
// Counts down to the replay collector's next run: the server renders the
// seconds left in data-countdown; this ticks it once a second, then says the
// collection is running (the page shows new replays on the next visit).

(function () {
  "use strict";

  const el = document.querySelector("[data-countdown]");
  if (!el) return;

  const ends = Date.now() + Number(el.dataset.countdown) * 1000;
  const line = el.closest("[data-collector-next]");

  function tick() {
    const left = Math.round((ends - Date.now()) / 1000);
    if (left <= 0) {
      line.textContent = "Collecting new replays now";
      return;
    }
    el.textContent = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
    setTimeout(tick, 1000);
  }
  tick();
})();
