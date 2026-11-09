// core/js/bv-wear.js
//
// Wearing a skin on bonk.io, and the one bonk.io login modal
// (skins/partials/_bonk_login_modal.html). Every page that has a Wear button
// uses this; none has its own copy. Needs bv-api.js and toast.js.
//
//   BVWear.wear(url)                          // toasts the outcome
//   BVWear.wear(url, { onStatus: (text, type) => ... })   // show it yourself
//
// The JSON contract is in skins/wear_skin.py:
//   ok                          -> applied
//   401 auth="bonkverse"        -> sign in to the site
//   401 auth="bonk"             -> open the bonk.io login modal (expired token)
//   anything else               -> show `message` (too big, rate limited, ...)
//
// Spam guard (incident 2026-11-09): one wear at a time per tab, and after the
// server says to wait (429/503 with retry_after) the page waits without
// sending anything. The server enforces the same per account
// (skins/wear_skin.py); this just stops the requests from being sent.
//
// After a successful bonk.io login the wear is retried ONCE. If bonk.io still
// wants a login, we say so instead of reopening the modal: a modal that keeps
// coming back was the bug fixed in #39, and this keeps it from returning.

(function (window, document) {
  "use strict";

  var APPLIED = "Applied to your active slot.";
  var FAILED = "Failed to apply skin.";
  var STILL_REFUSED = "bonk.io still didn't accept the login. Please try again in a minute.";
  var IN_PROGRESS = "Still applying your last skin. Give it a second.";

  var inFlight = false;   // a wear request is waiting on the server
  var waitUntil = 0;      // Date.now() before which we don't send wears

  function secondsLeft() {
    return Math.max(0, Math.ceil((waitUntil - Date.now()) / 1000));
  }

  function waitMessage() {
    var s = secondsLeft();
    return "Wearing is paused for a moment. Try again in " + s + " second" + (s === 1 ? "" : "s") + ".";
  }

  function toast(text, type) {
    if (window.BVToast) window.BVToast.show(text, { type: type });
  }

  // ── The login modal ─────────────────────────────────────────
  var modal = null;
  var pendingSuccess = null;

  function el(id) { return document.getElementById(id); }

  function setMsg(text, kind) {
    var msg = el("bonk-login-msg");
    if (!msg) return;
    msg.textContent = text;
    msg.className = "modal-feedback" + (kind ? " " + kind : "");
  }

  function openLogin(onSuccess) {
    modal = modal || el("bonk-login-modal");
    if (!modal) {
      // A page with a Wear button but no modal partial: say so plainly.
      console.error("BVWear: page is missing skins/partials/_bonk_login_modal.html");
      return false;
    }
    pendingSuccess = onSuccess;
    setMsg("", "");
    modal.classList.add("open");
    document.body.style.overflow = "hidden";
    var first = el("bonk-username");
    if (first) first.focus();
    return true;
  }

  function closeLogin() {
    if (!modal) return;
    modal.classList.remove("open");
    document.body.style.overflow = "";
    var form = el("bonk-login-form");
    if (form) form.reset();
    pendingSuccess = null;
  }

  async function submitLogin(e) {
    e.preventDefault();
    var form = e.target;
    var url = modal.dataset.loginUrl;
    setMsg("Logging in…", "");
    var res = await window.BVApi.post(url, new FormData(form));
    if (!res.ok || !res.json.ok) {
      setMsg("❌ " + (res.json.message || res.json.error || "Login failed"), "error");
      return;
    }
    setMsg("✅ Logged in!", "success");
    var done = pendingSuccess;
    setTimeout(function () {
      closeLogin();
      if (done) done();
    }, 400);
  }

  function wireModal() {
    modal = el("bonk-login-modal");
    if (!modal) return;
    el("bonk-login-form").addEventListener("submit", submitLogin);
    el("bonk-login-modal-close").addEventListener("click", closeLogin);
    el("bonk-login-cancel-btn").addEventListener("click", closeLogin);
    modal.addEventListener("click", function (e) { if (e.target === modal) closeLogin(); });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && modal.classList.contains("open")) closeLogin();
    });
  }

  // ── Wearing ─────────────────────────────────────────────────
  async function wear(url, opts) {
    opts = opts || {};
    var report = opts.onStatus || toast;
    if (!url) { report("This skin can't be worn.", "error"); return; }
    if (inFlight) { report(IN_PROGRESS, "error"); return; }
    if (secondsLeft() > 0) { report(waitMessage(), "error"); return; }

    inFlight = true;
    var res;
    try {
      res = await window.BVApi.post(url, opts.data || {});
    } finally {
      inFlight = false;
    }

    // 429 (this account is going too fast) or 503 (bonk.io is limiting
    // Bonkverse): remember how long to wait so repeat clicks send nothing.
    if ((res.status === 429 || res.status === 503) && res.json.retry_after) {
      waitUntil = Date.now() + res.json.retry_after * 1000;
    }
    if (res.status === 429 && res.json.error === "rate_limited") {
      report(waitMessage(), "error");
      return;
    }

    if (res.ok && res.json.ok) { report(APPLIED, "success"); return; }
    if (window.BVApi.needsSiteLogin(res)) { window.BVApi.goToLogin(); return; }

    if (res.status === 401 && res.json.auth === "bonk") {
      if (opts.isRetry) { report(STILL_REFUSED, "error"); return; }
      var opened = openLogin(function () {
        wear(url, { onStatus: opts.onStatus, data: opts.data, isRetry: true });
      });
      if (!opened) report(FAILED, "error");
      return;
    }

    report(res.json.message || FAILED, "error");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wireModal);
  } else {
    wireModal();
  }

  window.BVWear = { wear: wear, openLogin: openLogin, closeLogin: closeLogin };
})(window, document);
