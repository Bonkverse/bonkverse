// xp_calculator.js — the XP & Level calculator (players/xp_calculator.html)
//
// Everything updates as you type: level ↔ XP, a goal planner with a
// projection chart, where a level stands among replay players, a
// level-over-time comparison of up to four players, and an account's
// creation date from its ID. bonk.io's formulas (core/bonk/levels.py):
//   total XP at level L = 100·(L−1)², a won round = 100 XP, 18,000 XP a day max.
//
// Data: #xc-constants (json_script) has the formulas' constants, the known
// account-ID dates and the JSON endpoints for players and the level spread.

(function () {
  "use strict";

  const root = document.querySelector("[data-xc]");
  const constEl = document.getElementById("xc-constants");
  if (!root || !constEl) return;
  const C = JSON.parse(constEl.textContent);

  const XP_PER_WIN = C.xp_per_win;
  const DAILY_CAP = C.daily_cap;
  const MAX_LEVEL = 5000;
  const DAY_MS = 86400000;
  const COLORS = ["#47d8c4", "#90b7ff", "#ffb454", "#c79bff"];

  const $ = (sel, el = root) => el.querySelector(sel);
  const num = (n) => Math.round(n).toLocaleString();
  const fmtDay = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" });
  const fmtMonth = new Intl.DateTimeFormat(undefined, { month: "short", year: "numeric" });
  const parseDay = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
  const today = new Date(new Date().toDateString());

  const xpFor = (level) => 100 * Math.pow(Math.max(1, Math.floor(level)) - 1, 2);
  const levelFor = (xp) => Math.floor(Math.sqrt(Math.floor(Math.max(0, xp) / 100))) + 1;
  const clampLevel = (v) => Math.min(MAX_LEVEL, Math.max(1, Math.floor(v)));
  const readInt = (input) => {
    const v = parseInt(String(input.value).replace(/[^\d]/g, ""), 10);
    return Number.isFinite(v) ? v : null;
  };
  const daysLabel = (d) => (d < 1 ? "today" : d === 1 ? "1 day" : `${num(d)} days`);
  const svgEl = (tag, attrs) => {
    const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const k in attrs) el.setAttribute(k, attrs[k]);
    return el;
  };

  // Show a tooltip box near the pointer inside a chart figure.
  function placeTip(tip, fig, clientX, lines) {
    const r = fig.getBoundingClientRect();
    const x = clientX - r.left;
    tip.replaceChildren(...lines.map(([text, color]) => {
      const row = document.createElement("div");
      if (color) {
        const sw = document.createElement("span");
        sw.className = "pv-swatch";
        sw.style.setProperty("--slice", color);
        row.append(sw);
      }
      row.append(text);
      return row;
    }));
    tip.hidden = false;
    tip.style.setProperty("--x", `${Math.min(Math.max(x, 70), r.width - 70)}px`);
  }

  // ── Level ↔ XP ──────────────────────────────────────────────
  const conv = {
    level: $("[data-conv-level]"),
    xp: $("[data-conv-xp]"),
    progress: $("[data-conv-progress]"),
  };
  let convExact = false; // true when the XP box was typed (not derived)

  function renderConverter() {
    const level = readInt(conv.level);
    const xp = readInt(conv.xp);
    const list = $("[data-conv-milestones]");
    if (!level) { conv.progress.hidden = true; list.replaceChildren(); return; }
    const from = xpFor(level), to = xpFor(level + 1);
    conv.progress.hidden = !convExact;
    if (convExact && xp != null) {
      const into = xp - from;
      $("[data-conv-from]").textContent = `Level ${level}`;
      $("[data-conv-to]").textContent = `Level ${level + 1}`;
      $("[data-conv-pct]").textContent = `${((into / (to - from)) * 100).toFixed(2)}%`;
      $("[data-conv-fill]").style.setProperty("--bar", `${(into / (to - from)) * 100}%`);
      $("[data-conv-left]").textContent =
        `${num(into)} / ${num(to - from)} XP into this level · ${num(to - xp)} XP (${num(Math.ceil((to - xp) / XP_PER_WIN))} wins) to level ${level + 1}`;
    }
    const base = convExact && xp != null ? xp : from;
    const marks = [];
    for (let m = Math.floor(level / 50) * 50 + 50; marks.length < 3 && m <= MAX_LEVEL; m += 50) marks.push(m);
    list.replaceChildren(...marks.map((m) => {
      const need = xpFor(m) - base;
      const li = document.createElement("li");
      const strong = document.createElement("strong");
      strong.textContent = `Level ${m}`;
      const meta = document.createElement("span");
      meta.className = "pv-muted pv-small";
      meta.textContent = `${num(xpFor(m))} XP · ${num(need)} to go · ${num(Math.ceil(need / XP_PER_WIN))} wins · ${daysLabel(Math.ceil(need / DAILY_CAP))} at the max`;
      li.append(strong, meta);
      return li;
    }));
  }
  conv.level.addEventListener("input", () => {
    const level = readInt(conv.level);
    convExact = false;
    conv.xp.value = level ? xpFor(clampLevel(level)) : "";
    renderConverter();
  });
  conv.xp.addEventListener("input", () => {
    const xp = readInt(conv.xp);
    convExact = xp != null;
    conv.level.value = xp != null ? levelFor(xp) : "";
    renderConverter();
  });

  // ── Goal planner ─────────────────────────────────────────────
  const g = {
    startLevel: $("[data-start-level]"),
    startXp: $("[data-start-xp]"),
    goalLevel: $("[data-goal-level]"),
    goalXp: $("[data-goal-xp]"),
    pace: $("[data-pace]"),
  };
  function pair(levelInput, xpInput, onChange) {
    levelInput.addEventListener("input", () => {
      const lv = readInt(levelInput);
      xpInput.value = lv ? xpFor(clampLevel(lv)) : "";
      onChange();
    });
    xpInput.addEventListener("input", () => {
      const xp = readInt(xpInput);
      levelInput.value = xp != null ? levelFor(xp) : "";
      onChange();
    });
  }
  pair(g.startLevel, g.startXp, () => { renderGoal(); renderStand(); renderCompareTable(); });
  pair(g.goalLevel, g.goalXp, () => { renderGoal(); renderCompareTable(); });
  g.pace.addEventListener("input", renderGoal);

  function goalState() {
    const startXp = readInt(g.startXp);
    const goalXp = readInt(g.goalXp);
    if (startXp == null || goalXp == null) return null;
    const need = Math.max(0, goalXp - startXp);
    const wins = Number(g.pace.value);
    return {
      startXp, goalXp, need,
      startLevel: levelFor(startXp), goalLevel: levelFor(goalXp),
      winsNeeded: Math.ceil(need / XP_PER_WIN),
      daysCap: Math.ceil(need / DAILY_CAP),
      daysPace: Math.ceil(need / Math.min(DAILY_CAP, wins * XP_PER_WIN)),
      playerXpDay: player && player.pace && player.pace.xp_per_day > 0 ? player.pace.xp_per_day : null,
      wins,
    };
  }

  function renderGoal() {
    $("[data-pace-out]").textContent = g.pace.value;
    $("[data-pace-legend]").textContent = g.pace.value;
    const s = goalState();
    const out = (sel, text) => { $(sel).textContent = text; };
    if (!s) {
      ["[data-goal-xp-needed]", "[data-goal-wins]", "[data-goal-days-cap]"].forEach((sel) => out(sel, "—"));
      out("[data-goal-eta]", "Enter a start and a goal, or load a player.");
      $("[data-goal-eta-player]").hidden = true;
      drawProjection(null);
      return;
    }
    out("[data-goal-xp-needed]", num(s.need));
    out("[data-goal-wins]", num(s.winsNeeded));
    out("[data-goal-days-cap]", num(s.daysCap));
    const pct = s.goalXp > 0 ? Math.min(100, (s.startXp / s.goalXp) * 100) : 0;
    $("[data-goal-fill]").style.setProperty("--bar", `${pct}%`);
    out("[data-goal-bar-text]", `${num(s.startXp)} / ${num(s.goalXp)} XP · ${pct.toFixed(2)}% of the way to level ${s.goalLevel}`);
    if (s.need === 0) {
      out("[data-goal-eta]", "Already there.");
    } else {
      out("[data-goal-eta]", `At ${s.wins} wins a day: ${daysLabel(s.daysPace)}, around ${fmtDay.format(new Date(today.getTime() + s.daysPace * DAY_MS))}.`);
    }
    const playerEta = $("[data-goal-eta-player]");
    if (s.playerXpDay && s.need > 0) {
      const d = Math.ceil(s.need / s.playerXpDay);
      playerEta.hidden = false;
      playerEta.textContent = `At ${player.username}'s pace lately (≈${player.pace.wins_per_day} wins a day): ${daysLabel(d)}, around ${d > 36500 ? "a century from now" : fmtMonth.format(new Date(today.getTime() + d * DAY_MS))}.`;
    } else {
      playerEta.hidden = true;
    }
    drawProjection(s);
  }

  // Projection: level over the coming days at the daily max, at the chosen
  // pace and (with a player loaded) at their recent pace.
  const proj = { fig: $("[data-proj]"), svg: $("[data-proj-svg]"), cross: $("[data-proj-cross]"), tip: $("[data-proj-tip]") };
  let projState = null;
  function projLines(s) {
    const lines = [
      { name: "At the max", color: "#47d8c4", rate: DAILY_CAP },
      { name: `At ${s.wins} wins a day`, color: "#90b7ff", rate: Math.min(DAILY_CAP, s.wins * XP_PER_WIN) },
    ];
    if (s.playerXpDay) lines.push({ name: `${player.username}'s pace`, color: "#ffb454", rate: s.playerXpDay });
    return lines;
  }
  function drawProjection(s) {
    proj.svg.replaceChildren();
    $("[data-proj-player-legend]").hidden = !(s && s.playerXpDay);
    projState = null;
    if (!s || s.need === 0) { proj.fig.hidden = true; return; }
    proj.fig.hidden = false;
    const lines = projLines(s);
    const slowest = Math.max(...lines.map((l) => s.need / l.rate));
    const span = Math.min(Math.max(7, slowest * 1.08), 3650);
    const lo = s.startLevel, hi = s.goalLevel + Math.max(1, Math.round((s.goalLevel - s.startLevel) * 0.04));
    const x = (d) => (d / span) * 600;
    const y = (lv) => 210 - ((lv - lo) / Math.max(1, hi - lo)) * 200;
    proj.svg.append(svgEl("line", { x1: 0, x2: 600, y1: y(s.goalLevel), y2: y(s.goalLevel), class: "xc-goalline" }));
    for (const l of lines) {
      const pts = [];
      for (let i = 0; i <= 120; i++) {
        const d = (span * i) / 120;
        const lv = Math.min(s.goalLevel, levelFor(s.startXp + l.rate * d));
        pts.push(`${x(d).toFixed(1)},${y(lv).toFixed(1)}`);
      }
      proj.svg.append(svgEl("polyline", { points: pts.join(" "), class: "xc-line", style: `--line: ${l.color}` }));
    }
    projState = { s, lines, span };
  }
  function projHover(e) {
    if (!projState) return;
    const r = proj.fig.getBoundingClientRect();
    const f = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    const d = Math.round(projState.span * f);
    proj.cross.hidden = false;
    proj.cross.style.setProperty("--x", `${f * 100}%`);
    placeTip(proj.tip, proj.fig, e.clientX, [
      [`In ${daysLabel(d)} (${fmtDay.format(new Date(today.getTime() + d * DAY_MS))})`],
      ...projState.lines.map((l) => [`${l.name}: level ${Math.min(projState.s.goalLevel, levelFor(projState.s.startXp + l.rate * d))}`, l.color]),
    ]);
  }
  proj.fig.addEventListener("pointermove", projHover);
  proj.fig.addEventListener("pointerdown", projHover);
  proj.fig.addEventListener("pointerleave", () => { proj.cross.hidden = true; proj.tip.hidden = true; });

  // ── Where a level stands ────────────────────────────────────
  let spread = null; // {levels: [[level, players]], players}
  const BUCKET = 10;
  function renderStand() {
    const hist = $("[data-hist]");
    const headline = $("[data-stand-headline]");
    if (!spread) return;
    const level = readInt(g.startLevel) || (player && player.level) || null;
    const buckets = new Map();
    let total = 0, below = 0, top = 0;
    for (const [lv, n] of spread.levels) {
      const b = Math.floor(lv / BUCKET) * BUCKET;
      buckets.set(b, (buckets.get(b) || 0) + n);
      total += n;
      if (level && lv < level) below += n;
    }
    const maxB = Math.max(...buckets.keys(), 0);
    for (const v of buckets.values()) top = Math.max(top, v);
    const bars = [];
    for (let b = 0; b <= maxB; b += BUCKET) {
      const n = buckets.get(b) || 0;
      const bar = document.createElement("span");
      bar.className = "xc-hist__bar";
      // Square-root scale so the long tail of high levels stays visible.
      bar.style.setProperty("--bar", `${n ? Math.max(2, Math.sqrt(n / top) * 100) : 0}%`);
      if (level && level >= b && level < b + BUCKET) bar.dataset.here = "";
      const label = `Levels ${Math.max(1, b)}–${b + BUCKET - 1}: ${num(n)} player${n === 1 ? "" : "s"}`;
      bar.setAttribute("aria-label", label);
      bar.addEventListener("pointerenter", () => { $("[data-hist-tip]").textContent = label; });
      bars.push(bar);
    }
    hist.replaceChildren(...bars);
    const axis = $("[data-hist-axis]");
    axis.replaceChildren(...[0, Math.round(maxB / 2 / 50) * 50, maxB].map((v) => {
      const s = document.createElement("span");
      s.textContent = `Level ${Math.max(1, v)}`;
      return s;
    }));
    $("[data-stand-source]").textContent = `${num(total)} players seen in replays`;
    if (level) {
      const pct = total ? (below / total) * 100 : 0;
      headline.textContent = `Level ${level} is higher than ${pct >= 99.9 ? pct.toFixed(2) : pct.toFixed(1)}% of players seen in replays.`;
    } else {
      headline.textContent = "Enter a start level (or load a player) to see where it stands.";
    }
  }
  fetch(C.levels_url, { headers: { Accept: "application/json" } })
    .then((r) => r.json())
    .then((res) => {
      if (!res.ok) throw new Error(res.error);
      spread = res.data;
      renderStand();
    })
    .catch(() => { $("[data-stand-headline]").textContent = "The level spread can't be loaded right now."; });

  // ── Players: load and compare ───────────────────────────────
  let player = null;
  const compare = [];
  const cache = new Map();
  const ERRORS = {
    not_found: "No replays for that registered player.",
    private: "That player keeps their level private.",
    unavailable: "Replay stats can't be loaded right now.",
  };

  async function fetchPlayer(name) {
    const key = name.toLowerCase();
    if (cache.has(key)) return cache.get(key);
    const r = await fetch(`${C.player_url}?name=${encodeURIComponent(name)}`, { headers: { Accept: "application/json" } });
    const res = await r.json().catch(() => ({ ok: false, error: "unavailable" }));
    if (!res.ok) throw new Error(ERRORS[res.error] || ERRORS.unavailable);
    cache.set(key, res.data);
    return res.data;
  }
  // A player's profile path (players/urls.py: player/<name>/). Built here
  // rather than from the page's data so it is always a same-site path; the
  // name is percent-encoded, so it can't become a different URL.
  const profileUrl = (name) => `/player/${encodeURIComponent(String(name))}/`;
  const playerXp = (p) => (p.xp != null ? p.xp : p.xp_floor);

  async function loadPlayer(name, { setGoal = true } = {}) {
    const status = $("[data-load-status]");
    status.hidden = false;
    status.textContent = `Loading ${name}…`;
    try {
      player = await fetchPlayer(name);
    } catch (err) {
      status.textContent = err.message;
      return;
    }
    status.hidden = true;
    $("[data-player]").hidden = false;
    $("[data-player-initials]").textContent = player.username.trim().slice(0, 2).toUpperCase();
    const link = $("[data-player-link]");
    link.textContent = player.username;
    link.href = profileUrl(player.username);
    $("[data-player-facts]").textContent = player.created
      ? `Account made ${player.created_extrapolated ? "around" : "≈"} ${fmtMonth.format(parseDay(player.created))} · ID ${num(player.bonk_id)}`
      : "Account date unknown";
    $("[data-player-level]").textContent = player.level ?? "—";
    $("[data-player-xp-label]").textContent = player.xp != null ? "XP" : "XP (at least)";
    $("[data-player-xp]").textContent = player.xp_floor != null ? num(playerXp(player)) : "—";
    $("[data-player-pace]").textContent = !player.pace
      ? "—"
      : player.pace.levels > 0
        ? `+${player.pace.levels} level${player.pace.levels === 1 ? "" : "s"} in ${player.pace.days} days`
        : "No level-ups";

    if (player.level) {
      g.startXp.value = playerXp(player);
      g.startLevel.value = player.level;
      conv.level.value = player.level;
      conv.xp.value = playerXp(player);
      convExact = player.xp != null;
      if (setGoal || !readInt(g.goalLevel)) {
        const goal = Math.floor(player.level / 50) * 50 + 50;
        g.goalLevel.value = goal;
        g.goalXp.value = xpFor(goal);
      }
      if (player.pace && player.pace.wins_per_day > 0) {
        g.pace.value = String(Math.min(180, Math.max(1, Math.round(player.pace.wins_per_day))));
      }
    }
    if (player.bonk_id) {
      $("[data-dbid-input]").value = player.bonk_id;
      renderDbid();
    }
    addCompare(player);
    renderConverter();
    renderGoal();
    renderStand();
    const url = new URL(window.location.href);
    url.searchParams.set("player", player.username);
    history.replaceState(null, "", url);
  }

  $("[data-load-form]").addEventListener("submit", (e) => {
    e.preventDefault();
    const name = $("[data-load-input]").value;
    if (name) loadPlayer(name);
  });

  function addCompare(p) {
    if (compare.some((c) => c.username.toLowerCase() === p.username.toLowerCase())) return renderCompare();
    if (compare.length >= 4) compare.shift();
    compare.push(p);
    renderCompare();
  }
  $("[data-cmp-form]").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = $("[data-cmp-input]");
    const name = input.value;
    if (!name) return;
    const status = $("[data-cmp-status]");
    status.textContent = `Loading ${name}…`;
    try {
      addCompare(await fetchPlayer(name));
      status.textContent = "";
      input.value = "";
    } catch (err) {
      status.textContent = err.message;
    }
  });

  const cmp = { fig: $("[data-cmp-chart]"), svg: $("[data-cmp-svg]"), cross: $("[data-cmp-cross]"), tip: $("[data-cmp-tip]") };
  let cmpState = null;

  function levelOn(series, t) {
    let lv = null;
    for (const [d, l] of series) { if (parseDay(d).getTime() <= t) lv = l; else break; }
    return lv;
  }

  function renderCompare() {
    const chips = $("[data-cmp-chips]");
    chips.replaceChildren(...compare.map((p, i) => {
      const li = document.createElement("li");
      li.className = "xc-chip";
      li.style.setProperty("--slice", COLORS[i]);
      const sw = document.createElement("span");
      sw.className = "pv-swatch";
      const a = document.createElement("a");
      a.href = profileUrl(p.username);
      a.textContent = p.username;
      const x = document.createElement("button");
      x.type = "button";
      x.className = "xc-chip__x";
      x.setAttribute("aria-label", `Remove ${p.username}`);
      x.textContent = "×";
      x.addEventListener("click", () => { compare.splice(i, 1); renderCompare(); });
      li.append(sw, a, x);
      return li;
    }));

    const withSeries = compare.filter((p) => p.series && p.series.length);
    cmp.fig.hidden = withSeries.length === 0;
    $("[data-cmp-tablewrap]").hidden = compare.length === 0;
    cmp.svg.replaceChildren();
    cmpState = null;
    if (withSeries.length) {
      let t0 = Infinity, t1 = -Infinity, lo = Infinity, hi = -Infinity;
      for (const p of withSeries) {
        for (const [d, l] of p.series) {
          const t = parseDay(d).getTime();
          t0 = Math.min(t0, t); t1 = Math.max(t1, t); lo = Math.min(lo, l); hi = Math.max(hi, l);
        }
      }
      t1 = Math.max(t1, t0 + DAY_MS);
      lo = Math.max(1, lo - 2); hi += 2;
      const x = (t) => ((t - t0) / (t1 - t0)) * 1000;
      const y = (l) => 290 - ((l - lo) / (hi - lo)) * 280;
      compare.forEach((p, i) => {
        if (!p.series || !p.series.length) return;
        const pts = [];
        let prev = null;
        for (const [d, l] of p.series) {
          const px = x(parseDay(d).getTime());
          if (prev != null) pts.push(`${px.toFixed(1)},${y(prev).toFixed(1)}`);
          pts.push(`${px.toFixed(1)},${y(l).toFixed(1)}`);
          prev = l;
        }
        cmp.svg.append(svgEl("polyline", { points: pts.join(" "), class: "xc-line", style: `--line: ${COLORS[i]}` }));
      });
      $("[data-cmp-from]").textContent = fmtMonth.format(new Date(t0));
      $("[data-cmp-to]").textContent = fmtMonth.format(new Date(t1));
      cmpState = { t0, t1 };
    }
    renderCompareTable();
  }

  function renderCompareTable() {
    const goalLevel = readInt(g.goalLevel);
    $("[data-cmp-goal-label]").textContent = goalLevel ? `level ${goalLevel}` : "goal";
    $("[data-cmp-rows]").replaceChildren(...compare.map((p, i) => {
      const tr = document.createElement("tr");
      const name = document.createElement("td");
      const sw = document.createElement("span");
      sw.className = "pv-swatch";
      sw.style.setProperty("--slice", COLORS[i]);
      const a = document.createElement("a");
      a.href = profileUrl(p.username);
      a.textContent = p.username;
      name.append(sw, a);
      let eta = "—";
      if (goalLevel && p.level) {
        const need = xpFor(goalLevel) - playerXp(p);
        if (need <= 0) eta = "Already there";
        else if (p.pace && p.pace.xp_per_day > 0) {
          const d = Math.ceil(need / p.pace.xp_per_day);
          eta = d > 36500 ? "Not at this pace" : `≈ ${fmtMonth.format(new Date(today.getTime() + d * DAY_MS))}`;
        } else eta = "No recent level-ups";
      }
      const cells = [
        name,
        p.level ?? "—",
        p.xp != null ? num(p.xp) : p.xp_floor != null ? `≥ ${num(p.xp_floor)}` : "—",
        p.created ? `${p.created_extrapolated ? "around " : ""}${fmtMonth.format(parseDay(p.created))}` : "Unknown",
        p.pace ? (p.pace.levels_per_day * 30).toFixed(1) : "—",
        eta,
      ];
      cells.forEach((c, k) => {
        const td = c instanceof Node ? c : document.createElement("td");
        if (!(c instanceof Node)) td.textContent = String(c);
        if (k === 1 || k === 2 || k === 4) td.className = "pv-num";
        tr.append(td);
      });
      return tr;
    }));
  }

  function cmpHover(e) {
    if (!cmpState) return;
    const r = cmp.fig.getBoundingClientRect();
    const f = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    const t = cmpState.t0 + f * (cmpState.t1 - cmpState.t0);
    cmp.cross.hidden = false;
    cmp.cross.style.setProperty("--x", `${f * 100}%`);
    placeTip(cmp.tip, cmp.fig, e.clientX, [
      [fmtDay.format(new Date(t))],
      ...compare.map((p, i) => {
        const lv = p.series ? levelOn(p.series, t) : null;
        return [`${p.username}: ${lv == null ? "not seen yet" : `level ${lv}`}`, COLORS[i]];
      }),
    ]);
  }
  cmp.fig.addEventListener("pointermove", cmpHover);
  cmp.fig.addEventListener("pointerdown", cmpHover);
  cmp.fig.addEventListener("pointerleave", () => { cmp.cross.hidden = true; cmp.tip.hidden = true; });

  // ── Account ID → date ───────────────────────────────────────
  const points = C.dbid_points.map(([n, d]) => [n, parseDay(d).getTime()]);
  function dbidDate(id) {
    if (!(id >= 1)) return null;
    for (let i = 0; i < points.length - 1; i++) {
      const [n0, t0] = points[i], [n1, t1] = points[i + 1];
      if (id >= n0 && id <= n1) return { t: t0 + ((t1 - t0) * (id - n0)) / Math.max(1, n1 - n0), extrapolated: false };
    }
    const [n0, t0] = points[points.length - 2], [n1, t1] = points[points.length - 1];
    const t = t0 + ((t1 - t0) * (id - n0)) / (n1 - n0);
    return { t: Math.max(t1, Math.min(t, today.getTime())), extrapolated: true };
  }
  const db = { fig: $("[data-dbid-chart]"), svg: $("[data-dbid-svg]"), cross: $("[data-dbid-cross]"), dot: $("[data-dbid-dot]"), tip: $("[data-dbid-tip]") };
  const dT0 = points[0][1], dT1 = Math.max(points[points.length - 1][1], today.getTime());
  const dN1 = points[points.length - 1][0] * 1.02;
  const dx = (t) => ((t - dT0) / (dT1 - dT0)) * 1000;
  const dy = (n) => 250 - (n / dN1) * 240;
  db.svg.append(svgEl("polyline", {
    points: points.map(([n, t]) => `${dx(t).toFixed(1)},${dy(n).toFixed(1)}`).join(" "),
    class: "xc-line", style: "--line: #47d8c4",
  }));
  $("[data-dbid-first]").textContent = fmtMonth.format(new Date(dT0));
  $("[data-dbid-last]").textContent = fmtMonth.format(new Date(dT1));

  function idAt(t) {
    for (let i = 0; i < points.length - 1; i++) {
      const [n0, t0] = points[i], [n1, t1] = points[i + 1];
      if (t >= t0 && t <= t1) return n0 + ((n1 - n0) * (t - t0)) / Math.max(1, t1 - t0);
    }
    return points[points.length - 1][0];
  }
  function renderDbid() {
    const id = readInt($("[data-dbid-input]"));
    const est = id ? dbidDate(id) : null;
    db.dot.hidden = !est;
    if (!est) { $("[data-dbid-date]").textContent = "—"; $("[data-dbid-age]").textContent = ""; return; }
    const years = (today.getTime() - est.t) / (365.25 * DAY_MS);
    $("[data-dbid-date]").textContent = `${est.extrapolated ? "Around " : ""}${fmtDay.format(new Date(est.t))}`;
    $("[data-dbid-age]").textContent = years >= 1 ? `about ${years.toFixed(1)} years old` : `about ${Math.max(0, Math.round(years * 12))} months old`;
    db.dot.style.setProperty("--x", `${dx(est.t) / 10}%`);
    db.dot.style.setProperty("--y", `${(dy(id) / 260) * 240}px`); // the SVG is 240px tall
  }
  $("[data-dbid-input]").addEventListener("input", renderDbid);
  function dbidHover(e) {
    const r = db.fig.getBoundingClientRect();
    const f = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    const t = dT0 + f * (dT1 - dT0);
    db.cross.hidden = false;
    db.cross.style.setProperty("--x", `${f * 100}%`);
    placeTip(db.tip, db.fig, e.clientX, [[fmtMonth.format(new Date(t))], [`Accounts made then: ID ≈ ${num(idAt(t))}`, "#47d8c4"]]);
  }
  db.fig.addEventListener("pointermove", dbidHover);
  db.fig.addEventListener("pointerdown", dbidHover);
  db.fig.addEventListener("pointerleave", () => { db.cross.hidden = true; db.tip.hidden = true; });

  // ── Start ───────────────────────────────────────────────────
  renderConverter();
  renderGoal();
  const prefill = root.dataset.prefillPlayer;
  const prefillGoal = parseInt(root.dataset.prefillGoal, 10);
  if (prefill) {
    $("[data-load-input]").value = prefill;
    loadPlayer(prefill, { setGoal: !prefillGoal });
  }
  if (prefillGoal > 0) {
    g.goalLevel.value = clampLevel(prefillGoal);
    g.goalXp.value = xpFor(clampLevel(prefillGoal));
    renderGoal();
  }
})();
