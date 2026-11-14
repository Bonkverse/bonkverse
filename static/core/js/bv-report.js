// core/js/bv-report.js
//
// Reporting a skin: the one report modal (skins/partials/_report_skin_modal.html)
// and every button that opens it. Loaded in base.html; needs bv-api.js.
//
//   <button data-report-skin="{{ skin.id }}" data-skin-name="{{ skin.name }}">Report</button>
//
// Any element with data-report-skin opens the modal for that skin, on any page
// that includes the partial. The search cards' menu and the skin page both use
// this; neither has its own copy.

(function (window, document) {
  "use strict";

  var ALREADY = "You have already reported this skin.";
  var FAILED = "Something went wrong. Please try again.";
  var THANKS = "✓ Report submitted. Thank you!";

  var skinId = null;

  function el(id) { return document.getElementById(id); }

  function feedback(text, kind) {
    var fb = el("report-feedback");
    fb.textContent = text;
    fb.className = "modal-feedback" + (kind ? " " + kind : "");
  }

  function open(id, name) {
    var modal = el("report-modal");
    if (!modal) {
      console.error("BVReport: page is missing skins/partials/_report_skin_modal.html");
      return;
    }
    skinId = id;
    el("report-skin-name").textContent = name ? '"' + name + '"' : "";
    el("report-reason").value = "";
    el("report-details").value = "";
    feedback("", "");
    modal.classList.add("open");
    document.body.style.overflow = "hidden";
  }

  function close() {
    var modal = el("report-modal");
    if (!modal || !modal.classList.contains("open")) return;
    modal.classList.remove("open");
    document.body.style.overflow = "";
    skinId = null;
  }

  async function submit() {
    var button = el("report-submit-btn");
    var reason = el("report-reason").value;
    var details = el("report-details").value.trim();
    if (!reason) { feedback("Please select a reason.", "error"); return; }

    button.disabled = true;
    feedback("Submitting…", "");
    var res = await window.BVApi.post("/api/skins/" + skinId + "/report/", { reason: reason, details: details });
    button.disabled = false;

    if (res.ok) {
      feedback(THANKS, "success");
      setTimeout(close, 1200);
      return;
    }
    feedback(res.status === 409 ? ALREADY : FAILED, "error");
  }

  function wire() {
    var modal = el("report-modal");
    if (!modal) return;
    el("report-modal-close").addEventListener("click", close);
    el("report-cancel-btn").addEventListener("click", close);
    el("report-submit-btn").addEventListener("click", submit);
    modal.addEventListener("click", function (e) { if (e.target === modal) close(); });
  }

  document.addEventListener("click", function (e) {
    var trigger = e.target.closest("[data-report-skin]");
    if (!trigger) return;
    // Close the menu it was in (opened by ui/ui.js).
    var menu = trigger.closest(".bv-menu");
    if (menu) {
      menu.hidden = true;
      var toggle = document.querySelector('[aria-controls="' + menu.id + '"]');
      if (toggle) toggle.setAttribute("aria-expanded", "false");
    }
    open(trigger.dataset.reportSkin, trigger.dataset.skinName);
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") close();
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }

  window.BVReport = { open: open, close: close };
})(window, document);
