// share_skin.js: the share page (skins/share_skin.html).
// "Add to Collection" adds the skin to the visitor's favorites. Image zoom is
// core/js/bv-cards.js (img[data-zoom]).

(function () {
  "use strict";

  const button = document.getElementById("collect-btn");
  if (!button) return; // logged out

  button.addEventListener("click", async () => {
    button.disabled = true;
    const json = await BVApi.postOrLogin(button.dataset.favoriteUrl);
    if (!json) { button.disabled = false; return; }

    // The endpoint toggles; the button is only enabled while not favorited,
    // so this adds. If it somehow removed, say so and let them click again.
    document.getElementById("fav-count").textContent = json.favorites;
    if (json.favorited) {
      button.textContent = "⭐ In your collection";
      BVToast.show("Added to your collection.", { type: "success" });
    } else {
      button.textContent = "⭐ Add to Collection";
      button.disabled = false;
    }
  });
})();
