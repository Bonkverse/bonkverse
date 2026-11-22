// core/js/bv-dates.js
//
// Date formatters in the viewer's language, with one safety net: some
// browsers have no month names for the viewer's language and fall back to
// labels like "2025 M03 17". When that happens, use English instead.
//
//   const fmt = BVDates.format({ month: "short", day: "numeric", year: "numeric" });
//   fmt.format(date)   // "Mar 17, 2025", "17 mars 2025", ...
//
// Load this before bv-chart.js and any page script that formats dates.

(function (window) {
  "use strict";

  const PROBE = new Date(2025, 2, 17);

  // The locale to format with: the browser's (undefined) when it has real
  // month names, otherwise "en". `preferred` is only for tests.
  function pickLocale(preferred) {
    try {
      const month = new Intl.DateTimeFormat(preferred, { month: "short" }).format(PROBE);
      return /^M\d/.test(month) ? "en" : preferred;
    } catch (e) {
      return "en";
    }
  }

  const LOCALE = pickLocale(undefined);

  window.BVDates = {
    locale: LOCALE,
    format: (opts) => new Intl.DateTimeFormat(LOCALE, opts),
    pickLocale,
  };
})(window);
