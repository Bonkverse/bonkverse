// friend_request.js: the friend-request waiting page
// (accounts/friend_request_wait.html, accounts/link_claims.py).
// Checks the claim every few seconds; when it's done, goes where the server
// says (now signed in, or the account added). Shows the time left, and while
// bonk.io pauses Bonkverse's calls ("paused" seconds in the answer), when
// checking resumes: the server keeps the claim until then.

(function () {
  "use strict";

  const box = document.querySelector("[data-friend-claim]");
  if (!box) return;
  const message = box.querySelector("[data-claim-message]");
  const countdown = box.querySelector("[data-claim-countdown]");
  const pausedNote = box.querySelector("[data-claim-paused]");
  const pausedFor = box.querySelector("[data-claim-paused-for]");
  let left = parseInt(box.dataset.secondsLeft, 10) || 0;
  if (!countdown || left <= 0) return; // already finished

  const CHECK_EVERY_MS = 4000;
  let stopped = false;

  function clock(seconds) {
    const s = Math.max(0, seconds);
    return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  }
  function show(seconds) {
    countdown.textContent = clock(seconds);
  }
  function showPause(seconds) {
    if (!pausedNote) return;
    pausedNote.hidden = !(seconds > 0);
    if (pausedFor && seconds > 0) pausedFor.textContent = clock(seconds);
  }
  let paused = parseInt(box.dataset.paused, 10) || 0;
  show(left);
  showPause(paused);
  const tick = setInterval(() => {
    show(--left);
    if (paused > 0) showPause(--paused);
  }, 1000);

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
    // The server may have moved the end (held through a pause).
    if (typeof json.seconds_left === "number") left = json.seconds_left;
    paused = json.paused || 0;
    showPause(paused);
    setTimeout(check, CHECK_EVERY_MS);
  }
  setTimeout(check, CHECK_EVERY_MS);
})();
