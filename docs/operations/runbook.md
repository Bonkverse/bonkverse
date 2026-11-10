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

Merging to `main` deploys both services built from this repo: `bonkverse` (the
site) and `worker` (background jobs). The site's container runs `python manage.py migrate` and
then gunicorn; the deploy takes traffic only after `/` answers (healthcheck).
The worker runs Celery only (no migrate, no healthcheck).
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

## Background jobs aren't running

Symptoms: the Discord directory's counts and "next refresh" stop moving; after
login, the friend-sync toast never finishes; new replay names stop showing on
the Players page; logs show no
`celery` lines.

1. Railway → `worker` service: is the latest deploy up? Its log should start
   with `beat: Starting...` and `celery@... ready.` A crash loop usually means a
   missing variable (`ImproperlyConfigured`) or a bad `REDIS_URL`; the worker
   needs the same references as `bonkverse` (see
   [configuration.md](configuration.md#background-worker)).
2. Is work arriving? Search the worker's logs for `received`. Nothing at all
   while people log in means jobs aren't being queued: search `bonkverse`'s
   logs for `could not queue task` (Redis down or unreachable from the web
   service).
3. Is it failing? Search for `raised unexpected` (a task's exception, with
   traceback) or `TimeLimitExceeded`. Every line from one run carries the
   same `task_id` (and a short form in the message, e.g.
   `[skins.tasks.refresh_discord_servers 0d4fcc8a]`); filter on
   `@task_id:<id>` to read the whole run.
4. Is the schedule there? `/admin` → Periodic tasks: each entry from
   `CELERY_BEAT_SCHEDULE` with a recent "Last run at". A schedule with no
   last run should run within a minute of the worker starting (the worker
   log says `schedule <name> has never run: running it now`). An entry missing or
   disabled in /admin is restored on the worker's next deploy (schedules are
   code).
5. **Never scale the worker above 1 replica**: it runs the scheduler, and two
   would send every scheduled job twice.

Restarting the worker is always safe: an unfinished at-least-once task runs
again; an at-most-once task (the Discord refresh) waits for its next hour.

## Skin images are broken: re-render them

How images are made and where they live: [skin-images.md](../architecture/skin-images.md).

One skin: the **Re-render** button on the search page (staff), which also
purges that skin's three files from Cloudflare.

Many or all skins: `manage.py rerender_skins`, on the **`bonkverse`** service
(the media volume is only mounted there; the command refuses `--run` anywhere
else). It renders each skin from its stored code through the editor's render
service, like the button, and points `image_url` at `/media/`. A skin that
fails keeps its old images. Skins with no stored code can't be re-rendered.

0. **Check the editor first.** The render service silently leaves out any
   layer whose shape it doesn't have and still reports success, so a bulk run
   would save those skins without that layer
   ([incident](../incidents/2026-11-10-rerender-dropped-layers.md)). Make sure
   the deployed editor has every shape in use (`TOTAL_BONK_SHAPES`, 115 with
   the whisp), and run `python manage.py audit_skin_codes`: a code it refuses
   can't be rendered either.
1. **Dry run** (changes nothing): `railway ssh` into `bonkverse`, then
   `python manage.py rerender_skins`. It reports how many skins have a code,
   how many have missing / empty / non-image files (with example ids), and how
   long a run would take.
2. **Run it in the background** so closing the SSH session doesn't stop it:
   ```
   nohup python manage.py rerender_skins --run --per-second 8 --purge-cache > /tmp/rerender.log 2>&1 &
   tail -n 15 /tmp/rerender.log
   ```
   8 per second is safe (a render takes 20–250 ms, one at a time): about 20
   minutes for 9,400 skins. The default is 2. `--only-broken` limits it to
   skins whose files look broken. **Don't merge to `main` while it runs**: a
   deploy restarts the container and stops it. It's done when the log ends
   with `Re-rendered N skin(s).` and the failures by reason.
3. **If it stops** (a deploy, or 10 render failures in a row, which usually
   means the editor's render service is down): the log's last progress line
   says `resume with --start-after <id>`. Run the same command with that
   added. Re-running from earlier is harmless; it only redoes work.
4. **Cache:** `--purge-cache` empties Cloudflare's whole cache once, at the
   end of a run that wasn't stopped early. The site is a little slower for a
   few minutes while the cache refills. Browsers keep their own copy of an
   image for up to an hour (`media.py`). If the run was stopped and resumed,
   add `--purge-cache` to the last run.
5. **Failures** are listed at the end by reason (`render_failed`,
   `unsafe_svg`, `too_large`, `storage_failed`) with skin ids. A
   `render_failed` the editor answered with 400 is a code it couldn't read:
   send the codes to whoever maintains the editor's decoder
   (`python manage.py shell -c "from skins.models import Skin; [print(s.id, s.skin_code) for s in Skin.objects.filter(id__in=[...])]"`).
6. **A few skins only** (the failures, or skins using one shape): there's no
   `--ids` option yet. Re-render them from `python manage.py shell`, then
   purge just their files:
   ```python
   from integrations.cloudflare import purge_media_paths
   from skins.models import Skin
   from skins.rerender import rerender

   paths = []
   for skin in Skin.objects.filter(id__in=[166, 543]):
       result = rerender(skin)
       print(skin.id, result.error or "ok")
       paths += [f"/media/{p}" for p in (result.paths or {}).values()]
   for n in range(0, len(paths), 30):
       purge_media_paths(paths[n : n + 30])
   ```

## Vote counts look wrong

Symptoms: a skin's up/down numbers don't match what people say they did, or
a leaderboard order looks off. A skin's `upvotes`/`downvotes` must always
equal its `SkinVote` rows ([ADR 0014](../adr/0014-counters-follow-their-rows.md)).

1. **Check** (read-only): `railway ssh` into `bonkverse`, then
   `python manage.py audit_vote_counts`. It prints how many skins differ;
   add `--show 50` to list them with stored and real counts.
2. **Repair:** `python manage.py audit_vote_counts --fix`. It sets each
   drifted skin's counters to the real counts, under the skin's row lock, so
   it's safe while people vote. Re-running is harmless.
3. **If drift comes back** after a repair, something is changing the counters
   outside `skins/votes.py: cast_vote` (an admin edit, a script, a new view).
   Every vote change must go through `cast_vote`; search the code for
   `upvotes`/`downvotes` writes.

The 2026-11-10 audit after RFC-0001 4.1 found no drift.

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
