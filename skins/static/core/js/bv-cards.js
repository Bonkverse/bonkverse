// core/js/bv-cards.js
//
// What every skin card does, on every page that shows them. Loaded once in
// base.html; needs bv-api.js and bv-wear.js. Markup: skins/partials/_skin_card.html
// (full card) and _skin_card_compact.html (a plain link: only the image
// fallback below applies to it).
//
//   ⋯ menu       opens/closes; one open at a time; a click elsewhere closes it
//   image        click zooms it; a broken image falls back to the default
//   img[data-zoom]  any other image that should zoom on click (leaderboards,
//                   the share page) gets the same overlay
//   img[data-fallback]  any other skin image that should fall back when broken
//                       (the skin page)
//   votes, star  POST and update the counts (sends logged-out visitors to log in)
//   Wear         BVWear.wear(card.dataset.wearUrl)
//
// Everything is delegated from document, so cards a page swaps in later (the
// profile's paged grid) work without re-wiring. Inside a grid in select mode
// (.select-mode, the profile's bulk delete) a click selects the card instead:
// no zoom, no vote, no Wear. Page-specific menu items (Edit, Delete, Report,
// Re-render) stay with the page's own script.

(function (window, document) {
  "use strict";

  var FALLBACK_IMG = "/static/images/default_skin.png";

  function inSelectMode(card) {
    return !!card.closest(".select-mode");
  }

  // ── Image zoom ──────────────────────────────────────────────
  // One overlay for the page, made on first use (base.css: .modal).
  var zoom = null;

  function closeZoom() {
    if (zoom) zoom.style.display = "none";
  }

  function openZoom(src) {
    if (!zoom) {
      zoom = document.createElement("div");
      zoom.id = "bv-image-zoom";
      zoom.className = "modal";
      var close = document.createElement("span");
      close.className = "close";
      close.textContent = "×";
      var img = document.createElement("img");
      img.className = "modal-content";
      img.alt = "";
      zoom.appendChild(close);
      zoom.appendChild(img);
      zoom.addEventListener("click", closeZoom);
      document.body.appendChild(zoom);
    }
    zoom.querySelector("img").src = src;
    zoom.style.display = "flex";
  }

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeZoom();
  });

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

  // ── ⋯ menu ──────────────────────────────────────────────────
  function closeMenus(except) {
    document.querySelectorAll(".card-more-dropdown.open").forEach(function (d) {
      if (d !== except) d.classList.remove("open");
    });
  }

  // ── Votes and favorites ─────────────────────────────────────
  async function vote(card, direction) {
    var json = await window.BVApi.postOrLogin("/api/skins/" + card.dataset.id + "/vote/", { vote: direction });
    if (!json) return;
    card.querySelector(".up-count").textContent = json.upvotes;
    card.querySelector(".down-count").textContent = json.downvotes;
    card.querySelector(".vote-up").classList.toggle("active", json.current_vote === "up");
    card.querySelector(".vote-down").classList.toggle("active", json.current_vote === "down");
  }

  async function favorite(card) {
    var json = await window.BVApi.postOrLogin("/api/skins/" + card.dataset.id + "/favorite/");
    if (!json) return;
    card.querySelector(".fav-count").textContent = json.favorites;
    card.querySelector(".fav-toggle").classList.toggle("active", json.favorited);
  }

  // ── One click handler for all of it ─────────────────────────
  document.addEventListener("click", function (e) {
    var t = e.target;

    var moreBtn = t.closest(".card-more-btn");
    if (moreBtn) {
      e.stopPropagation();
      var dropdown = moreBtn.closest(".card-more-menu").querySelector(".card-more-dropdown");
      closeMenus(dropdown);
      dropdown.classList.toggle("open");
      return;
    }
    // Clicks inside an open menu are the page's (links, Edit, Report...).
    if (t.closest(".card-more-dropdown")) return;
    closeMenus(null);

    var zoomable = t.closest("img[data-zoom]");
    if (zoomable) { openZoom(zoomable.src); return; }

    var card = t.closest(".skin-card[data-id]");
    if (!card || inSelectMode(card)) return;

    if (t.closest(".skin-card-img")) { openZoom(t.closest(".skin-card-img").src); return; }

    var voteBtn = t.closest(".vote-up, .vote-down");
    if (voteBtn) { vote(card, voteBtn.classList.contains("vote-up") ? "up" : "down"); return; }

    if (t.closest(".fav-toggle")) { favorite(card); return; }

    if (t.closest(".wear-card-action")) { window.BVWear.wear(card.dataset.wearUrl); return; }
  });

  window.BVCards = { openZoom: openZoom, closeZoom: closeZoom, closeMenus: closeMenus };
})(window, document);
