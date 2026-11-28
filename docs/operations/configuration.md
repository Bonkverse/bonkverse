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
| `BONK_TOKEN_KEYS` | Fernet keys that encrypt stored bonk.io tokens, comma-separated, newest first ([ADR 0016](../adr/0016-bonk-tokens-encrypted-at-rest.md)) | Production refuses to start without it. Never derived from `SECRET_KEY`. Unset outside production: a public development key. Set and rotate: [runbook](runbook.md#bonkio-token-keys-set-rotate-or-recover). |

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
| `BONK_LOGIN_SITE_PER_MINUTE` | `4` password logins sent to bonk.io per minute, whole site (`0` = no cap) |
| `BONK_LOGIN_ACCOUNT_PER_MINUTE` | `1` per bonk.io account per minute (`0` = no cap) |
| `BONK_LOGIN_SITE_WRONG_PASSWORDS` | `2` wrong passwords site-wide in 15 min before new logins wait (`0` = off) |
| `BONK_LOGIN_VISITOR_WRONG_PASSWORDS` / `BONK_LOGIN_ACCOUNT_WRONG_PASSWORDS` | `2` / `2` before that visitor, or that account from that visitor, is held 15 min |
| `BONK_LOGIN_VISITOR_UNKNOWN_USERNAMES` | `5` unknown usernames per visitor before a hold |

| `TURNSTILE_SITE_KEY` | `0x4AAAAAAGP08z9bSQTcL_Xu` (public; it's in the page) |
| `TURNSTILE_SECRET_KEY` | empty = the "not a bot" check on bonk.io logins is off. Secret: set it in Railway only |

The `BONK_LOGIN_*` guards and the Turnstile check are explained in
[bonk/login-rate-limit.md](../bonk/login-rate-limit.md#what-bonkverse-does-about-it).

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
`BONK_TOKEN_KEYS`, `DATABASE_URL`, `REDIS_URL`, `ENV`, `SENTRY_DSN`; for the replay sync
`BONKVERSE_SYNC_TOKEN` and `BONKVERSE_REPLAYS_URL` (and
`REPLAY_SYNC_INTERVAL_SECONDS` if `bonkverse` sets it); for the friend sync the
`BONK_*` variables if `bonkverse` sets any. It needs no `PORT` and no volume.

| Variable | Default | Notes |
|---|---|---|
| `BONKVERSE_SYNC_TOKEN` | unset → replay sync off | Shared secret for the replay site's internal sync endpoints (`integrations/replay_sync.py`). Worker and web. |
| `REPLAY_SYNC_INTERVAL_SECONDS` | `300` | How often the worker runs `players.tasks.sync_replays` (at least 60). A run takes about a second; its time limit (80% of this) and lock (all of it) scale with it. The archive checks bonk.io every 2 minutes. |

## Railway build and deploy

Set in the **Railway dashboard** (Settings of each service), which is the
source of truth: Railway stops reading `railway.json` on 2026-12-01
([ADR 0027](../adr/0027-railway-settings-in-the-dashboard.md)). Change a value
there **and** in this table. All three build from a Dockerfile, deploy from
`main` and run in `us-west2`.

| Setting | `bonkverse` (web) | `worker` | `roombot` |
|---|---|---|---|
| Root directory | (repo root) | (repo root) | `roombot` |
| Builder | Dockerfile | Dockerfile | Dockerfile |
| Dockerfile path | `Dockerfile` | `Dockerfile` | `Dockerfile` |
| Start command | (the Dockerfile's: `migrate`, then gunicorn) | `celery -A bonk_skin_search worker --beat --loglevel INFO --without-gossip --without-mingle` | (the Dockerfile's) |
| Healthcheck | `/`, 180 s | none: it serves no pages | `/health`, 60 s |
| Replicas | 1 (media volume) | **exactly 1** (it runs the scheduler) | **exactly 1** (rooms live in memory) |
| Restart | default | On failure, 10 retries | On failure, 10 retries |
| Public domain | `bonkverse.io` | none | **none** (private network only) |

Why the web build must use the Dockerfile and wait for the healthcheck:
[ADR 0004](../adr/0004-dockerfile-build-and-healthcheck.md). The worker:
[ADR 0010](../adr/0010-background-work-on-celery.md).

### Room-code sign-in service (`roombot`, experimental)

Room-code sign-in ([ADR 0026](../adr/0026-room-code-sign-in.md)) needs the
`roombot` service: a small Node app in `roombot/` that hosts the bonk.io rooms.
It joins bonk.io **as a guest**, so it needs no bonk.io account or password.

**The `roombot` service** (new service from this repo):

- **Root directory:** `roombot`.
- **Build and deploy:** the `roombot` column of the table above: builder
  Dockerfile (`Dockerfile`), healthcheck `/health` (60 s), restart on failure
  (10 retries), **exactly one replica** (rooms live in memory). New services
  can't use a config file, so set these in the service's Settings.
- **No public domain.** Bonkverse reaches it over Railway's private network.
- **Variables:**
  - `ROOMBOT_TOKEN`: a random secret of 32+ characters (for example
    `openssl rand -hex 32`). It refuses to start without one.
  - `PORT=8080`: the port it listens on, which `ROOMBOT_URL` below uses.

**On `bonkverse` (web)**, as Railway reference variables, so nothing is copied
by hand:

| Variable | Value | Notes |
|---|---|---|
| `ROOMBOT_URL` | `http://${{roombot.RAILWAY_PRIVATE_DOMAIN}}:8080` | Where Bonkverse finds roombot. **Empty = room-code sign-in hidden** on the site. |
| `ROOMBOT_TOKEN` | `${{roombot.ROOMBOT_TOKEN}}` | The same secret, so only Bonkverse can open, read and close rooms. |

`ROOMBOT_TOKEN` isn't a bonk.io credential. Without it, anyone who could reach
roombot could use up its rooms (bonk.io allows one IP about 5 rooms per
5 minutes), read what's typed in them, or close them.

The worker needs neither: the web service talks to roombot directly.
