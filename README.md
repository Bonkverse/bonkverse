Bonkverse
=========

**Bonkverse** is the resource hub for everything related to the game **Bonk.io** --- skins, players, search, stats, tools, and community data.

This repository contains the Django backend that powers [bonkverse.io](https://bonkverse.io). The skin editor (`editor.bonkverse.io`) and replay tools live in their own repos.

**Docs:** [docs/](docs/README.md) covers how requests flow, every environment variable, the production runbook, rate limiting, search, past incidents and design decisions.

## TL;DR — Quick Start (Local Dev)

```bash
git clone https://github.com/Bonkverse/bonkverse.git
cd bonkverse

python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # app + test/lint tooling
pre-commit install                    # lint + format on every commit

cp .env.example .env
docker compose up -d                  # Postgres (5433) + Redis (6379)

python manage.py migrate
python manage.py populate_all         # fake local data, safe to re-run

python manage.py runserver            # http://localhost:8000
pytest                                # run the test suite
```

Tech Stack
-------------

-   **Python 3.13 / Django 5.2**
-   **PostgreSQL** (full-text search, `pg_trgm`, `unaccent`)
-   **Redis** (cache, rate limiting, Celery broker)
-   **Celery** + `django-celery-beat`
-   **Railway** (production, built from the `Dockerfile`)
-   **Cloudflare** (production edge / protection)
-   **Sentry** (error reporting)


Local Development Setup
--------------------------

Bonkverse is designed to run **fully locally**, without touching production.

### Prerequisites

-   Python **3.13**
-   Docker & Docker Compose
-   Git
-   Cairo (for CairoSVG): `brew install cairo` on macOS, `apt install libcairo2` on Debian/Ubuntu


### 1. Virtual environment and dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pre-commit install
```

`requirements.txt` is what production installs. `requirements-dev.txt` adds pytest, ruff and the security scanners. `requirements-scripts.txt` adds what the hand-run scripts in `scripts/` need (openai for `label_skins.py`).


### 2. Environment variables

Copy the example and adjust if needed (`.env` is never committed):

```bash
cp .env.example .env
```

```bash
ENV=local
SECRET_KEY=dev-insecure-secret-key
DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5433/bonkverse
REDIS_URL=redis://localhost:6379/0
```

> Do **not** include quotes around values.

Redis is required, not optional: `django-ratelimit` refuses to start with an in-memory cache.


### 3. Start Postgres + Redis

```bash
docker compose up -d
```

This starts PostgreSQL on port **5433** and Redis on port **6379**.


### 4. Migrate and seed

```bash
python manage.py migrate
python manage.py populate_all
```

`populate_all` installs the Postgres extensions search needs (`pg_trgm`, `unaccent`), then fills most models with fake data. It **does not** use production data and is safe to run multiple times. To install only the extensions: `python manage.py init_pg_extensions`.


### 5. Run the server

```bash
python manage.py runserver
```

-   Site: `http://localhost:8000`

Log in with your real bonk.io account; it creates a user in your **local** database only. To give that user staff access (the `/staff/` page, re-render buttons):

```bash
python manage.py shell -c "from skins.models import BonkUser; BonkUser.objects.filter(username='YourBonkName').update(is_staff=True)"
```

There is no `createsuperuser`: site accounts have no passwords because login goes through bonk.io. To make yourself a superuser for `/admin/`, run `python manage.py grant_admin "YourBonkName"` ([ADR 0005](docs/adr/0005-admin-login-through-bonk.md)).

### 6. Background jobs (optional)

Scheduled jobs (the hourly Discord refresh) and work queued after login run on a Celery worker. In a second terminal:

```bash
celery -A bonk_skin_search worker --beat --loglevel INFO
```

Or set `CELERY_TASK_ALWAYS_EAGER=1` in `.env` to run queued jobs inline without a worker. See [docs/architecture/background-work.md](docs/architecture/background-work.md).


Tests, Linting and CI
------------------------

```bash
pytest                          # full suite (needs Postgres + Redis running)
pytest tests/test_wear.py -x    # one file, stop at first failure
pytest --cov                    # with coverage

ruff check .                    # lint
ruff format .                   # format
pre-commit run --all-files      # everything the commit hook runs
```

-   Tests run against **real Postgres**, because search depends on Postgres-only features.
-   Tests never call bonk.io or any other outside service. Register fake replies on the `mocked_http` fixture (recorded bonk.io bodies are in `tests/fixtures/bonk/`); an un-mocked request fails the test.
-   `tests/test_architecture.py` fails if anything outside `integrations/` makes outside HTTP calls ([ADR 0006](docs/adr/0006-outside-calls-through-integrations.md)).
-   `tests/test_smoke.py` requests every route automatically. Known bugs are marked `xfail(strict=True)`: when you fix one, the test turns red until you remove its mark.

Every push and pull request runs `.github/workflows/ci.yml`: ruff, pytest on Postgres, a migrations check, `pip-audit`, `bandit` and `manage.py check --deploy`. `main` only accepts changes with a green run.


Working with the Database
----------------------------

### Django shell

```bash
python manage.py shell_plus
```

```python
Skin.objects.count()
Skin.objects.filter(name__icontains="dragon")[:10]
BonkPlayer.objects.all()[:5]
```

### Database shell (psql)

```bash
python manage.py dbshell
```

If `psql` is missing on macOS: `brew install libpq && brew link --force libpq`.

### Resetting the local database

```bash
python manage.py reset_db       # from django-extensions
python manage.py migrate
python manage.py populate_all
```


Project Structure
--------------------

```
bonkverse/
├── bonk_skin_search/       # Django project: settings, root urls, celery app
├── core/                   # shared helpers; core/bonk/ = bonk.io types (slots, usernames, skin codes, session)
├── integrations/           # one client per outside service; the only code that makes outside HTTP calls
├── players/                # player profiles, replay sync, profile privacy, XP calculator
├── public_api/             # /api/v1/, API keys, developer portal
├── site_pages/             # home, privacy, terms, staff, map decoder
├── communities/            # Discord server directory
├── stats/                  # leaderboards: one LEADERBOARDS entry per board
├── skins/                  # the original app, being split into domain apps (docs/apps/README.md)
│   ├── models.py
│   ├── querysets.py        # Skin.objects: with_favorite_count, with_score, created_in, search
│   ├── auth_guards.py      # JSON auth decorators (auth="bonkverse" / auth="bonk")
│   ├── selectors.py        # read-only page queries (decorate_skins_for_user for skin cards)
│   ├── votes.py            # cast_vote: the one way vote counters change (ADR 0014)
│   ├── skin_media.py       # the one writer of skin image files (docs/architecture/skin-images.md)
│   ├── rerender.py         # re-render a skin from its code (button + rerender_skins)
│   ├── sign_in.py          # what a successful bonk.io login does; login.py has the pages
│   ├── friends_sync.py     # friends.php → Friendship edges, in named steps
│   ├── tasks.py            # Celery entry points (friend sync, Discord refresh)
│   ├── templates/skins/    # pages; partials/ holds the skin cards and shared modals
│   ├── static/core/js/     # shared page helpers: BVApi, BVWear, BVCards, BVReport, bv-boot
│   ├── static/js/, css/    # one script / stylesheet per page (docs/architecture/frontend.md)
│   └── management/commands/
├── tests/                  # pytest suite, recorded bonk.io fixtures, pinned URL paths (fixtures/url_routes.json)
├── docs/                   # how things work: apps, architecture, operations/runbook, bonk.io reference, incidents, ADRs
├── scripts/                # one-off maintenance scripts
├── .github/                # CI workflow, Dependabot, PR template
├── Dockerfile              # production image (runs collectstatic at build time)
├── pyproject.toml          # ruff + pytest config
├── requirements.txt        # production dependencies
├── requirements-dev.txt    # + test and lint tooling
└── requirements-scripts.txt # + what scripts/ needs (not in the production image)
```

`staticfiles/` is build output and is not committed; the Dockerfile rebuilds it with `collectstatic`.

The plan for reorganizing this repo, and the conventions new code should follow, are in **RFC-0001: Code Organization & Conventions**. [CONTRIBUTING.md](CONTRIBUTING.md) has the short version.


Production vs Local
----------------------
-   **Local** uses Docker + `.env`
-   **Production** runs on Railway from the `Dockerfile`, behind Cloudflare
-   Never point local code at production databases
-   Never commit `.env` files, tokens, or data exports (`*.csv` is ignored)


Contributing
---------------
See [CONTRIBUTING.md](CONTRIBUTING.md). In short: branch, follow the setup above, keep `pytest` and `pre-commit` green, and open a PR using the template.

If something is unclear or broken locally, please open an issue.


Acknowledgements
-------------------
Bonkverse is built by the Bonk.io community, for the Bonk.io community.


AI Usage
---------------

Yes this code was made with the help of ChatGPT. What does this mean? It means that most likely the code you're about to see is gonna be shit.
The purpose of making this repo public and open source is to step away from AI-generated code into something useful and made by community members.

We hope that you'll bear with us as we undergo this transition of being more community and developer friendly :)
