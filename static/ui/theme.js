/*
 * Bonkverse theme and seasons (v0.1.7)
 *
 * Load this in <head>, before any stylesheet, without defer or async:
 *
 *   <script src="/static/ui/theme.js"></script>
 *
 * It sets data-bv-theme on <html> from the saved choice before the page
 * paints, so a reload never flashes the wrong theme. New visitors get
 * "bonkverse" whatever their device setting.
 *
 * The choice is saved in a cookie on .bonkverse.io, so picking a theme on
 * bonkverse.io also applies on replays.bonkverse.io and docs.bonkverse.io,
 * and in localStorage as a backup (and for localhost, where there's no
 * shared domain).
 *
 * Any <select data-bv-theme-picker> on the page becomes the picker once the
 * page has loaded. Scripts can also call:
 *
 *   BonkverseTheme.get()        -> "bonkverse" | "light" | "dark"
 *   BonkverseTheme.set("dark")
 *   document.addEventListener("bv:themechange", e => e.detail.theme)
 *
 * Seasons (seasons.css): by the visitor's own date it also sets
 * data-bv-season-now on <html> to "halloween" (October), "christmas"
 * (December 1–30) or "newyear" (December 31 – January 7), and
 * data-bv-season to the same unless they've switched seasons off. That
 * choice ("bv-season=off") is saved the same way as the theme. Any
 * <input type="checkbox" data-bv-season-toggle> becomes the switch.
 *
 * Each choice the visitor makes also stamps "bv-appearance-at" (milliseconds
 * since 1970) next to it, so a site that saves the choice to their account
 * can tell a newer choice from an old one left on another device.
 * ?bv-season=halloween|christmas|newyear|none in the address previews a
 * season (or none) on that page without saving anything.
 *
 *   BonkverseTheme.season()        -> the season showing, or null
 *   BonkverseTheme.seasonNow()     -> the season on the calendar, or null
 *   BonkverseTheme.setSeasonal(false)
 *   document.addEventListener("bv:seasonchange", e => e.detail.season)
 */
(function () {
  "use strict";

  var THEMES = ["bonkverse", "light", "dark"];
  var DEFAULT = "bonkverse";
  var KEY = "bv-theme";
  var SEASON_KEY = "bv-season";
  var SEASONS = ["halloween", "christmas", "newyear"];
  var ONE_YEAR = 60 * 60 * 24 * 365;
  var root = document.documentElement;

  function valid(theme) {
    return THEMES.indexOf(theme) !== -1;
  }

  function sharedDomain() {
    var host = location.hostname;
    return host === "bonkverse.io" || /\.bonkverse\.io$/.test(host) ? ".bonkverse.io" : null;
  }

  function readSaved() {
    var match = document.cookie.match(/(?:^|;\s*)bv-theme=([a-z]+)/);
    if (match && valid(match[1])) return match[1];
    try {
      var stored = localStorage.getItem(KEY);
      if (valid(stored)) return stored;
    } catch (e) { /* storage blocked: fall through to the default */ }
    return DEFAULT;
  }

  function store(key, value) {
    var domain = sharedDomain();
    document.cookie =
      key + "=" + value + "; Path=/; Max-Age=" + ONE_YEAR + "; SameSite=Lax" +
      (domain ? "; Domain=" + domain : "") +
      (location.protocol === "https:" ? "; Secure" : "");
    try { localStorage.setItem(key, value); } catch (e) { /* cookie is enough */ }
  }

  function stamp() {
    store("bv-appearance-at", String(Date.now()));
  }

  function save(theme) {
    store(KEY, theme);
    stamp();
  }

  // ── Seasons ──────────────────────────────────────────────────────────────

  function calendarSeason(now) {
    var month = now.getMonth(); // 0 = January
    var day = now.getDate();
    if (month === 9) return "halloween";
    if (month === 11) return day === 31 ? "newyear" : "christmas";
    if (month === 0 && day <= 7) return "newyear";
    return null;
  }

  function preview() {
    var match = location.search.match(/[?&]bv-season=([a-z]+)/);
    if (!match) return undefined;
    return SEASONS.indexOf(match[1]) !== -1 ? match[1] : null; // "none" → no season
  }

  function seasonalOn() {
    var match = document.cookie.match(/(?:^|;\s*)bv-season=(on|off)/);
    if (match) return match[1] === "on";
    try {
      if (localStorage.getItem(SEASON_KEY) === "off") return false;
    } catch (e) { /* storage blocked: seasons stay on */ }
    return true;
  }

  function applySeason() {
    var previewed = preview();
    var now = previewed !== undefined ? previewed : calendarSeason(new Date());
    var showing = now && (previewed !== undefined || seasonalOn()) ? now : null;
    if (now) root.setAttribute("data-bv-season-now", now);
    else root.removeAttribute("data-bv-season-now");
    if (showing) root.setAttribute("data-bv-season", showing);
    else root.removeAttribute("data-bv-season");
    apply(get()); // the header color, for the theme-color meta, may have changed
    return showing;
  }

  function season() {
    var current = root.getAttribute("data-bv-season");
    return SEASONS.indexOf(current) !== -1 ? current : null;
  }

  function seasonNow() {
    var current = root.getAttribute("data-bv-season-now");
    return SEASONS.indexOf(current) !== -1 ? current : null;
  }

  function syncToggles() {
    var toggles = document.querySelectorAll("input[data-bv-season-toggle]");
    for (var i = 0; i < toggles.length; i++) toggles[i].checked = seasonalOn();
  }

  function setSeasonal(on) {
    store(SEASON_KEY, on ? "on" : "off");
    stamp();
    var showing = applySeason();
    syncToggles();
    document.dispatchEvent(new CustomEvent("bv:seasonchange", { detail: { season: showing } }));
  }

  function apply(theme) {
    root.setAttribute("data-bv-theme", theme);
    // Match the browser's own toolbar (mobile) to the header.
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) {
      var header = getComputedStyle(root).getPropertyValue("--bv-header").trim();
      if (header) meta.setAttribute("content", header);
    }
  }

  function syncPickers(theme) {
    var pickers = document.querySelectorAll("select[data-bv-theme-picker]");
    for (var i = 0; i < pickers.length; i++) pickers[i].value = theme;
  }

  function set(theme) {
    if (!valid(theme)) return;
    apply(theme);
    save(theme);
    syncPickers(theme);
    document.dispatchEvent(new CustomEvent("bv:themechange", { detail: { theme: theme } }));
  }

  function get() {
    var current = root.getAttribute("data-bv-theme");
    return valid(current) ? current : DEFAULT;
  }

  root.setAttribute("data-bv-theme", readSaved());
  applySeason();

  document.addEventListener("change", function (event) {
    if (!event.target.matches) return;
    if (event.target.matches("select[data-bv-theme-picker]")) {
      set(event.target.value);
    } else if (event.target.matches("input[data-bv-season-toggle]")) {
      setSeasonal(event.target.checked);
    }
  });

  function onReady() {
    syncPickers(get());
    syncToggles();
    apply(get()); // theme-color meta exists by now
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", onReady);
  } else {
    onReady();
  }

  window.BonkverseTheme = {
    themes: THEMES.slice(),
    get: get,
    set: set,
    seasons: SEASONS.slice(),
    season: season,
    seasonNow: seasonNow,
    setSeasonal: setSeasonal,
  };
})();
