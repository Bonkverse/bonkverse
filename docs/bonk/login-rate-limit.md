# How bonk.io limits logins

What bonk.io does when a login (`login_legacy.php`) is refused with
`{"r": "fail", "e": "ratelimited"}`, measured on 2026-11-10, and what
Bonkverse does about it. bonk.io doesn't document any of this; everything here
comes from the experiments below, so it can change without notice. Re-run them
(see "Re-running the tests") if the numbers stop matching production.

## The rules, as far as we know

1. **It's per IP address, not per account.** Once an IP is limited, every
   login from it is refused, for every account, even with the correct
   password. The same accounts log in fine from another IP at the same moment.
2. **From a datacenter or VPN IP it allows 4 wrong passwords.** The 5th login
   from that IP is refused, whatever it is. How fast they come doesn't matter:
   1, 2, 3 and 5 seconds apart all gave exactly 4.
3. **A correct login doesn't reset the count.** Wrong, wrong, correct, wrong,
   wrong: the next login (a correct password) was refused.
4. **Unknown usernames don't seem to count.** 20 `username_fail` answers in a
   row from one IP, no limit.
5. **A block lasts about 15 minutes after the last request bonk.io saw from
   the IP**, and **every request during the block starts the 15 minutes
   over**, even a correct password. Left alone, a blocked IP was still blocked
   at 15 minutes and fine at 20. Tried once a minute, it was still blocked
   after 45 minutes.
