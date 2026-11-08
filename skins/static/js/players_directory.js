// players_directory.js — the Players page (players/directory.html)
//
// The advanced-search form sends every field, most of them blank or at
// their default ("Any", "Contains"). Leave those out on submit so the
// address stays short and readable. Without JavaScript the form still
// works; the address is just longer.

(function () {
  "use strict";

  const form = document.querySelector("[data-dir-form]");
  if (!form) return;

  const DEFAULTS = { match: "contains" };

  form.addEventListener("submit", () => {
    form.querySelectorAll("input, select").forEach((el) => {
      if (!el.name || el.name === "view") return;
      if ((el.type === "radio" || el.type === "checkbox") && !el.checked) return;
      if (el.value === "" || DEFAULTS[el.name] === el.value) el.disabled = true;
    });
  });

  // Coming back to the page (bfcache) must not leave fields disabled.
  window.addEventListener("pageshow", () => {
    form.querySelectorAll(":disabled").forEach((el) => { el.disabled = false; });
  });
})();
