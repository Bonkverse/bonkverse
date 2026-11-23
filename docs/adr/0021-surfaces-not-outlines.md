# ADR 0021: Surfaces, not outlines; teal glow only for a highlight

**Status:** accepted, 2026-11-22

**Context.** In the Bonkverse Discord (2026-11-22), players liked what the
site does but not how it looked: "not every UI component needs a shiny
outline", the glow "makes it look like AI slop", "the most shoegaze website
ever". The code showed why. About 66 CSS rules across this site and
Bonkverse/ui drew a teal (`--bv-link`) border or ring, and every card,
notice and nested tile had its own border, so borders stacked and nothing
stood out. The owner compared three versions of the profile Friends tab
(today, hairline borders, borderless) and picked **borderless**, keeping the
teal glow only for what's worth the user's attention. The plan is in the
Project doc `claude/design-feedback-2026-11-22.md`.

**Decision.**
- **Surfaces draw the edges.** Bonkverse/ui v0.1.6:
  - darkens the page and card;
  - adds `--bv-inset` for things inside a card;
  - gives `.bv-card` and `.bv-skin-card` a transparent border, which forced-colors mode still draws, plus `--bv-card-shadow`.
- **No borders on surfaces.**
  - Top-level cards get the shadow.
  - Things inside a card get `--bv-inset`.
  - Hover is a fill (`--bv-hover`), not a border.
  - Fields and buttons keep `--bv-control` borders, so people can find them.
- **Teal means one of three things:**
  - keyboard focus;
  - the selected item in a group: fill plus a 1px teal border, so selection isn't shown by fill alone (WCAG 1.4.11);
  - a control's own on-state: a checked switch, a range thumb.
- **The highlight.** `.bv-highlight` is a teal ring plus a soft glow, used at
  most once per view, for:
  - the week's most active player;
  - your own row in a list;
  - something new;
  - something to do. The first use is the new API key, shown once.
- **Read-only pills are labels.** Their text carries them, so
  `scripts/check_contrast.mjs` checks their text, not their edge.
- **Charts** use the package's `--bv-series-1…4`. The site's own
  `--site-series` block and its exemption in
  [ADR 0020](0020-one-look-held-by-tests.md) are gone.

**Consequences.**
- **The test:** `tests/test_one_look.py` fails a PR when the site's CSS draws a
  `--bv-link` border, outline or box-shadow on any selector except these:
  - focus, `:checked` and `[open]`;
  - selected: `aria-pressed`, `aria-current`, `aria-selected`, `.selected`;
  - `.bv-highlight`;
  - range thumbs;
  - the level chart's legend line.
- **The active page in pagination** is marked `aria-current="page"`, which
  screen readers announce and the style keys on.
- **"One highlight per view" is a review rule, not a test.** A reviewer checks
  that a page with `.bv-highlight` has only one.
