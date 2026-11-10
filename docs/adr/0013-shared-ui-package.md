# ADR 0013: One UI package for every Bonkverse site

**Status:** accepted, 2026-11-09

**Context.** bonkverse.io, the replay site and the docs each had their own
colors, fonts, header and buttons (the design review counted 55 font sizes,
323 colors and 34 button classes on bonkverse.io alone). RFC-0002 ("One
Bonkverse look") and the Skin card design guide set one look: three themes
(Bonkverse, Bonkverse Light, Bonkverse Dark), Jost, a brown main action, the
guide's skin card, and one header for every site.

**Decision.**
- The look lives in its own repo, `Bonkverse/ui`: plain CSS, two small
  scripts and `nav.json`, no build step, released as git tags. A gallery
  page shows every component in all three themes, and CI checks contrast
  (WCAG AA) and 21 screen sizes on every change.
- This site copies a release into `skins/static/ui/` with
  `scripts/sync_ui.py` and commits it, keeping the no-build-step rule
  ([ADR 0009](0009-frontend-structure.md)). A test fails if those files are
  edited here. The React sites install the same tag as an npm dependency.
- The header and footer come from `nav.json`, so a link changes once for
  every site.
- Every page follows the theme from day one: the site's own CSS uses the
  `--bv-*` tokens instead of hard-coded colors. Pages then move onto the
  `bv-` components one at a time.
- Log out is a POST form in the account menu, and `/logout/` refuses GET.

**Consequences.**
- Changing the look is two PRs: one in Bonkverse/ui, then a sync here with
  before and after screenshots.
- `skins/static/ui/` holds 16 copied files (about 120 KB), fonts included.
  `.gitattributes` keeps its PNG out of Git LFS so the hashes match and the
  deploy needs no LFS fetch.
- Three site classes were renamed (`site-toast`, `site-pagination`,
  `site-num`) because the package uses those `bv-` names.
