#!/usr/bin/env node
// Opens bonkverse.io's pages in all three themes and fails if something is
// hard to see (WCAG 2.2 AA, measured on the page as rendered):
//   - text below 4.5:1 against what's actually behind it (3:1 if large),
//   - a button, field, chip or tag whose edge is below 3:1 against what's
//     around it (its border or its fill has to stand out),
//   - a chart bar below 3:1 against its track or the card,
//   - hover that changes nothing you can see, or leaves text below 4.5:1,
//   - a selected item (aria-pressed, aria-current, .active) that looks the
//     same as its unselected neighbours,
//   - a disabled control that looks the same as an enabled one.
// scripts/check_responsive.mjs checks sizes; this checks color and states.
//
//   python manage.py runserver            # in another terminal, with some data
//   node scripts/check_contrast.mjs [--base http://localhost:8000]
//        [--session <sessionid cookie>]   # signed-in pages too
//        [--pages search,detail]          # only some pages
//        [--width 1280]                   # viewport width (default 1280)
//   BV_LUCIDE_FILE=path/to/lucide.min.js   serve the icon library locally (offline)

import { chromium } from "playwright";

function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  return i === -1 ? fallback : process.argv[i + 1];
}
const BASE = arg("base", "http://localhost:8000").replace(/\/$/, "");
const SESSION = arg("session", process.env.BV_SESSIONID || "");
const ONLY = arg("pages", "");
const WIDTH = Number(arg("width", "1280"));

// [path, label, needs a signed-in session]
const PAGES = [
  ["/", "home", false],
  ["/search/?q=", "search", false],
  ["/skins/detail/1", "detail", false],
  ["/new/", "new", false],
  ["/categories/", "categories", false],
  ["/leaderboards/upvoted/", "leaderboards", false],
  ["/players/", "players", false],
  ["/player/tester/", "player", false],
  ["/tools/xp/", "xp", false],
  ["/social-stats/", "social-stats", false],
  ["/serverlist/", "servers", false],
  ["/submit/", "submit-server", false],
  ["/tools/map-decode/", "map-decode", false],
  ["/developers/", "developers", false],
  ["/login/", "login", false],
  ["/privacy/", "privacy", false],
  ["/my-profile/", "my-profile", true],
  ["/upload/", "upload", true],
  ["/settings/profile/", "settings", true],
  ["/developers/keys/", "api-keys", true],
  ["/staff/", "staff", true],
];
const THEMES = ["bonkverse", "light", "dark"];

// Things you click, type in or read as a label.
const CONTROLS = [
  "button", "input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=range])", "select", "textarea",
  ".bv-btn", ".bv-chip", ".bv-pill", ".page-btn", ".page-nav", "[role=button]", "[role=tab]",
  ".tag-bubble", ".tag", ".pill", "[class*=pill]", "[class*=chip]", "[class*=-btn]", "[class*=badge]",
].join(", ");
const BARS = ".bv-chart__bar, .bar-inner, .pv-week__fill, [class*=bar-fill], [class*=__bar-fill]";
const SELECTED = '[aria-pressed="true"], [aria-current]:not([aria-current="false"]), [aria-selected="true"], .active, .selected, .is-active, .is-selected';

