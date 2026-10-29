# Contributing to Bonkverse

Thanks for helping. This is the short version of **RFC-0001: Code Organization & Conventions**; the RFC has the reasoning. Every rule traces back to one question: *could someone find, understand and safely change this in five minutes?*

## Workflow

1. Set up locally with the [README](README.md) (`pip install -r requirements-dev.txt`, `pre-commit install`).
2. Branch from `main`. Keep a PR to one purpose.
3. **Refactor commits contain no behavior changes; feature commits contain no refactors.**
4. **Fixing a bug? First write a test that reproduces it, then fix it.**
5. `pytest` and `pre-commit run --all-files` pass locally; CI must be green to merge.
6. Fill in the PR template checklist.

Boy-scout rule: a file you touch for a feature gets brought up to these conventions in the same PR, so new work never adds to the debt.

## Where code goes

The repo is moving from one `skins` app to six domain apps (`accounts`, `skins`, `players`, `stats`, `communities`, `site_pages`) plus two shared packages:

- `integrations/` — one client per external system (bonk.io, editor render service, BonkBot, Discord, Cloudflare). **Only these files import `requests`.**
- `core/` — cross-cutting helpers: auth guards, event logging, pagination, the one definition of today/week/month periods, JSON response helpers.

Until a phase lands, put new code where its future home will be, or as close as the current layout allows.

Inside an app, dependencies point one way:

```
views -> services / selectors -> models
              services -> integrations
```

| File | Contains | Must not contain |
|------|----------|------------------|
| `models.py` | Fields, constraints, `__str__`, small properties, custom QuerySets | HTTP calls, request handling |
| `services.py` | Business rules as typed functions; transactions | `request`, `JsonResponse`, `render` |
| `selectors.py` | Read-only queries shaped for pages | Writes |
| `views/*.py` | Parse input → call service → return response (≤ 40 lines, nesting ≤ 2) | ORM queries beyond `get_object_or_404`, `requests` |
| `integrations/*.py` | URLs, headers, timeouts, parsing, token redaction for one system | Models, request objects |
| `tasks.py` | Celery entry points that call services | Business logic |
| `management/commands/` | Thin, idempotent CLI wrappers with `--dry-run` for writes | One-off logic that belongs in a service |
| `templates/` | Markup, partials (`_name.html`), `json_script` data | Inline JS logic, inline `style=""` |

Apps talk to each other only through another app's `services.py`.

## Conventions

**Views.** Function-based by default. A class-based base view only for a family of three or more pages that differ only in data (the leaderboards are the first case).

**JSON endpoints** return one of two shapes:

```json
{"ok": true, "data": {...}}
{"ok": false, "error": "skin_code_not_found", "auth": "bonk"}
```

Error codes are `snake_case`. `auth` appears only on 401s: `"bonkverse"` means sign in to the site, `"bonk"` means a bonk.io token is needed.

**Config** comes from `settings.py`, read from env. No hardcoded URLs, TTLs or feature flags in modules.

**Background work** goes through Celery, not `threading.Thread`.

**Logging:** `logger = logging.getLogger(__name__)`. No `print()`. Never log a token or password.

**Delete, don't comment out.** Git is the archive. Ruff (`ERA001`) rejects commented-out code.

**Patterns:** extract a base class on the third real variant, not the first. Two copies is a warning; three is a pattern.

## Naming

- Python: PEP 8. JS: camelCase with the same vocabulary.
- Booleans start with `is_`, `has_`, `can_`. Durations carry units: `token_ttl_seconds`.
- No single-letter names outside comprehensions and short loops.
- URL names are namespaced (`skins:detail`). Management commands start with a verb (`backfill_`, `import_`, `audit_`, `populate_`).

Fixed bonk.io vocabulary:

| Term | Means | Never call it |
|------|-------|---------------|
| `user` / `BonkUser` | A Bonkverse site account | player, account |
| `player` / `BonkPlayer` | An in-game bonk.io identity | user |
| `bonk_id` | bonk.io's dbid for a registered player | id, user_id, dbid |
| `bonk_username` | Username exactly as bonk.io returns it | typed_username (after login) |
| `skin_code` | Encoded avatar string bonk.io accepts | avatar, code |
| `avatar_slot` | Slot 1–5 on a bonk.io account | slot, active |
| `bonk_token` | Short-lived session token from bonk.io | token |
| `remember_token` | Long-lived token from the remember-me flow | — |

## Comments and docs

- Every module starts with a one-paragraph docstring: what it owns and what it does not.
- Public functions in `services.py`, `selectors.py` and `integrations/` get a Google-style docstring.
- Comments explain *why*, never *what*.
- Tag bonk.io quirks with `# BONK:` (e.g. `# BONK: login_legacy returns 200 on failure`) so they can be collected into the bonk.io reference docs.
- `TODO` needs an issue: `# TODO(#42): ...`.
- A PR that changes behavior updates the matching doc in the same PR.

## Tests

- `pytest` + `pytest-django` against real Postgres; `factory_boy` factories in `tests/factories.py`.
- Fake every outside service with the `mocked_http` fixture; recorded bonk.io bodies (tokens scrubbed) go in `tests/fixtures/bonk/`.
- New or changed services and integrations ship with tests. Write tests for every error path, not just the happy path.
- Known-broken routes are `xfail(strict=True)` in `tests/test_smoke.py`. When you fix one, remove its entry.

## Security

- `csrf_exempt` only on endpoints that truly need it, and never on anything that writes as a logged-in user.
- Every write endpoint must be safe for anonymous users, normal users, *other* users, and staff.
- Report vulnerabilities privately to the maintainer rather than in a public issue.
