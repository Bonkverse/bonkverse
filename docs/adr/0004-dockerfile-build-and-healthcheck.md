# ADR 0004: Railway builds from the Dockerfile, behind a healthcheck

**Status:** accepted, 2026-11-03 (#21)

**Context.** The builder (Dockerfile vs Nixpacks) was a dashboard setting.
Builds without the Dockerfile skipped `collectstatic` and `migrate` and used a
different Python. Deploys took traffic as soon as the container started, even
if every request then failed
([incident](../incidents/2026-11-03-redis-rotation.md)).

**Decision.**
- `railway.json` pins `builder: DOCKERFILE` and a healthcheck on `/` (180 s
  window).
- The Dockerfile is the only start command (Procfile removed).
- Settings validate risky configuration (`REDIS_URL`) at startup, so bad
  config fails the healthcheck instead of failing requests.

**Consequences.**
- A deploy that can't serve the home page never replaces a working one.
- Every deploy runs `migrate` before starting, so a migration that fails blocks
  the deploy (good).
- A slow migration counts against the 180 s healthcheck window.
- `healthcheck.railway.app` must stay in production `ALLOWED_HOSTS`.
