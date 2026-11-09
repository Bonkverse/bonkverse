/*
 * Bonkverse UI behavior (v0.1.1)
 *
 * Load with defer:  <script src="/static/ui/ui.js" defer></script>
 * Works on markup that's on the page now or added later (event delegation).
 *
 *   data-bv-toggle         on a button with aria-controls: opens and closes
 *                          that element (menus, the header's Menu button).
 *                          One menu open at a time; Escape and outside clicks
 *                          close it and focus returns to the button.
 *   data-bv-dialog-open="id"  opens <dialog id> as a modal; focus returns to
 *                          the opener when it closes.
 *   data-bv-dialog-close   closes the dialog it's in. Clicking the backdrop
 *                          closes too.
 *   data-bv-copy="id"      copies the value or text of #id (or, without a
 *                          value, the attribute data-bv-copy-text).
 *
 *   BonkverseUI.toast("Link copied", "success" | "error" | "info")
 */
(function () {
  "use strict";

  // ── Disclosure: menus and the header Menu button ─────────────────────────
  var openToggle = null;

  function targetOf(button) {
    return document.getElementById(button.getAttribute("aria-controls"));
  }

  function setOpen(button, open) {
    var target = targetOf(button);
    if (!target) return;
    button.setAttribute("aria-expanded", open ? "true" : "false");
    if (target.classList.contains("bv-header__nav")) {
      // The nav is always visible on wide screens; only the attribute moves.
      if (open) target.setAttribute("data-open", ""); else target.removeAttribute("data-open");
    } else {
      target.hidden = !open;
    }
    if (open) {
      if (openToggle && openToggle !== button && !openToggle.contains(button) && !targetOf(openToggle).contains(button)) {
        setOpen(openToggle, false);
      }
      if (!target.classList.contains("bv-header__nav")) openToggle = button;
    } else if (openToggle === button) {
      openToggle = null;
    }
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-bv-toggle]");
    if (button) {
      setOpen(button, button.getAttribute("aria-expanded") !== "true");
      return;
    }
    if (openToggle && !targetOf(openToggle).contains(event.target)) {
      setOpen(openToggle, false);
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape" || !openToggle) return;
    var button = openToggle;
    setOpen(button, false);
    button.focus();
  });

  // ── Dialogs ──────────────────────────────────────────────────────────────
  document.addEventListener("click", function (event) {
    var opener = event.target.closest("[data-bv-dialog-open]");
    if (opener) {
      var dialog = document.getElementById(opener.getAttribute("data-bv-dialog-open"));
      if (dialog && typeof dialog.showModal === "function") {
        dialog._bvOpener = opener;
        dialog.showModal();
      }
      return;
    }
    var closer = event.target.closest("[data-bv-dialog-close]");
    if (closer) {
      var parent = closer.closest("dialog");
      if (parent) parent.close();
      return;
    }
    // A click on the backdrop lands on the <dialog> element itself.
    if (event.target.matches && event.target.matches("dialog.bv-dialog[open]")) {
      var rect = event.target.getBoundingClientRect();
      var inside = event.clientX >= rect.left && event.clientX <= rect.right &&
                   event.clientY >= rect.top && event.clientY <= rect.bottom;
      if (!inside) event.target.close();
    }
  });

  document.addEventListener("close", function (event) {
    var dialog = event.target;
    if (dialog._bvOpener && document.contains(dialog._bvOpener)) dialog._bvOpener.focus();
    dialog._bvOpener = null;
  }, true);

  // ── Toasts ───────────────────────────────────────────────────────────────
  function region() {
    var el = document.querySelector(".bv-toasts");
    if (!el) {
      el = document.createElement("div");
      el.className = "bv-toasts";
      el.setAttribute("role", "status");
      el.setAttribute("aria-live", "polite");
      document.body.appendChild(el);
    }
    return el;
  }

  function toast(message, kind) {
    var el = document.createElement("div");
    el.className = "bv-toast bv-toast--" + (kind || "info");
    var text = document.createElement("span");
    text.textContent = message;
    el.appendChild(text);
    region().appendChild(el);
    // Errors stay until dismissed; everything else goes after 4 s.
    if (kind === "error") {
      var close = document.createElement("button");
      close.type = "button";
      close.className = "bv-btn bv-btn--ghost bv-toast__close";
      close.textContent = "Dismiss";
      close.addEventListener("click", function () { el.remove(); });
      el.appendChild(close);
    } else {
      setTimeout(function () { el.remove(); }, 4000);
    }
    return el;
  }

  // ── Copy ─────────────────────────────────────────────────────────────────
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-bv-copy], [data-bv-copy-text]");
    if (!button) return;
    var source = button.getAttribute("data-bv-copy");
    var field = source ? document.getElementById(source) : null;
    var value = field ? ("value" in field ? field.value : field.textContent) : button.getAttribute("data-bv-copy-text");
    if (value == null) return;

    function done() {
      var label = button.querySelector("span") || button;
      var before = label.textContent;
      label.textContent = button.getAttribute("data-bv-copied-label") || "Copied";
      setTimeout(function () { label.textContent = before; }, 1600);
    }
    function fallback() {
      // Clipboard blocked: select the text so Ctrl/Cmd+C works.
      if (field && field.select) { field.focus(); field.select(); }
      toast("Couldn't copy automatically. The text is selected: press Ctrl+C or ⌘C.", "info");
    }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(value.trim()).then(done, fallback);
    } else {
      fallback();
    }
  });

  window.BonkverseUI = { toast: toast };
})();
