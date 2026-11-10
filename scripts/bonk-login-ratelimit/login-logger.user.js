// ==UserScript==
// @name         bonk.io Login Rate-Limit Logger
// @namespace    https://bonkverse.io/
// @version      1.2.0
// @description  Logs every bonk.io login attempt (time, account, result, error code, your public IP) so you can work out how bonk.io rate-limits wrong passwords. Never records passwords.
// @author       Bonkverse
// @match        https://bonk.io/*
// @run-at       document-start
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_addValueChangeListener
// @grant        GM_setClipboard
// @grant        unsafeWindow
// @connect      api.ipify.org
// @connect      api64.ipify.org
// ==/UserScript==

/*
 * How it works
 * - bonk.io's login form (inside the game iframe) posts to
 *   bonk2.io/scripts/login_legacy.php; "remember me" auto-logins use
 *   login_auto.php. This script watches those requests in every bonk.io frame
 *   and records what came back: {"r":"success"} or {"r":"fail","e":"<code>"}.
 *   Codes you'll see: "password" (wrong password), "username_fail" (no such
 *   account), "ratelimited".
 * - With each attempt it looks up your public IP (IPv4 and, if you have one,
 *   IPv6) through ipify, so the log shows whether a VPN was on.
 * - The log is kept in Tampermonkey storage (last 500 entries) and shown in a
 *   panel in the bottom-left corner of bonk.io. Copy it as text or download CSV.
 * - Passwords and tokens are never read into the log. Only the username field
 *   is taken from the request.
 *
 * VPN note: the IP is looked up from the bonk.io page itself, the same way
 * bonk.io's own login requests go out, so a browser-extension VPN is
 * included. Only if the page can't reach ipify does it fall back to
 * Tampermonkey's own request (marked "via TM" in the log), which a browser
 * VPN may not cover. When your IP changes, a note is added automatically.
 */

