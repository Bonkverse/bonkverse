// server_list.js: the Discord server directory (skins/server_list.html).
// Tag filters (click a tag to add or remove it, then search again) and the
// countdown to the next hourly refresh. Data from the page: the active tags
// (#active-tags, a json_script) and the refresh time (#refresh-countdown's
// data-next-refresh, ISO 8601).

(function () {
  "use strict";

  // ── Tag filters ─────────────────────────────────────────────
  const activeEl = document.getElementById("active-tags");
  const active = new Set(activeEl ? JSON.parse(activeEl.textContent) : []);
  const inputs = document.getElementById("tag-inputs");
  const form = document.getElementById("tag-filter-form");

  function syncInputs() {
    inputs.replaceChildren(
      ...[...active].map((tag) => {
        const i = document.createElement("input");
        i.type = "hidden";
        i.name = "tag";
        i.value = tag;
        return i;
      })
    );
  }

  document.querySelectorAll(".selectable-tag").forEach((tag) => {
    tag.addEventListener("click", () => {
      const name = tag.dataset.tag;
      tag.classList.toggle("active");
      active.has(name) ? active.delete(name) : active.add(name);
      syncInputs();
      form.submit();
    });
  });

  syncInputs();

  // ── Refresh countdown ───────────────────────────────────────
  const countdown = document.getElementById("refresh-countdown");
  if (countdown && countdown.dataset.nextRefresh) {
    const nextRefresh = new Date(countdown.dataset.nextRefresh).getTime();

    const update = () => {
      const diff = nextRefresh - Date.now();
      if (diff <= 0) {
        countdown.innerText = "updating now…";
        return;
      }
      const minutes = Math.floor(diff / 60000);
      const seconds = Math.floor((diff % 60000) / 1000);
      countdown.innerText = `${minutes}m ${seconds}s`;
    };

    update();
    setInterval(update, 1000);
  }
})();
