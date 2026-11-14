// player_friends.js — the Friends tab of a player profile (players/friends.html)
//
// Instant search over the whole list (the HTML only has the first rows),
// sorting, the bonk.io / Flash switch and "Mutual only". Rows are drawn
// 120 at a time with "Show more".
//
// Data (#friends-data, from players/selectors.py friends):
//   bonk:  [{n: name, j: "Mon YYYY" | null, id, f: friends, m: member,
//            mu: also the viewer's friend, you: is the viewer}]
//   flash: [{n: name, now: current bonk.io name | null, p: has a profile,
//            mu: also in the viewer's Flash list}]
//   viewer: the viewer's bonk.io name, or null

(function () {
  "use strict";

  const dataEl = document.getElementById("friends-data");
  const root = document.querySelector("[data-friends]");
  if (!dataEl || !root) return;
  const data = JSON.parse(dataEl.textContent);

  const $ = (sel) => root.querySelector(sel);
  const list = $("[data-rows]");
  const tools = $("[data-tools]");
  const search = $("[data-search]");
  const sortSel = $("[data-sort]");
  const mutualOnly = $("[data-mutual-only]");
  const more = $("[data-more]");
  const count = $("[data-count]");
  const lists = $("[data-lists]");
  const nojs = document.querySelector("[data-nojs-more]");
  const PAGE = 120;
  const fmt = (n) => n.toLocaleString();

  // Profile paths, built here so links never come from page data. Names
  // like "." and ".." get a "~" in front (players/converters.py).
  const urlName = (name) => (/^~*\.{1,2}$/.test(name) ? `~${name}` : name);
  const profileUrl = (name) => `/player/${encodeURIComponent(urlName(String(name)))}/`;
  // Spaces that would vanish (at the ends, doubled, or a name of only
  // spaces) are drawn as "␣", like the player cards.
  const shown = (name) => (name !== name.trim() || name.includes("  ") || !name.trim() ? name.replace(/ /g, "␣") : name);
  const initials = (name) => name.trim().slice(0, 2).toUpperCase() || "?";
  // A friend's worn skin, drawn over their initials (players/partials/_avatar.html).
  // `s` is the skin's version, a hex digest; the URL is built here from the name.
  const skinUrl = (name, version) =>
    /^[0-9a-f]{12}$/.test(version || "") ? `${profileUrl(name)}skin-thumb.png?v=${version}` : null;

  let which = "bonk";
  let shownCount = PAGE;
  let rows = [];

  function filtered() {
    const q = search.value.toLowerCase(); // not trimmed: spaces are part of names
    let out = data[which].filter((r) => (!q || r.n.toLowerCase().includes(q) || (r.now && r.now.toLowerCase().includes(q))));
    if (mutualOnly && mutualOnly.checked) out = out.filter((r) => r.mu);
    const sort = which === "bonk" ? sortSel.value : "az";
    const byName = (a, b) => a.n.toLowerCase().localeCompare(b.n.toLowerCase());
    const sorters = {
      az: byName,
      friends: (a, b) => b.f - a.f || byName(a, b),
      old: (a, b) => a.id - b.id,
      new: (a, b) => b.id - a.id,
    };
    out.sort(sorters[sort] || byName);
    // Exact name first, then mutual friends, then the rest.
    if (q) out.sort((a, b) => (b.n.toLowerCase() === q) - (a.n.toLowerCase() === q));
    else if (data.viewer) out.sort((a, b) => b.mu - a.mu);
    return out;
  }

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function row(r) {
    const li = document.createElement("li");
    const link = which === "bonk" ? r.n : r.now || (r.p ? r.n : null);
    const box = link ? el("a", "pv-friend") : el("div", "pv-friend pv-friend--quiet");
    if (link) box.href = profileUrl(link);
    if (r.mu) box.classList.add("is-mutual");
    const av = el("span", "pv-initials", initials(r.n));
    av.setAttribute("aria-hidden", "true");
    const skin = skinUrl(link || r.n, r.s);
    if (skin) {
      av.classList.add("pv-initials--skin");
      av.style.setProperty("--skin", `url("${skin}")`);
    }
    const text = el("span", "pv-friend__text");
    const name = el("span", "pv-friend__name", shown(r.n));
    if (shown(r.n) !== r.n) name.setAttribute("aria-label", r.n);
    const meta = [];
    if (which === "bonk") {
      if (r.j) meta.push(`Joined ≈ ${r.j}`);
      if (r.f) meta.push(`${fmt(r.f)} friends`);
    } else {
      meta.push(r.now ? `Now ${r.now}` : r.p ? "On bonk.io" : "Not found on bonk.io yet");
    }
    text.append(name, el("span", "pv-friend__meta", meta.join(" · ")));
    box.append(av, text);
    if (r.you) box.append(el("span", "pv-friend__tag pv-friend__tag--you", "You"));
    else if (r.mu) box.append(el("span", "pv-friend__tag", "Mutual"));
    if (r.m) {
      const badge = el("i", "pv-friend__member");
      badge.dataset.lucide = "badge-check";
      badge.setAttribute("aria-label", "Bonkverse member");
      box.append(badge);
    }
    li.append(box);
    return li;
  }

  function render(reset) {
    if (reset) {
      rows = filtered();
      shownCount = PAGE;
    }
    const total = data[which].length;
    if (!total) {
      list.replaceChildren(el("li", "pv-friends__empty pv-muted", which === "bonk" ? "No bonk.io friends to show." : "No Flash friends imported."));
    } else if (!rows.length) {
      list.replaceChildren(el("li", "pv-friends__empty pv-muted", "No friends match."));
    } else {
      list.replaceChildren(...rows.slice(0, shownCount).map(row));
    }
    more.hidden = rows.length <= shownCount;
    count.textContent = total
      ? rows.length === total
        ? `${fmt(total)} ${which === "bonk" ? "bonk.io" : "Flash"} friend${total === 1 ? "" : "s"}`
        : `${fmt(rows.length)} of ${fmt(total)}`
      : "";
    if (window.lucide && window.lucide.createIcons) window.lucide.createIcons();
  }

  tools.hidden = false;
  if (nojs) nojs.hidden = true;
  if (lists) {
    lists.hidden = false;
    lists.querySelectorAll("button").forEach((btn) => {
      btn.addEventListener("click", () => {
        which = btn.dataset.list;
        lists.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
        sortSel.querySelectorAll("[data-bonk-only]").forEach((o) => { o.hidden = which !== "bonk"; });
        if (which !== "bonk") sortSel.value = "az";
        render(true);
      });
    });
  }
  let timer;
  search.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => render(true), 80); });
  sortSel.addEventListener("change", () => render(true));
  if (mutualOnly) mutualOnly.addEventListener("change", () => render(true));
  more.addEventListener("click", () => { shownCount += PAGE; render(false); });
  render(true);
})();
