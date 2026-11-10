// player_level.js — the Level tab of a player profile (players/level.html)
//
// One large level-over-time chart (core/js/bv-chart.js): point at it for the
// level on any day, drag across it to look at just that stretch, "Reset
// zoom" to go back; the buttons show the last week, month, 3 months or year.
// The numbers, level-ups and "What's next" below follow whatever stretch is
// shown. Without JavaScript the page keeps the static line and the latest
// level-ups.
//
// Data (#level-data, from players/charts.py level_script_data):
//   days:  [["2026-11-07", 206], ...]   highest level seen per day
//   games: [["2026-11-07", 31], ...]    replays per day
//   ups:   [{level, day, at, replays}]  each new highest level, oldest first

(function () {
  "use strict";

  const dataEl = document.getElementById("level-data");
  const root = document.querySelector("[data-level]");
  const chartEl = root && root.querySelector("[data-level-chart]");
  if (!dataEl || !chartEl || !window.BVChart) return;
  const data = JSON.parse(dataEl.textContent);
  if (data.days.length < 2) return;

  const DAY = 86400000;
  const parse = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d).getTime(); };
  const fmt = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" });
  const fmtTime = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
  const fmtMonth = new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric" });
  const $ = (sel) => document.querySelector(sel);

  // Highest level so far, one point per day with replays.
  let best = 0;
  const points = data.days.map(([d, lv]) => { best = Math.max(best, lv); return [parse(d), best]; });
  const games = new Map(data.games.map(([d, n]) => [parse(d), n]));
  const ups = data.ups.filter((u) => u.day).map((u) => ({ ...u, t: parse(u.day) }));
  const first = points[0][0], last = points[points.length - 1][0];

  const presets = root.querySelector("[data-presets]");
  const chart = BVChart.line(chartEl, {
    xType: "time", height: 420, zoom: true, yFloor: 1,
    label: "Level over time",
    series: [{ name: "Level", color: "var(--site-series-1)", points, step: true, area: true, extend: true }],
    xDomain: [first, last],
    yFormat: (v) => `${Math.round(v)}`,
    tip: (t) => {
      const day = new Date(t); day.setHours(0, 0, 0, 0);
      const lv = BVChart.valueAt({ points, step: true, extend: true }, t);
      const up = ups.find((u) => u.t === day.getTime());
      const rows = [{ label: "Level", value: lv == null ? "—" : String(lv), color: "var(--site-series-1)" }];
      const n = games.get(day.getTime());
      if (n) rows.push({ label: "Replays that day", value: n.toLocaleString() });
      if (up) rows.push({ label: "Levelled up to", value: String(up.level) });
      return { title: fmt.format(day), rows };
    },
    onZoom: (domain, zoomed) => {
      presets.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(!zoomed && b.dataset.days === "all")));
      summarize(domain);
    },
  });

  presets.hidden = false;
  $("[data-range-stats]").hidden = false;
  presets.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => {
      const domain = btn.dataset.days === "all" ? null : [Math.max(first, last - Number(btn.dataset.days) * DAY), last];
      chart.setDomain(domain, true);
      presets.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
      summarize(chart.currentDomain());
    });
  });

  function summarize([t0, t1]) {
    const at = (t) => BVChart.valueAt({ points, step: true, extend: true }, t) ?? points[0][1];
    const gained = at(t1) - at(t0);
    let replays = 0;
    for (const [t, n] of games) if (t >= t0 && t <= t1) replays += n;
    const days = Math.max(1, Math.round((t1 - t0) / DAY));
    $("[data-range-label]").textContent = `${fmt.format(t0)} – ${fmt.format(t1)}`;
    $("[data-t-gained]").textContent = `+${gained}`;
    $("[data-t-replays]").textContent = replays.toLocaleString();
    $("[data-t-per-level]").textContent = gained ? Math.round(replays / gained).toLocaleString() : "—";
    $("[data-t-days-per-level]").textContent = gained ? `${(days / gained).toFixed(1)} days` : "—";

    const inRange = ups.filter((u) => u.t >= t0 && u.t <= t1).reverse().slice(0, 15);
    const body = $("[data-ups]");
    if (inRange.length) {
      body.replaceChildren(...inRange.map((u, i) => {
        const next = inRange[i + 1];
        const tr = document.createElement("tr");
        [
          String(u.level),
          u.at ? fmtTime.format(new Date(u.at)) : fmt.format(u.t),
          u.replays != null ? u.replays.toLocaleString() : "—",
          next ? String(Math.round((u.t - next.t) / DAY)) : "—",
        ].forEach((text, c) => {
          const td = document.createElement("td");
          td.textContent = text;
          if (c >= 2) td.className = "pv-num";
          tr.append(td);
        });
        return tr;
      }));
    } else {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 4;
      td.className = "pv-muted";
      td.textContent = "No level-ups in this stretch.";
      tr.append(td);
      body.replaceChildren(tr);
    }
    const whole = t0 <= first && t1 >= last;
    $("[data-ups-scope]").textContent = whole ? "latest" : "in this stretch";

    const now = points[points.length - 1][1];
    const target = Math.floor(now / 5) * 5 + 5;
    const perDay = gained / days;
    $("[data-next-text]").textContent = perDay > 0
      ? `At this pace, level ${target} around ${fmtMonth.format(last + ((target - now) / perDay) * DAY)}.`
      : "No level-ups in this stretch, so no pace to go on. Try a longer one.";
  }

  summarize([first, last]);
})();
