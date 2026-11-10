// ==UserScript==
// @name         bonk.io Rate-Limit Lab
// @namespace    https://bonkverse.io/
// @version      1.2.0
// @description  Runs a fixed, timed set of bonk.io login experiments (wrong-password speed, whether a success resets the count, how long a block lasts, whether retrying extends it) and logs every request to the millisecond. Passwords stay in local Tampermonkey storage and never appear in the log or export.
// @author       Bonkverse
// @match        https://bonk.io/
// @match        https://bonk.io/index.html
// @noframes
// @run-at       document-idle
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_setClipboard
// @grant        unsafeWindow
// ==/UserScript==

/*
 * What it does
 * - Sends login requests to bonk2.io/scripts/login_legacy.php itself, from the
 *   bonk.io page, exactly the way bonk.io's own login does (and the way
 *   Bonkverse's server does), on a fixed schedule.
 * - Every experiment starts on a NEW public IP. When one is needed, the panel
 *   asks you to switch VPN location, checks your IP every 2 s, and starts on
 *   its own once it sees an IP it hasn't used before (stable for 2 checks).
 *   If the IP changes in the middle of an experiment, that experiment is
 *   marked invalid and the protocol moves on.
 * - Each request is logged with: experiment, IP, account, whether the password
 *   was the correct one or the fake one, planned time, send time, answer time,
 *   bonk.io's answer. The password itself is never logged.
 *
 * Keep the tab VISIBLE while it runs (not minimized, not a background tab).
 * Browsers slow down timers in hidden tabs, which would wreck the timing. The
 * log has a "late" column (send time minus planned time) so any slip shows.
 *
 * Disable the "bonk.io Login Rate-Limit Logger" script while this runs, or it
 * will log the same requests a second time.
 */

