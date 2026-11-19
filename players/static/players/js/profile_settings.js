// profile_settings.js — the switches on Profile settings (players/settings.html)
//
// A switch looks like it takes effect at once, so it does: flipping one sends
// the whole form (the server saves every section from it) and shows "Saved"
// beside that switch, or "Not saved" and flips it back if that fails. The
// Save button is only for browsers without scripts, so it's hidden here.

(function () {
  "use strict";

  const form = document.querySelector("[data-profile-settings]");
  if (!form || !window.fetch) return;
  const save = form.querySelector("[data-save]");
  if (save) save.hidden = true;

  let pending = Promise.resolve();

  function say(label, text, state) {
    const status = label.querySelector("[data-saved]");
    if (!status) return;
    status.dataset.state = state;
    status.replaceChildren();
    if (state === "ok") {
      const tick = document.createElement("i");
      tick.dataset.lucide = "check";
      tick.setAttribute("aria-hidden", "true");
      status.append(tick);
    }
    status.append(document.createTextNode(text));
    if (window.lucide) window.lucide.createIcons({ root: status });
    clearTimeout(status._hide);
    if (state === "ok") status._hide = setTimeout(() => status.replaceChildren(), 2500);
  }

  form.addEventListener("change", (event) => {
    const input = event.target;
    if (!input.matches('input[type="checkbox"]')) return;
    const label = input.closest("label");
    say(label, "Saving…", "busy");
    // One save at a time, in order, so the last flip always wins.
    pending = pending.then(() =>
      fetch(form.action || window.location.href, {
        method: "POST",
        body: new FormData(form),
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      })
        .then((response) => {
          if (!response.ok) throw new Error(String(response.status));
          say(label, "Saved", "ok");
        })
        .catch(() => {
          input.checked = !input.checked;
          say(label, "Not saved. Try again", "error");
        })
    );
  });
})();
