// search.js: the skin search page (skins/search.html).
// The search controls. What a card does is core/js/bv-cards.js; Re-render
// and Report are on the skin's own page (js/skin_detail.js).

(function () {
  "use strict";

  // Changing "Search By" or "Sort By" searches again.
  const searchForm = document.getElementById("searchForm");
  document.querySelectorAll(".site-search-filters select").forEach((select) => {
    select.addEventListener("change", () => searchForm.submit());
  });

  // Keep the visitor's timezone offset in the URL (the "uploaded today" count uses it).
  const url = new URL(window.location.href);
  if (!url.searchParams.get("tz_offset")) {
    url.searchParams.set("tz_offset", new Date().getTimezoneOffset());
    window.history.replaceState({}, "", url.toString());
  }
})();
