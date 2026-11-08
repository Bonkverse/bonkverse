# Outside services (`integrations/`)

Every call the site makes to another service goes through one module in
`integrations/`. Nothing else imports an HTTP library;
`tests/test_architecture.py` fails if something does (RFC-0001 Phase 2).

Each client follows the same rules:

- **Never raises** for the other service being down or saying no. It returns
  a small result object with an error code, and the caller decides what
  people see.
- **Always has a timeout**, as `(connect, read)` seconds.
- **Logs the reason** for a failure (status, error code, exception type),
  never a token, password or key.
- **No Django at import time** and no imports from `skins/` or `django.db`,
  so it could be lifted into a shared package. A `*_configured()` or
  `get_client()` helper reads settings.

Setting names and defaults: [configuration.md](../operations/configuration.md).

| Service | Client | Called from | Failures people see |
|---|---|---|---|
| bonk.io account scripts (login, friends, avatar) | `bonk_api.py` (`BonkApi`) | `skins/login.py`, `skins/wear_skin.py`, friend sync | Wrong password / unknown name / "bonk.io isn't responding" (502, no login modal). Details: [bonk/api.md](../bonk/api.md) |
| Skin editor render service (`/api/render-bundle`) | `editor_render.py` | `skins/rerender.py`, `skins/skin_import.py` | "The render service couldn't render this skin" |
| BLSkinFetcher (BonkLeagues link → skin) | `bl_skin_fetcher.py` | `skins/skin_import.py` (upload form, BonxBot) | "Couldn't get that skin from BonkLeagues right now" |
| Cloudflare cache purge | `cloudflare.py` | `skins/rerender.py` | None; staff get `cache_purged: false`, logs say `cloudflare purge failed` |
| Discord invite API (public, no auth) | `discord_api.py` | `skins/discord_views.py` (submit), `skins/tasks.py` (hourly refresh) | Invalid / inaccessible invite, "Couldn't reach Discord right now" |
| BonkBot API | `bonkbot.py` | `skins/bonkbot.py` (`/api/join-matchmaking/`) | `{"error": "matchmaking_unavailable"}` (502) |
| Map decoder service | `map_decoder.py` | `skins/utils/tools/map_decode.py` | "Couldn't decode that map string" (400, with the decoder's reason) or "isn't responding" (502) |
| Replay site player API (`/api/player/<name>`, `/api/player/<name>/map/<mapid>`) | `replays.py` | `players/selectors.py` (every profile tab) | "Replay stats can't be loaded right now" (page still renders); unknown name → 404 page |
| BonxBot's Postgres (one-time migration) | `bonxbot_db.py` | `import_bonxbot_skins` command | Command output |

## Discord: pace your calls

Invite lookups are unauthenticated, so they share Discord's per-IP limits with
everything else on the server. The hourly refresh looks up **one invite per
second**. On a 429 it waits Discord's `retry_after` (at most 60 s) and tries
once more; if it is still limited, it stops that run and logs
`discord refresh stopped: rate limited`. The next hourly run picks up from
the start. Invites Discord no longer knows (404) are counted and logged, and
the server stays listed.

The task returns `{"refreshed", "not_found", "failed", "stopped_rate_limited"}`,
which Celery stores as the result and which is logged as `discord refresh done`.

## Adding a new outside call

1. Add `integrations/<service>.py` with a module docstring saying what it owns
   and what it doesn't, a result dataclass, and a timeout.
2. Put the URL (and any key) in settings, read in a `*_configured()` helper.
3. Test it with `responses` (the `mocked_http` fixture): success, refusal,
   unreachable, and a non-JSON reply. Real HTTP is blocked in tests.
4. Add a row to the table above and the setting to configuration.md.