(function () {
  "use strict";

  const W = unsafeWindow;
  const pageFetch = W.fetch.bind(W);
  const LOGIN_URL = "https://bonk2.io/scripts/login_legacy.php";
  // Remember-me login: bonk.io's own client posts {rememberToken} here
  // (seen in bonk.io's alpha2s.js, 2026-11-10).
  const AUTO_URL = "https://bonk2.io/scripts/login_auto.php";
  const IPIFY = "https://api.ipify.org?format=json";

  const KEYS = {
    config: "lab_config", // accounts + passwords: local only, never exported
    log: "lab_log",
    usedIps: "lab_used_ips",
    results: "lab_results",
  };

  const MIN = 60 * 1000;

  // ── The protocol ──────────────────────────────────────────────
  //
  // trip: send wrong passwords every `interval` ms until bonk.io says
  //       "ratelimited" (stops at the first one, so no extra requests are sent
  //       into the block) or `max` tries.
  // probe "once": after the trip, wait `after` ms, then ONE correct login with
  //       a different account. Measures the block without touching it.
  // probe "every": correct login with a different account every `every` ms
  //       until it works (max `max` ms). Compare with the "once" results to see
  //       whether retrying during a block makes it last longer.
  // pattern: a fixed sequence of W (wrong) / S (correct, same account) at
  //       `interval` ms, stopping at the first "ratelimited".
  // pre + wait: before the trip, send `pre.count` wrong passwords, then send
  //       nothing for `wait` ms. The trip after it shows how many wrong
  //       passwords bonk.io still remembered: 1 more = it remembered all of
  //       them, 4 more = it forgot them.
  const PROTOCOL = [
    { id: "speed-0.5s", what: "Wrong passwords every 0.5 s", trip: { interval: 500, max: 40 } },
    { id: "speed-1s", what: "Wrong passwords every 1 s", trip: { interval: 1000, max: 40 } },
    { id: "speed-2s", what: "Wrong passwords every 2 s", trip: { interval: 2000, max: 40 } },
    { id: "speed-3s", what: "Wrong passwords every 3 s", trip: { interval: 3000, max: 40 } },
    { id: "speed-5s", what: "Wrong passwords every 5 s", trip: { interval: 5000, max: 40 } },
    {
      id: "unknown-user-1s",
      what: "A username that doesn't exist, every 1 s",
      trip: { interval: 1000, max: 40, unknownUser: true },
    },
    {
      id: "success-reset-1s",
      what: "W W S W W S W W S W W W W W W at 1 s (S = correct password, same account)",
      pattern: { seq: "WWSWWSWWSWWWWWW", interval: 1000 },
    },
    {
      id: "hold-5min",
      what: "Trip fast, then ONE correct login (other account) after 5 min",
      trip: { interval: 500, max: 40 },
      probe: { mode: "once", after: 5 * MIN },
    },
    {
      id: "hold-10min",
      what: "Trip fast, then ONE correct login after 10 min",
      trip: { interval: 500, max: 40 },
      probe: { mode: "once", after: 10 * MIN },
    },
    {
      id: "hold-15min",
      what: "Trip fast, then ONE correct login after 15 min",
      trip: { interval: 500, max: 40 },
      probe: { mode: "once", after: 15 * MIN },
    },
    {
      id: "hold-20min",
      what: "Trip fast, then ONE correct login after 20 min",
      trip: { interval: 500, max: 40 },
      probe: { mode: "once", after: 20 * MIN },
    },
    {
      id: "retry-every-1min",
      what: "Trip fast, then a correct login every 1 min until it works (max 45 min)",
      trip: { interval: 500, max: 40 },
      probe: { mode: "every", every: 1 * MIN, max: 45 * MIN },
    },
    // How long bonk.io remembers wrong passwords (added 2026-11-10, after the
    // first run showed the limit is 4 wrong passwords per IP).
    ...[5, 15, 30, 60].map((m) => ({
      id: `memory-${m}min`,
      what: `3 wrong, nothing for ${m} min, then wrong every 1 s until limited`,
      pre: { count: 3, interval: 1000 },
      wait: m * MIN,
      trip: { interval: 1000, max: 10 },
    })),
    // Remember-me tokens (added 2026-11-10): can junk tokens sent to
    // login_auto.php use up an IP's budget, and is login_auto.php blocked
    // along with login_legacy.php? Decides how an extension login can be
    // checked on the server.
    {
      id: "tokens-alone-1s",
      what: "A made-up remember-me token to login_auto.php every 1 s",
      trip: { interval: 1000, max: 20, tokens: true },
    },
    {
      id: "tokens-then-wrong",
      what: "3 made-up tokens, then wrong passwords every 1 s until limited",
      pre: { count: 3, interval: 1000, tokens: true },
      wait: 1000,
      trip: { interval: 1000, max: 10 },
    },
    {
      id: "token-during-block",
      what: "Trip with wrong passwords, then one made-up token to login_auto.php",
      trip: { interval: 1000, max: 40 },
      after: { tokens: 1, delay: 3000 },
    },
  ];

  // ── Storage ───────────────────────────────────────────────────

  const get = (k, d) => {
    const v = GM_getValue(k, d);
    return v == null ? d : v;
  };
  const set = (k, v) => GM_setValue(k, v);

  function config() {
    const c = get(KEYS.config, null) || {};
    return {
      accounts: Array.isArray(c.accounts) ? c.accounts : [],
      wrongPassword: c.wrongPassword || "",
    };
  }
  const usableAccounts = () => config().accounts.filter((a) => a.username && a.password);

  function appendLog(entry) {
    const log = get(KEYS.log, []);
    log.push(entry);
    set(KEYS.log, log);
    ui.addRow(entry);
  }

  function saveResult(result) {
    const results = get(KEYS.results, {});
    results[result.id] = result;
    set(KEYS.results, results);
    ui.renderResults();
  }

  // ── Run state ─────────────────────────────────────────────────

  const state = { running: false, stop: false, currentIp: null, expIp: null };

  class Stopped extends Error {}
  class IpChanged extends Error {}

  function sleepUntil(ts, label) {
    return new Promise((resolve, reject) => {
      const tick = () => {
        if (state.stop) return reject(new Stopped());
        const left = ts - Date.now();
        if (label) ui.countdown(label, left);
        if (left <= 0) return resolve();
        setTimeout(tick, Math.min(left, 250));
      };
      tick();
    });
  }
  const sleep = (ms, label) => sleepUntil(Date.now() + ms, label);

  // ── Network ───────────────────────────────────────────────────

  async function publicIp() {
    try {
      const res = await pageFetch(IPIFY, { cache: "no-store", credentials: "omit" });
      const data = await res.json();
      return data && data.ip ? data.ip : null;
    } catch (e) {
      return null;
    }
  }

  // One login_legacy.php call, the same three fields bonk.io's client sends.
  async function bonkLogin(username, password) {
    return bonkPost(LOGIN_URL, { username, password, remember: "false" });
  }

  // A made-up remember-me token: 32 random hex characters.
  function fakeToken() {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  }

  async function bonkPost(url, fields) {
    const body = new URLSearchParams(fields);
    const sent = Date.now();
    let status = 0;
    let text = "";
    let netError = "";
    try {
      const res = await pageFetch(url, {
        method: "POST",
        body,
        credentials: "omit",
        cache: "no-store",
      });
      status = res.status;
      text = await res.text();
    } catch (e) {
      netError = String((e && e.message) || e);
    }
    const recv = Date.now();
    let result = "no_json";
    let error = netError || `http ${status}`;
    try {
      const data = JSON.parse(text);
      if (data && data.r === "success") {
        result = "success";
        error = "";
      } else if (data) {
        result = "fail";
        error = String(data.e || data.error || data.r || "?");
      }
    } catch (e) {
      /* keep no_json */
    }
    // `text` (which holds the token on success) is dropped here on purpose.
    return { sent, recv, status, result, error };
  }

  // Sends one request at `planned` and logs it. Checks the IP hasn't moved.
  // pwKind: "correct" / "wrong" password on login_legacy.php, or "fake token"
  // on login_auto.php (account is then just a label).
  async function request(exp, step, account, pwKind, planned) {
    await sleepUntil(planned);
    let r;
    if (pwKind === "fake token") {
      r = await bonkPost(AUTO_URL, { rememberToken: fakeToken() });
    } else {
      const password = pwKind === "correct" ? account.password : config().wrongPassword;
      r = await bonkLogin(account.username, password);
    }
    const entry = {
      exp: exp.id,
      step,
      ip: state.expIp,
      account: account.username,
      pw: pwKind,
      planned: new Date(planned).toISOString(),
      sent: new Date(r.sent).toISOString(),
      late_ms: r.sent - planned,
      rtt_ms: r.recv - r.sent,
      result: r.result,
      error: r.error,
      status: r.status,
      hidden: document.hidden,
    };
    appendLog(entry);
    return { ...r, entry };
  }

  async function assertSameIp() {
    const ip = await publicIp();
    if (ip && ip !== state.expIp) throw new IpChanged(`${state.expIp} → ${ip}`);
  }

  // ── Fresh-IP gate ─────────────────────────────────────────────

  async function waitForFreshIp(exp) {
    const used = get(KEYS.usedIps, {});
    let candidate = null;
    let seen = 0;
    for (;;) {
      if (state.stop) throw new Stopped();
      const ip = await publicIp();
      state.currentIp = ip;
      ui.ip(ip);
      if (ip && !used[ip]) {
        seen = ip === candidate ? seen + 1 : 1;
        candidate = ip;
        if (seen >= 2) break; // same new IP on two checks in a row
        ui.status(`New IP ${ip} found for ${exp.id}; confirming…`, "go");
      } else {
        candidate = null;
        seen = 0;
        ui.status(
          `▶ Switch VPN to a NEW location for "${exp.id}". ` +
            (ip ? `${ip} was already used.` : "Couldn't read your IP."),
          "warn"
        );
      }
      await sleep(2000);
    }
    used[candidate] = new Date().toISOString();
    set(KEYS.usedIps, used);
    state.expIp = candidate;
  }

  // ── Experiments ───────────────────────────────────────────────

  function pickAccounts(index) {
    const accounts = usableAccounts();
    const tripper = accounts[index % accounts.length];
    const prober = accounts[(index + 1) % accounts.length];
    return { tripper, prober };
  }

  // 8 random hex characters for a username nobody has registered.
  function randomTag() {
    const bytes = new Uint8Array(4);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  }

  // Requests go out on schedule without waiting for the previous answer
  // (over a VPN an answer can take longer than the interval). Once any answer
  // says "ratelimited", nothing new is sent; requests already in flight finish.
  async function runTrip(exp, account) {
    const { interval, max, unknownUser } = exp.trip;
    const user = unknownUser
      ? { username: `bvlab_nouser_${randomTag()}`, password: "" }
      : account;
    const start = Date.now() + 1000;
    let limited = false;
    const inFlight = [];
    for (let i = 0; i < max; i++) {
      await sleepUntil(start + i * interval);
      if (limited) break;
      inFlight.push(
        request(exp, "trip", user, exp.trip.tokens ? "fake token" : "wrong", start + i * interval).then((r) => {
          if (r.error === "ratelimited") limited = true;
          return r;
        })
      );
    }
    const answers = (await Promise.all(inFlight)).sort((a, b) => a.sent - b.sent);
    const first = answers.find((r) => r.error === "ratelimited");
    // In token mode every answer that isn't "ratelimited" counts as a try.
    const counted = (r) =>
      exp.trip.tokens ? r.error !== "ratelimited" : r.error === "password" || r.error === "username_fail";
    const wrongBefore = answers.filter((r) => counted(r) && (!first || r.sent < first.sent)).length;
    return {
      limited: Boolean(first),
      wrongBefore,
      tripAt: first ? first.sent : null,
      firstAt: start,
      triesSent: answers.length,
    };
  }

  async function runPattern(exp, account) {
    const { seq, interval } = exp.pattern;
    const start = Date.now() + 1000;
    const steps = [];
    for (let i = 0; i < seq.length; i++) {
      const kind = seq[i] === "S" ? "correct" : "wrong";
      const r = await request(exp, `pattern ${i + 1}/${seq.length} (${seq[i]})`, account, kind, start + i * interval);
      steps.push(seq[i] + ":" + (r.error || "ok"));
      if (r.error === "ratelimited") {
        return { limitedAtStep: i + 1, sequence: steps.join(" ") };
      }
    }
    return { limitedAtStep: null, sequence: steps.join(" ") };
  }

  async function runProbe(exp, prober, tripAt) {
    const p = exp.probe;
    if (p.mode === "once") {
      const at = tripAt + p.after;
      // Check the IP a few seconds early so the check doesn't delay the probe.
      await sleepUntil(at - 5000, `${exp.id}: one correct login in`);
      await assertSameIp();
      const r = await request(exp, `probe once +${p.after / MIN}min`, prober, "correct", at);
      return { probeOk: r.result === "success", probeError: r.error, probeAfterMin: p.after / MIN };
    }
    const deadline = tripAt + p.max;
    for (let n = 1; ; n++) {
      const at = tripAt + n * p.every;
      if (at > deadline) return { unblockedAfterMin: null, probes: n - 1 };
      await sleepUntil(at - 5000, `${exp.id}: retry #${n} in`);
      await assertSameIp();
      const r = await request(exp, `retry #${n}`, prober, "correct", at);
      if (r.result === "success") {
        return { unblockedAfterMin: +((r.sent - tripAt) / MIN).toFixed(2), probes: n };
      }
    }
  }

  // The wrong passwords before a memory experiment's wait, one at a time.
  async function runPre(exp, account) {
    const { count, interval, tokens } = exp.pre;
    const start = Date.now() + 1000;
    let wrong = 0;
    const answers = [];
    for (let i = 0; i < count; i++) {
      const kind = tokens ? "fake token" : "wrong";
      const r = await request(exp, `before wait ${i + 1}/${count}`, account, kind, start + i * interval);
      answers.push(r.error || r.result);
      if (r.error === "ratelimited") return { wrong, limited: true, lastAt: r.sent, answers };
      if (tokens || r.error === "password") wrong++;
    }
    return { wrong, limited: false, lastAt: Date.now(), answers };
  }

  async function runExperiment(exp, index) {
    await waitForFreshIp(exp);
    const { tripper, prober } = pickAccounts(index);
    ui.status(`Running ${exp.id} on ${state.expIp}: ${exp.what}`, "go");
    const result = { id: exp.id, what: exp.what, ip: state.expIp, startedAt: new Date().toISOString() };
    try {
      if (exp.pattern) {
        Object.assign(result, await runPattern(exp, tripper));
      } else {
        if (exp.pre) {
          const pre = await runPre(exp, tripper);
          result.wrongBeforeWait = pre.wrong;
          result.preAnswers = pre.answers.join(" ");
          if (pre.limited) throw new Error(`${exp.id}: limited before the wait (IP already used?)`);
          await sleepUntil(pre.lastAt + exp.wait - 5000, `${exp.id}: quiet wait, next request in`);
          await assertSameIp();
          await sleepUntil(pre.lastAt + exp.wait);
        }
        const trip = await runTrip(exp, tripper);
        Object.assign(result, {
          limited: trip.limited,
          triesSent: trip.triesSent,
          wrongBeforeLimit: trip.wrongBefore,
          secondsToLimit: trip.limited ? +((trip.tripAt - trip.firstAt) / 1000).toFixed(2) : null,
        });
        if (exp.after && trip.limited) {
          const at = trip.tripAt + exp.after.delay;
          const r = await request(exp, "token after block", tripper, "fake token", at);
          result.tokenAnswerDuringBlock = r.error || r.result;
        }
        if (exp.probe && trip.limited) {
          Object.assign(result, await runProbe(exp, prober, trip.tripAt));
        } else if (exp.probe) {
          result.note = "never limited, so no probe";
        }
      }
      result.valid = true;
    } catch (e) {
      if (e instanceof Stopped) throw e;
      result.valid = false;
      result.note =
        e instanceof IpChanged
          ? `IP changed mid-experiment (${e.message}); result discarded`
          : `${e.message}; result discarded`;
    }
    result.finishedAt = new Date().toISOString();
    saveResult(result);
  }

  async function runSelected(ids) {
    if (usableAccounts().length < 2) {
      alert("Add at least 2 accounts (5 is best) with their passwords first.");
      return;
    }
    if (!config().wrongPassword) {
      alert("Set the fake (wrong) password first.");
      return;
    }
    state.running = true;
    state.stop = false;
    ui.running(true);
    try {
      let i = 0;
      for (const exp of PROTOCOL.filter((e) => ids.includes(e.id))) {
        await runExperiment(exp, i++);
      }
      ui.status("Protocol finished. Export the results and send them over.", "go");
    } catch (e) {
      ui.status(e instanceof Stopped ? "Stopped." : `Error: ${e.message}`, "warn");
    } finally {
      state.running = false;
      ui.running(false);
      ui.countdown(null);
    }
  }

  // ── Export (no passwords, ever) ───────────────────────────────

  function exportJson() {
    return JSON.stringify(
      {
        exportedAt: new Date().toISOString(),
        protocol: PROTOCOL,
        accounts: usableAccounts().map((a) => a.username),
        results: get(KEYS.results, {}),
        log: get(KEYS.log, []),
      },
      null,
      2
    );
  }

  function exportCsv() {
    const cols = ["exp", "step", "ip", "account", "pw", "planned", "sent", "late_ms", "rtt_ms", "result", "error", "status", "hidden"];
    const esc = (v) => `"${String(v == null ? "" : v).replace(/"/g, '""')}"`;
    return [cols.join(",")]
      .concat(get(KEYS.log, []).map((e) => cols.map((c) => esc(e[c])).join(",")))
      .join("\n");
  }

  function download(name, text, type) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type }));
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  // ── UI ────────────────────────────────────────────────────────

  const CSS = `
    #lab { position: fixed; top: 8px; right: 8px; z-index: 2147483647; width: 560px;
      max-width: calc(100vw - 16px); max-height: calc(100vh - 16px); overflow: auto;
      background: rgba(20,28,36,.97); color: #ddd; border: 1px solid #009688; border-radius: 8px;
      font: 12px/1.4 ui-monospace, Menlo, Consolas, monospace; box-shadow: 0 4px 18px rgba(0,0,0,.5); }
    #lab.min > :not(.lab-head) { display: none; }
    #lab section { padding: 6px 8px; border-top: 1px solid #2c3a46; }
    #lab .lab-head { display: flex; gap: 6px; align-items: center; padding: 6px 8px; }
    #lab .lab-head b { color: #4dd0c4; margin-right: auto; }
    #lab button { background: #263440; color: #ddd; border: 1px solid #3b4d5c; border-radius: 4px;
      padding: 2px 8px; cursor: pointer; font: inherit; }
    #lab button:hover:not(:disabled) { border-color: #009688; }
    #lab button:disabled { opacity: .45; cursor: default; }
    #lab input[type=text], #lab input[type=password] { background: #0f171e; color: #ddd;
      border: 1px solid #3b4d5c; border-radius: 4px; padding: 2px 5px; font: inherit; width: 46%; }
    #lab .row { display: flex; gap: 6px; margin: 3px 0; align-items: center; }
    #lab label { display: block; margin: 2px 0; }
    #lab .status { padding: 6px 8px; font-weight: bold; }
    #lab .status.warn { color: #ffc107; } #lab .status.go { color: #81c784; }
    #lab .muted { color: #8fa3b3; }
    #lab table { width: 100%; border-collapse: collapse; }
    #lab td, #lab th { padding: 1px 5px; text-align: left; white-space: nowrap; }
    #lab th { color: #8fa3b3; position: sticky; top: 0; background: #1a2733; }
    #lab tr.rl td { color: #ff8a65; } #lab tr.ok td { color: #81c784; }
    #lab .scroll { max-height: 180px; overflow: auto; }
  `;

  const ui = (() => {
    const h = (tag, attrs, text) => {
      const n = document.createElement(tag);
      Object.assign(n, attrs || {});
      if (text != null) n.textContent = text;
      return n;
    };

    let root, statusEl, ipEl, countEl, resultsBody, logBody, startBtn, stopBtn, checks;

    function build() {
      document.head.appendChild(h("style", {}, CSS));
      root = h("div", { id: "lab" });

      const head = h("div", { className: "lab-head" });
      head.appendChild(h("b", {}, "bonk.io Rate-Limit Lab"));
      ipEl = h("span", { className: "muted" }, "IP …");
      head.appendChild(ipEl);
      const minBtn = h("button", {}, "–");
      minBtn.onclick = () => {
        root.classList.toggle("min");
        minBtn.textContent = root.classList.contains("min") ? "+" : "–";
      };
      head.appendChild(minBtn);
      root.appendChild(head);

      statusEl = h("div", { className: "status" }, "Set up accounts, pick experiments, press Start.");
      root.appendChild(statusEl);
      countEl = h("div", { className: "muted", style: "padding:0 8px 6px" });
      root.appendChild(countEl);

      // Accounts: saved locally only.
      const acc = h("section");
      acc.appendChild(h("div", { className: "muted" }, "Accounts (stay on this computer; never logged or exported)"));
      const cfg = config();
      const rows = [];
      for (let i = 0; i < 5; i++) {
        const a = cfg.accounts[i] || {};
        const row = h("div", { className: "row" });
        const u = h("input", { type: "text", placeholder: `account ${i + 1} username`, value: a.username || "" });
        const p = h("input", { type: "password", placeholder: "its real password", value: a.password || "" });
        row.append(u, p);
        acc.appendChild(row);
        rows.push([u, p]);
      }
      const wrongRow = h("div", { className: "row" });
      const wrong = h("input", { type: "password", placeholder: "fake (wrong) password for all", value: cfg.wrongPassword });
      wrongRow.appendChild(wrong);
      const save = h("button", {}, "Save");
      save.onclick = () => {
        set(KEYS.config, {
          accounts: rows.map(([u, p]) => ({ username: u.value.trim(), password: p.value })),
          wrongPassword: wrong.value,
        });
        save.textContent = "Saved";
        setTimeout(() => (save.textContent = "Save"), 1200);
      };
      const forget = h("button", {}, "Forget passwords");
      forget.onclick = () => {
        if (!confirm("Remove the saved passwords from this browser?")) return;
        set(KEYS.config, { accounts: rows.map(([u]) => ({ username: u.value.trim(), password: "" })), wrongPassword: "" });
        rows.forEach(([, p]) => (p.value = ""));
        wrong.value = "";
      };
      wrongRow.append(save, forget);
      acc.appendChild(wrongRow);
      root.appendChild(acc);

      // Protocol picker.
      const proto = h("section");
      proto.appendChild(h("div", { className: "muted" }, "Experiments (each on its own new IP), in order:"));
      const done = get(KEYS.results, {});
      checks = PROTOCOL.map((e) => {
        // Experiments that already have a valid result start unticked.
        const cb = h("input", { type: "checkbox", checked: !(done[e.id] && done[e.id].valid) });
        const label = h("label");
        label.append(cb, ` ${e.id} `, h("span", { className: "muted" }, `— ${e.what}`));
        proto.appendChild(label);
        return [e.id, cb];
      });
      const ctl = h("div", { className: "row" });
      startBtn = h("button", {}, "Start");
      startBtn.onclick = () => runSelected(checks.filter(([, cb]) => cb.checked).map(([id]) => id));
      stopBtn = h("button", { disabled: true }, "Stop");
      stopBtn.onclick = () => (state.stop = true);
      const forgetIps = h("button", {}, "Forget used IPs");
      forgetIps.onclick = () => confirm("Allow reusing IPs from earlier runs?") && set(KEYS.usedIps, {});
      ctl.append(startBtn, stopBtn, forgetIps);
      proto.appendChild(ctl);
      proto.appendChild(
        h(
          "div",
          { className: "muted" },
          "Rough time: memory ones about 2 h, token ones a few minutes. Keep this tab visible."
        )
      );
      root.appendChild(proto);

      // Results.
      const res = h("section");
      res.appendChild(h("div", { className: "muted" }, "Results"));
      const rt = h("table");
      rt.innerHTML = "<thead><tr><th>experiment</th><th>IP</th><th>outcome</th></tr></thead>";
      resultsBody = h("tbody");
      rt.appendChild(resultsBody);
      res.appendChild(rt);
      const exp = h("div", { className: "row" });
      const bJson = h("button", {}, "Export JSON");
      bJson.onclick = () => download(`bonk-ratelimit-lab-${Date.now()}.json`, exportJson(), "application/json");
      const bCsv = h("button", {}, "Export CSV");
      bCsv.onclick = () => download(`bonk-ratelimit-lab-${Date.now()}.csv`, exportCsv(), "text/csv");
      const bCopy = h("button", {}, "Copy JSON");
      bCopy.onclick = () => GM_setClipboard(exportJson(), "text");
      const bClear = h("button", {}, "Clear results");
      bClear.onclick = () => {
        if (!confirm("Clear all results and the request log?")) return;
        set(KEYS.results, {});
        set(KEYS.log, []);
        renderResults();
        logBody.textContent = "";
      };
      exp.append(bJson, bCsv, bCopy, bClear);
      res.appendChild(exp);
      root.appendChild(res);

      // Request log.
      const lg = h("section");
      lg.appendChild(h("div", { className: "muted" }, "Requests (newest first)"));
      const wrap = h("div", { className: "scroll" });
      const lt = h("table");
      lt.innerHTML =
        "<thead><tr><th>sent</th><th>exp</th><th>step</th><th>account</th><th>pw</th><th>answer</th><th>late</th><th>rtt</th></tr></thead>";
      logBody = h("tbody");
      lt.appendChild(logBody);
      wrap.appendChild(lt);
      lg.appendChild(wrap);
      root.appendChild(lg);

      document.body.appendChild(root);
      get(KEYS.log, []).slice(-200).forEach(addRow);
      renderResults();
      publicIp().then((ip) => ui.ip(ip));
      document.addEventListener("visibilitychange", () => {
        if (document.hidden && state.running) {
          console.warn("[bonk lab] tab hidden: timing may slip");
        }
      });
    }

    function time(iso) {
      const d = new Date(iso);
      return `${d.toLocaleTimeString([], { hour12: false })}.${String(d.getMilliseconds()).padStart(3, "0")}`;
    }

    function addRow(e) {
      if (!logBody) return;
      const tr = h("tr", { className: e.error === "ratelimited" ? "rl" : e.result === "success" ? "ok" : "" });
      [time(e.sent), e.exp, e.step, e.account, e.pw, e.error || e.result, `${e.late_ms}ms`, `${e.rtt_ms}ms`].forEach(
        (v) => tr.appendChild(h("td", {}, String(v)))
      );
      logBody.prepend(tr);
    }

    function describe(r) {
      if (r.valid === false) return r.note;
      const parts = [];
      if ("wrongBeforeWait" in r) parts.push(`${r.wrongBeforeWait} before (${r.preAnswers || ""}), then`);
      if ("tokenAnswerDuringBlock" in r) parts.push(`token during block: ${r.tokenAnswerDuringBlock}`);
      if (r.limited === false) parts.push(`never limited (${r.wrongBeforeLimit} wrong)`);
      if (r.limited) parts.push(`limited after ${r.wrongBeforeLimit} wrong in ${r.secondsToLimit}s`);
      if (r.sequence) parts.push(r.limitedAtStep ? `limited at step ${r.limitedAtStep}` : "never limited");
      if ("probeOk" in r) parts.push(`after ${r.probeAfterMin} min: ${r.probeOk ? "UNBLOCKED" : "still " + r.probeError}`);
      if ("unblockedAfterMin" in r)
        parts.push(r.unblockedAfterMin ? `unblocked after ${r.unblockedAfterMin} min (${r.probes} retries)` : `still blocked after ${r.probes} retries`);
      if (r.note) parts.push(r.note);
      return parts.join("; ");
    }

    function renderResults() {
      if (!resultsBody) return;
      resultsBody.textContent = "";
      const results = get(KEYS.results, {});
      for (const exp of PROTOCOL) {
        const r = results[exp.id];
        if (!r) continue;
        const tr = h("tr");
        [exp.id, r.ip, describe(r)].forEach((v) => tr.appendChild(h("td", {}, v)));
        resultsBody.appendChild(tr);
      }
    }

    return {
      build,
      addRow,
      renderResults,
      status(text, kind) {
        statusEl.textContent = text;
        statusEl.className = `status ${kind || ""}`;
      },
      ip(ip) {
        ipEl.textContent = `IP ${ip || "?"}`;
      },
      countdown(label, left) {
        if (!label) return (countEl.textContent = "");
        const s = Math.max(0, Math.ceil(left / 1000));
        countEl.textContent = s > 1 ? `${label} ${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}` : "";
      },
      running(on) {
        startBtn.disabled = on;
        stopBtn.disabled = !on;
      },
    };
  })();

  ui.build();
})();
