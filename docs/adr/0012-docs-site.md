# ADR 0012: The platform docs site is Docusaurus, at docs.bonkverse.io

**Status:** accepted, 2026-11-08

**Context.** RFC-0001 ("Documentation") splits docs in two: each repo's
`docs/` for how one system works, and a platform-wide `Bonkverse/docs` repo,
published as a site, for architecture, cross-service contracts, RFCs, ADRs
and the bonk.io reference. It left the site tool open: MkDocs Material
(Python, fits this repo) or Docusaurus (JS, fits the editor and SDK side).
The public API ([ADR 0011](0011-public-api.md)) made the question real: its
readers are developers on other sites, who need copy-paste examples in
several languages.

**Decision.**
- `Bonkverse/docs` is a Docusaurus site at `docs.bonkverse.io`, published by
  GitHub Pages from `main` (the host RFC-0001 named). Pull requests build it,
  and a broken link or anchor fails the build.
- The public API guide is its first section, under `/api/`. Platform docs
  move there next, each section with its own sidebar.
- Why Docusaurus over MkDocs Material: tabbed examples whose language choice
  sticks across pages, React components where a page needs one, and the same
  JavaScript toolchain as the editor, replay site and extension. The cost is
  a Node toolchain for writing docs, which this repo's contributors already
  have for the editor.
- Each repo keeps its own `docs/` (this repo's architecture pages, runbooks,
  ADRs). A PR that changes a cross-service contract here links its matching
  `Bonkverse/docs` PR; the PR template asks for it.
- `developers.bonkverse.io` is kept for a developer portal (signing in and
  managing API keys), which would be part of this Django app. It links to the
  docs rather than hosting them.

**Consequences.**
- RFC-0001's "MkDocs Material" line is superseded by this ADR.
- Two repos means two PRs for an API change; the link between them is a
  habit the PR template enforces, not a check.
- RFC-0001 itself and the platform-level ADRs move to `Bonkverse/docs` as its
  next section.
