# ADR 0003: Rate limits: named tiers, real client IP, fail open

**Status:** accepted, 2026-11-03 (#19, #20, #27)

**Context.** Limits were numbers scattered across `@ratelimit` decorators; some
were attached to the wrong function and crashed. Behind Cloudflare and Railway,
the IP Django saw was a proxy's, so one limit could hit many visitors at once.
Some routes had no limit, including bonk.io login (password guessing) and
`/media/`.

**Decision.**
- One `@limit("<tier>")` decorator.
- Tiers defined once in `settings.RATE_LIMITS`, each overridable by
  environment variable.
- The client IP comes from `CF-Connecting-IP`, trusted only when the request
  arrived from Cloudflare.
- A test fails if any route lacks a tier.
- If Redis is unreachable, requests go through (fail open), with Cloudflare's
  edge rule as the backstop.

**Consequences.**
- Changing a limit is a Railway variable change (which redeploys), not a code change.
- Adding a route requires picking a tier.
- During a Redis outage there is no origin rate limiting.
- A malformed `REDIS_URL` is not "unreachable"; it is refused at startup
  instead ([ADR 0004](0004-dockerfile-build-and-healthcheck.md)).
