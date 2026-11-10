# bonk.io login rate-limit tools

Two Tampermonkey userscripts used to measure how bonk.io limits logins
(2026-11-10). What they found, and how to read their results:
[docs/bonk/login-rate-limit.md](../../docs/bonk/login-rate-limit.md).

| Script | What it does |
|---|---|
| `ratelimit-lab.user.js` | Runs the experiments on a fixed clock, one fresh VPN IP each, and exports the results as JSON/CSV |
| `login-logger.user.js` | Records every login bonk.io's own page makes (time, account, answer, your public IP), for manual testing |

Rules:

- Use your own test accounts, never a player's. Passwords stay in
  Tampermonkey storage on your computer and are never logged or exported.
- Never run them from Railway or anything sharing Bonkverse's outbound IP:
  tripping the limit there locks every Bonkverse user out.
- Use a VPN (not home internet) for numbers that match Railway's.
- Turn the logger off while the lab runs, or requests are logged twice.
- Keep the lab's tab visible; hidden tabs slow its timers.
