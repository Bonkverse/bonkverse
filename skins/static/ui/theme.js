/*
 * Bonkverse theme (v0.1.2)
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
 */
(function () {
  "use strict";

  var THEMES = ["bonkverse", "light", "dark"];
  var DEFAULT = "bonkverse";
  var KEY = "bv-theme";
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

  function save(theme) {
    var domain = sharedDomain();
    document.cookie =
      KEY + "=" + theme + "; Path=/; Max-Age=" + ONE_YEAR + "; SameSite=Lax" +
      (domain ? "; Domain=" + domain : "") +
      (location.protocol === "https:" ? "; Secure" : "");
    try { localStorage.setItem(KEY, theme); } catch (e) { /* cookie is enough */ }
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

  apply(readSaved());

  document.addEventListener("change", function (event) {
    if (event.target.matches && event.target.matches("select[data-bv-theme-picker]")) {
      set(event.target.value);
    }
  });

  function onReady() {
    syncPickers(get());
    apply(get()); // theme-color meta exists by now
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", onReady);
  } else {
    onReady();
  }

  window.BonkverseTheme = { themes: THEMES.slice(), get: get, set: set };
})();
