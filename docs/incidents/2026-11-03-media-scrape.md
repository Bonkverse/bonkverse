# 2026-11-03: Skin image scrape

**Impact:** none visible to visitors. About 22 minutes
(≈02:28–02:50 UTC Nov 4; 21:28–21:50 EST Nov 3) of heavy load, handled by the
new workers.
**Fixed in:** #27.

## What happened

From Cloudflare analytics for that hour:

- One IP sent 29.5k of 30.9k requests (96%), transferring 1.88 GB.
- It peaked around 2,700 requests a minute, in three bursts.
- It sent a Mac Chrome user-agent over HTTP/1.1 only, and Cloudflare classified
  the browser as "Unknown", so it was a script.
- It walked `/media/skins/<id>.png|svg` one URL at a time: almost all cache
  misses, and 3.1k 404s for IDs that don't exist.

Each URL was fetched once, so Cloudflare's cache couldn't help. Django served
`/media/` with a bare `django.views.static.serve`, with **no rate limit**, and
both the rate-limit audit and the smoke test skipped `media/`. "Every route
has a tier" was true only for the routes we checked.

## What changed

- `skins/media.py`: `/media/` has its own `media` tier (600/min per IP) and
  sends `Cache-Control: public, max-age=3600, s-maxage=604800` on hits.
- The audit no longer skips `/media/`.
- [Runbook](../operations/runbook.md#someone-is-scraping-or-flooding): what to
  do next time.

## Lessons

- A guard that skips a path is a blind spot; list exceptions explicitly.
