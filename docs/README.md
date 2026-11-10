# Bonkverse (Django site) docs

How this repo works and how to run it in production. Setup and day-to-day
development are in the [README](../README.md); code conventions in
[CONTRIBUTING](../CONTRIBUTING.md).

**Rule:** a PR that changes behavior updates the matching page here in the same PR.

| Page | Read it when |
|---|---|
| [apps/](apps/README.md) | Deciding which app owns new code, using another app from yours, or creating / moving an app |
| [architecture/request-flow.md](architecture/request-flow.md) | You want to know what happens between a click and a response |
| [architecture/frontend.md](architecture/frontend.md) | Changing a page: where its script and styles go, the shared `BV*` helpers, skin cards, what `tests/test_frontend.py` checks |
| [architecture/background-work.md](architecture/background-work.md) | Writing or queueing a background job, adding a schedule, or jobs aren't running |
| [architecture/skin-images.md](architecture/skin-images.md) | A skin's images are wrong or missing, re-rendering, adding a shape, or changing how skins are published or imported |
| [architecture/integrations.md](architecture/integrations.md) | Calling another service (bonk.io, the editor, Discord, Cloudflare…), or one of them is failing |
| [architecture/public-api.md](architecture/public-api.md) | Issuing or revoking an API key, changing `/api/v1/`, or a partner says the API is wrong |
| [operations/configuration.md](operations/configuration.md) | Adding, changing or looking up an environment variable |
| [operations/runbook.md](operations/runbook.md) | Something is wrong in production, or you're deploying / rotating a secret |
| [operations/rate-limiting.md](operations/rate-limiting.md) | Adding a route, changing a limit, or someone hits a 429 / Cloudflare 1015 |
| [search.md](search.md) | Changing search, sorting, or the skin indexes |
| [bonk/](bonk/) | What bonk.io sends and accepts: [the account API](bonk/api.md) (login, friends, avatar update), [how bonk.io limits logins](bonk/login-rate-limit.md) (measured rules, and what Bonkverse does about them), [accounts and usernames](bonk/accounts.md) and [skin codes](bonk/skin-codes.md) (format, what a code must pass) |
| [incidents/](incidents/) | What went wrong before, and what changed because of it |
| [adr/](adr/) | Why a hard-to-reverse decision was made |

## Incidents

- [2026-11-03 Search flood stalls the site](incidents/2026-11-03-search-stall.md)
- [2026-11-03 Redis password rotation takes the site down](incidents/2026-11-03-redis-rotation.md)
- [2026-11-03 Skin image scrape](incidents/2026-11-03-media-scrape.md)
- [2026-11-05 The reappearing bonk.io login modal, and bonk.io rate limits](incidents/2026-11-05-bonk-rate-limit.md)
- [2026-11-09 Wrong passwords lock everyone out of bonk.io login](incidents/2026-11-09-login-lockouts.md)
- [2026-11-10 New scheduled jobs didn't run for three hours after the worker started](incidents/2026-11-10-scheduled-jobs-never-ran.md)
- [2026-11-10 The whole-gallery re-render dropped layers it couldn't draw](incidents/2026-11-10-rerender-dropped-layers.md)

## Decisions (ADRs)

- [0001 Gunicorn runs threaded workers](adr/0001-gunicorn-threaded-workers.md)
- [0002 Search must be index-backed and time-limited](adr/0002-index-backed-search.md)
- [0003 Rate limits: named tiers, real client IP, fail open](adr/0003-rate-limit-tiers.md)
- [0004 Railway builds from the Dockerfile, behind a healthcheck](adr/0004-dockerfile-build-and-healthcheck.md)
- [0005 Admins sign in through bonk.io](adr/0005-admin-login-through-bonk.md)
- [0006 Every outside call goes through `integrations/`](adr/0006-outside-calls-through-integrations.md)
- [0007 bonk.io names are stored exactly; identity is case-insensitive](adr/0007-bonk-usernames.md)
- [0008 How Bonkverse answers bonk.io refusals](adr/0008-bonk-refusals.md)
- [0009 One copy of each page behavior, in static files](adr/0009-frontend-structure.md)
- [0010 Background work runs on one Celery worker, queued through `enqueue`](adr/0010-background-work-on-celery.md)
- [0011 A public, versioned API for other sites, with keys](adr/0011-public-api.md)
- [0012 The platform docs site is Docusaurus, at docs.bonkverse.io](adr/0012-docs-site.md)
- [0013 One UI package for every Bonkverse site](adr/0013-shared-ui-package.md)
- [0014 A counter on a row is changed in SQL under a lock, and can be recounted from its rows](adr/0014-counters-follow-their-rows.md)
- [0015 Skin images are rendered by Bonkverse from the stored skin code, and a code must be a real skin](adr/0015-skin-images-from-skin-codes.md)
