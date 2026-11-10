# 2026-11-05: The reappearing bonk.io login modal, and bonk.io rate limits

**Impact:** for days (at least since 2026-10-30, the oldest logs we could
read), some players saw the bonk.io login modal open again after every
login when they wore certain skins. Separately, bonk.io refused most logins
through Bonkverse with `ratelimited` in bursts on most days, usually for an
hour or two at a time.
**Fixed by:** #39 (the modal). The rate-limit bursts are not fixed; their
cause is unknown (below).

> **Update 2026-11-10:** the login bursts are now explained, at least from
> 2026-11-08 on: about 4 wrong passwords from anyone on the site block the
> server's IP for ~15 minutes, and any request during the block restarts it.
> See [2026-11-09](2026-11-09-login-lockouts.md) and
> [bonk/login-rate-limit.md](../bonk/login-rate-limit.md).

> This page was first written with the wrong cause: that the modal loop
> generated enough logins to get Bonkverse rate-limited. A closer read of
> the logs disproved that (see "Rate limits"). Corrected the same night.

## The modal loop (found and fixed)

1. A player wears a skin bonk.io won't accept, e.g. skin 5397 (a
   1,552-character code). bonk.io answers `{"r": "fail", "e": "avatar_too_big"}`.
2. Bonkverse treated **every** refusal as an expired token (a fallback from
   Phase 2.2, when the real codes were unknown), answered 401 `auth: "bonk"`,
   and the page opened the bonk.io login modal.
3. The player logs in, the page retries, bonk.io refuses again, and the modal
   reopens. The same happened for every `ratelimited` refusal.

Of 49 refused wears on the evening of Nov 5, 24 were `avatar_too_big`,
24 `ratelimited`, and 1 `token`. Only that one should have opened the modal.

`_debug_wear` (kept since Phase 1 for this bug; removed in Phase 3.2 once
production logs showed the loop gone) and the
`bonk.io refused avatar update | bonk_error=...` line from #31 made it visible.

## Rate limits (not caused by Bonkverse's traffic, as far as we can tell)

bonk.io's `ratelimited` appears in the logs on most days since at least
Oct 30. Logged per day: Oct 30: 92, Oct 31: 6, Nov 1: 0, Nov 2: 42,
Nov 3: 104, Nov 4: 60+, Nov 5: 87+ (counts after Nov 3 are login refusals
only). Before #31, players saw these as "Bonk.io login failed: fail", the same
message as every other failure, so they looked like nothing new.

Hour by hour, the bursts **don't follow Bonkverse's own traffic**:

| Hour (UTC) | Successful logins | Too-big refusals (loop) | `ratelimited` |
|---|---|---|---|
| Nov 1 21:00 | 7 | 5 | 0 |
| Nov 3 15:00 | 0 | 0 | 12 |
| Nov 3 17:00 | 1 | 0 | 12 |
| Nov 3 19:00 | 8 | 5 | 0 |
| Oct 30 21:00 | 1 | 0 | 13 |

Each burst is mostly the same people retrying after the first refusal.

**Likeliest cause (unconfirmed):** bonk.io appears to limit by IP. Every
Bonkverse user reaches bonk.io from the server's outbound IP, and Railway's
docs say outbound IPs "may be shared with other customers" (even static
ones). Other traffic to bonk.io from that IP, from other services in the
Bonkverse Railway project or other Railway customers, would trigger limits
Bonkverse didn't cause. bonk.io changing its limits is also possible.

## What changed in #39

- `integrations/bonk_api.py` maps each code: `token` → `token_rejected`,
  `avatar_too_big`, `ratelimited` → `rate_limited`; anything else → `rejected`.
- **Only `token_rejected` opens the login modal.** Other wear failures return
  422 / 503 / 502 with a `message` the page shows.
- Login says "bonk.io is limiting logins from Bonkverse right now" instead of
  "bonk.io didn't accept that login".
- After any `ratelimited`, Bonkverse makes no bonk.io calls for 120 s, so it
  doesn't add requests while bonk.io is limiting the IP.

## Follow-ups

- **Find what triggers the rate limits:**
  - Check which other services in the Bonkverse project call bonk2.io
    (ReplayFetcher makes HTTPS calls to Cloudflare-hosted addresses every
    few minutes; bonk.io is behind Cloudflare, but that's unconfirmed).
  - During a burst, log in to bonk.io from a home connection. If that works
    while Bonkverse is refused, the limit is on the server's IP, not the
    accounts.
- bonk.io's size limit for skin codes is unknown. If we learn it, warn on the
  skin page before someone tries to wear an oversized skin.
- If bursts continue, share the cooldown across workers (Redis).
- Phase 3's single login modal removes the three copies of the wear flow.
  Done in Phase 3.2: `static/core/js/bv-wear.js` retries once after a login
  and never reopens the modal, so a future wrong answer can't loop.
- **Confirmed fixed (2026-11-06 logs, after #39 deployed):** a real expired
  token opened the modal once and the retry succeeded; skin 5397 was refused
  as too big with no login after it; the rate-limit burst ended at 01:59 UTC.
