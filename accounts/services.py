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
- `connect_from_wear(user, result, remember=...)`: after the Wear popup's
  login, link that bonk.io account with its new tokens (sign_in.py).
- The token broker (bonk_tokens.py), the only way to get a stored bonk.io
  token: `active_link(request)`, `usable_bonk_token(link, force_refresh=...)`
  raising `ReconnectNeeded`, `TokensPaused` or `TokensUnavailable`;
  `disconnect_bonk(link)`; `bonk_connection(link)` for display.
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
from .bonk_tokens import Paused as TokensPaused
from .bonk_tokens import ReconnectNeeded
from .bonk_tokens import Unavailable as TokensUnavailable
from .bonk_tokens import active_link
from .bonk_tokens import connection as bonk_connection
from .bonk_tokens import disconnect as disconnect_bonk
from .bonk_tokens import usable_token as usable_bonk_token
from .sign_in import connect_from_wear, sign_in, site_account_for

__all__ = [
    "attempt_login",
    "bot_check_site_key",
    "log_event",
    "login_failure_message",
    "ReconnectNeeded",
    "TokensPaused",
    "TokensUnavailable",
    "active_link",
    "bonk_connection",
    "connect_from_wear",
    "disconnect_bonk",
    "usable_bonk_token",
    "sign_in",
    "site_account_for",
]
