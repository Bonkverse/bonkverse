// core/js/bv-api.js
//
// The one place page scripts talk to Bonkverse's JSON endpoints from.
// Loaded once in base.html. Pages must not define their own getCSRF/postForm
// (tests/test_frontend.py checks).
//
//   const { ok, status, json } = await BVApi.post(url, { vote: "up" });
//   const json = await BVApi.postOrLogin(url, data);   // null if sent to log in
//
// post() never throws: a network failure comes back as { ok: false, status: 0 }.

(function (window) {
  "use strict";

  var CSRF_COOKIE = "bv_csrftoken";

  function getCSRF() {
    var m = document.cookie.match(new RegExp("(?:^|;\\s*)" + CSRF_COOKIE + "=([^;]+)"));
    return m ? decodeURIComponent(m[1]) : "";
  }

  function headers(extra) {
    var h = { "X-CSRFToken": getCSRF(), "X-Requested-With": "XMLHttpRequest" };
    for (var k in extra || {}) h[k] = extra[k];
    return h;
  }

  async function send(url, init) {
    var r;
    try {
      r = await fetch(url, init);
    } catch (err) {
      console.error("BVApi:", url, err);
      return { ok: false, status: 0, json: {} };
    }
    var json = {};
    try { json = await r.json(); } catch (e) { /* not JSON (e.g. an HTML error page) */ }
    return { ok: r.ok, status: r.status, json: json || {} };
  }

  // POST form fields (a plain object or FormData).
  function post(url, data) {
    var body = data instanceof FormData ? data : new URLSearchParams(data || {});
    return send(url, { method: "POST", headers: headers(), body: body });
  }

  // POST a JSON body.
  function postJSON(url, obj) {
    return send(url, {
      method: "POST",
      headers: headers({ "Content-Type": "application/json" }),
      body: JSON.stringify(obj || {}),
    });
  }

  // True when the reply means "sign in to Bonkverse". Two shapes exist:
  // auth guards answer {auth: "bonkverse"}; vote/favorite answer
  // {error: "auth required"}. A 401 with auth: "bonk" is NOT this; that is
  // the bonk.io login (see bv-wear.js).
  function needsSiteLogin(res) {
    if (res.status !== 401) return false;
    return res.json.auth === "bonkverse" || res.json.error === "auth required";
  }

  function goToLogin() {
    var next = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.href = "/login/?next=" + next;
  }

  // POST, sending the visitor to log in if the site asks. Returns the JSON on
  // success, or null (logged-out redirect, or any failure; check the console).
  async function postOrLogin(url, data) {
    var res = await post(url, data);
    if (needsSiteLogin(res)) { goToLogin(); return null; }
    if (!res.ok) { console.error("BVApi:", url, res.status, res.json); return null; }
    return res.json;
  }

  window.BVApi = {
    getCSRF: getCSRF,
    post: post,
    postJSON: postJSON,
    postOrLogin: postOrLogin,
    needsSiteLogin: needsSiteLogin,
    goToLogin: goToLogin,
  };
})(window);
