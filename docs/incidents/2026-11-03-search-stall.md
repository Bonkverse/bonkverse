# 2026-11-03: Search flood stalls the whole site

**Impact:** about 6 minutes (22:26–22:32 UTC; 17:26–17:32 EST) where every page
took 46–115 s or timed out, for all visitors.
**Trigger:** the owner tested the search rate limit in production by clicking
search repeatedly (about 240 searches from one IP; 258 requests abandoned with
499).
**Fixed in:** #20.

## What happened

1. The Cloudflare search rule had just been raised to 50 requests / 10 s, on
   the assumption (wrong) that searches were cheap.
2. Every search read the entire skins table: no index could serve the
   full-text and fuzzy-name conditions as written, so each took 240–770 ms of
   Postgres time, more with sorting.
3. Production ran gunicorn's defaults: **one sync worker**, one request at a
   time. Each abandoned search still ran to completion, so the queue grew
   faster than it drained, and every other visitor waited behind it.

## What changed

- gunicorn runs 4 workers × 4 threads (`gunicorn.conf.py`,
  [ADR 0001](../adr/0001-gunicorn-threaded-workers.md)).
- Search is index-backed (stored `search_vector` + GIN, trigram GIN on
  name/creator/description) and limited to 3 s per query
  ([ADR 0002](../adr/0002-index-backed-search.md), [search.md](../search.md)).
  Typical search: ~3 ms, down from 240–770 ms; results verified identical
  across 17 queries.
- The empty-query sort crash (random sample sliced then re-sorted) was fixed
  along the way.

## Verified

`scripts/load_test_search.py` against a local production-like server:
home page median 4.7 s / max 15 s before; median 0.07 s / max 0.14 s after,
even at 960 searches/min.

## Lessons

- Load-test locally, never in production (the script refuses production hosts).
- A rate limit protects capacity only if one request is cheap; check the query
  plan before raising a limit.
