# ADR 0001: Gunicorn runs threaded workers

**Status:** accepted, 2026-11-03 (#20)

**Context.** Production ran gunicorn's defaults: one sync worker serving one
request at a time. One slow request blocked everyone
([incident](../incidents/2026-11-03-search-stall.md)).

**Decision.** `gunicorn.conf.py` with `gthread`, 4 workers × 4 threads, 30 s
timeout, workers recycled every ~2,000 requests (with jitter). All tunable via
`WEB_CONCURRENCY`, `GUNICORN_THREADS`, `GUNICORN_TIMEOUT`. The Dockerfile is
the only start command.

**Consequences.**
- 16 requests can run at once; most request time is I/O wait (Postgres, Redis,
  bonk.io), which threads overlap well.
- At most 16 database connections in use, under Postgres's 100.
- About 150 MB per worker.
- Code must be thread-safe: no mutable module-level state shared between
  requests.
- Several replicas would need media moved off the single Railway volume (to
  object storage) first; until then, scale with workers/threads.
