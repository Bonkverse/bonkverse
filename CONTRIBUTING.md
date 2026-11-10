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

- `integrations/` — one client per external system (bonk.io, editor render service, BLSkinFetcher, BonkBot, Discord, Cloudflare, map decoder). **Only these files make outside HTTP calls** (any HTTP library; enforced by `tests/test_architecture.py`). How to add one: [docs/architecture/integrations.md](docs/architecture/integrations.md).
- `core/` — cross-cutting helpers: auth guards, event logging, pagination, the one definition of today/week/month periods, JSON response helpers.

Until a phase lands, put new code where its future home will be, or as close as the current layout allows ([docs/apps/README.md](docs/apps/README.md) shows each app's state).

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
| `tasks.py` | Celery entry points that call services ([background-work.md](docs/architecture/background-work.md)) | Business logic |
| `management/commands/` | Thin, idempotent CLI wrappers with `--dry-run` for writes | One-off logic that belongs in a service |
| `templates/` | Markup, partials (`_name.html`), `json_script` data | Inline JS logic, inline `style=""` |

Apps use each other only through another app's `services`, `selectors` or `models`, and `core/` and `integrations/` import no app (enforced by `tests/test_app_boundaries.py`). Which app owns what, and how to create or move one: [docs/apps/README.md](docs/apps/README.md). Every URL path is pinned by `tests/test_url_snapshot.py`; a new route means updating `tests/fixtures/url_routes.json` in the same PR.

**Background work** goes to the Celery worker, queued with `core.background.enqueue` (never `.delay()`, never a thread); tasks set their own time limits, take ids, and are safe to run twice. Standard and checklist: [docs/architecture/background-work.md](docs/architecture/background-work.md) (enforced by `tests/test_background.py`).

## Conventions

**Views.** Function-based. A family of pages that differ only in data is one view plus a config dict (`stats/leaderboards.py: LEADERBOARDS`), not a class hierarchy.

**Querysets.** Skin filters and annotations live on `Skin.objects` (`skins/querysets.py`: `with_favorite_count()`, `with_score()`, `created_in(period)`, `search(q, mode)`); periods come from `core/periods.py`. Don't rewrite those expressions in a view; a test fails if you do.

**Stored counters** (like `Skin.upvotes`) change only in one service, in SQL with `F()`, under the parent row's lock, and get an audit command that recounts them from their rows ([ADR 0014](docs/adr/0014-counters-follow-their-rows.md)). If you don't need to sort by it, count it in the query instead.

**Skin images and codes.** Only `skins/skin_media.py: save_render` writes a skin's files; a code a client sends must pass `core.bonk.SkinCode.parse()` ([docs/architecture/skin-images.md](docs/architecture/skin-images.md), [ADR 0015](docs/adr/0015-skin-images-from-skin-codes.md)).

**JSON endpoints** return one of two shapes:

```json
{"ok": true, "data": {...}}
{"ok": false, "error": "skin_code_not_found", "auth": "bonk"}
```

Error codes are `snake_case`. `auth` appears only on 401s: `"bonkverse"` means sign in to the site, `"bonk"` means a bonk.io token is needed.

The frontend rules below, with the load order and examples, are in [docs/architecture/frontend.md](docs/architecture/frontend.md).

**Page scripts** call the server through `BVApi` (`static/core/js/bv-api.js`: `post`, `postJSON`, `postOrLogin`, `getCSRF`) and wear skins through `BVWear.wear(url)` (`static/core/js/bv-wear.js`), which owns the one bonk.io login modal (`skins/partials/_bonk_login_modal.html`). Both load in `base.html`, as do `bv-report.js` (the one report modal, `skins/partials/_report_skin_modal.html`; any element with `data-report-skin="<id>"` opens it) and `bv-boot.js` (Django messages as toasts, the particle background, icons). Don't write a page-local `getCSRF`/`postForm`, login modal or report modal; `tests/test_frontend.py` fails if you do.

**No inline scripts.** A page's script is a file in its app's static folder (named after the page: `skins/static/js/search.js`; in apps created in Phase 5, `<app>/static/<app>/js/<page>.js`, e.g. `site_pages/static/site_pages/js/map_decoder.js`) loaded from `{% block extra_scripts %}`. Data it needs comes from the template as `data-` attributes (URLs: `data-wear-url="{% url 'wear_skin' skin.id %}"`) or `{{ value|json_script:"id" }}`, never by writing template tags into JavaScript. No `onclick=""`-style attributes; add listeners in the script. Show and hide with the `hidden` attribute.

**Styles** go in a stylesheet: a shared file in `skins/static/css/` when the rule is shared (`modal.css`, `cards.css`, `forms.css`), or the page's own file in its app's static folder, loaded from its `{% block extra_head %}` (`site_pages/static/site_pages/css/privacy.css`, `skins/static/css/social_stats.css`, ...). No `style=""` attributes and no `<style>` blocks in templates. The one exception is a value the template computes, passed as a CSS custom property (`style="--bar: 42%"`) and used by the stylesheet. `tests/test_frontend.py` checks; `500.html` is exempt because it must render without static files.

**Skin cards** come from two partials: `skins/partials/_skin_card.html` (the full card; `mode` is `search`, `mine` or `favorite`) and `_skin_card_compact.html` (the linked tile on the home carousels and browse pages). Feed the full card with `skins.selectors.decorate_skins_for_user(skins, request.user)`, which adds the favorite count and the visitor's vote and favorite in a fixed number of queries. What a card does (⋯ menu, image zoom, broken-image fallback, votes, favorites, Wear) is `static/core/js/bv-cards.js`, loaded in `base.html`; a page script only adds its own menu items (Edit, Delete, Re-render). Don't write card markup or wire card buttons in a page; `tests/test_frontend.py` fails if you do.

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