6. **Home internet is treated more leniently.** A residential IP (Jorge's)
   took 16 wrong passwords at 0.5 s apart, and 32 at 2–6 s apart, before
   being limited. Railway is a datacenter IP, so **Bonkverse gets rule 2.**

For Bonkverse, where every user's login reaches bonk.io from the server's one
IP, that means: **about 4 wrong passwords from anyone on the site, and
nobody can log in for at least 15 minutes.**

## What we measured

All runs used five test accounts owned by Jorge, a fake password for the wrong
ones, and the lab script below. Each experiment ran on its own fresh VPN IP
unless it says otherwise. Times are UTC.

| Question | Test | Result |
|---|---|---|
| Per account or per IP? | Trip the limit on account A at home, then log in to account B (correct password) at home, then A on a VPN | B refused at home; A **and** B fine on the VPN (manual run, 15:44–15:50) |
| How many wrong passwords? | Wrong passwords every 1 / 2 / 3 / 5 s | 4, 4, 4, 4, then `ratelimited` (16:18–16:20) |
| Does speed matter? | Same as above | No: 1 s and 5 s both allowed exactly 4 |
| Does a success reset it? | W W ✓ W W ✓ at 1 s, one account | The second ✓ was refused (16:22) |
| Do unknown usernames count? | A made-up username every 1 s | 20 `username_fail`, never limited (16:21); see the note below |
| How long does a block last? | Trip, then **one** correct login (other account) after 5 / 10 / 15 / 20 min | Refused, refused, refused, **worked** (16:22–17:14) |
| Does retrying make it longer? | Trip, then a correct login every minute | Refused all 45 times, 17:15–18:00 |
| Same, on home internet | Manual: last refused request 15:47:55, nothing until 16:02:44 | Worked, 14 m 49 s later |
| Home vs VPN | Wrong passwords at 0.5 s from home | 16 before the limit (16:17); 32 at 2–6 s in the manual run |

Notes on the data:

- **Bursts can get past the count.** In two runs the VPN held requests back
  and then delivered 12 and 23 of them at the same instant; bonk.io answered
  all of them `password` before its counter caught up. Bonkverse sends logins
  one at a time, so this doesn't help or hurt us. Those two runs still
  measured the block length correctly.
- **The unknown-username run ended oddly.** After 20 answers, the requests
  failed with a network error instead of a bonk.io answer. Most likely the
  VPN connection dropped; it could also be a block below bonk.io's own API.
  Treat "unknown usernames don't count" as likely, not certain.
- **The 15 minutes are approximate.** The single-try results put the end
  between 15 m 03 s (still refused) and 20 m (fine) after the trip; the home
  run was fine at 14 m 49 s after the last refused request. "About 15 minutes,
  maybe a little more" covers all three.
- **`ratelimited` answers come back fast** (often 100–300 ms, against 300–700
  ms for a normal answer), so bonk.io decides before checking the password.

What production logs showed before the tests, and how they fit:

- Nearly every `ratelimited` on login (2026-11-08 to 11-10) came minutes after
  one to three wrong passwords. With 4 allowed for the whole site, wrong
  passwords from different players add up.
- On 2026-11-09 two outages lasted 68 and 78 minutes. Bonkverse's pause then
  checked bonk.io again after 2, 4, 8 and 16 minutes; each check landed inside
  the block and, by rule 5, restarted it.

## Remember-me tokens

Measured on 2026-11-24 with the lab's "remember" experiments (1.3), on two
fresh VPN IPs, with two test accounts (RFC-0003 lab tests 1–5).

| Question | Result |
|---|---|
| How long does a session token last? | 24 hours, with or without `remember: true`, and from `login_auto.php` too |
| What does `login_auto.php` answer? | The password login's answer minus `rememberToken`: a fresh 24 h `token`, `friends`, `xp`, `activeAvatarNumber`, the avatars |
| Does a remember-me token rotate or wear out? | No: the same token worked again and again (30 times in 30 s) and no new one came back |
| Does a second `remember: true` login cancel the first token? | No: both kept working |
| What does `login_clearauto.php` revoke? | Only the token sent; it then answers `not_found`. The account's other tokens keep working |
| Does a password change revoke tokens? | Not measured yet (the lab's optional `remember-password-change`) |
| Do `login_auto.php` calls count toward the login limit? | No: 30 calls in 30 s, all accepted, and a correct password login right after worked |
| Does `login_auto.php` work during a login block? | **Yes**: accepted 3 s and 10 min after the IP was blocked |
| Does a `login_auto.php` call during a block extend it? | **Probably**: a correct login 22 min after the trip (12 min after the last `login_auto.php`) was still refused, when blocks left alone ended by 20 min in the first lab. One run; the lab's `block-control-22min` (a trip with nothing after it, then a login at 22 min) settles it |

What this means for Bonkverse (RFC-0003 Part 2): one password login per
account and device, then `login_auto.php` refreshes the session daily without
a password and without spending the wrong-password budget. While Bonkverse's
own login pause is on, refreshes still wait (the broker answers "paused"),
because a request during bonk.io's block seems to restart it.

## What we don't know yet

- **How long bonk.io remembers wrong passwords** that didn't cause a block.
  This decides whether wrong passwords spread over a busy afternoon add up to
  4. The lab's `memory-5/15/30/60min` experiments measure it (3 wrong, a quiet
  wait, then count how many more get through).
- **Whether made-up remember-me tokens sent to `login_auto.php` count.**
  Real ones don't, and `login_auto.php` isn't blocked along with
  `login_legacy.php` (see "Remember-me tokens" above). This
  decides how a login made by the extension (from the player's IP) can be
  checked on the server. The lab's `tokens-alone-1s`, `tokens-then-wrong` and
  `token-during-block` experiments measure it. bonk.io's own client posts
  `{rememberToken}` to `login_auto.php` (seen in its `alpha2s.js`).
- Whether successful logins count toward some other, much higher limit
  (a player said about 500 an hour).
- Whether `friends.php` and `avatar_update.php` follow the same rules. They
  keep the older doubling pause until measured (`integrations/bonk_api.py`).
- Why home IPs are treated more leniently (IP reputation, IPv6, or something
  else).

## What Bonkverse does about it

Production showed the lab's 4 is 3 from Railway's IP: on 2026-11-10 three
trips came after exactly 3 wrong passwords, and one came from a burst of
correct logins with none wrong (a bot logging in 10 new accounts 17 times in
100 s, each from a different visitor IP). So Bonkverse guards the whole
site's budget, not only each visitor's (RFC-0003 Part 1, from the
production check of 2026-11-10).

| Rule | What the code does | Where |
|---|---|---|
| Per IP, and our IP is everyone's | Every login goes through one place, which checks the guards below before bonk.io sees anything | `accounts/login_attempts.py` |
| About 3 wrong passwords, site-wide | After 2 wrong passwords anywhere on the site in 15 minutes, new logins wait (with a countdown) until the oldest ages out, instead of one of them spending the third | `site_wrong_passwords` |
| — | 2 wrong per account per visitor, 2 per visitor across accounts, then a 15-minute hold. Keyed on name **and** visitor, so a stranger's wrong passwords for your name hold only the stranger | `account_wrong_passwords`, `visitor_wrong_passwords` |
| Unknown usernames don't count | They don't count toward the site budget or the wrong-password allowances; a looser per-visitor count (5) only stops guessing names through Bonkverse | `visitor_unknown_usernames` |
| Fast bursts trip it too | At most 4 logins a minute reach bonk.io site-wide, and 1 a minute per bonk.io account; above that, "Lots of logins right now" and nothing is sent | `site_per_minute`, `account_per_minute` |
| — | One login at a time per account and visitor, on the server, so a double submit is one try | `_in_flight` |
| Any request restarts the block | After `ratelimited`, no login reaches bonk.io for 17 minutes, with no checks inside the pause. Wears and friend reads wait too: on 2026-11-10 two wears during a pause were the only calls before it re-tripped | `LOGIN_RATE_LIMIT_PAUSE`, `_Cooldowns.remaining` in `integrations/bonk_api.py` |
| — | When bonk.io limits the site anyway, everyone with a wrong password in the window is held 5 minutes past the pause, not whoever's login happened to get the refusal | `AFTER_PAUSE_SECONDS` |
| — | One login per click on `/login/` and in the wear login popup | `accounts/static/accounts/js/login.js`, `core/js/bv-wear.js` |

The limits in the right-hand column are `BONK_LOGIN_LIMITS` in settings,
each overridable with `BONK_LOGIN_<NAME>` (docs/operations/configuration.md),
so they can be tuned from the logs. Every turned-away login is logged under
`skins.login` ("bonk login held", "waiting for the site budget", "busy",
"already in flight").

Players read why: a shared wait says it is for everyone and not their fault,
and the login page adds the time it ends in their own time zone.

None of this can stop different players' wrong passwords from adding up; it
only keeps them from reaching bonk.io's count. The lasting fix is for logins
to leave from **each player's own IP**, so a wrong password only ever blocks
the person who typed it: the Bonkverse extension can make the request itself;
a normal web page can't, because bonk2.io doesn't allow other sites to read
its answers (checked 2026-11-10: a `fetch` from bonkverse.io to
`login_legacy.php` was blocked by CORS, no `Access-Control-Allow-Origin`
header). Remember-me logins (`login_auto.php`, RFC-0003 Part 2) would also
mean fewer typed passwords.

The pause, holds and log lines are described in [api.md](api.md#rate-limits-and-the-cooldown).

## Re-running the tests

The scripts are in [`scripts/bonk-login-ratelimit/`](../../scripts/bonk-login-ratelimit/).
Both are Tampermonkey userscripts for bonk.io:

- `ratelimit-lab.user.js` runs the experiments above on a fixed clock. You
  enter test accounts and a fake password in its panel (kept in Tampermonkey
  storage on your computer; never logged or exported), press Start, and
  switch VPN location when it asks; it waits for an IP it hasn't used and
  marks a run invalid if the IP changes mid-way. Export JSON when done.
- `login-logger.user.js` just records every login bonk.io's own page makes
  (time, account, answer, your public IP), for manual testing.

Use your own test accounts, never a player's, and don't run them on Railway:
tripping the limit from the server's IP locks every Bonkverse user out.
Run them from a VPN rather than home internet if you want numbers that match
Railway's (rule 6). Expect each IP you use to be blocked on bonk.io for about
15 minutes afterwards.
