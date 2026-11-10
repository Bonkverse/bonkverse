// player_activity.js — the Activity tab of a player profile (players/activity.html)
//
// Week view like a phone's screen-time screen: replays per day for one week
// (Monday first) with the daily average, arrows to move between weeks, and
// the selected day hour by hour. Everything is in the viewer's time zone.
//
// Data (#activity-data, from players/charts.py activity_script_data):
//   days:  [["2026-11-07", 31], ...]  every replay, by UTC or estimated day
//   hours: [["2026-11-07T21:00:00Z", 6], ...]  live replays per UTC hour
// Replays collected after the fact have only a day: they count toward that
// day but not toward any hour.

(function () {
  "use strict";

  const dataEl = document.getElementById("activity-data");
  const root = document.querySelector("[data-activity]");
  if (!dataEl || !root) return;
  const data = JSON.parse(dataEl.textContent);

  const DAY_MS = 86400000;
  const pad = (n) => String(n).padStart(2, "0");
  const ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const fromYmd = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
  const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
  const monday = (d) => addDays(d, -((d.getDay() + 6) % 7));
  const fmtDay = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });
  const fmtLong = new Intl.DateTimeFormat(undefined, { weekday: "long", month: "short", day: "numeric" });
  const fmtShort = new Intl.DateTimeFormat(undefined, { weekday: "short" });
  const fmtHour = new Intl.DateTimeFormat(undefined, { hour: "numeric" });

  // ── Counts in the viewer's time zone ──────────────────────────
  const perDay = new Map();      // local "YYYY-MM-DD" -> replays
  const timed = new Map();       // local day -> number[24]
  const untimed = new Map();     // day -> replays with no time
  const liveByUtcDay = new Map();
  const allHours = new Array(24).fill(0);

  for (const [t, n] of data.hours) {
    const when = new Date(t);
    const key = ymd(when);
    if (!timed.has(key)) timed.set(key, new Array(24).fill(0));
    timed.get(key)[when.getHours()] += n;
    allHours[when.getHours()] += n;
    perDay.set(key, (perDay.get(key) || 0) + n);
    const utcKey = t.slice(0, 10);
    liveByUtcDay.set(utcKey, (liveByUtcDay.get(utcKey) || 0) + n);
  }
  for (const [day, n] of data.days) {
    const rest = Math.max(0, n - (liveByUtcDay.get(day) || 0));
    if (rest) {
      perDay.set(day, (perDay.get(day) || 0) + rest);
      untimed.set(day, (untimed.get(day) || 0) + rest);
    }
  }

  const today = new Date();
  const thisMonday = monday(today);
  const firstDay = data.days.length ? fromYmd(data.days[0][0]) : today;
  const oldestOffset = Math.max(0, Math.round((thisMonday - monday(firstDay)) / (7 * DAY_MS)));

  // Start on the latest week with replays, on its busiest day.
  let offset = 0;
  while (offset < oldestOffset && weekCounts(offset).every((n) => n === 0)) offset++;
  let selected = bestDay(offset);

  function weekStart(off) { return addDays(thisMonday, -7 * off); }
  function weekCounts(off) {
    const start = weekStart(off);
    return [0, 1, 2, 3, 4, 5, 6].map((i) => perDay.get(ymd(addDays(start, i))) || 0);
  }
  function bestDay(off) {
    const c = weekCounts(off);
    return c.indexOf(Math.max(...c));
  }

  const $ = (sel) => root.querySelector(sel);
  const bars = $("[data-week-bars]");
  const dayCard = document.querySelector("[data-day]");

  function renderWeek() {
    const start = weekStart(offset);
    const counts = weekCounts(offset);
    const prev = weekCounts(offset + 1);
    const total = counts.reduce((a, b) => a + b, 0);
    const prevTotal = prev.reduce((a, b) => a + b, 0);
    const top = Math.max(1, ...counts);
    const avg = total / 7;

    $("[data-week-label]").textContent = offset === 0
      ? "This week"
      : offset === 1 ? "Last week" : `${fmtDay.format(start)} – ${fmtDay.format(addDays(start, 6))}`;
    $("[data-week-total]").textContent = total.toLocaleString();
    $("[data-week-avg]").textContent = Math.round(avg).toLocaleString();
    const delta = $("[data-week-delta]");
    if (prevTotal) {
      const pct = Math.round(((total - prevTotal) / prevTotal) * 100);
      delta.textContent = `${pct >= 0 ? "+" : ""}${pct}%`;
      delta.dataset.trend = pct >= 0 ? "up" : "down";
    } else {
      delta.textContent = "—";
      delta.dataset.trend = "";
    }
    $("[data-prev]").disabled = offset >= oldestOffset;
    $("[data-next]").disabled = offset === 0;

    const avgLine = $("[data-week-avgline]");
    avgLine.hidden = total === 0;
    avgLine.style.setProperty("--avg", String(avg / top));

    bars.replaceChildren(...counts.map((n, i) => {
      const day = addDays(start, i);
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "pv-week__bar";
      btn.setAttribute("aria-pressed", String(i === selected));
      btn.setAttribute("aria-label", `${fmtLong.format(day)}: ${n} replay${n === 1 ? "" : "s"}`);
      btn.disabled = day > today;
      btn.style.setProperty("--bar", `${(n / top) * 100}%`);
      const num = document.createElement("span");
      num.className = "pv-week__num";
      num.textContent = n ? n.toLocaleString() : "";
      const track = document.createElement("span");
      track.className = "pv-week__track";
      const fill = document.createElement("span");
      fill.className = "pv-week__fill";
      track.append(fill);
      const label = document.createElement("span");
      label.className = "pv-week__day";
      label.textContent = fmtShort.format(day);
      btn.append(num, track, label);
      btn.addEventListener("click", () => { selected = i; renderWeek(); renderDay(); });
      return btn;
    }));

    document.querySelectorAll(".pv-heat__week[data-week]").forEach((el) => {
      el.setAttribute("aria-pressed", String(el.dataset.week === ymd(start)));
    });
  }

  function renderDay() {
    const day = addDays(weekStart(offset), selected);
    const key = ymd(day);
    const hours = timed.get(key) || new Array(24).fill(0);
    const total = perDay.get(key) || 0;
    const noTime = untimed.get(key) || 0;
    const top = Math.max(1, ...hours);
    const peak = hours.indexOf(Math.max(...hours));

    dayCard.querySelector("[data-day-title]").textContent = fmtLong.format(day);
    dayCard.querySelector("[data-day-summary]").textContent = total
      ? `${total.toLocaleString()} replay${total === 1 ? "" : "s"}${hours[peak] ? ` · busiest ${fmtHour.format(new Date(2000, 0, 1, peak))}` : ""}`
      : "No replays";
    dayCard.querySelector("[data-day-hours]").replaceChildren(...hours.map((n, h) => {
      const bar = document.createElement("span");
      bar.className = "pv-hours__bar";
      if (h === peak && n) bar.dataset.peak = "";
      bar.style.setProperty("--bar", `${(n / top) * 100}%`);
      bar.title = `${fmtHour.format(new Date(2000, 0, 1, h))}: ${n} replay${n === 1 ? "" : "s"}`;
      return bar;
    }));
    dayCard.querySelector("[data-day-note]").textContent = noTime
      ? `${noTime.toLocaleString()} replay${noTime === 1 ? "" : "s"} this day ${noTime === 1 ? "was" : "were"} collected later, so ${noTime === 1 ? "it has" : "they have"} no time. Times are in your time zone.`
      : "Times are in your time zone.";
  }

  // "When they play most": the busiest 4-hour stretch, wrapping past midnight.
  function renderPeak() {
    const total = allHours.reduce((a, b) => a + b, 0);
    if (!total) return;
    let best = 0, bestSum = -1;
    for (let h = 0; h < 24; h++) {
      const sum = [0, 1, 2, 3].reduce((s, k) => s + allHours[(h + k) % 24], 0);
      if (sum > bestSum) { bestSum = sum; best = h; }
    }
    const name = best >= 21 || best < 3 ? "Night owl" : best < 9 ? "Early bird" : best < 15 ? "Daytime player" : "Evening player";
    const from = fmtHour.format(new Date(2000, 0, 1, best));
    const to = fmtHour.format(new Date(2000, 0, 1, (best + 4) % 24));
    document.querySelector("[data-peak-name]").textContent = name;
    document.querySelector("[data-peak-hours]").textContent =
      `${Math.round((bestSum / total) * 100)}% of timed replays ${from} – ${to}`;
  }

  $("[data-prev]").addEventListener("click", () => { offset++; selected = bestDay(offset); renderWeek(); renderDay(); });
  $("[data-next]").addEventListener("click", () => { offset--; selected = bestDay(offset); renderWeek(); renderDay(); });
  document.querySelectorAll(".pv-heat__week[data-week]").forEach((el) => {
    el.addEventListener("click", () => {
      const start = monday(fromYmd(el.dataset.week));
      offset = Math.max(0, Math.round((thisMonday - start) / (7 * DAY_MS)));
      selected = bestDay(offset);
      renderWeek();
      renderDay();
      root.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });

  renderWeek();
  renderDay();
  renderPeak();
})();
