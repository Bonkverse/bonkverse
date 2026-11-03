## What and why

<!-- One or two sentences. Link the issue: Closes #123 -->

## Type

- [ ] Feature / behavior change
- [ ] Refactor (no behavior change)
- [ ] Bug fix (regression test included)
- [ ] Docs / tooling only

Refactor commits contain no behavior changes, and feature commits contain no refactors.

## Checklist (RFC-0001 recipe)

- [ ] Code lives in the owning app and the right layer (views thin, logic in services, external calls in integrations)
- [ ] Model changes have a migration
- [ ] New or changed services/integrations have tests; a fixed bug has a test that reproduced it first
- [ ] Frontend calls go through `bv-api.js`; UI reuses existing partials (once Phase 3 lands)
- [ ] No commented-out code, `print()`, or untracked `TODO` (use `TODO(#issue)`)
- [ ] Config read from settings/env, not hardcoded
- [ ] Docs updated in this PR if behavior changed (README, `docs/`, bonk.io quirks tagged `# BONK:`)
- [ ] Changelog entry added; `navbar.html` updated if a nav item was added
