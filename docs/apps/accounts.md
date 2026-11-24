# accounts

Signing in to Bonkverse with a bonk.io account. Bonkverse has no passwords of its own: `/login/` sends the bonk.io username and password to bonk.io once, and a successful reply signs the visitor in to their site account (created on first login). RFC-0001 step 5.5 moved this out of `skins/`.

**Owns:** the login and logout pages, the one way any page tries a bonk.io login (`attempt_login`), Bonkverse's limit on wrong passwords, the sentences a player sees when a login is turned down, what a successful login does on our side, `/api/me/`, and `grant_admin`. **Does not own:** the bonk.io calls (`integrations/bonk_api.py`) or bonk.io's own pause after `ratelimited` (the cooldown there), which bonk.io account a browser acts as (`core/bonk/session.py`), the JSON auth guards every app uses (`core/auth_guards.py`), friend storage and syncing (`players`), or wearing a skin (`skins/views/wear.py`, which uses this app's services for its in-page login).

## Routes

Names are in the `accounts` namespace (`app_name` in `accounts/urls.py`): `{% url 'accounts:<name>' %}`, `reverse("accounts:<name>")`.

| Path | Name | What |
|---|---|---|
| `/login/` | `login` | Login page (GET) and bonk.io login (POST, `login` rate tier). `?add=1` while signed in: "Add account" (`?username=` fills the name) |
| `/logout/` | `logout` | POST only, so another site can't sign people out with a link. `scope=this`: only the account in use, switching to another signed in here |
| `/api/me/` | `api_me` | Who is signed in (the skin editor and the other sites' headers use it), with `accounts`: the person's bonk.io accounts for the switcher, each with its worn-skin `avatar`; 401 when nobody is |
| `/api/me/switch/` | `api_switch_account` | The other sites' switcher: POST JSON `{"account": id}` with the `X-Bonkverse-Switch` header, from an origin in `CORS_ALLOWED_ORIGINS`. Answers like `/api/me/` |
| `/accounts/switch/` | `switch_account` | POST `account`: use another account signed in on this browser |
| `/accounts/remove/` | `remove_account` | POST `account`: take it out of the group (it keeps its own history) |
| `/accounts/main/` | `make_main_account` | POST `account`: make it the group's main |

## A person's bonk.io accounts (groups)

RFC-0003 phase 5, [ADR 0023](../adr/0023-account-groups-of-site-accounts.md), `accounts/groups.py`. Each bonk.io account is its own site account (`BonkUser`), with its own profile, favorites, votes, uploads and privacy. An `AccountGroup` ties a person's accounts together:

- **The account in use** is `request.user`. It decides Wear (its link's tokens), upload credit, votes, favorites, and the header on every Bonkverse site (they share the session cookie).
- **Switching** needs no password, but only between accounts signed in on this browser (`groups.SIGNED_IN_KEY` in the session). The group's other accounts show "Sign in". Trusted devices (a later PR) will let any account unlock the group on a device the group used before.
- **Adding:** "Add account" (`/login/?add=1`) or a Wear popup login with another account joins the group and keeps both signed in. A plain login while signed in replaces the session, so logging in to a friend's account never groups it. An account in another group moves (the password proves who controls it now).
- **Removing:** the account itself, or the main when it's signed in here. Its history goes with it. Two becoming one deletes the group; the main leaving hands main to the next account.
- **Shared:** appearance (`appearance.from_cookies` writes it to every account in the group; a new account takes the group's).
- `manage.py group_linked_accounts` (dry run; `--run`) converts site accounts that hold links to several bonk.io accounts, from before groups: each link moves to its own account's site account, all in one group, main = the most recently connected.

## Public entry points for other apps

`accounts/services.py`:
- `attempt_login(request, username, password, via=...)`: tries the bonk.io login unless a guard on the shared login budget turns it away first (holds, the site-wide wrong-password budget, per-minute caps, one at a time). Every attempt is logged with pseudonyms, never names or IPs.
- `login_failure_message(error, retry_after)`: the sentence for a turned-down login.
- `log_event(user, event_type, skin=None, **metadata)`: the event log (logins, wears, votes, uploads, friend syncs…); never raises. `manage.py analyze_events` reports on it.
- `sign_in(request, result, remember=...)`: logs in the site account, notes in the session which bonk.io account this browser acts as (id, username, active slot; never a token), links it to the BonkPlayer and hands the tokens to the token broker (`bonk_tokens.store_login`; recording the skin the player wears, `players.services.record_worn_skin`), stores Flash friends and queues the friend sync on the worker (`players.services`): from the login answer's own friend list when it has one, else from `friends.php`. Each login logs which (`login answer carried friends` / `carried no friend list`).
- `connect_from_wear(user, result, remember=...)`: after the wear popup's login, links the bonk.io account the player just proved they own (or updates their link) and stores its tokens.
- The token broker (`accounts/bonk_tokens.py`, exported as `usable_bonk_token`, `active_link`, `bonk_connection`, `disconnect_bonk` and the exceptions `ReconnectNeeded`, `TokensPaused`, `TokensUnavailable`): see below.

The wear popup (`/api/bonk/login/`, in `skins`) uses `attempt_login`, `login_failure_message` and `connect_from_wear`.

## How long sign-ins last

Two lifetimes, kept apart (RFC-0003 phase 2):

- **The Bonkverse sign-in** (the Django session): 90 days from the last visit (`SESSION_COOKIE_AGE`). `sessions.SessionRenewalMiddleware` re-saves a signed-in player's session at most once a day, and a login counts as that day's renewal. Browsing, favorites, votes, settings and API keys need nothing more.
- **The bonk.io connection**: the session token bonk.io issued at the latest login, about a day, stored only on the account link. Its own `exp` (`core/bonk/tokens.py`) sets `BonkAccountLink.token_expires_at`; an expired one is never sent to bonk.io. With "Keep me connected for Wear" (ticked by default, on `/login/` and the wear popup) the link also keeps bonk.io's remember-me token, and the token broker swaps it for a fresh session token when an action needs one, so the player isn't asked for the password again. Settings show the state ("bonk.io connection": stays connected, connected until a time, or not connected) with Reconnect and Disconnect (`players/views.py`).

## The token broker

`accounts/bonk_tokens.py` is the one place that reads or writes stored bonk.io tokens (RFC-0003 Part 2, [ADR 0022](../adr/0022-remember-me-tokens-and-the-token-broker.md)). `usable_token(link)`:

1. The stored session token while it's good for more than 5 minutes. No bonk.io call.
2. Else, with a remember-me token: `login_auto.php`, one refresh per link at a time (a Redis lock; others wait and use what it stored). Stores the new token, its expiry, the active slot and XP, and queues the friend list from the answer.
3. bonk.io answers `not_found`: the remember-me token is marked revoked and deleted; `ReconnectNeeded` (the password login).
4. bonk.io's login pause is on, or it limits `login_auto.php`: `Paused(seconds)`. During the login pause nothing is sent at all.
5. bonk.io can't be reached: `Unavailable`.

Wear asks again with `force_refresh=True` once if bonk.io refuses a token before its expiry. Nothing refreshes on a schedule. `disconnect(link)` revokes the remember-me token on bonk.io (`login_clearauto.php`, which revokes only that token) and deletes both tokens; the link stays. `manage.py revoke_bonk_remember_tokens --run` does that for every link's remember-me token (the runbook says when).

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
  bot_check.py          # when a login needs the Turnstile "not a bot" check, and checking it
  sign_in.py            # what a successful login does; connect_from_wear for the wear popup
  bonk_tokens.py        # the token broker: stored bonk.io tokens, refreshed with remember-me
  groups.py             # a person's bonk.io accounts: add, switch, sign out, remove, main
  context_processors.py # viewer_accounts: the header's account switcher
  sessions.py           # 90-day sign-ins, renewed at most once a day
  forms.py              # LoginForm (username and password never stripped)
  models.py             # BonkUser (AUTH_USER_MODEL), BonkAccountLink, UserEvent
  admin.py              # site accounts in /admin/
  templates/accounts/login.html
  static/accounts/js/login.js   # keeps Login off until a wait ends; one submit per click
  events.py             # log_event: the event log (UserEvent)
  management/commands/grant_admin.py, reencrypt_bonk_tokens.py,
                        # revoke_bonk_remember_tokens.py, group_linked_accounts.py,
                        # analyze_events.py
```

## Models

| Model | Table | What |
|---|---|---|
| `BonkUser` | `skins_bonkuser` (+ `skins_bonkuser_groups`, `skins_bonkuser_user_permissions`) | The site account: `AUTH_USER_MODEL`, a bonk.io username, no usable password (sign-in is through bonk.io). Admin: `/admin/accounts/bonkuser/` |
| `AccountGroup` | `accounts_accountgroup` | A person's bonk.io accounts: `main`, and `BonkUser.account_group` / `joined_group_at` on each member. Never one member (groups.py deletes it) |
| `UserEvent` | `skins_userevent` | The event log: one row per thing a person (or the site for them) did. Written only by `log_event`. Moved from `skins` in 5.6c, no data moved (`accounts.0003`, `skins.0035`) |
| `BonkAccountLink` | `skins_bonkaccountlink` | A site account ↔ a `players.BonkPlayer`, with the bonk.io session token from the latest login, encrypted (`encrypt_token()` / `bonk_token()`, [ADR 0016](../adr/0016-bonk-tokens-encrypted-at-rest.md)), when it stops being usable (`token_expires_at`, from the token's `exp`; `bonk_token()` returns None after it) the account's active slot (`active_slot`), and with "Keep me connected" bonk.io's remember-me token, encrypted the same way (`remember_token_encrypted`, `remember_token()`; `remember_status`: none, active or revoked; `last_refreshed_at`) |

It moved here from `skins/` in step 5.5 without moving data (migrations `accounts.0001` and `skins.0033`, both state-only). It keeps its table, and its constraint and index names (they come from the table name). Since 5.5b the token is encrypted with `BONK_TOKEN_KEYS` (`core/token_crypto.py`); `manage.py reencrypt_bonk_tokens` re-encrypts every stored copy after a key change.

`BonkUser` moved here in step 5.5c, also without moving data, and `AUTH_USER_MODEL` is now `accounts.BonkUser`. Django doesn't support switching that setting, so the move pins the old migrations to `skins.bonkuser` and creates the model in `accounts.0001`'s state; [ADR 0017](../adr/0017-user-model-moved-by-pinning-history.md) explains how, and the runbook has the rollback.
