#!/usr/bin/env node
// Opens bonkverse.io's main pages at every screen size, from a 280 px folded
// phone to a 3,440 px ultrawide (1,280 px at 200% zoom is the 640 px size),
// in all three themes, and fails if anything:
//   - makes the page scroll sideways,
//   - sticks out past the edge of the screen,
//   - has its text cut off instead of wrapping,
//   - is a control smaller than 44 × 44 px.
// The same check Bonkverse/ui runs on its gallery (scripts/responsive.mjs
// there), pointed at real pages.
//
//   npm install --no-save playwright && npx playwright install chromium
//   python manage.py runserver            # in another terminal, with some skins
//   node scripts/check_responsive.mjs [--base http://localhost:8000]
//        [--session <sessionid cookie>]   # to check signed-in pages too
//        [--pages search,detail]          # only some pages
//        [--shots shots/]                 # save screenshots at 375 and 1440 px
//
// Pages still on their old CSS ("site-legacy") are checked too: a problem
// there is real, even if the fix is moving the page onto bv- components.

import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  return i === -1 ? fallback : process.argv[i + 1];
}
const BASE = arg("base", "http://localhost:8000").replace(/\/$/, "");
const SESSION = arg("session", process.env.BV_SESSIONID || "");
const ONLY = arg("pages", "");
const SHOTS = arg("shots", "");
if (SHOTS) mkdirSync(SHOTS, { recursive: true });

// [path, label, needs a signed-in session]
const PAGES = [
  ["/search/?q=", "search", false],
  ["/search/?q=zzzzqqqq", "search-empty", false],
  ["/skins/detail/1", "detail", false],
  ["/", "home", false],
  ["/new/", "new", false],
  ["/categories/", "categories", false],
  ["/leaderboards/upvoted/", "leaderboards", false],
  ["/players/", "players", false],
  ["/tools/xp/", "xp", false],
  ["/developers/", "developers", false],
  ["/my-profile/", "my-profile", true],
  ["/developers/keys/", "api-keys", true],
];
const SIZES = [
  [280, 653], [320, 568], [375, 667], [430, 932], [667, 375], [600, 900], [768, 1024], [899, 900],
  [900, 900], [1024, 768], [1199, 900], [1280, 800], [1440, 900], [1920, 1080], [3440, 1440],
];
const THEMES = ["bonkverse", "light", "dark"];

// Things that scroll sideways on purpose; what's inside them may be wider.
const SCROLLERS = ".bv-table-wrap, .bv-tabs, .bv-code pre, pre, .carousel, .carousel-track, .site-scroll, .pv-tabs, .pv-tablewrap";
const CONTROLS = [
  ".bv-btn", ".bv-header__link", ".bv-menu__item", ".bv-tab", ".bv-details-link", ".bv-back", ".bv-fav",
  ".bv-theme-picker select", ".bv-input", ".bv-select", ".bv-search", ".bv-search button", ".page-btn", ".page-nav",
].join(", ");

function audit({ SCROLLERS, CONTROLS }) {
  const out = [];
  const vw = document.documentElement.clientWidth;
  const name = (el) =>
    `${el.tagName.toLowerCase()}.${[...el.classList].slice(0, 3).join(".")} “${(el.getAttribute("aria-label") || el.textContent || "").trim().replace(/\s+/g, " ").slice(0, 30)}”`;
  const visible = (el) => {
    if (el.closest("[hidden], dialog:not([open]), template")) return false;
    const s = getComputedStyle(el);
    if (s.display === "none" || s.visibility === "hidden") return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  if (document.documentElement.scrollWidth > vw + 1) {
    out.push(`page scrolls sideways (${document.documentElement.scrollWidth}px in ${vw}px)`);
  }
  for (const el of document.body.querySelectorAll("*")) {
    if (!visible(el) || el.closest(SCROLLERS)) continue;
    if (el.matches("svg *, .bv-visually-hidden, .pv-visually-hidden, .bv-skip-link")) continue;
    const s = getComputedStyle(el);
    if (s.position === "fixed") continue;
    const r = el.getBoundingClientRect();
    if (r.right > vw + 1 || r.left < -1) out.push(`off screen: ${name(el)}`);
    const clips = ["hidden", "clip"].includes(s.overflowX) || s.textOverflow === "ellipsis";
    if (clips && el.scrollWidth > el.clientWidth + 1 && el.textContent.trim()) out.push(`text cut off: ${name(el)}`);
  }
  for (const el of document.querySelectorAll(CONTROLS)) {
    if (!visible(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.height < 43.5 || r.width < 43.5) out.push(`control under 44 px: ${name(el)}`);
  }
  return out;
}

const browser = await chromium.launch();
const found = {};
let runs = 0;
for (const [path, label, signedIn] of PAGES) {
  if (ONLY && !ONLY.split(",").includes(label)) continue;
  if (signedIn && !SESSION) continue;
  for (const theme of THEMES) {
    for (const [width, height] of SIZES) {
      const context = await browser.newContext({ viewport: { width, height }, reducedMotion: "reduce" });
      const cookies = [{ name: "bv-theme", value: theme, url: BASE }];
      if (SESSION) cookies.push({ name: "sessionid", value: SESSION, url: BASE });
      await context.addCookies(cookies);
      const page = await context.newPage();
      const problems = [];
      page.on("pageerror", (e) => problems.push(`script error: ${e.message}`));
      page.on("response", (r) => {
        if (r.status() >= 500 && r.url().startsWith(BASE)) problems.push(`HTTP ${r.status()} ${r.url().slice(BASE.length)}`);
      });
      await page.goto(BASE + path, { waitUntil: "networkidle" });
      await page.evaluate(() => document.fonts.ready);
      problems.push(...(await page.evaluate(audit, { SCROLLERS, CONTROLS })));
      runs++;
      for (const p of problems) (found[`${label} · ${p}`] ||= []).push(`${theme} ${width}px`);
      if (SHOTS && (width === 375 || width === 1440)) {
        await page.screenshot({ path: join(SHOTS, `${label}-${theme}-${width}.png`), fullPage: true });
      }
      await context.close();
    }
  }
}
await browser.close();

for (const [problem, where] of Object.entries(found).sort()) {
  console.log(`✗ ${problem}\n    ${where.slice(0, 6).join(", ")}${where.length > 6 ? ` and ${where.length - 6} more` : ""}`);
}
const count = Object.keys(found).length;
console.log(`\n${runs} page loads, ${count} distinct problem${count === 1 ? "" : "s"}.`);
if (!SESSION) console.log("Signed-in pages skipped; pass --session <sessionid> to include them.");
process.exit(count ? 1 : 0);
