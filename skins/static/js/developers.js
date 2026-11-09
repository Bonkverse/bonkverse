// Developer portal key page (templates/developers/keys.html):
// - [data-copy="<input id>"] copies that input's value and says so;
// - form[data-confirm] asks before submitting (revoking a key).
(function () {
  "use strict";

  document.addEventListener("click", async function (event) {
    const button = event.target.closest("[data-copy]");
    if (!button) return;
    const input = document.getElementById(button.dataset.copy);
    if (!input) return;
    input.select();
    let copied = false;
    try {
      await navigator.clipboard.writeText(input.value);
      copied = true;
    } catch (err) {
      copied = document.execCommand && document.execCommand("copy");
    }
    const label = button.querySelector("span");
    if (copied && label) {
      const before = label.textContent;
      label.textContent = button.dataset.copiedLabel || "Copied";
      setTimeout(function () { label.textContent = before; }, 2000);
    }
  });

  document.addEventListener("submit", function (event) {
    const form = event.target.closest("form[data-confirm]");
    if (form && !window.confirm(form.dataset.confirm)) event.preventDefault();
  });
})();
