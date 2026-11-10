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

## What we don't know yet

- **How long bonk.io remembers wrong passwords** that didn't cause a block.
  This decides whether wrong passwords spread over a busy afternoon add up to
  4. The lab's `memory-5/15/30/60min` experiments measure it (3 wrong, a quiet
  wait, then count how many more get through).
- **Whether made-up remember-me tokens sent to `login_auto.php` count**, and
  whether `login_auto.php` is blocked along with `login_legacy.php`. This
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

| Rule | What the code does | Where |
|---|---|---|
| Per IP, and our IP is everyone's | Every login goes through one place that limits wrong passwords before bonk.io sees them | `skins/login_attempts.py` |
| 4 wrong passwords per IP | 2 wrong per account per visitor in 15 min, 3 per visitor across accounts, then a 15-minute hold. Keyed on name **and** visitor, so a stranger's wrong passwords for your name hold only the stranger | `ACCOUNT_FAILURES_ALLOWED`, `CLIENT_FAILURES_ALLOWED` |
| Unknown usernames don't count | They count per visitor only, not per account | `ACCOUNT_COUNTED_FAILURES` |
| Any request restarts the block | After `ratelimited`, no login reaches bonk.io for 17 minutes, with no checks inside the pause | `LOGIN_RATE_LIMIT_PAUSE` in `integrations/bonk_api.py` |
| — | Whoever had wrong passwords when bonk.io limited the site is held 30 minutes, so their retry isn't the first login after the pause | `TRIGGER_HOLD_SECONDS` |
| — | One login per click on `/login/` and in the wear login popup | `static/js/login.js`, `core/js/bv-wear.js` |

None of this can stop four different players' wrong passwords from adding up.
The lasting fix is for logins to leave from **each player's own IP**, so a
wrong password only ever blocks the person who typed it: the Bonkverse
extension can make the request itself; a normal web page can't,
because bonk2.io doesn't allow other sites to read its answers (checked
2026-11-10: a `fetch` from bonkverse.io to `login_legacy.php` was blocked by
CORS, no `Access-Control-Allow-Origin` header).
Remember-me logins (`login_auto.php`) would also mean fewer typed passwords.

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
