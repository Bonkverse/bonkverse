// skin_detail.js: the skin page (skins/skin_detail.html).
// Votes, the staff Re-render, and "Search results" going back to the search
// you came from. Favorite, Wear and Enlarge are core/js/bv-cards.js (the page
// is a data-skin-card); Report is core/js/bv-report.js; the menus and Copy
// link are ui/ui.js.

(function () {
  "use strict";

  const page = document.getElementById("skin-detail");
  if (!page) return;

  // ── Votes: one at a time; the server's counts win ───────────
  const votes = page.querySelectorAll(".bv-vote");
  votes.forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (btn.getAttribute("aria-busy") === "true") return;
      btn.setAttribute("aria-busy", "true");
      try {
        const json = await BVApi.postOrLogin(page.dataset.voteUrl, { vote: btn.dataset.vote });
        if (!json) return;
        page.querySelector(".up-count").textContent = json.upvotes;
        page.querySelector(".down-count").textContent = json.downvotes;
        votes.forEach((b) => b.setAttribute("aria-pressed", b.dataset.vote === json.current_vote ? "true" : "false"));
      } finally {
        btn.removeAttribute("aria-busy");
      }
    });
  });

  // ── Re-render (staff only) ──────────────────────────────────
  const rerender = page.querySelector("[data-rerender]");
  if (rerender) {
    rerender.addEventListener("click", async () => {
      const label = rerender.lastChild;
      rerender.disabled = true;
      label.textContent = " Re-rendering…";
      const { ok, status, json } = await BVApi.post(page.dataset.rerenderUrl);
      if (ok && json.ok) {
        page.querySelector(".bv-skin-art").src = json.image_url + "?t=" + Date.now();
        BVToast.show("Skin re-rendered.", { type: "success" });
      } else {
        BVToast.show(status === 0 ? "Re-render request failed." : "Re-render failed: " + (json.error || "unknown error"), { type: "error" });
      }
      rerender.disabled = false;
      label.textContent = " Re-render image";
    });
  }

  // ── Back to the search you came from (query, page and scroll) ─
  const back = page.querySelector("[data-back-to-search]");
  if (back && document.referrer) {
    try {
      const from = new URL(document.referrer);
      if (from.origin === location.origin && from.pathname === back.pathname) {
        back.href = from.href;
        back.addEventListener("click", (e) => {
          if (history.length > 1) { e.preventDefault(); history.back(); }
        });
      }
    } catch (e) { /* no usable referrer: the plain link to search is fine */ }
  }
})();
