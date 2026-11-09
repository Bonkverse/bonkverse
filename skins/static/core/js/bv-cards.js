// core/js/bv-cards.js
//
// What every skin card does, on every page that shows them. Loaded once in
// base.html; needs bv-api.js and bv-wear.js. Markup: skins/partials/_skin_card.html
// (the Bonkverse/ui .bv-skin-card) and _skin_card_compact.html (a plain link:
// only the image fallback below applies to it).
//
//   artwork      the art button (or img[data-zoom] anywhere) opens it large in
//                a dialog; Escape, the Close button or the backdrop close it and
//                focus goes back to what opened it
//   broken art   falls back to the default image (also img[data-fallback])
//   Favorite     POSTs, then sets aria-pressed and the count from the reply
//   Wear         Wear → Applying… → ✓ Applied (or Retry), with the outcome in
//                the card's status line (Skin card design guide, section 05)
//
// The ⋯ menu on your own skins opens with static/ui/ui.js. Everything here is
// delegated from document, so cards a page swaps in later (the profile's paged
// grid) work without re-wiring. Inside a grid in select mode (.select-mode,
// the profile's bulk delete) a click selects the card instead: no zoom, no
// favorite, no Wear.

(function (window, document) {
  "use strict";

  var FALLBACK_IMG = "/static/images/default_skin.png";
  var APPLIED_FOR = 2800; // ms "✓ Applied" stays before Wear comes back

  function inSelectMode(card) {
    return !!card.closest(".select-mode");
  }

  // ── Enlarge ─────────────────────────────────────────────────
  // One <dialog> for the page, made on first use (ui/components.css .bv-dialog--zoom).
  var zoom = null;

  function openZoom(src, title, opener) {
    if (!zoom) {
      zoom = document.createElement("dialog");
      zoom.className = "bv-dialog bv-dialog--zoom";
      zoom.id = "bv-image-zoom";
      zoom.setAttribute("aria-labelledby", "bv-image-zoom-title");
      zoom.innerHTML =
        '<div class="bv-dialog__header">' +
        '<h2 class="bv-dialog__title" id="bv-image-zoom-title"></h2>' +
        '<button class="bv-btn bv-btn--ghost bv-btn--icon" type="button" aria-label="Close" data-bv-dialog-close>' +
        '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>' +
        "</button></div>" +
        '<div class="bv-dialog__body"><img alt=""></div>';
      document.body.appendChild(zoom);
    }
    zoom.querySelector(".bv-dialog__title").textContent = title || "Skin";
    var img = zoom.querySelector("img");
    img.src = src;
    img.alt = title ? title + ", enlarged" : "Skin, enlarged";
    zoom._bvOpener = opener || null; // ui.js returns focus here on close
    if (!zoom.open) zoom.showModal();
  }

  function closeZoom() {
    if (zoom && zoom.open) zoom.close();
  }

  // ── Broken images ───────────────────────────────────────────
  // "error" doesn't bubble, so listen in the capture phase.
  document.addEventListener("error", function (e) {
    var img = e.target;
    if (!(img instanceof HTMLImageElement)) return;
    if (!img.matches(".skin-card-img, .skin-tile-img, img[data-fallback]")) return;
    if (img.dataset.fellBack) return;
    img.dataset.fellBack = "1";
    img.src = FALLBACK_IMG;
  }, true);

  // ── Favorites ───────────────────────────────────────────────
  async function favorite(card, button) {
    if (button.getAttribute("aria-busy") === "true") return;
    button.setAttribute("aria-busy", "true");
    try {
      var json = await window.BVApi.postOrLogin("/api/skins/" + card.dataset.id + "/favorite/");
      if (!json) return;
      button.querySelector(".bv-fav__count").textContent = json.favorites;
      button.setAttribute("aria-pressed", json.favorited ? "true" : "false");
    } finally {
      button.removeAttribute("aria-busy");
    }
  }

  // ── Wear ────────────────────────────────────────────────────
  function setWear(button, state, label) {
    clearTimeout(button._bvReset);
    button.textContent = label;
    if (state === "pending") {
      button.setAttribute("aria-busy", "true");
      button.removeAttribute("data-state");
    } else {
      button.removeAttribute("aria-busy");
      if (state) button.setAttribute("data-state", state); else button.removeAttribute("data-state");
    }
  }

  function setStatus(card, text, kind) {
    var status = card.querySelector(".bv-status");
    if (!status) return;
    status.className = "bv-status" + (kind ? " bv-status--" + kind : "");
    status.textContent = text || "";
  }

  async function wear(card, button) {
    if (button.getAttribute("aria-busy") === "true") return; // no double sends
    var reported = false;
    setWear(button, "pending", "Applying…");
    setStatus(card, "");
    await window.BVWear.wear(card.dataset.wearUrl, {
      onStatus: function (text, type) {
        reported = true;
        if (type === "success") {
          setWear(button, "success", "✓ Applied");
          var title = card.querySelector(".bv-skin-card__title, .bv-skin-detail__title");
          setStatus(card, (title ? title.textContent.trim() : "This skin") + " is in your active slot.", "success");
          button._bvReset = setTimeout(function () {
            setWear(button, null, "Wear");
          }, APPLIED_FOR);
        } else {
          setWear(button, "error", "Retry");
          setStatus(card, text, "error");
        }
      },
    });
    // No outcome yet: the page went to the site login, or the bonk.io login
    // dialog opened (a successful login retries and reports above).
    if (!reported) setWear(button, null, "Wear");
  }

  // ── One click handler for all of it ─────────────────────────
  document.addEventListener("click", function (e) {
    var t = e.target;

    var zoomable = t.closest("img[data-zoom]");
    if (zoomable) { openZoom(zoomable.src, zoomable.alt, zoomable); return; }

    var card = t.closest("[data-skin-card]");
    if (!card || inSelectMode(card)) return;

    var art = t.closest(".bv-skin-card__art, .bv-skin-detail__art");
    if (art) {
      var title = card.querySelector(".bv-skin-card__title, .bv-skin-detail__title");
      openZoom(art.querySelector("img").src, title && title.textContent.trim(), art);
      return;
    }

    var fav = t.closest("button.bv-fav");
    if (fav) { favorite(card, fav); return; }

    var wearBtn = t.closest("button.bv-wear");
    if (wearBtn) { wear(card, wearBtn); return; }
  });

  window.BVCards = { openZoom: openZoom, closeZoom: closeZoom, wear: wear, favorite: favorite };
})(window, document);