(function () {
  "use strict";

  const W = unsafeWindow;
  const STORE_KEY = "bvl_log";
  const MAX_ENTRIES = 500;
    const LOGIN_SCRIPTS = /\/scripts\/(login_legacy|login_auto)\.php/;

  // The page's own fetch, captured before it's hooked below. Requests made
  // with it take the same route as bonk.io's (browser VPN included).
  const pageFetch = typeof W.fetch === "function" ? W.fetch.bind(W) : null;

  // Firefox needs page-visible functions exported; Chrome doesn't.
  const toPage = (fn) =>
    typeof exportFunction === "function" ? exportFunction(fn, W) : fn;

  // ── Log storage ───────────────────────────────────────────────

  function readLog() {
    const log = GM_getValue(STORE_KEY, []);
    return Array.isArray(log) ? log : [];
  }

  function append(entry) {
    const log = readLog();
    log.push(entry);
    GM_setValue(STORE_KEY, log.slice(-MAX_ENTRIES));
  }

  // HH:MM:SS.mmm in local time.
  function fmtTime(iso) {
    const d = new Date(iso);
    const ms = String(d.getMilliseconds()).padStart(3, "0");
    return `${d.toLocaleTimeString([], { hour12: false })}.${ms}`;
  }

  // ── Public IP lookup ──────────────────────────────────────────

  let ipCache = { at: 0, value: null };
  let lastSeenV4 = GM_getValue("bvl_last_ipv4", null);
  let lastSeenAt = null; // when lastSeenV4 was last confirmed

  // From the page first (same route as bonk.io), Tampermonkey as a fallback.
  async function lookup(url) {
    if (pageFetch) {
      try {
        const res = await pageFetch(url, { cache: "no-store", credentials: "omit" });
        const data = await res.json();
        if (data && data.ip) return { ip: data.ip, via: "page" };
      } catch (e) {
        /* blocked or offline: fall back below */
      }
    }
    const ip = await lookupViaTampermonkey(url);
    return { ip, via: "TM" };
  }

  function lookupViaTampermonkey(url) {
    return new Promise((resolve) => {
      GM_xmlhttpRequest({
        method: "GET",
        url,
        timeout: 5000,
        onload: (res) => {
          try {
            resolve(JSON.parse(res.responseText).ip || null);
          } catch (e) {
            resolve(null);
          }
        },
        onerror: () => resolve(null),
        ontimeout: () => resolve(null),
      });
    });
  }

  async function currentIp(force) {
    if (!force && ipCache.value) {
      return ipCache.value;
    }
    const [v4, any] = await Promise.all([
      lookup("https://api.ipify.org?format=json"),
      lookup("https://api64.ipify.org?format=json"),
    ]);
    const viaTm = v4.via === "TM";
    const value = {
      // "via TM" marks a lookup a browser VPN may not have covered.
      v4: (v4.ip || "?") + (viaTm && v4.ip ? " (via TM)" : ""),
      v6: any.ip && any.ip.includes(":") ? any.ip : "",
    };
    ipCache = { at: Date.now(), value };
    noteIfChanged(value);
    return value;
  }

  // Adds a log note whenever the public IPv4 changes (VPN on/off).
  function noteIfChanged(ip) {
    if (ip.v4.startsWith("?")) return;
    const now = new Date().toISOString();
    if (lastSeenV4 && lastSeenV4 !== ip.v4) {
      // The switch happened between the last check that saw the old IP and now.
      const since = lastSeenAt ? ` (old IP last seen ${fmtTime(lastSeenAt)})` : "";
      append({
        type: "note",
        at: now,
        note: `IP changed: ${lastSeenV4} → ${ip.v4}${since}`,
        ipv4: ip.v4,
        ipv6: ip.v6,
      });
    }
    lastSeenV4 = ip.v4;
    lastSeenAt = now;
    GM_setValue("bvl_last_ipv4", ip.v4);
  }

  // ── Reading the request and response ──────────────────────────

  function scriptName(url) {
    const m = String(url).match(LOGIN_SCRIPTS);
    return m ? m[1] + ".php" : null;
  }

  // Only the username is taken; the password never leaves the request.
  function usernameFrom(body) {
    try {
      if (!body) return "";
      if (typeof body === "string") {
        return new URLSearchParams(body).get("username") || "";
      }
      if (typeof body.get === "function") {
        const v = body.get("username");
        return typeof v === "string" ? v : "";
      }
    } catch (e) {
      /* unreadable body: leave blank */
    }
    return "";
  }

  function parseResult(text, status) {
    let data = null;
    try {
      data = typeof text === "string" ? JSON.parse(text) : text;
    } catch (e) {
      /* not JSON */
    }
    if (!data || typeof data !== "object") {
      return { result: "no_json", error: `http ${status}` };
    }
    if (data.r === "success") return { result: "success", error: "" };
    return { result: "fail", error: String(data.e || data.error || data.r || "?") };
  }

  async function record(script, username, startedAt, status, responseText, ipPromise) {
    const ip = await ipPromise;
    const { result, error } = parseResult(responseText, status);
    append({
      type: "attempt",
      at: new Date(startedAt).toISOString(),
      ms: Date.now() - startedAt,
      script,
      username: username || (script === "login_auto.php" ? "(remember-me)" : ""),
      result,
      error,
      status,
      ipv4: ip.v4,
      ipv6: ip.v6,
    });
  }

  // ── Hook XMLHttpRequest (what bonk.io uses) ───────────────────

  const xhrInfo = new WeakMap();
  const XHR = W.XMLHttpRequest.prototype;
  const origOpen = XHR.open;
  const origSend = XHR.send;

  XHR.open = toPage(function (method, url) {
    xhrInfo.set(this, { script: scriptName(url) });
    return origOpen.apply(this, arguments);
  });

  XHR.send = toPage(function (body) {
    const info = xhrInfo.get(this);
    if (info && info.script) {
      const xhr = this;
      const startedAt = Date.now();
      const username = usernameFrom(body);
      // A fresh lookup for every attempt, so a VPN switched on a moment ago
      // is what gets logged. Started now, while bonk.io answers.
      const ipPromise = currentIp(true);
      xhr.addEventListener(
        "loadend",
        toPage(function () {
          let text = "";
          try {
            text =
              xhr.responseType === "" || xhr.responseType === "text"
                ? xhr.responseText
                : xhr.response;
          } catch (e) {
            /* ignore */
          }
          record(info.script, username, startedAt, xhr.status, text, ipPromise);
        })
      );
    }
    return origSend.apply(this, arguments);
  });

  // ── Hook fetch too, in case a page uses it ────────────────────

  if (typeof W.fetch === "function") {
    const origFetch = W.fetch;
    W.fetch = toPage(function (input, init) {
      const url = typeof input === "string" ? input : input && input.url;
      const script = scriptName(url || "");
      const promise = origFetch.apply(this, arguments);
      if (script) {
        const startedAt = Date.now();
        const username = usernameFrom(init && init.body);
        const ipPromise = currentIp(true);
        promise.then(
          (res) =>
            res
              .clone()
              .text()
              .then((text) => record(script, username, startedAt, res.status, text, ipPromise)),
          () => record(script, username, startedAt, 0, "", ipPromise)
        );
      }
      return promise;
    });
  }

  // ── Panel (top window only; every frame writes to the same log) ──

  if (window.top !== window.self) return;

  const CSS = `
    #bvl-panel { position: fixed; left: 8px; bottom: 8px; z-index: 2147483647;
      width: 640px; max-width: calc(100vw - 16px); max-height: 45vh; display: flex;
      flex-direction: column; background: rgba(20, 28, 36, 0.96); color: #ddd;
      font: 12px/1.35 ui-monospace, Menlo, Consolas, monospace; border: 1px solid #009688;
      border-radius: 8px; box-shadow: 0 4px 18px rgba(0,0,0,.5); }
    #bvl-panel.bvl-min #bvl-body { display: none; }
    #bvl-head { display: flex; gap: 6px; align-items: center; padding: 6px 8px;
      border-bottom: 1px solid #2c3a46; flex-wrap: wrap; }
    #bvl-head b { color: #4dd0c4; margin-right: auto; }
    #bvl-head button { background: #263440; color: #ddd; border: 1px solid #3b4d5c;
      border-radius: 4px; padding: 2px 7px; cursor: pointer; font: inherit; }
    #bvl-head button:hover { border-color: #009688; }
    #bvl-status { padding: 4px 8px; color: #bbb; border-bottom: 1px solid #2c3a46; }
    #bvl-status .bvl-warn { color: #ffc107; }
    #bvl-scroll { overflow: auto; }
    #bvl-table { width: 100%; border-collapse: collapse; }
    #bvl-table th, #bvl-table td { padding: 2px 6px; text-align: left; white-space: nowrap; }
    #bvl-table th { position: sticky; top: 0; background: #1a2733; color: #8fa3b3; }
    #bvl-table tr.bvl-ok td { color: #81c784; }
    #bvl-table tr.bvl-rl td { color: #ff8a65; font-weight: bold; }
    #bvl-table tr.bvl-note td { color: #ffc107; font-style: italic; }
  `;

  function el(tag, attrs, text) {
    const node = document.createElement(tag);
    Object.assign(node, attrs || {});
    if (text != null) node.textContent = text;
    return node;
  }



  function fmtDuration(ms) {
    const s = Math.max(0, Math.round(ms / 1000));
    const m = Math.floor(s / 60);
    return m ? `${m}m ${String(s % 60).padStart(2, "0")}s` : `${s}s`;
  }

  function summary(log) {
    // Wrong tries per account since its last success, and the first
    // "ratelimited" since the last success of any account.
    const wrong = {};
    let firstLimit = null;
    let lastLimit = null;
    for (const e of log) {
      if (e.type !== "attempt") continue;
      const key = (e.username || "").toLowerCase();
      if (e.result === "success") {
        wrong[key] = 0;
        firstLimit = null;
      } else if (e.error === "password" || e.error === "username_fail") {
        wrong[key] = (wrong[key] || 0) + 1;
      } else if (e.error === "ratelimited") {
        if (!firstLimit) firstLimit = e;
        lastLimit = e;
      }
    }
    return { wrong, firstLimit, lastLimit };
  }

  function toText(log) {
    return log
      .map((e) =>
        e.type === "note"
          ? `${e.at}  NOTE: ${e.note}  (ip ${e.ipv4}${e.ipv6 ? " / " + e.ipv6 : ""})`
          : `${e.at}  ${e.script}  user=${e.username}  ${e.result}` +
            `${e.error ? " (" + e.error + ")" : ""}  ip=${e.ipv4}` +
            `${e.ipv6 ? " / " + e.ipv6 : ""}  ${e.ms}ms`
      )
      .join("\n");
  }

  function toCsv(log) {
    const cols = ["at", "type", "script", "username", "result", "error", "status", "ipv4", "ipv6", "ms", "note"];
    const esc = (v) => `"${String(v == null ? "" : v).replace(/"/g, '""')}"`;
    return [cols.join(",")].concat(log.map((e) => cols.map((c) => esc(e[c])).join(","))).join("\n");
  }

  function buildPanel() {
    const style = el("style", {}, CSS);
    document.head.appendChild(style);

    const panel = el("div", { id: "bvl-panel" });
    const head = el("div", { id: "bvl-head" });
    head.appendChild(el("b", {}, "Login rate-limit log"));
    const ipLabel = el("span", { id: "bvl-ip" }, "IP …");
    head.appendChild(ipLabel);

    const buttons = {
      note: el("button", { title: 'Add a marker, e.g. "VPN on" or "step 2"' }, "Note"),
      ip: el("button", { title: "Look up your public IP now" }, "Refresh IP"),
      copy: el("button", {}, "Copy"),
      csv: el("button", {}, "CSV"),
      clear: el("button", {}, "Clear"),
      min: el("button", { title: "Collapse" }, "–"),
    };
    Object.values(buttons).forEach((b) => head.appendChild(b));

    const body = el("div", { id: "bvl-body" });
    const status = el("div", { id: "bvl-status" });
    const scroll = el("div", { id: "bvl-scroll" });
    const table = el("table", { id: "bvl-table" });
    table.innerHTML =
      "<thead><tr><th>Time</th><th>Account</th><th>Script</th><th>Result</th>" +
      "<th>Error</th><th>IPv4</th><th>IPv6</th><th>ms</th></tr></thead><tbody></tbody>";
    scroll.appendChild(table);
    body.appendChild(status);
    body.appendChild(scroll);
    panel.appendChild(head);
    panel.appendChild(body);
    document.body.appendChild(panel);

    const tbody = table.querySelector("tbody");

    function showIp(ip) {
      ipLabel.textContent = `IP ${ip.v4}${ip.v6 ? " / " + ip.v6 : ""}`;
    }

    function render() {
      const log = readLog();
      tbody.textContent = "";
      for (const e of log.slice().reverse()) {
        const tr = el("tr");
        if (e.type === "note") {
          tr.className = "bvl-note";
          const td = el("td", { colSpan: 8 }, `${fmtTime(e.at)}  — ${e.note}  (IP ${e.ipv4})`);
          tr.appendChild(td);
        } else {
          tr.className = e.result === "success" ? "bvl-ok" : e.error === "ratelimited" ? "bvl-rl" : "";
          [fmtTime(e.at), e.username, e.script, e.result, e.error, e.ipv4, e.ipv6, e.ms].forEach((v) =>
            tr.appendChild(el("td", {}, v == null ? "" : String(v)))
          );
        }
        tbody.appendChild(tr);
      }
      renderStatus(log);
    }

    function renderStatus(log) {
      const { wrong, firstLimit, lastLimit } = summary(log || readLog());
      status.textContent = "";
      const wrongText = Object.entries(wrong)
        .filter(([, n]) => n > 0)
        .map(([u, n]) => `${u || "(blank)"}: ${n}`)
        .join(", ");
      status.appendChild(el("div", {}, `Wrong tries since last success — ${wrongText || "none"}`));
      if (firstLimit) {
        const line = el("div", { className: "bvl-warn" });
        line.textContent =
          `First "ratelimited" at ${fmtTime(firstLimit.at)} (${firstLimit.username || "?"}, IP ${firstLimit.ipv4}) — ` +
          `${fmtDuration(Date.now() - new Date(firstLimit.at))} ago` +
          (lastLimit && lastLimit !== firstLimit
            ? `; last at ${fmtTime(lastLimit.at)} (${fmtDuration(Date.now() - new Date(lastLimit.at))} ago)`
            : "");
        status.appendChild(line);
      }
    }

    buttons.note.addEventListener("click", async () => {
      const note = prompt('Note for the log (e.g. "VPN on", "step 2: main account"):');
      if (!note) return;
      const ip = await currentIp(true);
      showIp(ip);
      append({ type: "note", at: new Date().toISOString(), note, ipv4: ip.v4, ipv6: ip.v6 });
    });
    buttons.ip.addEventListener("click", async () => {
      ipLabel.textContent = "IP …";
      showIp(await currentIp(true));
    });
    buttons.copy.addEventListener("click", () => {
      GM_setClipboard(toText(readLog()), "text");
      buttons.copy.textContent = "Copied";
      setTimeout(() => (buttons.copy.textContent = "Copy"), 1200);
    });
    buttons.csv.addEventListener("click", () => {
      const blob = new Blob([toCsv(readLog())], { type: "text/csv" });
      const a = el("a", {
        href: URL.createObjectURL(blob),
        download: `bonk-login-log-${new Date().toISOString().slice(0, 19).replace(/:/g, "")}.csv`,
      });
      document.body.appendChild(a);
      a.click();
      a.remove();
    });
    buttons.clear.addEventListener("click", () => {
      if (confirm("Clear the whole login log?")) GM_setValue(STORE_KEY, []);
    });
    buttons.min.addEventListener("click", () => {
      panel.classList.toggle("bvl-min");
      buttons.min.textContent = panel.classList.contains("bvl-min") ? "+" : "–";
    });

    GM_addValueChangeListener(STORE_KEY, () => render());
    setInterval(() => renderStatus(), 1000); // keeps "x ago" ticking
    render();
    currentIp(true).then(showIp);
    // Background check every 5 s, so a VPN switch is noted within seconds.
    // Login attempts don't rely on this: each one does its own lookup.
    setInterval(() => currentIp(true).then(showIp), 5000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", buildPanel);
  } else {
    buildPanel();
  }
})();
