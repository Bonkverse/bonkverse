# ADR 0016: bonk.io tokens are stored encrypted, under their own keys

**Status:** accepted, 2026-11-14 (RFC-0001 Phase 5, step 5.5b; RFC-0003 Part 2)

**Context.** After a bonk.io login Bonkverse keeps the player's bonk.io
session token: Wear and the friend sync use it to act on bonk.io as that
player until it expires (about a day). It was kept in two places, neither
encrypted:
- `BonkAccountLink.token_encrypted`, despite the name, held the token
  *signed* with `django.core.signing`: base64 that anyone with the database
  can decode;
- the site session (`BonkSession`, in the `django_session` table) held it as
  plain text, inside session data Django also only signs.

A copy of the database (a backup, a leaked dump, a read-only account) handed
over every recently signed-in player's bonk.io session. RFC-0003 plans to
store bonk.io's remember-me token too, which is as good as a password until
bonk.io revokes it, so storage had to be fixed first.

**Decision.**
- **Every stored copy of a bonk.io token is encrypted** with Fernet
  (`cryptography`; AES-128-CBC with an HMAC) by `core/token_crypto.py`. The
  account link stores `encrypt_token()`'s output and reads it with
  `bonk_token()`; the site session is opened only through
  `core.token_crypto.bonk_session(request)`, which gives `BonkSession` the
  encrypt and decrypt functions. `core/bonk/` stays free of Django and keys.
- **The keys are their own secret**, `BONK_TOKEN_KEYS`: Fernet keys kept in
  Railway variables, never in the database and never derived from
  `SECRET_KEY`. A database copy alone, or `SECRET_KEY` alone, reveals no
  token. Production refuses to start without valid keys (an invalid one is
  named by its position, never shown). Local runs and tests without the
  variable use a fixed development key, derived from a public label.
- **Rotation without logging anyone out:** the variable lists keys newest
  first; new values use the first, any listed key decrypts.
  `manage.py reencrypt_bonk_tokens --run` re-encrypts every link and live
  session with the newest key, after which the old key can go.
- **A token no key can open is no token.** The player is asked to log in again
  when they next need one, as with an expired token.
- **Moving over:** values stored before this change are still read (signed
  link values; plain JWTs in sessions, re-encrypted on first use), until
  `reencrypt_bonk_tokens --run` has replaced them. A follow-up PR removes
  that fallback.

**Alternatives considered.**
- *Derive the key from `SECRET_KEY`*: no new variable, but one leaked secret
  would again expose every token, and rotating `SECRET_KEY` (sessions,
  password-reset links) would mean rotating tokens too.
- *Encrypt in the database* (`pgcrypto`): the key would travel to the
  database with every query and sit in its logs.
- *Keep tokens out of the site session* (only on the link): fewer copies, but
  every Wear would need a link query, and the session copy is what Wear uses
  today. RFC-0003's token broker revisits where tokens live.
- *A field class that encrypts transparently*: hides the boundary; explicit
  `encrypt_token()` / `bonk_token()` keep every read and write findable.

**Consequences.**
- **Losing every key loses every stored token, nothing else.** Players log in
  again when they next wear a skin or sync friends.
- `BONK_TOKEN_KEYS` must be set on `bonkverse` **and** `worker` (the worker's as
  a reference to `bonkverse`'s). A deploy without it fails at startup.
- Runbook: [bonk.io token keys](../operations/runbook.md#bonkio-token-keys-set-rotate-or-recover).
- The field keeps its name `token_encrypted` (now accurate); RFC-0003 renames
  it when it adds the remember-me token.