function audit({ CONTROLS, BARS, SELECTED }) {
  const out = [];
  const parse = (c) => {
    const m = c.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(/[\s,/]+/).filter(Boolean).map(Number);
    return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
  };
  const over = (top, bottom) => {
    const a = top[3];
    return [0, 1, 2].map((i) => top[i] * a + bottom[i] * (1 - a)).concat(1);
  };
  const lum = ([r, g, b]) => {
    const f = (v) => ((v /= 255) <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const ratio = (a, b) => {
    const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
    return (x + 0.05) / (y + 0.05);
  };
  const visible = (el) => {
    if (el.closest("[hidden], dialog:not([open]), template, .bv-visually-hidden, .pv-visually-hidden, .sr-only")) return false;
    const s = getComputedStyle(el);
    if (s.display === "none" || s.visibility === "hidden" || Number(s.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 1 && r.height > 1;
  };
  const disabled = (el) => !!el.closest("[disabled], [aria-disabled=true], .disabled, .is-disabled, fieldset[disabled]");
  // The color behind an element: its ancestors' fills, composited. null when an
  // image or gradient is in the way (can't measure that).
  const behind = (el, includeSelf = true) => {
    const layers = [];
    let node = includeSelf ? el : el.parentElement;
    for (; node && node.nodeType === 1; node = node.parentElement) {
      const s = getComputedStyle(node);
      if (s.backgroundImage !== "none" && !/^url\(.*\.svg/.test(s.backgroundImage)) return null;
      const c = parse(s.backgroundColor);
      if (c && c[3] > 0) {
        layers.push(c);
        if (c[3] >= 1) break;
      }
    }
    let base = [255, 255, 255, 1];
    if (!node) base = parse(getComputedStyle(document.documentElement).backgroundColor) || base;
    return layers.reverse().reduce((acc, c) => over(c, acc), base);
  };
  const opacityOf = (el) => {
    let o = 1;
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) o *= Number(getComputedStyle(n).opacity);
    return o;
  };
  const name = (el) =>
    `${el.tagName.toLowerCase()}${el.id ? "#" + el.id : ""}.${[...el.classList].slice(0, 3).join(".")} “${(el.getAttribute("aria-label") || el.textContent || el.value || el.placeholder || "").trim().replace(/\s+/g, " ").slice(0, 28)}”`;

  const textCheck = (el, label = "") => {
    const s = getComputedStyle(el);
    const bg = behind(el);
    const fg = parse(s.color);
    if (!bg || !fg) return;
    const color = over([...fg.slice(0, 3), fg[3] * opacityOf(el)], bg);
    const size = parseFloat(s.fontSize);
    const large = size >= 24 || (size >= 18.66 && Number(s.fontWeight) >= 700);
    const r = ratio(color, bg);
    const min = large ? 3 : 4.5;
    if (r < min - 0.05) out.push(`${label}text ${r.toFixed(2)}:1 (needs ${min}) ${name(el)}`);
  };

  // 1. Text
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const seen = new Set();
  for (let t = walker.nextNode(); t; t = walker.nextNode()) {
    const el = t.parentElement;
    if (!el || seen.has(el) || !t.textContent.trim()) continue;
    seen.add(el);
    if (el.closest("script, style, noscript, svg, option") || !visible(el) || disabled(el)) continue;
    textCheck(el);
  }
  for (const el of document.querySelectorAll("input:not([type=hidden]), textarea")) {
    if (visible(el) && !disabled(el) && (el.value || "").trim()) textCheck(el);
  }

  // 2. Control edges
  for (const el of document.querySelectorAll(CONTROLS)) {
    if (!visible(el) || disabled(el) || el.closest("svg")) continue;
    const s = getComputedStyle(el);
    const fill = parse(s.backgroundColor);
    const around = behind(el, false);
    if (!around || s.backgroundImage !== "none") continue;
    const own = fill && fill[3] > 0 ? over(fill, around) : around;
    const fillRatio = ratio(own, around);
    const bw = parseFloat(s.borderTopWidth) + parseFloat(s.borderBottomWidth);
    const bc = parse(s.borderTopColor);
    const borderRatio = bw > 0 && s.borderTopStyle !== "none" && bc ? ratio(over(bc, around), around) : 0;
    const shadowRing = /inset/.test(s.boxShadow) ? 3 : 0; // an inset ring is a drawn border
    // Text-only controls (no fill, no border) are links in look: their text is the cue.
    if (fillRatio < 1.01 && borderRatio === 0 && !shadowRing) continue;
    if (Math.max(fillRatio, borderRatio, shadowRing) < 2.95) {
      out.push(`edge ${Math.max(fillRatio, borderRatio).toFixed(2)}:1 (fill ${fillRatio.toFixed(2)}, border ${borderRatio.toFixed(2)}; needs 3) ${name(el)}`);
    }
  }

  // 3. Chart bars
  for (const el of document.querySelectorAll(BARS)) {
    if (!visible(el)) continue;
    const s = getComputedStyle(el);
    const paint = parse(el instanceof SVGElement ? s.fill : s.backgroundColor);
    const around = behind(el, false);
    if (!paint || !around || (!(el instanceof SVGElement) && s.backgroundImage !== "none")) continue;
    const r = ratio(over(paint, around), around);
    if (r < 2.95) out.push(`chart bar ${r.toFixed(2)}:1 (needs 3) ${name(el)}`);
  }

  // 4. Selected vs unselected neighbours
  for (const el of document.querySelectorAll(SELECTED)) {
    if (!visible(el) || el.matches("html, body, main, nav, header, footer, section, li, ul, div:not([role])") && !el.matches("[class*=chip], [class*=btn], [class*=tag], [class*=tab]")) continue;
    const parent = el.parentElement;
    const sib = [...(parent?.children || [])].find(
      (c) => c !== el && c.tagName === el.tagName && !c.matches(SELECTED) && visible(c) && !disabled(c),
    );
    if (!sib) continue;
    const a = getComputedStyle(el), b = getComputedStyle(sib);
    const fa = over(parse(a.backgroundColor) || [0, 0, 0, 0], behind(el, false) || [0, 0, 0, 1]);
    const fb = over(parse(b.backgroundColor) || [0, 0, 0, 0], behind(sib, false) || [0, 0, 0, 1]);
    const differs =
      ratio(fa, fb) >= 1.25 ||
      ratio(parse(a.borderTopColor) || [0, 0, 0, 1], parse(b.borderTopColor) || [0, 0, 0, 1]) >= 2 ||
      a.boxShadow !== b.boxShadow || a.borderBottomColor !== b.borderBottomColor && parseFloat(a.borderBottomWidth) >= 2 ||
      Math.abs(Number(a.fontWeight) - Number(b.fontWeight)) >= 200 ||
      a.textDecorationLine !== b.textDecorationLine ||
      getComputedStyle(el, "::before").content !== getComputedStyle(sib, "::before").content;
    if (!differs) out.push(`selected looks like unselected: ${name(el)} vs ${name(sib)}`);
  }

  // 5. Disabled vs enabled
  for (const el of document.querySelectorAll("button:disabled, [aria-disabled=true], .disabled")) {
    if (!visible(el)) continue;
    const sel = [el.tagName, ...[...el.classList].filter((c) => c !== "disabled").map((c) => CSS.escape(c))].join(".");
    const sib = [...document.querySelectorAll(sel)].find(
      (c) => c !== el && !disabled(c) && visible(c),
    );
    if (!sib) continue;
    const a = getComputedStyle(el), b = getComputedStyle(sib);
    if (a.opacity === b.opacity && a.borderStyle === b.borderStyle && a.color === b.color && a.backgroundColor === b.backgroundColor) {
      out.push(`disabled looks enabled: ${name(el)}`);
    }
  }
  return out;
}

// Hover: one of each kind of control, by class, compared before and after.
async function hoverChecks(page) {
  const handles = await page.evaluateHandle((CONTROLS) => {
    const kinds = new Map();
    for (const el of document.querySelectorAll(CONTROLS + ", a.bv-header__link, .bv-menu__item, .bv-tab, a[class]")) {
      if (el.closest("[hidden], dialog:not([open]), .bv-dropdown__menu, [role=menu]") || el.matches(":disabled, [aria-disabled=true], .disabled, input, select, textarea")) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 2 || r.height < 2 || r.bottom < 0 || r.top > innerHeight * 4) continue;
      const s = getComputedStyle(el);
      if (s.visibility === "hidden" || s.display === "none" || s.pointerEvents === "none") continue;
      const key = el.tagName + "." + [...el.classList].sort().join(".") + (el.matches('[aria-pressed="true"], [aria-current]') ? "+sel" : "");
      if (!kinds.has(key)) kinds.set(key, el);
    }
    return [...kinds.values()].slice(0, 40);
  }, CONTROLS);
  const els = [];
  const props = await handles.getProperties();
  for (const p of props.values()) {
    const e = p.asElement();
    if (e) els.push(e);
  }
  const out = [];
  const snap = (el) =>
    el.evaluate((el) => {
      const s = getComputedStyle(el);
      const img = el.querySelector("img");
      return {
        bg: s.backgroundColor, border: s.borderTopColor, color: s.color, deco: s.textDecorationLine,
        shadow: s.boxShadow, outline: s.outlineStyle, transform: img ? getComputedStyle(img).transform : s.transform,
        name: `${el.tagName.toLowerCase()}.${[...el.classList].slice(0, 3).join(".")} “${(el.getAttribute("aria-label") || el.textContent || "").trim().replace(/\s+/g, " ").slice(0, 28)}”`,
      };
    });
  for (const el of els) {
    try {
      const before = await snap(el);
      await el.hover({ timeout: 800 });
      await page.waitForTimeout(220);
      const after = await snap(el);
      const changed = ["bg", "border", "color", "deco", "shadow", "outline", "transform"].some((k) => before[k] !== after[k]);
      if (!changed) out.push(`hover changes nothing: ${before.name}`);
      else {
        const bad = await el.evaluate((el) => {
          const p = (c) => (c.match(/[\d.]+/g) || []).map(Number);
          const L = ([r, g, b]) => {
            const f = (v) => ((v /= 255) <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
            return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
          };
          let bg = null;
          for (let n = el; n; n = n.parentElement) {
            const c = p(getComputedStyle(n).backgroundColor);
            if (c.length && (c.length < 4 || c[3] > 0.5)) { bg = c; break; }
          }
          if (!bg || !el.textContent.trim()) return null;
          const fg = p(getComputedStyle(el).color);
          const [x, y] = [L(fg), L(bg)].sort((a, b) => b - a);
          const r = (x + 0.05) / (y + 0.05);
          return r < 4.45 ? r.toFixed(2) : null;
        });
        if (bad) out.push(`hovered text ${bad}:1 (needs 4.5) ${after.name}`);
      }
      await page.mouse.move(0, 0);
    } catch {
      /* covered or moved: skip */
    }
  }
  return out;
}

const browser = await chromium.launch();
const found = {};
let runs = 0;
async function check(path, label, theme) {
  const context = await browser.newContext({ viewport: { width: WIDTH, height: 900 }, reducedMotion: "reduce" });
  const cookies = [{ name: "bv-theme", value: theme, url: BASE }];
  if (SESSION) cookies.push({ name: "sessionid", value: SESSION, url: BASE });
  await context.addCookies(cookies);
  const page = await context.newPage();
  if (process.env.BV_LUCIDE_FILE) {
    await page.route("https://unpkg.com/lucide@*/**", (r) => r.fulfill({ path: process.env.BV_LUCIDE_FILE, contentType: "text/javascript" }));
  }
  try {
    const res = await page.goto(BASE + path, { waitUntil: "networkidle" });
    if (!res || res.status() >= 400) {
      (found[`${label} · HTTP ${res && res.status()}`] ||= []).push(theme);
      return;
    }
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(400); // charts draw after load
    const problems = [...(await page.evaluate(audit, { CONTROLS, BARS, SELECTED })), ...(await hoverChecks(page))];
    runs++;
    for (const p of new Set(problems)) (found[`${label} · ${p}`] ||= []).push(theme);
  } finally {
    await context.close();
  }
}
for (const [path, label, signedIn] of PAGES) {
  if (ONLY && !ONLY.split(",").includes(label)) continue;
  if (signedIn && !SESSION) continue;
  await Promise.all(THEMES.map((theme) => check(path, label, theme)));
}
await browser.close();

for (const [problem, where] of Object.entries(found).sort()) console.log(`✗ ${problem}  [${where.join(", ")}]`);
const count = Object.keys(found).length;
console.log(`\n${runs} page loads, ${count} distinct problem${count === 1 ? "" : "s"}.`);
if (!SESSION) console.log("Signed-in pages skipped; pass --session <sessionid> to include them.");
process.exit(count ? 1 : 0);
