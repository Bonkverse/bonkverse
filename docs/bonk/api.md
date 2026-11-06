# bonk.io account API

The three bonk.io scripts Bonkverse calls, the exact request we send, what
comes back, and the quirks. bonk.io doesn't document any of this; everything
here is either recorded from real responses or matches what other open-source
bonk.io clients rely on, and says which.

Code: `integrations/bonk_api.py` (`BonkApi`, `get_client()`). Quirks are
tagged `# BONK:` in the code. Fixtures: `tests/fixtures/bonk/`. Tests:
`tests/test_bonk_api.py`.

## Basics

- Base URL: `https://bonk2.io/scripts` (setting `BONK_API_BASE_URL`).
- Every call is a form-encoded `POST`
  (`application/x-www-form-urlencoded`).
- Headers: a desktop Chrome `User-Agent`, `Origin: https://bonk.io` and
  `Referer: https://bonk.io/`, the same as bonk.io's own web client calling
  across origins.
- Timeouts: `(BONK_CONNECT_TIMEOUT, BONK_READ_TIMEOUT)`, default `(4, 8)`
  seconds, for every call.
- **Failures are HTTP 200.** A refusal is `{"r": "fail", "e": "<code>"}`.
  Success is `{"r": "success", ...}`. Anything else (connection error,
  timeout, HTTP 4xx/5xx such as a Cloudflare challenge, a body that isn't a
  JSON object) is treated as bonk.io being unavailable.

## How results are reported

Every client call returns a result with `ok`, `error` and `bonk_error`
instead of raising. `error` is one of Bonkverse's codes (`BonkError`);
`bonk_error` is bonk.io's own `e` value, kept for logs.

| `error` | Meaning | What Bonkverse does |
|---|---|---|
| `wrong_password` | bonk.io `e: "password"` | "Wrong password." |
| `unknown_username` | bonk.io `e: "username_fail"` | "No bonk.io account has that username." |
| `token_rejected` | bonk.io `e: "token"` (expired or invalid token) | Wear: 401 `auth: "bonk"`. **The only case that opens the bonk.io login modal.** |
| `avatar_too_big` | bonk.io `e: "avatar_too_big"` | Wear: 422 "This skin is too big for bonk.io…" |
| `rate_limited` | bonk.io `e: "ratelimited"`, or Bonkverse is cooling down (below) | Login: "bonk.io is limiting logins from Bonkverse right now…" Wear: 503 |
| `rejected` | Any other refusal (unknown `e`, logged) | Login: "bonk.io didn't accept that login." Wear: 502 "bonk.io didn't accept this skin." |
| `network_error` | No usable answer | Login: "Network error talking to bonk.io." Wear: 502 |

Wear replies with no `auth` tag carry `message`, a sentence the page shows.

### The reappearing login modal (fixed 2026-11-05)

Wear used to treat every refusal as an expired token and open the login
modal. Production logs showed what that did: bonk.io refused one skin with
`avatar_too_big`, the player logged in, the retry was refused again, and the
modal came back, dozens of times. Of 49 refused wears in the logs, one was
really `token`. See the
[incident](../incidents/2026-11-05-bonk-rate-limit.md).

### Rate limits and the cooldown

bonk.io answers `{"r": "fail", "e": "ratelimited"}` (seen on both
`login_legacy.php` and `avatar_update.php`) when one IP sends too much. All
Bonkverse users reach bonk.io from the same server IP, so one person's
retries can lock everyone out. On 2026-11-05 most logins failed for hours.

So after any `ratelimited`, the client makes **no bonk.io calls for 120 s**
(`RATE_LIMIT_COOLDOWN`) and answers `rate_limited` itself (`bonk_error` is
empty for these). The cooldown is per server process. The log line is
`bonk.io rate-limited <script>; pausing bonk.io calls for 120.0s`.
How long bonk.io's own limit lasts is unknown.

## `login_legacy.php`

Exchange a username and password for a token.

Request:

