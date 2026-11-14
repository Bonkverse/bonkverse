# ADR 0017: The site account model moved to `accounts` by pinning migration history

**Status:** accepted, 2026-11-14 (RFC-0001 Phase 5, step 5.5c)

**Context.** `BonkUser`, the site account model, is Django's
`AUTH_USER_MODEL`. It lived in `skins/` since the first migration, so every
app that refers to a user did so through `settings.AUTH_USER_MODEL`, both in
code and in its migrations. Django doesn't support changing that setting once
tables exist: a migration that says `settings.AUTH_USER_MODEL` means whatever
the setting is *now*, so switching it silently rewrites what old migrations
did. The rest of Phase 5 moved models with state-only migrations
(`SeparateDatabaseAndState`), and this was the one move that might not be
possible. A spike (branch `spike/user-model`) tried it on local databases
first.

**Decision.** Move it the same way as the other models, plus three steps the
user model needs:
- **Same tables.** `accounts.BonkUser` keeps `db_table = "skins_bonkuser"`;
  its groups and permissions tables are named from it, so they keep
  `skins_bonkuser_groups` and `skins_bonkuser_user_permissions`. No data moves.
- **History is pinned.** Ten migrations written while the user was
  `skins.BonkUser` said `to=settings.AUTH_USER_MODEL` and
  `swappable_dependency(settings.AUTH_USER_MODEL)`. They now say
  `to="skins.bonkuser"` and `("skins", "__first__")`, exactly what the
  setting resolved to when they ran, so the switch can't change their meaning.
  Editing applied migrations is safe here because the state they describe is
  identical; `tests/test_user_model.py` keeps them pinned.
- **The user exists in `accounts` from its first migration.** Django's own
  `admin.0001` (which we can't edit) depends on the user app's first
  migration, so `accounts.0001` also creates `BonkUser` in Django's state
  (state only, plus a dependency on `auth`). Otherwise a fresh database fails
  creating the admin log.
- Then state-only migrations point every user field at `accounts.BonkUser`
  (`accounts.0002`, `players.0008`, `public_api.0003`, `skins.0034`), and
  `skins.0034` drops the model from skins' state. `accounts.0002` relabels the
  content type `skins.bonkuser` → `accounts.bonkuser` in place (same id), so
  permissions and admin history follow.

**Checked before shipping:**
- A database at main's schema with users, a group, a direct permission, a link, a vote, a favorite and an admin log entry migrates with a byte-identical schema and every row kept.
- A fresh database ends up identical to an upgraded one.
- `migrate accounts 0001` goes back with the label restored.
- Every migration in the move is state-only (no SQL).

**Alternatives considered.**
- *Leave the model under the `skins` label for good*: no risk, but `accounts`
  would own sign-in while the account itself lived in `skins`.
- *A new user table and a data copy*: what Django's docs imply, but it moves
  every row and every foreign key for no gain over keeping the table.
- *Insert a new first migration in `accounts`*: needs `migrate --fake` in
  production (it would be "applied after" `accounts.0001`), which we don't do.

**Consequences.**
- The admin page for site accounts is `/admin/accounts/bonkuser/`. Old
  `/admin/skins/bonkuser/…` links redirect. Permission names are
  `accounts.*_bonkuser`.
- New migrations refer to the user through `settings.AUTH_USER_MODEL` as
  usual; only the ten pinned ones spell it out.
- Deploy at a quiet time and don't use the admin during it: an old container
  doing admin work after the relabel could create a stray `skins.bonkuser`
  content type (harmless; `remove_stale_contenttypes` clears it).
- Rollback: `migrate accounts 0001` with this code first, then redeploy the
  old code, then `remove_stale_contenttypes` (runbook, "Deploying").
