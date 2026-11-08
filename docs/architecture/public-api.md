# The public API (`public_api/`, `/api/v1/`)

What other sites and bots can read from Bonkverse, and how keys work.
Why it's built this way: [ADR 0011](../adr/0011-public-api.md). The guide
for people *using* the API (with copy-paste examples) is the developer docs
site, `Bonkverse/developers`; this page is for running it.

## Endpoints

| Method and path | Tier | Returns |
|---|---|---|
| `GET /api/v1/me/` | `api` | The key you're using (name, prefix, tier) |
| `GET /api/v1/players/<username>/` | `api` | One player: level, peak, when seen, games, bonk.io account (DBID, join day), profile URL |
| `GET /api/v1/players/<username>/level-history/` | `api` | Level-ups and the highest level per day |
| `POST /api/v1/lookup/players/` | `api_bulk` | Up to 250 players at once, each with a `status` |

Usernames are matched ignoring case. `.` and `..` are written `~.` and `~..`
in the path (same converter as profile pages, `players/converters.py`).

Each player entry has a `status`: `found`, `not_found` (no replays),
`private` (they hid their Level section: `level` is null) or `unavailable`
(the replay site didn't answer). In the bulk lookup one bad name never fails
the request. The single-player endpoint turns `not_found` into 404 and
`unavailable` into 503.

## Where the numbers come from

- `level`, `peak`, `games`, `seen_*`: the replay site's
  `/api/players/lookup` (ReplayRenderer), cached per player for
  `PLAYER_PROFILE_CACHE_SECONDS` in Redis. A bulk lookup asks the replay
  site in chunks of 60 for names not in cache. Outages aren't cached.
- `seen_at` is the collection time of the latest replay showing that player
  (exact for live-collected replays, `null` for backfilled ones);
  `seen_day` is always set and `estimated: true` marks cycle-estimated days.
- `account` (`dbid`, `joined`, `joined_estimated`): Bonkverse's own
  `BonkPlayer` rows (from friend lists and logins), `null` when Bonkverse
  hasn't met that account. `joined` is estimated from the ID
  (`core/bonk/dbid.py`), as on player cards. The DBID is public there too.
- Level history reuses the profile pages' cached replay profile.
- Not published: login XP (`BonkPlayer.xp`), friends, Flash friends.

## Keys

```bash
# Create (prints the key ONCE; send it privately)
railway ssh -- python manage.py create_api_key \
  --name "Luna comp leaderboard" --contact "luna0051 (Discord)" --tier partner

# Revoke (takes effect immediately)
railway ssh -- python manage.py revoke_api_key bvk_ab12cd34
```

- Format `bvk_<8-char prefix>_<43-char secret>`. Only the prefix is safe to
  share or log; the database holds a SHA-256 of the whole key.
- Staff see keys, contacts and `last_used_at` in Django admin (Public API →
  API keys) and can revoke from there. Keys can't be created in admin.
- Logs: every call logs `public api: key=bvk_<prefix> <method> <path> -> <status>`.

## Limits

Per key, in fixed one-minute windows: `api` 60/m (`api_partner` 300/m),
`api_bulk` 10/m (`api_bulk_partner` 30/m). Failed key checks: 20/m per IP,
then that IP gets 429 until the window ends. Overrides and the shared
machinery: [rate-limiting.md](../operations/rate-limiting.md).

## Errors

`{"ok": false, "error": "<code>"}`. Codes are part of the contract:
`missing_api_key`, `invalid_api_key` (401, with `"auth": "api_key"`),
`rate_limited` (429, `retry_after`), `player_not_found` (404),
`player_private` (403, level history only), `upstream_unavailable` (503),
`invalid_username`, `usernames_required`, `too_many_usernames` (with `max`),
`invalid_json` (400), `method_not_allowed` (405).

## Changing it

Within v1, add fields and codes; never rename or remove them. Update the
developer docs site in the same PR. Tests: `tests/test_public_api.py`.
