"""What other apps may call in accounts.

- `attempt_login(request, username, password, via=...)`: the one way to try a
  bonk.io login, with Bonkverse's limit on wrong passwords (login_attempts.py).
- `login_failure_message(error, retry_after)`: the sentence a player sees
  when that login is turned down (login_messages.py).
- `sign_in(request, result)`: everything a successful login does on our side
  (sign_in.py).
- `log_event(user, event_type, skin=None, **metadata)`: write to the event log
  (events.py); every app records what people do through it.

The in-page login on wear (skins/views/wear.py) uses the first two; it only
refreshes the bonk.io token for a player who is already signed in.
"""

from .events import log_event
from .login_attempts import attempt_login
from .login_messages import login_failure_message
from .sign_in import sign_in

__all__ = ["attempt_login", "log_event", "login_failure_message", "sign_in"]
