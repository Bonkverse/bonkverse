# ADR 0018: Domain apps that use each other only through services, selectors and models

**Status:** accepted, 2026-11-14 (RFC-0001 Phase 5)

**Context.** Until November 2026 almost everything lived in one Django app,
`skins`: skins, but also site accounts and login, bonk.io players and friends,
leaderboards, the Discord directory, the home and legal pages, the event log
and the page frame. Its views file was thousands of lines, any module could
import any other, and the only way to know what a change touched was to read
everything. RFC-0001 Phase 5 set out to split it by domain without changing
a single URL or table.

**Decision.**
- **Six domain apps plus the public API**, each owning one area and documented
  in `docs/apps/<app>.md`: `site_pages`, `communities`, `stats`, `players`,
  `accounts`, `skins`, and the existing `public_api`. Two shared packages are
  not apps: `core/` (cross-cutting helpers) and `integrations/` (the only code
  that calls outside services, ADR 0006).
- **An app uses another only through its `services`** (business rules and
  writes), **`selectors`** (read queries for pages) **or `models`** (foreign
  keys, reading fields). Never its views, URLs, templates, tasks or helper
  modules. A helper another app needs is re-exported from `services` or
  `selectors`, which makes it part of the app's public surface on purpose.
  `core/` and `integrations/` import no app.
- **Writes to another app's data go through that app's services**, so its
  rules (locks, counters, logging) can't be skipped.
- **Templates follow the same rule.** Pages extend the project's frame
  (`templates/base.html` and `templates/partials/`) and may include another
  app's published partials (the skin cards in `skins/templates/skins/partials/`),
  never another app's page templates.
- **URL names are namespaced by app** (`skins:skin_detail`); every path stayed
  what it was and is pinned by `tests/test_url_snapshot.py`.
- **Apps may depend on each other in both directions** (accounts' login updates
  players; players writes to accounts' event log). When two apps' services
  need each other at import time, the side that only needs the other
  occasionally imports inside the function that uses it, with a comment.

**Enforced by** `tests/test_app_boundaries.py`: it parses every app file and
fails on an import of another app's private module, and it imports each app's
`services` and `selectors` first in a fresh interpreter, so an import cycle
fails CI instead of failing whichever process happens to load the wrong module
first. Its `ALLOWED` list of exceptions is empty and may only shrink: a new
exception needs a reason in review.

**Alternatives considered.**
- *Keep one app and split it into packages*: less churn, but nothing would stop
  imports across areas, and every model would still say `skins`.
- *Separate services (microservices)*: the site is one deploy with one
  database; the cost buys nothing at this size.
- *Layering only by technical role (all views together, all services together)*:
  makes a change to one feature touch every folder.
- *Rename URL paths to match apps*: would break links, bookmarks, the
  extension and partners; paths are not ours to change.

**Consequences.**
- A new feature starts with "which app owns it" (`docs/apps/README.md`) and
  "which layer" (CONTRIBUTING, "Where code goes").
- Table names still say `skins_*` for models that moved
  ([ADR 0019](0019-models-move-without-moving-tables.md)); renaming them is a
  separate, planned change.
- Celery tasks that moved kept their registered names (`skins.tasks.sync_friends`,
  `skins.tasks.refresh_discord_servers`) so queued runs and saved schedules keep
  working.
