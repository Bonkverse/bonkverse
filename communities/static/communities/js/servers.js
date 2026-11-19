// servers.js: the Discord server directory pages (communities/server_list.html,
// server_detail.html). A server icon that fails to load is removed, so the
// server's first letter underneath shows instead of a broken image.

(function () {
  "use strict";

  function drop(img) {
    img.remove();
  }

  document.querySelectorAll("img[data-server-icon]").forEach((img) => {
    // Already failed before this script ran
    if (img.complete && img.naturalWidth === 0) {
      drop(img);
      return;
    }
    img.addEventListener("error", () => drop(img), { once: true });
  });
})();
