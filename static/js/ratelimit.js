// 429 page (templates/429.html): live countdown, then reload once the limit resets.
//
// Reads #rate-limit-countdown:
//   data-seconds  seconds until the visitor's limit resets (absent when unknown)
//   data-reload   "true" for page views; absent for form submissions, which must
//                 not reload (the browser would offer to resubmit the form).
// The server-rendered text stays as-is when JS is off or the wait is unknown.
(function () {
  "use strict";

  const el = document.getElementById("rate-limit-countdown");
  const seconds = Number(el && el.dataset.seconds);
  if (!el || !Number.isFinite(seconds) || seconds <= 0) return;

  const reload = el.dataset.reload === "true";
  // Count against a fixed deadline so a backgrounded tab (whose timers slow down)
  // still shows the right time when it comes back.
  const deadline = Date.now() + seconds * 1000;
  // One extra second so the reload lands after the limit window has rolled over.
  const RELOAD_BUFFER_MS = 1000;

  function format(left) {
    if (left >= 60) {
      const m = Math.floor(left / 60);
      const s = String(left % 60).padStart(2, "0");
      return `${m}:${s}`;
    }
    return `${left} second${left === 1 ? "" : "s"}`;
  }

  function render(left) {
    el.textContent = reload
      ? `Try again in ${format(left)}.`
      : `Wait ${format(left)}, then submit again.`;
  }

  function finish() {
    if (reload) {
      el.textContent = "Ready. Reloading…";
      setTimeout(() => window.location.reload(), RELOAD_BUFFER_MS);
    } else {
      el.textContent = "You can submit again now.";
    }
  }

  function tick() {
    const left = Math.ceil((deadline - Date.now()) / 1000);
    if (left <= 0) {
      clearInterval(timer);
      finish();
      return;
    }
    render(left);
  }

  const timer = setInterval(tick, 250);
  tick();
})();
