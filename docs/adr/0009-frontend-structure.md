# ADR 0009: One copy of each page behavior, in static files

**Status:** accepted, 2026-11-05 (RFC-0001 Phase 3: #42, #43, #44, #45, #46)

**Context.** Before Phase 3, each page carried its own copy of shared
behavior inside its template:

- `getCSRF` was written 3 times and `postForm` 4 times.
- The wear + bonk.io login flow existed 3 times, one of them a separate
  `<dialog>` on the skin page. The reappearing-modal bug of
  [2026-11-05](../incidents/2026-11-05-bonk-rate-limit.md) had to be found
  and fixed in each.
- Skin-card markup was written in 5 templates, and the card JavaScript
  (menu, zoom, Wear) in 2.
- Even after the request and wear helpers were shared (#43), templates held
  34 inline `style=""` attributes, 9 `<style>` blocks, 18 inline `<script>`
  blocks and 29 `onclick`-style handlers.

The copies drifted. Phase 3 found, among others: leaderboard image zoom that
never worked, a share-page button calling a function that didn't exist, and
server-list filters that broke as soon as a tag was selected. All three were
in copies nobody was looking at.

**Decision.**
- Behavior shared by pages lives once, in `skins/static/core/js/`, loaded by
  `base.html` and exposed as a small global: `BVApi` (requests), `BVWear`
  (wearing + the bonk.io login modal), `BVCards` (skin cards, image zoom),
  `BVReport` (reporting), plus `bv-boot.js` for what every page does on load.
  Shared markup lives once, in a partial (`_bonk_login_modal.html`,
  `_report_skin_modal.html`, `_skin_card.html`, `_skin_card_compact.html`).
- A page's own behavior is a file in `skins/static/js/`, its own styles a
  file in `skins/static/css/`. Templates hold markup and pass data through
  `data-` attributes or `json_script`. No inline scripts, handlers or styles,
  except a computed value as a CSS custom property.
- Card data comes from one selector, `decorate_skins_for_user`, in a fixed
  number of queries.
- `tests/test_frontend.py` and `tests/test_query_budgets.py` enforce this.
- No framework and no build step for now. Plain scripts with globals match
  how the site already loads, need no tooling, and keep this change a pure
  move that screenshots can check.

**Consequences.**
- A fix to wearing, reporting or a card reaches every page at once.
- Changing a shared script changes every page that uses it: click through
  the pages listed in its header comment, not just the one you were on.
- Globals load in a fixed order in `base.html`; a shared script may use the
  ones loaded before it.
- Scripts are separate files (more requests, cached by WhiteNoise); no
  bundling or minification until a build step is chosen.
- A Content-Security-Policy without `'unsafe-inline'` for scripts is now
  possible (only `500.html` and `json_script` data remain inline).
- The next step, a design system and maybe React islands or htmx, is
  RFC-0002, and starts from this layout.
- Reference: [architecture/frontend.md](../architecture/frontend.md).
