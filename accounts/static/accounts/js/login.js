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

  // 3. Chosen from "Choose an account" (?username=): the name is filled in,
  //    so start in the password box.
  const name = document.querySelector('input[name="username"]');
  const password = document.querySelector('input[name="password"]');
  if (name && name.value && password && !password.value) password.focus();

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

  // Long waits also say when they end, in the player's own time zone
  // (RFC-0003 Part 1, item 8: "try again at 9:42 PM").
  const until = document.getElementById("login-wait-until");
  if (until && seconds >= 90) {
    const at = new Date(deadline).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    until.textContent = `You can try again at ${at}.`;
    until.hidden = false;
  }

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
      if (until) until.hidden = true;
      return;
    }
    button.textContent = `Log in (wait ${format(left)})`;
    setTimeout(tick, 1000);
  }

  tick();
})();
