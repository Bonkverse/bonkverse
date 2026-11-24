# bonk.io login rate-limit tools

Two Tampermonkey userscripts used to measure how bonk.io limits logins
(2026-11-10). What they found, and how to read their results:
[docs/bonk/login-rate-limit.md](../../docs/bonk/login-rate-limit.md).

| Script | What it does |
|---|---|
| `ratelimit-lab.user.js` | Runs the experiments on a fixed clock, one fresh VPN IP each where it matters, and exports the results as JSON/CSV. Since 1.3 it also runs the remember-me experiments (RFC-0003 lab tests 1–5) |
| `login-logger.user.js` | Records every login bonk.io's own page makes (time, account, answer, your public IP), for manual testing |

Rules:

- Use your own test accounts, never a player's. Passwords stay in
  Tampermonkey storage on your computer and are never logged or exported.
- Never run them from Railway or anything sharing Bonkverse's outbound IP:
  tripping the limit there locks every Bonkverse user out.
- Use a VPN (not home internet) for numbers that match Railway's.
- Turn the logger off while the lab runs, or requests are logged twice.
- Keep the lab's tab visible; hidden tabs slow its timers.

## Remember-me experiments (1.3)

Six experiments, grouped "remember", for RFC-0003 Part 2. They use the first
two saved accounts (A and B), log in with `remember: true` to get real
remember-me tokens, and revoke every token they got with
`login_clearauto.php` when they finish (or are stopped).

| Experiment | Test | Needs from you |
|---|---|---|
| `remember-answer` | 4 + 5: what `login_legacy.php` (remember true/false) and `login_auto.php` answer; session lifetimes; is a token reusable, does it rotate | Nothing (uses the current IP) |
| `remember-second-token` | 1: does a second remember-me login cancel the first token? | Nothing |
| `remember-revoke` | 3: `login_clearauto.php` on one token; is the other still good? | Nothing |
| `remember-password-change` | 3: does a password change revoke tokens? **Optional, unticked** | Change account A's password on bonk.io when asked, then change it back |
| `remember-auto-count` | 2a: 30 `login_auto.php` calls, 1 s apart; limited? A correct login after? | A new VPN location when asked |
| `remember-auto-during-block` | 2b: trip the limit, `login_auto.php` at +3 s and +10 min, one correct login at +22 min (~23 min) | A new VPN location when asked |

Tokens are never logged or exported: the log shows key names, token lengths,
a 4-byte SHA-256 fingerprint (to tell tokens apart), and the session token's
hours left. Export JSON when done and hand it over.
