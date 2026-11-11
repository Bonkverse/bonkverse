// Login page (skins/templates/skins/login.html).
//
// 1. One submit per click. The first press turns the button off until the
//    page comes back, so impatient clicks don't each send bonk.io another
//    password (four tries in one second on 2026-11-10, every one a wrong
//    password counted against the whole site).
// 2. When a login has to wait (bonk.io is limiting logins from Bonkverse, or
//    this account has had too many wrong passwords), the server renders the
//    button disabled with data-retry-after (seconds to wait). Count down on the
//    button and turn it back on when the wait ends (skins/login.py).
(function () {
  "use strict";

  const button = document.getElementById("login-submit");
  if (!button) return;

  const form = button.form;
  if (form) {
    form.addEventListener("submit", function () {
      // Disable after the submit event so the browser still sends the form.
      setTimeout(function () {
        button.disabled = true;
        button.textContent = "Logging in…";
      }, 0);
    });
    // Coming back with the Back button restores the page as it was left,
    // button off; turn it back on unless this page is counting down a wait.
    window.addEventListener("pageshow", function (event) {
      if (event.persisted && !button.dataset.retryAfter) {
        button.disabled = false;
        button.textContent = "Log in";
      }
    });
  }

  const seconds = Number(button.dataset.retryAfter);
  if (!Number.isFinite(seconds) || seconds <= 0) return;

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
      button.textContent = "Log in";
      return;
    }
    button.textContent = `Log in (wait ${format(left)})`;
    setTimeout(tick, 1000);
  }

  tick();
})();
