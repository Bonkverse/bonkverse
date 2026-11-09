// Login page (skins/templates/skins/login.html): when bonk.io is limiting
// logins from Bonkverse, the server renders the Login button disabled with
// data-retry-after (seconds left in the pause). Count down on the button and
// turn it back on when the pause ends, so players don't resubmit into it
// (six tries in a minute on 2026-11-09).
(function () {
  "use strict";

  const button = document.getElementById("login-submit");
  const seconds = Number(button && button.dataset.retryAfter);
  if (!button || !Number.isFinite(seconds) || seconds <= 0) return;

  // A fixed deadline keeps the count right if the tab is in the background.
  const deadline = Date.now() + seconds * 1000;

  function format(left) {
    if (left >= 60) {
      return `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
    }
    return `${left}s`;
  }

  function tick() {
    const left = Math.ceil((deadline - Date.now()) / 1000);
    if (left <= 0) {
      button.disabled = false;
      button.textContent = "Login";
      return;
    }
    button.textContent = `Login (wait ${format(left)})`;
    setTimeout(tick, 1000);
  }

  tick();
})();
