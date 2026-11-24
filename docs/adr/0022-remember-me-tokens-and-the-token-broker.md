# ADR 0022: Remember-me tokens, kept on the account link behind one token broker

**Status:** accepted, 2026-11-24 (RFC-0003 Part 2)

**Context.** A bonk.io session token lasts about 24 hours, so a player who
wears skins every few days typed their bonk.io password every time, and every
one of those logins spent the shared login budget that bonk.io limits per IP
(docs/bonk/login-rate-limit.md). bonk.io's own "remember me" gives a
long-lived token that `login_auto.php` swaps for a fresh session token, no
password. Measured with the lab on 2026-11-24: `login_auto.php` didn't count
toward the login limit (30 calls), doesn't rotate the remember-me token, a
second remember-me login doesn't cancel the first, `login_clearauto.php`
revokes only the token it's given, and a revoked token answers `not_found`.
`login_auto.php` works during a login block but seems to extend it.

A remember-me token is as good as a password until it's revoked, and session
tokens lived in two places (the account link and the site session).

**Decision.**
- **"Keep me connected for Wear"**, ticked by default on `/login/` and in the
  wear popup, sends `remember=true` and stores the remember-me token on the
  account link, encrypted under `BONK_TOKEN_KEYS` like the session token
  (ADR 0016). Unticked, nothing long-lived is kept, and a remember-me token
  stored before is revoked on bonk.io.
- **Tokens live only on the account link.** The site session keeps which
  bonk.io account the browser acts as (id, username, active slot), never a
  token. One copy to encrypt, rotate, revoke and reason about.
- **One token broker** (`accounts/bonk_tokens.py`) is the only code that reads
  or writes stored tokens. `usable_token(link)` returns the stored token while
  it's good, else refreshes through `login_auto.php` under a per-link Redis
  lock, and raises `ReconnectNeeded`, `Paused(seconds)` or `Unavailable`.
- **Refresh only when an action needs a token**, never on a schedule: an idle
  account costs bonk.io nothing, and Bonkverse never holds more live session
  tokens than players are using.
- **Nothing is sent during the login pause**, `login_auto.php` and
  `login_clearauto.php` included, because a request during the block seems to
  restart it.
- **`not_found` means revoked**: the token is deleted and the link marked
  `revoked`, so Settings can say why the player has to type the password.
- **Disconnect** (Settings) revokes the remember-me token on bonk.io, then
  deletes both tokens; the link (who owns which bonk.io account) stays.
  `revoke_bonk_remember_tokens --run` does this for everyone after a possible
  key and database leak (runbook).

**Alternatives considered.**
- *Refresh every link before its token expires* (a periodic task): Wear would
  never wait for a refresh, but Bonkverse would call bonk.io for thousands of
  idle accounts a day from the one IP bonk.io limits.
- *Keep the session copy for speed*: saves one indexed query per wear, at the
  cost of a second copy of every token to protect and to keep in step.
- *Ask for the password and keep it*: never.
- *Default the box to unticked*: safer per player, but most players would keep
  typing the password, which is the problem this solves; Disconnect and the
  settings card make the choice visible and reversible.

**Consequences.**
- A copy of the database plus a key now exposes tokens that work until
  revoked, not for a day. The runbook's leak steps revoke them on bonk.io.
- Existing site sessions still hold an old encrypted session token; nothing
  reads it, and it goes when the session ends. Players whose wear popup login
  never created a link see the popup once more.
- bonk.io can change `login_auto.php`'s limits without notice. The broker's
  `Paused` path, the shared cooldowns and the login-rate-limit audit lines
  are where that would show.
