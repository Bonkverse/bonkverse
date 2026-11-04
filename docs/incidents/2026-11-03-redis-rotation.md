# 2026-11-03: Redis password rotation takes the site down

**Impact:** about 22 minutes (≈01:03–01:25 UTC Nov 4; 20:03–20:25 EST Nov 3)
where every page returned 500.
**Trigger:** rotating the Redis password after it had leaked into logs (an old
`print(REDIS_URL)` in settings, removed in #20) and Railway published a
recommendation to rotate Redis credentials.
**Fixed by:** replacing the Redis service; hardening in #21 and #23/#24.

## What happened

1. The password was changed by hand (following advice that turned out to be
   wrong; Railway says to use **Regenerate**). The new value contained a
   character with meaning inside a URL.
2. `REDIS_URL` (built from it) could no longer be parsed. redis-py parses the
   URL only when it first connects, inside a request, so the app started fine
   and then every request failed with
   `ValueError: Port could not be cast to integer`.
3. Our fail-open setting (`IGNORE_EXCEPTIONS`) covers Redis being unreachable,
   not a malformed URL, so the rate limiter's cache call crashed every page.
4. Railway's **Regenerate** failed too: the old Bitnami-based Redis image cannot
   write its config file (`CONFIG REWRITE failed: Permission denied`), and each
   attempt could leave the live password and the variable out of sync.
5. Meanwhile some deploys were built by Nixpacks instead of the Dockerfile
   (Python 3.12, no `collectstatic`), so even the error pages failed with
   `Missing staticfiles manifest entry`. Nothing in the repo pinned the builder.
6. Production had `DEBUG_PROPAGATE_EXCEPTIONS = True` and no `LOGGING` config:
   visitors got bare gunicorn 500s, and errors were hard to read in the logs.

**Recovery:** a new Redis service from Railway's current template (generated
password, us-west2), with `REDIS_URL` set to the reference
`${{Redis.REDIS_URL}}`.

## What changed

- **#21:** `check_redis_url()` refuses a malformed `REDIS_URL` at startup;
  `railway.json` pins the Dockerfile build and adds a healthcheck on `/`, so a
  broken deploy never takes traffic ([ADR 0004](../adr/0004-dockerfile-build-and-healthcheck.md));
  the Procfile is gone; login and wear logs no longer contain player details.
- **#23/#24:** standalone `500.html`; `DEBUG_PROPAGATE_EXCEPTIONS` removed;
  `LOGGING` sends errors with tracebacks to stdout.
- [Runbook](../operations/runbook.md#rotating-the-redis-password): how to rotate
  the Redis password.

## Lessons

- "Fail open" needs a test for *misconfigured*, not just *unreachable*.
- Anything that decides how production is built belongs in the repo.
- Follow the provider's rotation guide; never hand-type secrets into URLs.
