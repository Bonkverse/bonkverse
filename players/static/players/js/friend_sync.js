// friend_sync.js: right after a login that started a friend sync, shows its
// progress as a toast on whatever page the login landed on. Loaded by
// templates/base.html only then (players/context_processors.py friend_sync);
// the status URL is #bv-friend-sync's data-url.

(function () {
  "use strict";

  const el = document.getElementById("bv-friend-sync");
  if (!el || !window.BVToast) return;

  const handle = BVToast.show("Syncing your friends…", { type: "info", spinner: true, sticky: true });
  let attempts = 0;

  function poll() {
    attempts++;
    fetch(el.dataset.url, { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then((r) => r.json())
      .then((data) => {
        if (data.status === "done") {
          let text = `Synced ${data.friends_now} friends`;
          const extras = [];
          if (data.added_edges > 0) extras.push(`${data.added_edges} new`);
          if (data.removed_edges > 0) extras.push(`${data.removed_edges} removed`);
          if (extras.length) text += `: ${extras.join(", ")}`;
          if (data.corrected_count > 0) {
            // Only this case stays up until closed; it lists names to check.
            const fixes = data.corrected_usernames.map((c) => `"${c.old_username}" → "${c.new_username}"`);
            handle.update(`${text}. Also fixed ${data.corrected_count} outdated username(s) from before a data cleanup: ${fixes.join(", ")}`, { type: "success", sticky: true });
          } else {
            handle.update(text, { type: "success" });
          }
          return;
        }
        if (attempts < 10) setTimeout(poll, 1200);
        else handle.update("Friend sync is taking longer than usual", { type: "info" });
      })
      .catch(() => handle.dismiss());
  }

  setTimeout(poll, 1200);
})();
