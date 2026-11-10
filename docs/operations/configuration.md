# Configuration

Every setting is read once, in `bonk_skin_search/settings.py`, from environment
variables. App code reads `django.conf.settings`, never `os.environ` (a test
enforces this). Locally, put values in `.env` (start from `.env.example`);
in production, set them on the Railway `bonkverse` service (and the `worker`
service where it needs them; see "Background worker").

Defaults are chosen so local development works with only the required ones set.

## Required

| Variable | What | Notes |
|---|---|---|
| `SECRET_KEY` | Django secret | Startup fails without it (the Docker build uses a dummy). |
| `DATABASE_URL` | Postgres URL | Production: reference `${{BonkverseDB.DATABASE_URL}}`. |
| `ENV` | `production` or anything else | `production` turns off DEBUG, sets secure cookies, trusts proxy headers. |

## Redis

| Variable | Default | Notes |
|---|---|---|
| `REDIS_URL` | unset → in-memory cache | Production: **always the reference `${{Redis.REDIS_URL}}`**, never a hand-typed URL. Checked at startup: a URL that can't be parsed stops the app ([incident](../incidents/2026-11-03-redis-rotation.md)). Never print or log it. |

## Other Bonkverse services

| Variable | Default | Used by |
|---|---|---|
| `BONKVERSE_BASE_URL` | `https://bonkverse.io` | Absolute URLs (Cloudflare purge, restore script). Page links are relative. |
| `BONKVERSE_EDITOR_URL` | `http://localhost:5173` | "Skin Editor" / "Open in editor" links |
| `BONKVERSE_REPLAYS_URL` | `http://localhost:5173` | "Replays" link; player profiles read its `/api/player/<name>` (`integrations/replays.py`) |
| `PLAYER_PROFILE_CACHE_SECONDS` | `300` | How long a player profile's replay stats are cached |
| `BONKVERSE_DOCS_URL` | `https://docs.bonkverse.io` | Docs links on the developer portal (`/developers/`) |
| `PUBLIC_API_MAX_KEYS_PER_USER` | `3` | Active API keys one account may create in the developer portal |
| `BONKVERSE_RENDER_URL` | `https://editor.bonkverse.io` | Staff re-render (`/api/render-bundle`). Production's works from local. |
| `BLSKIN_FETCHER_URL` | production fetcher | Upload from BonkLeagues |
| `BONKBOT_API_URL` | production BonkBot | `/api/join-matchmaking/` (`integrations/bonkbot.py`) |
| `DECODER_SERVICE_URL`, `DECODER_SERVICE_KEY` | unset | Tools → Map Decoder (`integrations/map_decoder.py`; 503 when unset) |
| `CLOUDFLARE_ZONE_ID`, `CLOUDFLARE_CACHE_API_TOKEN` | unset | Edge cache purge after re-render (`integrations/cloudflare.py`; skipped when unset, failures logged as `cloudflare purge failed`) |
| `SENTRY_DSN` | unset | Error reporting |

## bonk.io account API

Used by login, friend sync and wearing skins (`integrations/bonk_api.py`,
[bonk/api.md](../bonk/api.md)).

| Variable | Default |
|---|---|
| `BONK_API_BASE_URL` | `https://bonk2.io/scripts` |
| `BONK_CONNECT_TIMEOUT` / `BONK_READ_TIMEOUT` | `4` / `8` seconds, for every call (wear used a flat 10 before Phase 2.2) |
| `SYNC_FRIENDS_ON_LOGIN` | `1` (queue the friend sync on the worker after login) |

## Capacity and limits

| Variable | Default | See |
|---|---|---|
| `WEB_CONCURRENCY` / `GUNICORN_THREADS` / `GUNICORN_TIMEOUT` | `4` / `4` / `30` | [ADR 0001](../adr/0001-gunicorn-threaded-workers.md) |
| `SEARCH_STATEMENT_TIMEOUT_MS` | `3000` | [search.md](../search.md) |
| `RATE_LIMIT_<TIER>` (e.g. `RATE_LIMIT_SEARCH=60/m`) | per tier | [rate-limiting.md](rate-limiting.md) |
| `TRUST_PROXY_HEADERS` | `true` in production | [rate-limiting.md](rate-limiting.md) |
| `LOG_LEVEL` | `INFO` | Level for this app's loggers (`skins.*`, `core.*`) |

## Background worker

How background jobs work: [architecture/background-work.md](../architecture/background-work.md).

| Variable | Default | Notes |
|---|---|---|
| `CELERY_CONCURRENCY` | `2` | Worker processes. Each holds one Postgres connection while it works. |
| `CELERY_TASK_ALWAYS_EAGER` | `0` | Local only: run queued tasks inline, no worker needed. **Never in production.** |

The `worker` Railway service needs the variables its code reads at startup and
its tasks' integrations use, set as references to `bonkverse`'s values
(`${{bonkverse.SECRET_KEY}}` and so on, never copies): `SECRET_KEY`,
`DATABASE_URL`, `REDIS_URL`, `ENV`, `SENTRY_DSN`; for the replay sync
`BONKVERSE_SYNC_TOKEN` and `BONKVERSE_REPLAYS_URL` (and
`REPLAY_SYNC_INTERVAL_SECONDS` if `bonkverse` sets it); for the friend sync the
`BONK_*` variables if `bonkverse` sets any. It needs no `PORT` and no volume.

| Variable | Default | Notes |
|---|---|---|
| `BONKVERSE_SYNC_TOKEN` | unset → replay sync off | Shared secret for the replay site's internal sync endpoints (`integrations/replay_sync.py`). Worker and web. |
| `REPLAY_SYNC_INTERVAL_SECONDS` | `3600` | How often the worker runs `players.tasks.sync_replays`. Its time limit (28 min) must stay under this. |

## Railway build and deploy

Pinned in `railway.json`, not the dashboard: build from the `Dockerfile`
(which runs `collectstatic`; the container runs `migrate` then gunicorn), and a
healthcheck on `/` that must pass before a deploy takes traffic.
See [ADR 0004](../adr/0004-dockerfile-build-and-healthcheck.md).

The `worker` service uses `railway.worker.json` (set as its config file path in
the service settings): the same Dockerfile, started with
`celery -A bonk_skin_search worker --beat`, no healthcheck, one replica
([ADR 0010](../adr/0010-background-work-on-celery.md)).
