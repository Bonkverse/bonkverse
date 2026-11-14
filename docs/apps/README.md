# Apps: what each one owns

RFC-0001 Phase 5 (finished 2026-11-14) split the old do-everything `skins` app into domain apps. This page is the map: which app owns what, the rules between apps, and how an app is created or a model moved. Each app has its own page here (`docs/apps/<app>.md`); why it's built this way: [ADR 0018](../adr/0018-domain-apps-and-their-boundaries.md) and [ADR 0019](../adr/0019-models-move-without-moving-tables.md).

**Decide where new code goes by asking two questions:** which domain does it belong to (the table below), and which layer (the file table in [CONTRIBUTING](../../CONTRIBUTING.md#where-code-goes)).

## The apps

| App | Owns | Notes |
|---|---|---|
| [`site_pages`](site_pages.md) | Home, privacy, terms, staff page, small tools (map decoder) | No models of its own |
| [`communities`](communities.md) | Discord server directory: servers, tags, snapshots, submit, the hourly refresh | Hourly refresh task keeps its old name `skins.tasks.refresh_discord_servers` |
| [`stats`](stats.md) | Leaderboards (one config entry per board) and archived win/loss rows; future stat tracking | New board = one `LEADERBOARDS` entry ([recipe](stats.md#adding-a-board)) |
| [`players`](players.md) | bonk.io players, friendships, Flash friends, friend sync, player search and profiles, social stats, replay sync, XP calculator, profile privacy | Friend sync task keeps its old name `skins.tasks.sync_friends` |
| [`accounts`](accounts.md) | Site accounts (`BonkUser`), bonk.io account links and their tokens, sign in / out, `/api/me/` | `AUTH_USER_MODEL` is `accounts.BonkUser` ([ADR 0017](../adr/0017-user-model-moved-by-pinning-history.md)); also the event log (`log_event`, `UserEvent`) |
| [`skins`](skins.md) | Skins, votes, favorites, reports, images, search, categories, upload, wear, edit | The original app, now only the gallery |
| [`public_api`](public_api.md) | `/api/v1/`, API keys, the developer portal | Behavior and key handling: [public-api.md](../architecture/public-api.md) |

Shared packages (not apps): `core/` (cross-cutting helpers: auth guards, bonk.io types, token encryption, pagination, periods, logging, rate limits, background work) and `integrations/` (one client per outside system; [integrations.md](../architecture/integrations.md)).

## Rules between apps

Enforced by `tests/test_app_boundaries.py`:

- An app uses another app only through its **`services`** (business rules, writes), **`selectors`** (read queries for pages) or **`models`** (for foreign keys and reading fields). Never its views, URLs, templates, tasks or helper modules.
- Writes to another app's data go through that app's `services` (reviews check this; the test can't).
- `core/` and `integrations/` import no app.
- Need something another app has in a helper module? Add a function to its `selectors` or `services` and use that.
- **Templates:** every page extends the shared frame `base.html` (in the project's `templates/`, with the header, footer, error pages and generic partials: pagination, the bonk.io login modal) and may include the skin partials in `skins/templates/skins/partials/` (cards, carousels, search bar, report modal): those are the skins app's public UI, the template equivalent of its selectors. Other apps' page templates are off-limits. The frame's files (the `ui/` package, `core/js`, images, site-wide CSS and JS) are in the project's `static/`.

- Two apps may need each other (accounts' login updates players; players writes to accounts' event log). If that makes an import cycle, the side that needs the other only occasionally imports inside the function, with a comment saying why (`players/friends_sync.py`). The same test imports each app's `services` and `selectors` first in a fresh interpreter, so a cycle fails CI.

Exceptions would be listed in the test's `ALLOWED` with a reason. It has been empty since 5.7, and stays that way unless a review agrees to one.

## URL names are namespaced

Every URLconf sets `app_name`, one namespace per file: `skins`, `site_pages`, `accounts`, `stats`, `communities`, `players`, `public_api` (`/api/v1/`) and `developers` (`/developers/`, `public_api/portal_urls.py`). A name is always used with its prefix: `{% url 'players:player_profile' name %}`, `reverse("skins:skin_detail", args=[id])`, `LOGIN_URL = "accounts:login"`. Names inside a file keep their old spelling; `request.resolver_match.url_name` is still the bare name.

## Every URL path is pinned

`tests/test_url_snapshot.py` compares the URL conf with `tests/fixtures/url_routes.json`. Moving a view to another app must keep its path. Adding a route, or renaming a URL name, means updating that file in the same PR (and every `{% url %}` / `reverse()` for a rename):

```bash
python -m tests.test_url_snapshot > tests/fixtures/url_routes.json
```

## How a move is done

One app per PR, in two kinds of PR:

1. **Code first.** Views, templates, static files, URLs, services, tasks, commands move into the new app; the app's `urls.py` is included from the root URL conf. Models stay where they are. Refactor only: no behavior change, same paths, full suite green.
2. **Models last, one app per deploy.** The model classes move with `SeparateDatabaseAndState` and `Meta.db_table` set to the existing table name, so the tables and data stay exactly where they are (no `migrate --fake`). The same migration updates `django_content_type.app_label`, so admin history and permissions follow the model. Before merging, check `manage.py migrate --plan` and `sqlmigrate`: the move must run no SQL against the moved tables, on a fresh database and when upgrading from `main`.

### Moving models, step by step

The first model move was `communities` (5.2b); its `communities/migrations/0001_initial.py` and `skins/migrations/0030_move_discord_models_to_communities.py` are the template.

1. Copy the model classes into the new app's `models.py` and delete them from the old one. In the moved classes set:
   - `Meta.db_table` to the existing table (`skins_<model>`);
   - `db_table` on every `ManyToManyField` to the existing join table (`skins_<model>_<field>`), or Django will want a new one;
   - the existing `name` on every `Meta.indexes` entry (copy it from the old migration or `\d table` in psql), because auto names include the app label.
2. Point every import at the new app. A function a field uses (a validator, a default, `upload_to`) that the old app's migrations import by path must stay importable there: move it to its new home and leave the old name as an alias (`skins.models.validate_username` → `core.validators.validate_bonk_username`).
3. `makemigrations <new> <old>` generates a `CreateModel` set and a `DeleteModel` set. Wrap each in `SeparateDatabaseAndState(state_operations=[...], database_operations=[])`.
4. Order them: the new app's migration depends on the old app's latest; the old app's migration depends on the new app's. Add a reversible `RunPython` in the new app's migration that relabels `django_content_type` rows in place (skip a model whose row already has the new label, as on a fresh database).
5. Check on a database at `main`'s schema with a few rows: `migrate --plan`, `sqlmigrate` for both (no-op plus the `RunPython`), `pg_dump --schema-only -t '<tables>'` identical before and after, rows still there, content types relabelled, `migrate <new> zero` then `migrate` again, a fresh database, `makemigrations --check` clean.
6. Add a test pinning `_meta.db_table` for each model, the join table and index names, and the relabel both ways (see `tests/test_communities.py`).

The user model (`AUTH_USER_MODEL`) needed more: old migrations that said `settings.AUTH_USER_MODEL` are pinned to the model they meant, and the model exists in the new app's first migration because Django's admin depends on it. See [ADR 0017](../adr/0017-user-model-moved-by-pinning-history.md).

A task that moves keeps working for already-queued messages and saved schedules: either keep its registered name (`@shared_task(name="skins.tasks.x")`) or migrate the `PeriodicTask.task` rows in the same PR.

## Creating an app

```
<app>/
  __init__.py
  apps.py          # AppConfig with a docstring: what it owns
  models.py        # data + invariants
  services.py      # business rules; plain typed functions
  selectors.py     # read queries for pages (add when needed)
  views/           # thin: parse -> service/selector -> response
  urls.py          # included from bonk_skin_search/urls.py
  tasks.py         # Celery entry points (if any)
  templates/<app>/
  static/<app>/
  migrations/
docs/apps/<app>.md # purpose, models, services, routes, outside calls, quirks
```

Add it to `INSTALLED_APPS`, add its row to the table above, and write its page.
