# 2026-11-09: Wrong passwords lock everyone out of bonk.io login

**Impact:** nobody could log in to Bonkverse (or log in from the wear popup)
for 68 minutes (22:04–23:11 UTC, 5:04–6:11pm EST) and 78 minutes
(02:18–03:36 UTC, 9:18–10:36pm EST), plus shorter stretches most hours on
2026-11-09 and 11-10. Players saw "bonk.io is limiting logins from Bonkverse
right now."
**Trigger:** a few wrong passwords from players, through Bonkverse.
**Fixed in:** #81.

## What happened

1. bonk.io limits logins by IP. From a datacenter IP it allows about 4 wrong
   passwords, then refuses every login from that IP for about 15 minutes
   after the last request it sees ([bonk/login-rate-limit.md](../bonk/login-rate-limit.md)).
2. Every Bonkverse login reaches bonk.io from the server's one IP, so one
   player retyping a password (or two players each mistyping twice) used up
   the site's 4.
3. Bonkverse then paused logins site-wide, but checked bonk.io again after 2,
   4, 8 and 16 minutes. Each check landed inside bonk.io's block and restarted
   its 15 minutes, so the block lasted until the pause stretched past it.
4. Repeated clicks added to it: on 2026-11-10 the logs show 4–5 login
   submissions within 1–2 seconds, each a separate request to bonk.io.

At first this looked like a per-account limit, and then like a limit on how
fast logins come. Both were wrong; a scripted test on 2026-11-10 settled it
(the "What we measured" table in [bonk/login-rate-limit.md](../bonk/login-rate-limit.md)).

## What changed

- After `ratelimited`, logins pause once for 17 minutes with nothing sent to
  bonk.io inside the pause (`LOGIN_RATE_LIMIT_PAUSE`), instead of the
  2/4/8/16-minute checks. An outage now lasts about 17 minutes, not an hour.
- Bonkverse holds a player's login after 2 wrong passwords (per account, per
  visitor) or 3 per visitor, before bonk.io sees the next try
  (`skins/login_attempts.py`). Whoever had wrong passwords when the limit hit
  is held 30 minutes.
- The login button and the wear login popup send one login per click.
- Every login attempt is logged with pseudonyms for the account and visitor,
  so the next lockout can be traced to its cause.

## Still open

Four different players' wrong passwords can still add up to a lockout, since
they share one IP. The fix for that is logging in from each player's own IP
(through the extension); see "What Bonkverse does about it" in
[bonk/login-rate-limit.md](../bonk/login-rate-limit.md).