| Field | Value |
|---|---|
| `username` | As the player typed it, unchanged (never trimmed) |
| `password` | Never logged or stored |
| `remember` | `false` |

This is what bonk.io's web client sends, per two independent community
write-ups (the DemystifyBonk notes and the bonkonauts site's login code).
Before 2.2, Bonkverse had two shapes: the site login sent no `remember`, and
the in-page wear login sent `task=legacy` and no browser headers. Both
worked; the client now sends only the web client's shape.

Success (`login_success.json`, synthetic):

| Field | Meaning |
|---|---|
| `token` | Session token for the other scripts. Stored in the site session (`BonkSession`), and signed in `BonkAccountLink`. |
| `username` | The account's name **as bonk.io spells it**. Can differ in capitalization from what was typed: login accepts any capitalization (verified 2026-11-03). If missing, the typed name is used. |
| `id` | Numeric account id; the real identity (`BonkPlayer.bonk_id`). |
| `activeAvatarNumber` | The account's active avatar slot, 1–5. A lowercase `activeavatarnumber` is also accepted. |
| `legacyFriends` | Flash-era friends: one string of names separated by `#`. Empty segments are parsing artifacts; whitespace-only names are real. |
| `xp` and others | Not used. |

Refusals: `e: "password"` (`login_wrong_password.json`), `e: "username_fail"`
(`login_unknown_username.json`). Both codes are the ones other open-source
bonk.io clients check; our fixtures are hand-written to match.

## `friends.php`

The player's current friends and incoming friend requests.

Request: `token`, `task=getfriends`.

Success (`friends_success.json`, synthetic): `friends` and `requests`, each a
list of `{"id": ..., "name": ...}`. The client handles these cases, which
friend sync has guarded against since before 2.2 (not yet recorded):

- `id` can arrive as a number or a numeric string. Entries whose id isn't a
  number are dropped.
- `name` can be missing or empty. Such an entry is kept with `name=None` so
  the friendship isn't pruned just because this response had no name.
- Names are stored exactly as sent, spaces included.

Refusal for a stale token: not recorded. `friends_token_expired.json` uses
`e: "token"`, the code `avatar_update.php` gives (recorded), on the
assumption the scripts share token checking.

## `avatar_update.php`

Put a skin in one of the account's five avatar slots.

Request: `task=updateavatar`, `token`, `newavatarslot` (`"1"`–`"5"`),
`newavatar` (the skin code, as stored).

Success: `{"r": "success"}` (recorded 2026-11-03).

A token bonk.io doesn't accept gets `{"r": "fail", "e": "token"}`, whether
it has expired (recorded 2026-11-05, a genuine token after its `exp`) or been
tampered with (recorded 2026-11-03, signature altered).

Other refusals seen in production logs (2026-11-05, no recorded bodies yet):
`avatar_too_big` (a skin code of 1,552 characters; bonk.io's limit is
unknown) and `ratelimited`. Every refusal is logged with its `e` value
(never the token), as `bonk.io refused avatar update | bonk_error=...`.

The token is a JWT whose payload holds the account id, username, the IP it
was issued to and an `exp` time. Treat it like a password. The one recorded
was valid for about two days, and bonk.io refused it once `exp` passed.

Skin codes are sent as stored. A URL-encoded stored code (`%2F` etc.) is
form-encoded again on the way, and bonk.io still answers success
(2026-11-03); whether the skin then renders correctly in game is not yet
checked.

## Recording a fixture

Most fixtures are synthetic. To replace one with a real body:

1. In a browser signed in to bonk.io, open DevTools → Network and do the
   action (log in, open friends, change an avatar).
2. Copy the response body of the `*.php` request.
3. Replace every token with `SCRUBBED-...`, and every real name and id with
   made-up ones. Never commit a live token, password or real player's data.
4. Save it under `tests/fixtures/bonk/` and change its row in that folder's
   README from `synthetic` to `recorded YYYY-MM-DD`.

The most useful recordings still missing: `friends.php` (success and
expired token) and a real `login_legacy.php` success body.
