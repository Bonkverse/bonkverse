// skin_detail.js: the skin page (skins/skin_detail.html).
// Wear, favorite and vote for the one skin on the page. The URLs come from
// data attributes on #skin-detail. Shared pieces: wearing and the bonk.io
// login (core/js/bv-wear.js), Report (core/js/bv-report.js), the broken-image
// fallback (core/js/bv-cards.js).

(function () {
  "use strict";

  const page = document.getElementById("skin-detail");
  if (!page) return;
  const $ = (id) => document.getElementById(id);

  // Logged out, the page shows counts and a "Login to Wear" link only.
  const wearBtn = $("wear-btn");
  if (!wearBtn) return;

  wearBtn.addEventListener("click", () => {
    const msg = $("wear-msg");
    msg.textContent = "Applying…";
    BVWear.wear(page.dataset.wearUrl, {
      onStatus: (text, type) => { msg.textContent = (type === "success" ? "✅ " : "❌ ") + text; },
    });
  });

  $("fav-btn").addEventListener("click", async () => {
    const json = await BVApi.postOrLogin(page.dataset.favoriteUrl);
    if (!json) return;
    $("fav-count").textContent = json.favorites;
    $("fav-label").textContent = json.favorited ? "Favorited" : "Favorite";
    $("fav-btn").classList.toggle("active", json.favorited);
  });

  for (const btn of [$("btn-up"), $("btn-down")]) {
    btn.addEventListener("click", async () => {
      const json = await BVApi.postOrLogin(page.dataset.voteUrl, { vote: btn.dataset.vote });
      if (!json) return;
      $("up-count").textContent = json.upvotes;
      $("down-count").textContent = json.downvotes;
      $("btn-up").classList.toggle("active", json.current_vote === "up");
      $("btn-down").classList.toggle("active", json.current_vote === "down");
    });
  }
})();
