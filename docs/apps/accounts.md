# accounts

Signing in to Bonkverse with a bonk.io account. Bonkverse has no passwords of its own: `/login/` sends the bonk.io username and password to bonk.io once, and a successful reply signs the visitor in to their site account (created on first login). RFC-0001 step 5.5 moved this out of `skins/`.

**Owns:** the login and logout pages, the one way any page tries a bonk.io login (`attempt_login`), Bonkverse's limit on wrong passwords, the sentences a player sees when a login is turned down, what a successful login does on our side, `/api/me/`, and `grant_admin`. **Does not own:** the bonk.io calls (`integrations/bonk_api.py`) or bonk.io's own pause after `ratelimited` (the cooldown there), the bonk.io session stored in the Django session (`core/bonk/session.py`), the JSON auth guards every app uses (`core/auth_guards.py`), friend storage and syncing (`players`), or wearing a skin (`skins/wear_skin.py`, which uses this app's services for its in-page login).

## Routes

| Path | Name | What |
|---|---|---|
| `/login/` | `login` | Login page (GET) and bonk.io login (POST, `login` rate tier) |
| `/logout/` | `logout` | POST only, so another site can't sign people out with a link |
| `/api/me/` | `api_me` | Who is signed in (the skin editor uses it); 401 when nobody is |

## Public entry points for other apps

`accounts/services.py`:
- `attempt_login(request, username, password, via=...)`: tries the bonk.io login, holding a try first when this account or visitor has used up its wrong passwords. Every attempt is logged with pseudonyms, never names or IPs.
- `login_failure_message(error, retry_after)`: the sentence for a turned-down login.
- `sign_in(request, result)`: stores the bonk.io session, logs in the site account, links it to the BonkPlayer, stores Flash friends and queues the friend sync on the worker (`players.services`).

The wear popup (`/api/bonk/login/`, in `skins`) uses the first two to refresh the bonk.io token of a player who is already signed in.

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
  sign_in.py            # what a successful login does
  forms.py              # LoginForm (username and password never stripped)
  templates/accounts/login.html
  static/accounts/js/login.js   # keeps Login off until a wait ends; one submit per click
  management/commands/grant_admin.py
```

## Models

None yet. `BonkUser` (the site account, `AUTH_USER_MODEL`) and `BonkAccountLink` (site account ↔ BonkPlayer, with the stored bonk.io token) still live in `skins/models.py`. `BonkAccountLink` moves here next, then its token storage is fixed (5.5b); `BonkUser` is the riskiest move (it is `AUTH_USER_MODEL`) and gets a spike first (5.5c).
