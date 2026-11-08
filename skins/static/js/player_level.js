// player_level.js — the Level explorer on a player profile (players/level.html)
//
// Zoom presets, a mini chart with two handles to pick any stretch of days,
// a hover/tap readout on the main chart, and the level-ups and pace for the
// chosen range. Without JavaScript the page still shows the whole line and
// the latest level-ups.
//
// Data (#level-data, from players/charts.py level_script_data):
//   days:  [["2026-11-07", 206], ...]   highest level seen per day
//   games: [["2026-11-07", 31], ...]    replays per day
//   ups:   [{level, day, at, replays}]  each new highest level, oldest first

(function () {
  "use strict";

  const dataEl = document.getElementById("level-data");
  const root = document.querySelector("[data-level]");
  if (!dataEl || !root) return;
  const data = JSON.parse(dataEl.textContent);
  if (data.days.length < 2) return;

  const DAY_MS = 86400000;
  const parse = (s) => { const [y, m, d] = s.split("-").map(Number); return Date.UTC(y, m - 1, d); };
  const fmt = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
  const fmtTime = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
  const fmtMonth = new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric", timeZone: "UTC" });

  // One entry per calendar day from first to last, level carried forward.
  const known = new Map(data.days.map(([d, lv]) => [parse(d), lv]));
  const gamesOn = new Map(data.games.map(([d, n]) => [parse(d), n]));
  const first = parse(data.days[0][0]);
  const last = parse(data.days[data.days.length - 1][0]);
  const series = [];
  let lv = data.days[0][1];
  for (let t = first; t <= last; t += DAY_MS) {
    if (known.has(t)) lv = Math.max(lv, known.get(t));
    series.push({ t, level: lv, games: gamesOn.get(t) || 0 });
  }
  const max = series.length - 1;
  let from = 0, to = max, hover = null;

  const $ = (sel, el = document) => el.querySelector(sel);
  const plot = $("[data-plot]", root);
  const line = $("[data-plot-line]", root);
  const area = $("[data-plot-area]", root);
  const cross = $("[data-cross]", root);
  const dot = $("[data-dot]", root);
  const fromInput = $("[data-from]", root);
  const toInput = $("[data-to]", root);
  const presets = $("[data-presets]", root);

  $("[data-brush]", root).hidden = false;
  presets.hidden = false;
  document.querySelector("[data-range-tiles]").hidden = false;
  fromInput.max = toInput.max = String(max);
  toInput.value = String(max);

  // Mini chart: the whole history.
  const lo0 = series[0].level, hi0 = series[max].level, rise0 = Math.max(hi0 - lo0, 1);
  $("[data-mini-line]", root).setAttribute("points", series.map((p, i) =>
    `${((i / max) * 1000).toFixed(1)},${(52 - ((p.level - lo0) / rise0) * 48).toFixed(1)}`).join(" "));

  function view() {
    const win = series.slice(from, to + 1);
    let lo = win[0].level, hi = win[win.length - 1].level;
    if (hi - lo < 4) { lo -= 2; hi += 2; }
    return { win, lo, hi };
  }

  function draw() {
    const { win, lo, hi } = view();
    const n = win.length;
    const x = (i) => (n === 1 ? 500 : (i / (n - 1)) * 1000);
    const y = (lv) => 268 - ((lv - lo) / (hi - lo)) * 256;
    const pts = win.map((p, i) => `${x(i).toFixed(1)},${y(p.level).toFixed(1)}`).join(" ");
    line.setAttribute("points", pts);
    area.setAttribute("points", `0,280 ${pts} 1000,280`);
    $("[data-plot-hi]", root).textContent = `Level ${hi}`;
    $("[data-plot-lo]", root).textContent = `Level ${lo}`;
    $("[data-range-label]", root).textContent = `${fmt.format(win[0].t)} – ${fmt.format(win[n - 1].t)}`;
    $("[data-from-label]", root).textContent = fmt.format(win[0].t);
    $("[data-to-label]", root).textContent = fmt.format(win[n - 1].t);
    const mw = $("[data-mini-window]", root);
    mw.style.setProperty("--from", `${(from / max) * 100}%`);
    mw.style.setProperty("--to", `${(to / max) * 100}%`);

    const k = hover == null || hover >= n ? n - 1 : hover;
    $("[data-read-level]", root).textContent = `Level ${win[k].level}`;
    $("[data-read-day]", root).textContent = fmt.format(win[k].t);
    cross.hidden = dot.hidden = hover == null;
    cross.style.setProperty("--x", `${x(k) / 10}%`);
    dot.style.setProperty("--x", `${x(k) / 10}%`);
    dot.style.setProperty("--y", `${(y(win[k].level) / 280) * 100}%`);

    summarize(win);
  }

  function summarize(win) {
    const gained = win[win.length - 1].level - win[0].level;
    const replays = win.reduce((s, p) => s + p.games, 0);
    const days = win.length;
    $("[data-t-gained]").textContent = `+${gained}`;
    $("[data-t-replays]").textContent = replays.toLocaleString();
    $("[data-t-per-level]").textContent = gained ? Math.round(replays / gained).toLocaleString() : "—";
    $("[data-t-days-per-level]").textContent = gained ? `${(days / gained).toFixed(1)} days` : "—";

    const t0 = win[0].t, t1 = win[win.length - 1].t;
    const ups = data.ups.filter((u) => u.day && parse(u.day) >= t0 && parse(u.day) <= t1).reverse().slice(0, 15);
    const body = $("[data-ups]");
    if (ups.length) {
      body.replaceChildren(...ups.map((u, i) => {
        const next = ups[i + 1];
        const tr = document.createElement("tr");
        const cells = [
          String(u.level),
          u.at ? fmtTime.format(new Date(u.at)) : fmt.format(parse(u.day)),
          u.replays != null ? u.replays.toLocaleString() : "—",
          next ? String(Math.round((parse(u.day) - parse(next.day)) / DAY_MS)) : "—",
        ];
        cells.forEach((text, c) => {
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
      td.textContent = "No level-ups in this range.";
      tr.append(td);
      body.replaceChildren(tr);
    }
    $("[data-ups-scope]").textContent = from === 0 && to === max ? "(latest)" : "(in this range)";

    // Pace to the next multiple of 5.
    const nextCard = $("[data-next]");
    const now = series[max].level;
    const target = Math.floor(now / 5) * 5 + 5;
    const perDay = gained / days;
    nextCard.hidden = false;
    if (perDay > 0) {
      const eta = series[max].t + ((target - now) / perDay) * DAY_MS;
      $("[data-next-text]").textContent = `At this range's pace, level ${target} around ${fmtMonth.format(eta)}.`;
    } else {
      $("[data-next-text]").textContent = `No level-ups in this range, so no pace to go on. Pick a longer range.`;
    }
  }

  function setRange(a, b) {
    from = Math.max(0, Math.min(a, max - 1));
    to = Math.min(max, Math.max(b, from + 1));
    fromInput.value = String(from);
    toInput.value = String(to);
    hover = null;
    draw();
  }

  presets.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => {
      presets.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
      const span = btn.dataset.days === "all" ? max : Number(btn.dataset.days);
      setRange(max - span, max);
    });
  });
  const clearPreset = () => presets.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", "false"));
  fromInput.addEventListener("input", () => { clearPreset(); setRange(Number(fromInput.value), to); });
  toInput.addEventListener("input", () => { clearPreset(); setRange(from, Number(toInput.value)); });

  function pointAt(clientX) {
    const r = plot.getBoundingClientRect();
    const n = to - from + 1;
    hover = Math.round(Math.min(1, Math.max(0, (clientX - r.left) / r.width)) * (n - 1));
    draw();
  }
  plot.addEventListener("pointermove", (e) => pointAt(e.clientX));
  plot.addEventListener("pointerdown", (e) => pointAt(e.clientX));
  plot.addEventListener("pointerleave", (e) => { if (e.pointerType === "mouse") { hover = null; draw(); } });

  draw();
})();
