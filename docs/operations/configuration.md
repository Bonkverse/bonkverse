# Configuration

Every setting is read once, in `bonk_skin_search/settings.py`, from environment
variables. App code reads `django.conf.settings`, never `os.environ` (a test
enforces this). Locally, put values in `.env` (start from `.env.example`);
in production, set them on the Railway `bonkverse` service.

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
| `SYNC_FRIENDS_ON_LOGIN` | `1` (sync friends in a background thread after login) |

## Capacity and limits

| Variable | Default | See |
|---|---|---|
| `WEB_CONCURRENCY` / `GUNICORN_THREADS` / `GUNICORN_TIMEOUT` | `4` / `4` / `30` | [ADR 0001](../adr/0001-gunicorn-threaded-workers.md) |
| `SEARCH_STATEMENT_TIMEOUT_MS` | `3000` | [search.md](../search.md) |
| `RATE_LIMIT_<TIER>` (e.g. `RATE_LIMIT_SEARCH=60/m`) | per tier | [rate-limiting.md](rate-limiting.md) |
| `TRUST_PROXY_HEADERS` | `true` in production | [rate-limiting.md](rate-limiting.md) |
| `LOG_LEVEL` | `INFO` | Level for this app's loggers (`skins.*`, `core.*`) |

## Railway build and deploy

Pinned in `railway.json`, not the dashboard: build from the `Dockerfile`
(which runs `collectstatic`; the container runs `migrate` then gunicorn), and a
healthcheck on `/` that must pass before a deploy takes traffic.
See [ADR 0004](../adr/0004-dockerfile-build-and-healthcheck.md).
