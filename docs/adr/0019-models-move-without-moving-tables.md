# ADR 0019: A model changes app without its table moving

**Status:** accepted, 2026-11-14 (RFC-0001 Phase 5)

**Context.** Splitting `skins` into domain apps (ADR 0018) meant moving 13
models to other apps, including the user model, on a live database with
real users, votes and history. Django's default for a model that changes app
is to create a new table and drop the old one: a data copy for every row and
every foreign key, a long deploy, and a rollback that loses whatever was
written in between. We also don't use `migrate --fake` in production.

**Decision.** A model moves in Django's *state* only; the database is not
touched.
- The moved class keeps its table: `Meta.db_table = "skins_<model>"`, the
  existing join-table name on every many-to-many field, and the existing name
  on every index (auto names include the app label).
- The new app's migration wraps `CreateModel` in
  `SeparateDatabaseAndState(database_operations=[])`; the old app's migration
  does the same for `DeleteModel`. Each depends on the other's previous
  migration so they always apply in order.
- A reversible `RunPython` relabels the model's `django_content_type` row in
  place (same id), so permissions and admin history follow. It leaves a fresh
  database alone and copes with an empty row left behind by a rollback.
- Anything an old migration imports by path (a validator, a default) stays
  importable there as an alias.
- Code moves first in its own PR; models move last, one app per deploy.

Before each move merged, a database at `main`'s schema with sample rows was
migrated forward, back and forward again: `sqlmigrate` showed no SQL besides
the relabel, `pg_dump --schema-only` of the tables was identical, every row
remained and a fresh database matched. A test per app pins the table, join
table and index names and the relabel. The step-by-step is in
`docs/apps/README.md` ("Moving models, step by step"). The user model needed
more (ADR 0017).

**Alternatives considered.**
- *New tables and a data migration*: what Django does by default; moves every
  row for no gain.
- *`migrate --fake`*: no SQL either, but it records history that didn't
  happen and differs between databases.
- *Leave the models in `skins`*: no risk, but the code would keep saying a
  player or a login belongs to skins.

**Consequences.**
- Every move deployed with no downtime and no data copied. All ran in production
  in November 2026.
- Table names no longer match their app (`skins_bonkplayer` belongs to
  `players`). Renaming tables is possible as its own change (a rename per app
  with a compatibility view under the old name for the deploy, and raw SQL
  updated to use `_meta.db_table`), and is not part of RFC-0001.
- Changing `db_table` or an index name on a moved model makes Django rename the
  real table or index; the pinning tests stop that from happening by accident.
