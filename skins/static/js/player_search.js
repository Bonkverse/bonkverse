// player_search.js: Find Bonk Players (players_search/players.html) and Find
// Flash Friends (players_search/flash_friends.html). Same search, different
// results: the page says which with data-kind on #route-refs ("players" or
// "flash"), and where to search with data-search-url.
//
// The page marks its pieces with data-role: search-form, query, mode (players
// only: search by username or Bonk ID), results, pagination.

(function () {
  "use strict";

  const refs = document.getElementById("route-refs");
  if (!refs) return;
  const kind = refs.dataset.kind;
  const searchUrl = refs.dataset.searchUrl;
  const role = (name) => document.querySelector(`[data-role="${name}"]`);

  const loadingEl = document.getElementById("loading");
  const form = role("search-form");
  const qInput = role("query");
  const modeSelect = role("mode");
  const results = role("results");
  const paginationEl = role("pagination");

  function escapeHtml(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  const RENDER = {
    players: {
      empty: "No players found.",
      card: (p) => `
        <strong>${escapeHtml(p.username)}</strong>
        <span>Bonk.io ID: ${escapeHtml(p.bonk_id)}</span>
        <span>Friends (last sync): ${escapeHtml(p.last_friend_count ?? "—")}</span>
        <span>Flash Friends: ${escapeHtml(p.flash_friend_count ?? 0)}</span>`,
    },
    flash: {
      empty: "No flash friends found.",
      card: (f) => `
        <strong>${escapeHtml(f.name)}</strong>
        <span>${f.bonk_player_id ? "Linked Bonk ID: " + escapeHtml(f.bonk_player_id) : "Legacy only (unlinked)"}</span>`,
    },
  }[kind];

  let lastFetchAbort = null;

  function setLoading(is) {
    loadingEl.hidden = !is;
  }

  function renderResults(items) {
    if (!items.length) {
      results.innerHTML = `<p>${RENDER.empty}</p>`;
      return;
    }
    results.innerHTML = items
      .map((item) => `<div class="player-card" tabindex="0">${RENDER.card(item)}</div>`)
      .join("");
  }

  async function doSearch(q, page = 1) {
    const params = new URLSearchParams({ q, page });
    if (modeSelect) params.set("mode", modeSelect.value);
    try {
      setLoading(true);
      if (lastFetchAbort) lastFetchAbort.abort();
      lastFetchAbort = new AbortController();

      const resp = await fetch(`${searchUrl}?${params}`, { signal: lastFetchAbort.signal });
      if (!resp.ok) {
        const message =
          resp.status === 429
            ? "You're searching too fast. Wait a moment and try again."
            : "Search failed. Please try again.";
        BVToast.show(message, { type: "error" });
        return;
      }
      const data = await resp.json();
      renderResults(data.results);
      BVPagination.render(paginationEl, {
        page: data.page,
        pageSize: data.page_size,
        total: data.total,
        onNavigate: (p) => doSearch(q, p),
      });
    } catch (err) {
      if (err.name !== "AbortError") console.error(err);
    } finally {
      setLoading(false);
    }
  }

  const runSearch = () => doSearch(qInput.value.trim(), 1);

  // The button and Enter both submit the form.
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    runSearch();
  });
  if (modeSelect) modeSelect.addEventListener("change", runSearch);

  // Show the first page right away.
  doSearch("", 1);
})();
