# 2026-11-05: Login modal loop gets Bonkverse rate-limited by bonk.io

**Impact:** from about 22:25 UTC Nov 5 (17:25 EST) into the night, most
bonk.io logins through Bonkverse failed: 53 of 71 logged attempts in the
window we read. Wearing skins failed too. For days before that, the bonk.io
login modal kept reappearing for some players when they wore certain skins.
**Trigger:** one skin (id 5397, a 1,552-character skin code) that bonk.io
refuses as `avatar_too_big`.
**Fixed by:** the PR that adds this file. It handles bonk.io's refusal codes,
adds a client-side cooldown after `ratelimited`, and adds sentence messages.

## What happened

1. A player wore skin 5397. bonk.io answered
   `{"r": "fail", "e": "avatar_too_big"}`.
2. Bonkverse treated **every** bonk.io refusal as an expired token (a
   deliberate fallback from Phase 2.2, when the real codes were unknown), so
   it answered 401 `auth: "bonk"` and the page opened the bonk.io login modal.
3. The player logged in. The page retried the wear, bonk.io refused it again,
   and the modal opened again. The logs show this loop repeating every few
   seconds, for this skin and others.
4. Every one of those logins went to bonk.io from Bonkverse's server, which is
   a single IP for all users. bonk.io started answering `e: "ratelimited"` to
   logins and avatar updates, and every refusal reopened the modal.
5. People kept retrying, which kept the limit in place.

`_debug_wear` (kept since Phase 1 for exactly this bug) and the
`bonk.io refused avatar update | bonk_error=...` line added in #31 are what
made this visible.

Of 49 refused wears in the logs, 24 were `avatar_too_big`, 24 `ratelimited`,
and 1 `token`. Only that one should have opened the modal.

## What changed

- `integrations/bonk_api.py` maps each known code: `token` →
  `token_rejected`, `avatar_too_big`, `ratelimited` → `rate_limited`; anything
  else is `rejected`.
- **Only `token_rejected` opens the login modal.** Other wear failures return
  a status (422 / 503 / 502) and a `message` the page shows.
- After any `ratelimited`, Bonkverse makes no bonk.io calls for 120 s and
  answers `rate_limited` itself, so retries can't extend the limit.
- Login says "bonk.io is limiting logins from Bonkverse right now" instead of
  "bonk.io didn't accept that login".
- Details: [bonk/api.md](../bonk/api.md).

## Follow-ups

- bonk.io's size limit for skin codes is unknown. If we learn it, warn on the
  skin page before someone tries to wear an oversized skin.
- The cooldown is per server process. If rate limits keep happening, move it
  to Redis so all workers share it.
- Phase 3's single login modal removes the three copies of this flow, so a fix
  like this lands in one place next time.
