# Bonkverse (Django site) docs

How this repo works and how to run it in production. Setup and day-to-day
development are in the [README](../README.md); code conventions in
[CONTRIBUTING](../CONTRIBUTING.md).

**Rule:** a PR that changes behavior updates the matching page here in the same PR.

| Page | Read it when |
|---|---|
| [architecture/request-flow.md](architecture/request-flow.md) | You want to know what happens between a click and a response |
| [architecture/integrations.md](architecture/integrations.md) | Calling another service (bonk.io, the editor, Discord, Cloudflare…), or one of them is failing |
| [operations/configuration.md](operations/configuration.md) | Adding, changing or looking up an environment variable |
| [operations/runbook.md](operations/runbook.md) | Something is wrong in production, or you're deploying / rotating a secret |
| [operations/rate-limiting.md](operations/rate-limiting.md) | Adding a route, changing a limit, or someone hits a 429 / Cloudflare 1015 |
| [search.md](search.md) | Changing search, sorting, or the skin indexes |
| [bonk/](bonk/) | What bonk.io sends and accepts: [the account API](bonk/api.md) (login, friends, avatar update) and [accounts and usernames](bonk/accounts.md) |
| [incidents/](incidents/) | What went wrong before, and what changed because of it |
| [adr/](adr/) | Why a hard-to-reverse decision was made |

## Incidents

- [2026-11-03 Search flood stalls the site](incidents/2026-11-03-search-stall.md)
- [2026-11-03 Redis password rotation takes the site down](incidents/2026-11-03-redis-rotation.md)
- [2026-11-03 Skin image scrape](incidents/2026-11-03-media-scrape.md)
- [2026-11-05 The reappearing bonk.io login modal, and bonk.io rate limits](incidents/2026-11-05-bonk-rate-limit.md)

## Decisions (ADRs)

- [0001 Gunicorn runs threaded workers](adr/0001-gunicorn-threaded-workers.md)
- [0002 Search must be index-backed and time-limited](adr/0002-index-backed-search.md)
- [0003 Rate limits: named tiers, real client IP, fail open](adr/0003-rate-limit-tiers.md)
- [0004 Railway builds from the Dockerfile, behind a healthcheck](adr/0004-dockerfile-build-and-healthcheck.md)
- [0005 Admins sign in through bonk.io](adr/0005-admin-login-through-bonk.md)
