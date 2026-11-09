# Runbook

Production is the `bonkverse` service in the Railway project **Bonkverse**
(environment `production`, region us-west2), with `BonkverseDB` (Postgres 16)
and `Redis`. DNS, TLS and the WAF are in Cloudflare (zone `bonkverse.io`).

## The site is slow or down

Work top to bottom; stop when you find it.

1. **Is it everyone or one person?** Cloudflare → Analytics → Requests, last
   hour. Check *Top client IPs*: one IP with most of the traffic is a flood or
   scraper (see [media scrape](../incidents/2026-11-03-media-scrape.md)).
   Error 1015 in the browser is Cloudflare's rate limit, not the site.
2. **Is the latest deploy healthy?** Railway → bonkverse → Deployments. A
   deploy that fails its healthcheck never takes traffic, so a red deploy with
   the site up means the previous one is still serving. Read its logs.
3. **What do the logs say?** Railway → bonkverse → Logs. Unhandled errors are
   logged by `django.request` with a traceback. Look for:
   - `ImproperlyConfigured: REDIS_URL ...`: bad Redis URL; see below.
   - `Missing staticfiles manifest entry`: the build skipped `collectstatic`,
     i.e. it didn't use the Dockerfile. Check `railway.json` is present.
   - `search timed out`: a search hit the 3 s limit (harmless alone; many of
     them mean an index stopped being used; see [search.md](../search.md)).
   - `WORKER TIMEOUT`: a request ran 30 s. Find which view.
   - `django_redis` warnings: Redis unreachable; the site keeps working without
     the cache and without rate limits (fail open). Fix Redis soon.
   - Outside services log their own failures (one module each in
     `integrations/`, see [integrations.md](../architecture/integrations.md)):
     `bonk.io ... unreachable`, `bonk.io refused avatar update | bonk_error=`,
     `render service ...`, `skin fetcher ...`, `cloudflare purge failed`,
     `discord refresh ...`, `map decoder ...`, `bonkbot ...`.
4. **Is Postgres or Redis struggling?** Railway → service → Metrics (CPU,
   memory). Postgres connections in use are at most workers × threads (16).
5. **Roll back** if a deploy caused it: Railway → Deployments → previous
   successful deploy → Redeploy. Migrations do not roll back with it.

## Deploying

Merging to `main` deploys. The container runs `python manage.py migrate` and
then gunicorn; the deploy takes traffic only after `/` answers (healthcheck).
After a merge with a migration, check the deploy log shows `Applying ...` and
then gunicorn booting 4 workers.

Destructive migrations (dropping a table or column) say so in the PR
description and are their own PR.

## Rotating the Redis password

Railway's **Regenerate** button (Redis → Database → Config) is the supported way.
It does not work on the old Bitnami-based Redis image
(`CONFIG REWRITE failed: Permission denied`); that service was replaced on
2026-11-03 with one from Railway's current template.

1. Redis → Database → Config → **Regenerate**.
2. Make sure `bonkverse`'s `REDIS_URL` is the reference `${{Redis.REDIS_URL}}`
   (it updates automatically), then redeploy `bonkverse`.
3. Logs: no `ImproperlyConfigured`, no `WRONGPASS`/`NOAUTH`.

Never type a Redis password by hand. A `/`, `#`, `?` or `@` in it breaks the URL
([incident](../incidents/2026-11-03-redis-rotation.md)).

## bonk.io logins or wearing skins are failing

Railway → bonkverse → Logs, filter
`"bonk login response" OR "refused avatar update" OR "rate-limited"`.
The codes mean ([bonk/api.md](../bonk/api.md), [ADR 0008](../adr/0008-bonk-refusals.md)):

- `bonk_error=ratelimited` / `pausing <script> calls for <s>s`: bonk.io is
  limiting the server's IP for that script (logins and wears are paused
  separately). Everyone is affected; Bonkverse pauses its own calls to that
  script, starting at 2 minutes and doubling with each limit in a row up to
  30 (`(<n> in a row)` in the line). `answered rate_limited without calling
  it` lines are requests turned away during the pause. Nothing to deploy. Note the time and whether
  a bonk.io login from your own connection works meanwhile (that tells us the
  limit is on our IP). Bursts usually clear within an hour or two.
- `bonk_error=avatar_too_big`: one skin is over bonk.io's size limit. Players
  get a message; nothing is broken.
- `bonk_error=token`: an expired bonk.io token; the player is asked to log in
  again. Normal.
- `bonk.io ... unreachable` / `gave no usable answer`: bonk.io is down or
  showing a Cloudflare page. Players see "bonk.io isn't responding".
- `bonk_error=<anything else>`: a code we haven't seen. Add it to the table in
  `integrations/bonk_api.py` and [bonk/api.md](../bonk/api.md).

Recent history: [2026-11-05 incident](../incidents/2026-11-05-bonk-rate-limit.md).

## Buttons do nothing, or icons are missing

Page behavior is static JavaScript ([architecture/frontend.md](../architecture/frontend.md)).
Open the browser console on the broken page:

- **A red script error**: every listener after it on that page is dead. The
  file and line point at the script; a shared one (`core/js/bv-*.js`) breaks
  every page that loads it, so check a second page.
- **404 for `/static/...`**: the deploy's `collectstatic` didn't include the
  file. Check the build log, then redeploy.
- **Icons are blank squares or missing, the background has no particles**:
  unpkg (Lucide) or jsDelivr (particles.js) is down or blocked. Pages still
  work; `bv-boot.js` skips what didn't load. Nothing to deploy unless it lasts.
- **Only the GitHub icon on /terms/ is blank**: expected. Lucide dropped
  brand icons in 1.0.

## Giving someone admin access

They sign in to Bonkverse with bonk.io once, then, from a shell on the
`bonkverse` service (or locally against production):

```
python manage.py grant_admin "<bonk.io username>"          # superuser
python manage.py grant_admin "<bonk.io username>" --revoke # back to staff only
```

Staff (`is_staff`) can re-render skins and open `/admin/`, but see no models
without permissions. Superusers see everything.

## Someone is scraping or flooding

1. Cloudflare → Analytics: confirm the IP and paths.
2. Origin limits already apply per IP (`media` 600/min, `search` 60/min, ...).
   Lower one temporarily with a Railway variable, e.g. `RATE_LIMIT_MEDIA=200/m`,
   and redeploy.
3. To cut one client off entirely: Cloudflare → Security → WAF → Custom rules →
   block `ip.src eq <ip>`. Remove it later.

## Local development against production data

Don't point a local server at the production database (`.env` should have a
local `DATABASE_URL`). A safe, anonymized snapshot command is planned.
