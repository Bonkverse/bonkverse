"""What other apps may call in accounts.

- `attempt_login(request, username, password, via=...)`: the one way to try a
  bonk.io login, with Bonkverse's limit on wrong passwords (login_attempts.py).
- `bot_check_site_key(request)`: the Turnstile site key when this visitor's
  next login must pass the "not a bot" check, else None (bot_check.py).
- `login_failure_message(error, retry_after)`: the sentence a player sees
  when that login is turned down (login_messages.py).
- `sign_in(request, result)`: everything a successful login does on our side
  (sign_in.py).
- `log_event(user, event_type, skin=None, **metadata)`: write to the event log
  (events.py); every app records what people do through it.
- `refresh_link(user, result)`: after the in-page login on wear, store the
  new token, its expiry and the active slot on the user's existing link
  (sign_in.py).
- `site_account_for(username)`: the site account for a bonk.io name, made if
  it doesn't exist yet, exactly as first sign-in makes it (sign_in.py). For
  BonxBot, which verifies players itself (public_api/views/bot.py).

The in-page login on wear (skins/views/wear.py) uses the first two; it only
refreshes the bonk.io token for a player who is already signed in.
"""

from .bot_check import site_key_if_wanted as bot_check_site_key
from .events import log_event
from .login_attempts import attempt_login
from .login_messages import login_failure_message
from .sign_in import refresh_link, sign_in, site_account_for

__all__ = [
    "attempt_login",
    "bot_check_site_key",
    "log_event",
    "login_failure_message",
    "refresh_link",
    "sign_in",
    "site_account_for",
]
