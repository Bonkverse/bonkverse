# ADR 0020: Every page on the shared look, held by tests

**Status:** accepted, 2026-11-20

**Context.** [ADR 0013](0013-shared-ui-package.md) moved the look into
Bonkverse/ui and let pages move onto its `bv-` components one at a time,
with the rest marked `site-legacy`. By 2026-11-20 every page had moved
(RFC-0002 step 2, then the category index and matchmaking in step 5), and
the replay site and docs use the same package. Without a check, a hard-coded
color or a page on old styles would creep back in one PR at a time; the
design review had counted 323 colors on this site alone.

**Decision.**
- `site-legacy` is gone. Every page is `site-page` (the default in
  `templates/base.html`), and `css/forms.css`, the bare `form`, `input` and
  `button` rules it scoped, and `css/skin_detail.css` (unused since the
  skin page moved) are deleted.
- `tests/test_one_look.py` fails a PR when the site's own CSS or scripts
  carry a color that isn't a `--bv-*` token (hex, `rgb()`/`hsl()` other than
  black for shadows, or a named color), name a font other than
  `var(--bv-font)` or `var(--bv-mono)`, load Oxanium, Google Fonts or the
  particles background, or mention `site-legacy`.
- Exempt: `static/ui/` (the package itself) and `css/halloween.css`, a
  seasonal theme whose future is still open. The chart colors
  (`--site-series-1…4` in `css/base.css`) are exempt until the package has
  series tokens; then they move there.
- The old `/api/` placeholder page redirects to the Developers page.

**Consequences.**
- A new color starts in Bonkverse/ui as a token, then reaches this site in a
  sync PR ([ADR 0013](0013-shared-ui-package.md)).
- The browser checks (`scripts/check_responsive.mjs`,
  `scripts/check_contrast.mjs`) still cover what a source check can't: sizes,
  contrast and states.
