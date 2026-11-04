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
