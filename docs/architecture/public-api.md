# The public API (`public_api/`, `/api/v1/`)

What other sites and bots can read from Bonkverse, and how keys work.
Why it's built this way: [ADR 0011](../adr/0011-public-api.md). The guide
for people *using* the API (with copy-paste examples) is
[docs.bonkverse.io/api](https://docs.bonkverse.io/api), from `Bonkverse/docs`;
this page is for running it.

## Endpoints

| Method and path | Tier | Returns |
|---|---|---|
| `GET /api/v1/me/` | `api` | The key you're using (name, prefix, tier) |
| `GET /api/v1/players/<username>/` | `api` | One player: level, peak, when seen, games, bonk.io account (DBID, join day), worn skin, profile URL |
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
- `skin` (`image_url`, `thumbnail_url`, `seen_at`): images of the skin
  the player last wore in game, from `BonkPlayer.worn_skin_*` (their newest
  replay, their own bonk.io login or a wear from Bonkverse, whichever is
  newest; [players.md](../apps/players.md#worn-skins)). `null` until
  Bonkverse has seen one.
  Published because anyone sees it in game and on the profile; there's no
  switch for it. The image URLs are the profile avatar routes (512 and
  128 px PNG), rendered on first request; they answer 404 if the render
  service can't draw the skin. Where we saw it (replay, login or wear) isn't
  published. Not cached with the replay rows: one query per request.
- **The skin code is never published** (removed 2026-11-14, a few hours
  after `skin` launched). It is the skin itself: anyone holding it can wear
  or edit an exact copy, and the bulk lookup would hand out every player's
  in an afternoon, against creators' control over copies (skin
  permissions). The image URLs' `v` is a one-way digest of the code.
- Level history reuses the profile pages' cached replay profile.
- Not published: login XP (`BonkPlayer.xp`), friends, Flash friends.

## Keys

**Self-serve, standard tier:** anyone signed in to Bonkverse makes their
own keys at `/developers/keys/` (the developer portal, `public_api/views/portal.py`,
rules in `public_api/services.py`):

- They agree to the API terms first (`/developers/terms/`), recorded in
  `ApiTermsAcceptance` with `services.TERMS_VERSION`. Changing the terms
  means bumping that version; everyone agrees again before their next new
  key, and existing keys keep working.
- At most `PUBLIC_API_MAX_KEYS_PER_USER` (3) active keys per account;
  revoked keys don't count. Owner-less keys (staff-issued) don't count.
- The full key is shown once, in the reply to the POST that made it
  (`Cache-Control: no-store`, never redirected, never stored).
- They can revoke their own keys; someone else's key answers "not found".
- `developers.bonkverse.io` is a Cloudflare redirect rule to
  `bonkverse.io/developers/` (no Django host of its own).

**Partner tier, by staff:** higher limits, issued by hand. To raise an
existing key, change its tier in Django admin.

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

Within v1, add fields and codes; never rename or remove them. Open the
matching `Bonkverse/docs` PR (pages under `docs/api/`, plus its changelog)
and link it from this repo's PR. Tests: `tests/test_public_api.py`.
