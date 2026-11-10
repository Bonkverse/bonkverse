# Apps: what each one owns

RFC-0001 Phase 5 splits the old do-everything `skins` app into domain apps. This page is the map: which app owns what, the rules between apps, and how a move is done. Each app gets its own page here (`docs/apps/<app>.md`) in the PR that creates it.

**Decide where new code goes by asking two questions:** which domain does it belong to (the table below), and which layer (the file table in [CONTRIBUTING](../../CONTRIBUTING.md#where-code-goes)).

## The apps

| App | Owns | State |
|---|---|---|
| `site_pages` | Home, changelog, privacy, terms, staff page, small tools (map decoder) | Planned (step 5.1) |
| `communities` | Discord server directory: servers, tags, snapshots, submit, the hourly refresh | Planned (5.2) |
| `stats` | Leaderboards (one config entry per board) and archived win/loss rows; future stat tracking | Planned (5.3) |
| `players` | bonk.io players, friendships, Flash friends, friend sync, player search and profiles, social stats, replay sync, XP calculator, profile privacy | Exists (profiles, replay sync, privacy); the rest moves in 5.4 |
| `accounts` | Site accounts (`BonkUser`), bonk.io account links and their tokens, sign in / out, `/api/me/` | Planned (5.5) |
| `skins` | Skins, votes, favorites, reports, images, search, categories, upload, wear, edit | Today it still holds everything above; it shrinks to this by 5.6 |
| `public_api` | `/api/v1/`, API keys, the developer portal | Exists ([public-api.md](../architecture/public-api.md)) |

Shared packages (not apps): `core/` (cross-cutting helpers: auth guards, events, pagination, periods, logging, background work) and `integrations/` (one client per outside system; [integrations.md](../architecture/integrations.md)).

## Rules between apps

Enforced by `tests/test_app_boundaries.py`:

- An app uses another app only through its **`services`** (business rules, writes), **`selectors`** (read queries for pages) or **`models`** (for foreign keys and reading fields). Never its views, URLs, templates, tasks or helper modules.
- Writes to another app's data go through that app's `services` (reviews check this; the test can't).
- `core/` and `integrations/` import no app.
- Need something another app has in a helper module? Add a function to its `selectors` or `services` and use that.

Exceptions are listed in the test's `ALLOWED` with a reason; the list only shrinks.

## Every URL path is pinned

`tests/test_url_snapshot.py` compares the URL conf with `tests/fixtures/url_routes.json`. Moving a view to another app must keep its path. Adding a route, or renaming a URL name, means updating that file in the same PR (and every `{% url %}` / `reverse()` for a rename):

```bash
python -m tests.test_url_snapshot > tests/fixtures/url_routes.json
```

## How a move is done (Phase 5)

One app per PR, in two kinds of PR:

1. **Code first.** Views, templates, static files, URLs, services, tasks, commands move into the new app; the app's `urls.py` is included from the root URL conf. Models stay where they are. Refactor only: no behavior change, same paths, full suite green.
2. **Models last, one app per deploy.** The model classes move with `SeparateDatabaseAndState` and `Meta.db_table` set to the existing table name, so the tables and data stay exactly where they are (no `migrate --fake`). The same migration updates `django_content_type.app_label`, so admin history and permissions follow the model. Before merging, check `manage.py migrate --plan` and `sqlmigrate`: the move must run no SQL against the moved tables, on a fresh database and when upgrading from `main`.

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
