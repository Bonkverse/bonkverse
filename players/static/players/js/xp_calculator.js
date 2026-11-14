// xp_calculator.js — the XP & Level calculator (players/xp_calculator.html)
//
// Four tabs: Plan a goal, Compare players, Level spread, Account age. Every
// chart is a BVChart (core/js/bv-chart.js): big, with a tooltip at the
// pointer and drag-to-zoom on the line charts. bonk.io's formulas
// (core/bonk/levels.py): total XP at level L = 100·(L−1)², a won round =
// 100 XP, 18,000 XP a day at most.
//
// Data: #xc-constants (json_script): the constants, known account-ID dates
// and the JSON endpoints for players and the level spread.

(function () {
  "use strict";

  const root = document.querySelector("[data-xc]");
  const constEl = document.getElementById("xc-constants");
  if (!root || !constEl || !window.BVChart) return;
  const C = JSON.parse(constEl.textContent);

  const XP_PER_WIN = C.xp_per_win;
  const DAILY_CAP = C.daily_cap;
  const MAX_LEVEL = 5000;
  const DAY = 86400000;
  // Series colors are theme tokens (css/base.css), so charts follow the theme.
  const COLORS = ["var(--site-series-1)", "var(--site-series-2)", "var(--site-series-3)", "var(--site-series-4)"];
  const PACE = { cap: "var(--site-series-1)", pace: "var(--site-series-2)", player: "var(--site-series-3)", history: "var(--bv-text)" };

  const $ = (sel, el = root) => el.querySelector(sel);
  const $$ = (sel, el = root) => [...el.querySelectorAll(sel)];
  const num = (n) => Math.round(n).toLocaleString();
  const fmtDay = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" });
  const fmtMonth = new Intl.DateTimeFormat(undefined, { month: "short", year: "numeric" });
  const parseDay = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d).getTime(); };
  const today = new Date(new Date().toDateString()).getTime();

  const xpFor = (level) => 100 * Math.pow(Math.max(1, Math.floor(level)) - 1, 2);
  const levelFor = (xp) => Math.floor(Math.sqrt(Math.floor(Math.max(0, xp) / 100))) + 1;
  const clampLevel = (v) => Math.min(MAX_LEVEL, Math.max(1, Math.floor(v)));
  const readInt = (input) => {
    const v = parseInt(String(input.value).replace(/[^\d]/g, ""), 10);
    return Number.isFinite(v) ? v : null;
  };
  const daysLabel = (d) => (d < 1 ? "today" : d === 1 ? "1 day" : `${num(d)} days`);
  const when = (days) => (days > 36500 ? "more than a century away" : fmtMonth.format(today + days * DAY));
  // A player's profile path (players/urls.py: player/<name>/), built here so
  // links never come from page data; the name is percent-encoded. Names like
  // "." and ".." get a "~" in front, or the browser would read them as
  // folders (players/converters.py).
  const urlName = (name) => (/^~*\.{1,2}$/.test(name) ? `~${name}` : name);
  const profileUrl = (name) => `/player/${encodeURIComponent(urlName(String(name)))}/`;

  // ── Tabs ─────────────────────────────────────────────────────
  const TABS = ["plan", "compare", "spread", "age"];
  function showTab(name, push) {
    if (!TABS.includes(name)) name = "plan";
    for (const p of $$("[data-panel]")) p.hidden = p.dataset.panel !== name;
    for (const t of $$("[data-tab]")) {
      const on = t.dataset.tab === name;
      t.setAttribute("aria-selected", String(on));
      if (on) t.setAttribute("aria-current", "page"); else t.removeAttribute("aria-current");
    }
    if (push) history.replaceState(null, "", `${location.pathname}${location.search}#${name}`);
  }
  $$("[data-tab]").forEach((t) => t.addEventListener("click", (e) => { e.preventDefault(); showTab(t.dataset.tab, true); }));
  window.addEventListener("hashchange", () => showTab(location.hash.slice(1)));
  showTab(location.hash.slice(1));

  function segment(group, onPick) {
    group.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
      if (b.disabled) return;
      group.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      onPick(b);
    }));
  }

  // ── Plan a goal ──────────────────────────────────────────────
  const plan = {
    startLevel: $("[data-start-level]"), startXp: $("[data-start-xp]"),
    goalLevel: $("[data-goal-level]"), goalXp: $("[data-goal-xp]"),
    pace: $("[data-pace]"), view: "ahead",
  };
  let startXpTyped = false;

  function pair(levelInput, xpInput, isStart) {
    levelInput.addEventListener("input", () => {
      const lv = readInt(levelInput);
      xpInput.value = lv ? xpFor(clampLevel(lv)) : "";
      if (isStart) startXpTyped = false;
      update();
    });
    xpInput.addEventListener("input", () => {
      const xp = readInt(xpInput);
      levelInput.value = xp != null ? levelFor(xp) : "";
      if (isStart) startXpTyped = xp != null;
      update();
    });
  }
  pair(plan.startLevel, plan.startXp, true);
  pair(plan.goalLevel, plan.goalXp, false);
  plan.pace.addEventListener("input", () => { renderPlan(); });
  segment($("[data-plan-view]"), (b) => { plan.view = b.dataset.view; renderPlanChart(); });

  function setGoal(level) {
    plan.goalLevel.value = clampLevel(level);
    plan.goalXp.value = xpFor(clampLevel(level));
    update();
  }

  function state() {
    const startXp = readInt(plan.startXp);
    const goalXp = readInt(plan.goalXp);
    if (startXp == null || goalXp == null) return null;
    const need = Math.max(0, goalXp - startXp);
    const wins = Number(plan.pace.value);
    const playerRate = player && player.pace && player.pace.xp_per_day > 0 ? player.pace.xp_per_day : null;
    return {
      startXp, goalXp, need, wins, playerRate,
      startLevel: levelFor(startXp), goalLevel: levelFor(goalXp),
      winsNeeded: Math.ceil(need / XP_PER_WIN),
      daysCap: Math.ceil(need / DAILY_CAP),
      daysPace: Math.ceil(need / Math.min(DAILY_CAP, wins * XP_PER_WIN)),
      daysPlayer: playerRate ? Math.ceil(need / playerRate) : null,
    };
  }

  function renderQuickGoals() {
    const box = $("[data-quick-goals]");
    const start = readInt(plan.startLevel) || 1;
    const options = [...new Set([start + 10, Math.floor(start / 50) * 50 + 50, Math.floor(start / 100) * 100 + 100, 250, 300, 400, 500])]
      .filter((l) => l > start && l <= MAX_LEVEL).sort((a, b) => a - b).slice(0, 5);
    box.replaceChildren(...options.map((l) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "xc-quick__btn";
      b.textContent = l === start + 10 ? `+10 (${l})` : `Level ${l}`;
      b.addEventListener("click", () => setGoal(l));
      return b;
    }));
  }

  function renderStartProgress() {
    const xp = readInt(plan.startXp);
    const box = $("[data-start-progress]");
    if (xp == null) { box.hidden = true; return; }
    const level = levelFor(xp), from = xpFor(level), to = xpFor(level + 1);
    const pct = ((xp - from) / (to - from)) * 100;
    box.hidden = !startXpTyped;
    $("[data-start-fill]").style.setProperty("--bar", `${pct}%`);
    $("[data-start-progress-text]").textContent =
      `${pct.toFixed(2)}% through level ${level} · ${num(to - xp)} XP (${num(Math.ceil((to - xp) / XP_PER_WIN))} wins) to level ${level + 1}`;
  }

  function renderPlan() {
    $("[data-pace-out]").textContent = `${plan.pace.value} (${num(plan.pace.value * XP_PER_WIN)} XP)`;
    renderStartProgress();
    renderQuickGoals();
    const s = state();
    const set = (sel, text) => { $(sel).textContent = text; };
    if (!s) {
      ["[data-goal-xp-needed]", "[data-goal-wins]", "[data-goal-days-cap]"].forEach((sel) => set(sel, "—"));
      set("[data-goal-eta]", "Enter where you are and where you want to be, or load a player.");
      $("[data-eta-player]").hidden = $("[data-eta-cap]").hidden = true;
    } else {
      set("[data-goal-xp-needed]", num(s.need));
      set("[data-goal-wins]", num(s.winsNeeded));
      set("[data-goal-days-cap]", num(s.daysCap));
      if (s.need === 0) {
        set("[data-goal-eta]", "Already there.");
        $("[data-eta-player]").hidden = $("[data-eta-cap]").hidden = true;
      } else {
        set("[data-goal-eta]", `At ${s.wins} wins a day: ${daysLabel(s.daysPace)}, around ${fmtDay.format(today + s.daysPace * DAY)}.`);
        $("[data-eta-cap]").hidden = false;
        set("[data-goal-eta-cap]", `Every day at the max: ${daysLabel(s.daysCap)}, around ${fmtDay.format(today + s.daysCap * DAY)}.`);
        $("[data-eta-player]").hidden = !s.daysPlayer;
        if (s.daysPlayer) {
          set("[data-goal-eta-player]", `At ${player.username}'s pace lately (≈${player.pace.wins_per_day} wins a day): ${daysLabel(s.daysPlayer)}, around ${when(s.daysPlayer)}.`);
        }
      }
    }
    renderMilestones();
    renderPlanChart();
  }

  function renderMilestones() {
    const list = $("[data-milestones]");
    const xp = readInt(plan.startXp);
    if (xp == null) { list.replaceChildren(); return; }
    const level = levelFor(xp);
    const marks = [];
    for (let m = Math.floor(level / 50) * 50 + 50; marks.length < 4 && m <= MAX_LEVEL; m += 50) marks.push(m);
    const s = state();
    list.replaceChildren(...marks.map((m) => {
      const need = xpFor(m) - xp;
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "xc-milestone";
      btn.setAttribute("aria-label", `Plan for level ${m}`);
      const big = document.createElement("span");
      big.className = "xc-milestone__lvl";
      big.textContent = m;
      const meta = document.createElement("span");
      meta.className = "xc-milestone__meta";
      const pace = s && s.playerRate ? ` · ${when(Math.ceil(need / s.playerRate))} at their pace` : "";
      meta.textContent = `${num(need)} XP · ${num(Math.ceil(need / XP_PER_WIN))} wins · ${num(Math.ceil(need / DAILY_CAP))} days at the max${pace}`;
      btn.append(big, meta);
      btn.addEventListener("click", () => { setGoal(m); $("[data-plan-chart]").scrollIntoView({ behavior: "smooth", block: "center" }); });
      li.append(btn);
      return li;
    }));
  }

  const planChart = BVChart.line($("[data-plan-chart]"), {
    xType: "time", height: 420, zoom: true, series: [], yFloor: 1,
    label: "Level over time towards the goal",
    yFormat: (v) => `${Math.round(v)}`,
    tipValue: (v) => `Level ${Math.floor(v)}`,
    emptyText: "Enter a start and a goal to see how it plays out.",
  });

  function paceLine(name, color, rate, s, from, span) {
    const pts = [];
    const steps = 160;
    for (let i = 0; i <= steps; i++) {
      const d = (span * i) / steps;
      pts.push([from + d * DAY, Math.min(s.goalLevel, levelFor(s.startXp + rate * d))]);
    }
    return { name, color, points: pts, step: true, extend: true };
  }

  function renderPlanChart() {
    const s = state();
    if (!s || s.need === 0) { planChart.update({ series: [], hlines: [] }); return; }
    const rates = [
      ["Every day at the max", PACE.cap, DAILY_CAP],
      [`At ${s.wins} wins a day`, PACE.pace, Math.min(DAILY_CAP, s.wins * XP_PER_WIN)],
    ];
    if (s.playerRate) rates.push([`${player.username}'s pace`, PACE.player, s.playerRate]);
    const longest = Math.max(...rates.map(([, , r]) => s.need / r));
    const span = Math.min(Math.max(14, longest * 1.06), 3650);
    const series = rates.map(([n, c, r]) => paceLine(n, c, r, s, today, span));
    const markers = [];
    if (plan.view === "history" && player && player.series && player.series.length) {
      series.unshift({ name: `${player.username} so far`, color: PACE.history, points: player.series.map(([d, l]) => [parseDay(d), l]), step: true });
      markers.push({ x: today, y: s.startLevel, color: PACE.history, label: "Today" });
    }
    planChart.domain = null;
    planChart.update({ series, markers, hlines: [{ y: s.goalLevel, label: `Level ${s.goalLevel}` }] });
    planChart.reset_.hidden = true;
  }

  // ── Players ──────────────────────────────────────────────────
  let player = null;
  const compare = [];
  const cache = new Map();
  const ERRORS = {
    not_found: "No replays for that registered player.",
    private: "That player keeps their level private.",
    unavailable: "Replay stats can't be loaded right now.",
  };
  const playerXp = (p) => (p.xp != null ? p.xp : p.xp_floor);

  async function fetchPlayer(name) {
    const key = name.trim().toLowerCase();
    if (cache.has(key)) return cache.get(key);
    const r = await fetch(`${C.player_url}?name=${encodeURIComponent(name.trim())}`, { headers: { Accept: "application/json" } });
    const res = await r.json().catch(() => ({ ok: false, error: "unavailable" }));
    if (!res.ok) throw new Error(ERRORS[res.error] || ERRORS.unavailable);
    cache.set(key, res.data);
    return res.data;
  }

  async function loadPlayer(name, { keepGoal = false } = {}) {
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
    const avatar = $("[data-player-initials]");
    avatar.textContent = player.username.trim().slice(0, 2).toUpperCase();
    // Their worn skin over the initials; `skin` is a same-site path from the server.
    const skin = typeof player.skin === "string" && player.skin.startsWith("/player/") ? player.skin : null;
    avatar.classList.toggle("pv-initials--skin", Boolean(skin));
    if (skin) avatar.style.setProperty("--skin", `url("${skin}")`);
    else avatar.style.removeProperty("--skin");
    const link = $("[data-player-link]");
    link.textContent = player.username;
    link.href = profileUrl(player.username);
    $("[data-player-facts]").textContent = player.created
      ? `Account made ${player.created_extrapolated ? "around" : "≈"} ${fmtMonth.format(parseDay(player.created))} · ID ${num(player.bonk_id)}`
      : "Account date unknown";
    $("[data-player-level]").textContent = player.level ?? "—";
    $("[data-player-xp-label]").textContent = player.xp != null ? "XP" : "XP (at least)";
    $("[data-player-xp]").textContent = player.xp_floor != null ? num(playerXp(player)) : "—";
    $("[data-player-pace]").textContent = !player.pace ? "—"
      : player.pace.levels > 0 ? `+${player.pace.levels} level${player.pace.levels === 1 ? "" : "s"}` : "No level-ups";

    const historyBtn = $("[data-plan-view] [data-view=history]");
    historyBtn.disabled = !(player.series && player.series.length);
    if (player.level) {
      plan.startXp.value = playerXp(player);
      plan.startLevel.value = player.level;
      startXpTyped = player.xp != null;
      if (!keepGoal || !readInt(plan.goalLevel)) {
        const goal = Math.floor(player.level / 50) * 50 + 50;
        plan.goalLevel.value = goal;
        plan.goalXp.value = xpFor(goal);
      }
      if (player.pace && player.pace.wins_per_day > 0) {
        plan.pace.value = String(Math.min(180, Math.max(1, Math.round(player.pace.wins_per_day))));
        window.BVControls && window.BVControls.fill(plan.pace);
      }
    }
    if (player.bonk_id) { $("[data-dbid-input]").value = player.bonk_id; }
    addCompare(player);
    update();
    const url = new URL(window.location.href);
    url.searchParams.set("player", player.username);
    history.replaceState(null, "", url);
  }
  $("[data-load-form]").addEventListener("submit", (e) => {
    e.preventDefault();
    const name = $("[data-load-input]").value.trim();
    if (name) loadPlayer(name);
  });

  // ── Compare ──────────────────────────────────────────────────
  let cmpView = "level";
  const cmpChart = BVChart.line($("[data-cmp-chart]"), {
    xType: "time", height: 440, zoom: true, series: [],
    label: "Players' levels over time",
    emptyText: "Add players to compare their levels over time.",
  });
  segment($("[data-cmp-view]"), (b) => { cmpView = b.dataset.view; renderCompare(); });

  function addCompare(p) {
    if (!compare.some((c) => c.username.toLowerCase() === p.username.toLowerCase())) {
      if (compare.length >= 4) compare.shift();
      compare.push(p);
    }
    renderCompare();
  }
  $("[data-cmp-form]").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = $("[data-cmp-input]");
    const name = input.value.trim();
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

  function renderCompare() {
    $("[data-cmp-chips]").replaceChildren(...compare.map((p, i) => {
      const li = document.createElement("li");
      li.className = "xc-chip";
      li.style.setProperty("--c", COLORS[i]);
      const a = document.createElement("a");
      a.href = profileUrl(p.username);
      a.textContent = p.username;
      const x = document.createElement("button");
      x.type = "button";
      x.className = "xc-chip__x";
      x.setAttribute("aria-label", `Remove ${p.username}`);
      x.textContent = "×";
      x.addEventListener("click", () => { compare.splice(i, 1); renderCompare(); });
      li.append(a, x);
      return li;
    }));
    const xp = cmpView === "xp";
    cmpChart.update({
      series: compare.map((p, i) => ({
        name: p.username, color: COLORS[i], step: true, extend: false,
        points: (p.series || []).map(([d, l]) => [parseDay(d), xp ? xpFor(l) : l]),
      })),
      yFormat: xp ? undefined : (v) => `${Math.round(v)}`,
      tipValue: xp ? (v) => `≥ ${num(v)} XP` : (v) => `Level ${Math.round(v)}`,
    });
    renderCompareTable();
  }

  function renderCompareTable() {
    const table = $("[data-cmp-table]");
    table.hidden = compare.length === 0;
    const goal = readInt(plan.goalLevel);
    $("[data-cmp-goal-label]").textContent = goal ? `level ${goal}` : "goal";
    $("[data-cmp-rows]").replaceChildren(...compare.map((p, i) => {
      const tr = document.createElement("tr");
      const name = document.createElement("td");
      const sw = document.createElement("span");
      sw.className = "xc-sw";
      sw.style.setProperty("--c", COLORS[i]);
      const a = document.createElement("a");
      a.href = profileUrl(p.username);
      a.textContent = p.username;
      name.append(sw, a);
      let eta = "—";
      if (goal && p.level) {
        const need = xpFor(goal) - playerXp(p);
        if (need <= 0) eta = "Already there";
        else if (p.pace && p.pace.xp_per_day > 0) eta = `≈ ${when(Math.ceil(need / p.pace.xp_per_day))}`;
        else eta = "No recent level-ups";
      }
      const cells = [
        name, p.level ?? "—",
        p.xp != null ? num(p.xp) : p.xp_floor != null ? `≥ ${num(p.xp_floor)}` : "—",
        p.created ? `${p.created_extrapolated ? "around " : ""}${fmtMonth.format(parseDay(p.created))}` : "Unknown",
        p.pace ? (p.pace.levels_per_day * 30).toFixed(1) : "—",
        eta,
      ];
      cells.forEach((c, k) => {
        const td = c instanceof Node ? c : document.createElement("td");
        if (!(c instanceof Node)) td.textContent = String(c);
        if (k === 1 || k === 2 || k === 4) td.classList.add("pv-num");
        tr.append(td);
      });
      return tr;
    }));
  }

  // ── Level spread ─────────────────────────────────────────────
  let spread = null;
  let bucket = 10;
  let scale = "linear";
  const spreadChart = BVChart.bars($("[data-spread-chart]"), { bars: [], height: 440, label: "Players by level" });
  segment($("[data-spread-bucket]"), (b) => { bucket = Number(b.dataset.bucket); renderSpread(); });
  segment($("[data-spread-scale]"), (b) => { scale = b.dataset.scale; renderSpread(); });

  function percentileLevel(levels, total, q) {
    let run = 0;
    for (const [lv, n] of levels) { run += n; if (run / total >= q) return lv; }
    return levels.length ? levels[levels.length - 1][0] : null;
  }

  function renderSpread() {
    if (!spread) return;
    const levels = spread.levels;
    const total = levels.reduce((a, [, n]) => a + n, 0);
    const you = readInt(plan.startLevel);
    let below = 0;
    for (const [lv, n] of levels) if (you && lv < you) below += n;
    const pct = total ? (below / total) * 100 : 0;
    $("[data-spread-headline]").textContent = you
      ? `Level ${you} is higher than ${pct >= 99 ? pct.toFixed(2) : pct.toFixed(1)}% of players seen in replays.`
      : "Enter a level in Plan a goal (or load a player) to see where it stands.";
    $("[data-spread-stats]").hidden = false;
    $("[data-spread-players]").textContent = num(total);
    $("[data-spread-median]").textContent = `Level ${percentileLevel(levels, total, 0.5)}`;
    $("[data-spread-p90]").textContent = `Level ${percentileLevel(levels, total, 0.9)}`;
    $("[data-spread-p99]").textContent = `Level ${percentileLevel(levels, total, 0.99)}`;

    const buckets = new Map();
    let maxLv = 0;
    for (const [lv, n] of levels) {
      const b = Math.floor((lv - 1) / bucket) * bucket + 1;
      buckets.set(b, (buckets.get(b) || 0) + n);
      maxLv = Math.max(maxLv, lv);
    }
    const bars = [];
    let run = 0, here = -1;
    for (let b = 1; b <= maxLv; b += bucket) {
      const n = buckets.get(b) || 0;
      const hi = b + bucket - 1;
      const highlight = Boolean(you && you >= b && you <= hi);
      if (highlight) here = bars.length;
      bars.push({
        label: String(b), value: n, highlight,
        tip: {
          title: `Levels ${b}–${hi}`,
          rows: [
            { label: "Players", value: num(n) },
            { label: "Share of all", value: `${total ? ((n / total) * 100).toFixed(n / total < 0.001 ? 3 : 2) : 0}%` },
            { label: "Higher than", value: `${total ? ((run / total) * 100).toFixed(1) : 0}%` },
          ],
        },
      });
      run += n;
    }
    spreadChart.update({
      bars, yScale: scale,
      labelAt: (b, i) => i % Math.max(1, Math.round(50 / bucket)) === 0,
      markers: here >= 0 ? [{ index: here, label: `Level ${you}` }] : [],
    });
  }
  fetch(C.levels_url, { headers: { Accept: "application/json" } })
    .then((r) => r.json())
    .then((res) => { if (!res.ok) throw new Error(res.error); spread = res.data; renderSpread(); })
    .catch(() => { $("[data-spread-headline]").textContent = "The level spread can't be loaded right now."; });

  // ── Account age ──────────────────────────────────────────────
  const points = C.dbid_points.map(([n, d]) => [n, parseDay(d)]);
  function dbidDate(id) {
    if (!(id >= 1)) return null;
    for (let i = 0; i < points.length - 1; i++) {
      const [n0, t0] = points[i], [n1, t1] = points[i + 1];
      if (id >= n0 && id <= n1) return { t: t0 + ((t1 - t0) * (id - n0)) / Math.max(1, n1 - n0), extrapolated: false };
    }
    const [n0, t0] = points[points.length - 2], [n1, t1] = points[points.length - 1];
    const t = t0 + ((t1 - t0) * (id - n0)) / (n1 - n0);
    return { t: Math.max(t1, Math.min(t, today)), extrapolated: true };
  }
  function idAt(t) {
    if (t <= points[0][1]) return points[0][0];
    for (let i = 0; i < points.length - 1; i++) {
      const [n0, t0] = points[i], [n1, t1] = points[i + 1];
      if (t >= t0 && t <= t1) return n0 + ((n1 - n0) * (t - t0)) / Math.max(1, t1 - t0);
    }
    return points[points.length - 1][0];
  }

  let ageView = "timeline";
  const ageEl = $("[data-age-chart]");
  let ageChart = null;
  segment($("[data-age-view]"), (b) => { ageView = b.dataset.view; renderAge(); });
  $("[data-dbid-input]").addEventListener("input", renderAge);

  function renderAge() {
    const id = readInt($("[data-dbid-input]"));
    const est = id ? dbidDate(id) : null;
    if (est) {
      const years = (today - est.t) / (365.25 * DAY);
      $("[data-dbid-date]").textContent = `${est.extrapolated ? "Around " : ""}${fmtDay.format(est.t)}`;
      $("[data-dbid-age]").textContent = years >= 1 ? `About ${years.toFixed(1)} years old` : `About ${Math.max(0, Math.round(years * 12))} months old`;
    } else {
      $("[data-dbid-date]").textContent = "—";
      $("[data-dbid-age]").textContent = "Type an account ID to date it.";
    }
    if (ageView === "timeline") {
      const markers = compare.filter((p) => p.created && p.bonk_id).map((p) => ({
        x: parseDay(p.created), y: p.bonk_id, color: COLORS[compare.indexOf(p)], label: p.username,
      }));
      if (est && !compare.some((p) => p.bonk_id === id)) markers.push({ x: est.t, y: id, color: "var(--site-series-3)", label: `#${num(id)}` });
      const opts = {
        xType: "time", height: 420, zoom: true, label: "Account IDs by date",
        series: [{ name: "Accounts made then", color: "var(--site-series-1)", points: points.map(([n, t]) => [t, n]), area: true }],
        markers, yFloor: 0,
        tipValue: (v) => `ID ≈ ${num(v)}`,
      };
      if (!ageChart || ageChart.kind !== "line") { ageChart = BVChart.line(ageEl, opts); ageChart.kind = "line"; }
      else ageChart.update(opts);
    } else {
      const y0 = new Date(points[0][1]).getFullYear(), y1 = new Date(today).getFullYear();
      const bars = [];
      for (let y = y0; y <= y1; y++) {
        const a = new Date(y, 0, 1).getTime(), b = Math.min(new Date(y + 1, 0, 1).getTime(), today);
        const made = Math.max(0, Math.round(idAt(b) - idAt(a)));
        bars.push({
          label: String(y), value: made, highlight: est ? new Date(est.t).getFullYear() === y : false,
          tip: { title: String(y) + (y === y1 ? " (so far)" : ""), rows: [{ label: "New accounts", value: `≈ ${num(made)}` }] },
        });
      }
      const opts = { bars, height: 420, label: "New accounts a year", labelAt: (b, i) => i % 2 === 0 || bars.length < 10 };
      if (!ageChart || ageChart.kind !== "bars") { ageChart = BVChart.bars(ageEl, opts); ageChart.kind = "bars"; }
      else ageChart.update(opts);
    }
  }

  // ── Everything that depends on the plan inputs ───────────────
  function update() {
    renderPlan();
    renderSpread();
    renderCompare();
    renderAge();
  }

  const prefill = root.dataset.prefillPlayer;
  const prefillGoal = parseInt(root.dataset.prefillGoal, 10);
  update();
  if (prefillGoal > 0) setGoal(prefillGoal);
  if (prefill) {
    $("[data-load-input]").value = prefill;
    loadPlayer(prefill, { keepGoal: prefillGoal > 0 });
  }
})();
