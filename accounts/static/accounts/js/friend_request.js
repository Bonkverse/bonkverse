// friend_request.js: the friend-request waiting page
// (accounts/friend_request_wait.html, accounts/link_claims.py).
// Checks the claim every few seconds; when it's done, goes where the server
// says (now signed in, or the account added). Shows the time left.

(function () {
  "use strict";

  const box = document.querySelector("[data-friend-claim]");
  if (!box) return;
  const message = box.querySelector("[data-claim-message]");
  const countdown = box.querySelector("[data-claim-countdown]");
  let left = parseInt(box.dataset.secondsLeft, 10) || 0;
  if (!countdown || left <= 0) return; // already finished

  const CHECK_EVERY_MS = 4000;
  let stopped = false;

  function show(seconds) {
    const s = Math.max(0, seconds);
    countdown.textContent = Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  }
  show(left);
  const tick = setInterval(() => show(--left), 1000);

  async function check() {
    if (stopped) return;
    const res = await BVApi.post(box.dataset.statusUrl, {});
    const json = res.json || {};
    if (json.status === "done") {
      stopped = true;
      clearInterval(tick);
      message.textContent = "Got it! Signing you in…";
      window.location.assign(json.redirect || "/");
      return;
    }
    if (json.status === "expired" || json.status === "refused") {
      stopped = true;
      clearInterval(tick);
      message.textContent = json.message || "That didn't work. Start over to try again.";
      return;
    }
    setTimeout(check, CHECK_EVERY_MS);
  }
  setTimeout(check, CHECK_EVERY_MS);
})();
