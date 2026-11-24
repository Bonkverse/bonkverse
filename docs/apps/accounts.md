# accounts

Signing in to Bonkverse with a bonk.io account. Bonkverse has no passwords of its own: `/login/` sends the bonk.io username and password to bonk.io once, and a successful reply signs the visitor in to their site account (created on first login). RFC-0001 step 5.5 moved this out of `skins/`.

**Owns:** the login and logout pages, the one way any page tries a bonk.io login (`attempt_login`), Bonkverse's limit on wrong passwords, the sentences a player sees when a login is turned down, what a successful login does on our side, `/api/me/`, and `grant_admin`. **Does not own:** the bonk.io calls (`integrations/bonk_api.py`) or bonk.io's own pause after `ratelimited` (the cooldown there), the bonk.io session stored in the Django session (`core/bonk/session.py`), the JSON auth guards every app uses (`core/auth_guards.py`), friend storage and syncing (`players`), or wearing a skin (`skins/views/wear.py`, which uses this app's services for its in-page login).

## Routes

Names are in the `accounts` namespace (`app_name` in `accounts/urls.py`): `{% url 'accounts:<name>' %}`, `reverse("accounts:<name>")`.

| Path | Name | What |
|---|---|---|
| `/login/` | `login` | Login page (GET) and bonk.io login (POST, `login` rate tier) |
| `/logout/` | `logout` | POST only, so another site can't sign people out with a link |
| `/api/me/` | `api_me` | Who is signed in (the skin editor uses it); 401 when nobody is |

## Public entry points for other apps

`accounts/services.py`:
- `attempt_login(request, username, password, via=...)`: tries the bonk.io login unless a guard on the shared login budget turns it away first (holds, the site-wide wrong-password budget, per-minute caps, one at a time). Every attempt is logged with pseudonyms, never names or IPs.
- `login_failure_message(error, retry_after)`: the sentence for a turned-down login.
- `log_event(user, event_type, skin=None, **metadata)`: the event log (logins, wears, votes, uploads, friend syncs…); never raises. `manage.py analyze_events` reports on it.
- `sign_in(request, result)`: stores the bonk.io session, logs in the site account, links it to the BonkPlayer (token, its expiry and the active slot; recording the skin the player wears, `players.services.record_worn_skin`), stores Flash friends and queues the friend sync on the worker (`players.services`): from the login answer's own friend list when it has one, else from `friends.php`. Each login logs which (`login answer carried friends` / `carried no friend list`).
- `refresh_link(user, result)`: after the wear popup's login, stores the new token, its expiry and the active slot on the player's existing link. Never creates one.

The wear popup (`/api/bonk/login/`, in `skins`) uses `attempt_login`, `login_failure_message` and `refresh_link` to refresh the bonk.io token of a player who is already signed in.

## How long sign-ins last

Two lifetimes, kept apart (RFC-0003 phase 2):

- **The Bonkverse sign-in** (the Django session): 90 days from the last visit (`SESSION_COOKIE_AGE`). `sessions.SessionRenewalMiddleware` re-saves a signed-in player's session at most once a day, and a login counts as that day's renewal. Browsing, favorites, votes, settings and API keys need nothing more.
- **The bonk.io connection**: the token bonk.io issued at the latest login, about a day. Its own `exp` (`core/bonk/tokens.py`) sets when it stops being used, in the session (`core/bonk/session.py`) and on `BonkAccountLink.token_expires_at`; an expired one is never sent to bonk.io. Settings show it ("bonk.io connection", `players/views.py`).

## How a login works

1. `login_attempts.attempt_login`: checks the per-account and per-visitor holds, calls bonk.io once (`integrations/bonk_api.py`), counts wrong passwords. Why the limit exists: bonk.io limits logins per IP, and Bonkverse's IP is everyone's ([docs/bonk/login-rate-limit.md](../bonk/login-rate-limit.md)).
2. `sign_in.sign_in`: only the session and the site login are required; a failure in a later step is logged and the player stays signed in.
3. `views.login_view`: shows the message, or redirects to `next` (same host only) or My Profile.

Log lines from step 1 still use the logger name **`skins.login`** (its name before the move), so Railway searches like `@logger:skins.login` find old and new lines.

## Files

```
accounts/
  views.py              # /login/, /logout/, /api/me/
  services.py           # what other apps call
  login_attempts.py     # attempt_login + the wrong-password limit
  login_messages.py     # what a turned-down login says
  sign_in.py            # what a successful login does; refresh_link for the wear popup
  sessions.py           # 90-day sign-ins, renewed at most once a day
  forms.py              # LoginForm (username and password never stripped)
  models.py             # BonkUser (AUTH_USER_MODEL), BonkAccountLink, UserEvent
  admin.py              # site accounts in /admin/
  templates/accounts/login.html
  static/accounts/js/login.js   # keeps Login off until a wait ends; one submit per click
  events.py             # log_event: the event log (UserEvent)
  management/commands/grant_admin.py, reencrypt_bonk_tokens.py, analyze_events.py
```

## Models

| Model | Table | What |
|---|---|---|
| `BonkUser` | `skins_bonkuser` (+ `skins_bonkuser_groups`, `skins_bonkuser_user_permissions`) | The site account: `AUTH_USER_MODEL`, a bonk.io username, no usable password (sign-in is through bonk.io). Admin: `/admin/accounts/bonkuser/` |
| `UserEvent` | `skins_userevent` | The event log: one row per thing a person (or the site for them) did. Written only by `log_event`. Moved from `skins` in 5.6c, no data moved (`accounts.0003`, `skins.0035`) |
| `BonkAccountLink` | `skins_bonkaccountlink` | A site account ↔ a `players.BonkPlayer`, with the bonk.io session token from the latest login, encrypted (`encrypt_token()` / `bonk_token()`, [ADR 0016](../adr/0016-bonk-tokens-encrypted-at-rest.md)), when it stops being usable (`token_expires_at`, from the token's `exp`; `bonk_token()` returns None after it) and the account's active slot (`active_slot`) |

It moved here from `skins/` in step 5.5 without moving data (migrations `accounts.0001` and `skins.0033`, both state-only). It keeps its table, and its constraint and index names (they come from the table name). Since 5.5b the token is encrypted with `BONK_TOKEN_KEYS` (`core/token_crypto.py`); `manage.py reencrypt_bonk_tokens` re-encrypts every stored copy after a key change.

`BonkUser` moved here in step 5.5c, also without moving data, and `AUTH_USER_MODEL` is now `accounts.BonkUser`. Django doesn't support switching that setting, so the move pins the old migrations to `skins.bonkuser` and creates the model in `accounts.0001`'s state; [ADR 0017](../adr/0017-user-model-moved-by-pinning-history.md) explains how, and the runbook has the rollback.
