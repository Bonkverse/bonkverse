# ADR 0006: Every outside call goes through `integrations/`

**Status:** accepted, 2026-11-05 (#31, #35, #37, #38; RFC-0001 Phase 2)

**Context.** Views and helpers called bonk.io, the render service,
BLSkinFetcher, Cloudflare, Discord, BonkBot and the map decoder directly with
`requests`. Each copy chose its own request shape, timeout and error
handling, and they drifted: login and wear sent bonk.io different requests;
the Discord refresh ran at 40 requests/s; a Cloudflare purge failure was
swallowed by `except: pass`; raw exception text and service error bodies
reached users.

**Decision.**
- One module per outside system in `integrations/`, and nothing else makes
  outside HTTP calls. `tests/test_architecture.py` fails CI if any file
  outside `integrations/` imports `requests`, `httpx`, `aiohttp`,
  `urllib.request`, `http.client` or `urllib3`. The one exception
  (`scripts/load_test_search.py`) is named in the test.
- Every client:
  - **never raises** for the other service failing or refusing; it returns a
    small result object with an error code;
  - **always has a timeout**, `(connect, read)`;
  - **logs the reason** for a failure (status, error code, exception type),
    never a token, password or key;
  - **doesn't depend on Django models or views** (no `skins` or `django.db`
    imports, Django settings only inside a `*_configured()` / `get_client()`
    helper).
- Callers turn result codes into what people see: a sentence, never the
  service's own text.

**Consequences.**
- A change to how we talk to a service happens in one file, with its tests.
- Failures are visible in the logs with a code, which is how the
  reappearing-modal bug was found ([incident](../incidents/2026-11-05-bonk-rate-limit.md)).
- New outside calls follow the recipe in
  [integrations.md](../architecture/integrations.md); there is no shortcut
  past the test.
- The clients could later move into a shared package (the RFC's bonk.io SDK)
  for BonxBot and the extension.
