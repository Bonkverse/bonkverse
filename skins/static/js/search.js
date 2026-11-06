// search.js: the skin search page (skins/search.html).
// The search controls, and the staff-only Re-render in each card's menu.
// Everything else a card does is core/js/bv-cards.js; Report is
// core/js/bv-report.js.

(function () {
  "use strict";

  // Changing "Search By" or "Sort By" searches again.
  const searchForm = document.getElementById("searchForm");
  document.querySelectorAll(".search-controls-inline select").forEach((select) => {
    select.addEventListener("change", () => searchForm.submit());
  });

  // Keep the visitor's timezone offset in the URL (the "uploaded today" count uses it).
  const url = new URL(window.location.href);
  if (!url.searchParams.get("tz_offset")) {
    url.searchParams.set("tz_offset", new Date().getTimezoneOffset());
    window.history.replaceState({}, "", url.toString());
  }

  // ── Re-render (staff only) ──────────────────────────────────
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest(".card-rerender-btn");
    if (!btn) return;
    btn.closest(".card-more-dropdown")?.classList.remove("open");

    const skinId = btn.dataset.skinId;
    const img = document.querySelector(`.skin-card[data-id="${skinId}"] img`);

    btn.disabled = true;
    btn.textContent = "Re-rendering…";

    const { ok, status, json } = await BVApi.post(`/skins/${skinId}/rerender/`);
    if (ok && json.ok) {
      if (img) img.src = json.image_url + "?t=" + Date.now();
      BVToast.show("Skin re-rendered.", { type: "success" });
    } else if (status === 0) {
      BVToast.show("Re-render request failed.", { type: "error" });
    } else {
      BVToast.show("Re-render failed: " + (json.error || "unknown error"), { type: "error" });
    }

    btn.disabled = false;
    btn.innerHTML = '<i data-lucide="refresh-cw"></i> Re-render Image';
    if (window.lucide) lucide.createIcons({ nodes: [btn] });
  });
})();
