"""What a player reads when a bonk.io login is turned down.

Used by the /login/ page (views.py) and the in-page login on wear
(skins/views/wear.py, through accounts.services).

When the wait is shared by everyone on the site, the sentence says so and
that it isn't the player's fault (RFC-0003 Part 1, item 8). The login page
adds the time the wait ends, in the player's own time zone
(accounts/js/login.js).
"""

from core.ratelimits import describe_wait
from integrations.bonk_api import BonkError

from .login_attempts import (
    BOT_CHECK,
    BUSY,
    COUNTED_FAILURES,
    IN_PROGRESS,
    SITE_WAIT,
    TOO_MANY_ATTEMPTS,
)

# What a player sees when a login is turned down, by error code: bonk.io's
# (BonkError) or Bonkverse's own (login_attempts.py).
LOGIN_FAILURE_MESSAGES = {
    BonkError.WRONG_PASSWORD: "Wrong password.",
    BonkError.UNKNOWN_USERNAME: "No bonk.io account has that username.",
    BonkError.RATE_LIMITED: (
        "bonk.io has paused logins from Bonkverse for everyone, so this isn't your "
        "fault. Try again in {wait}."
    ),
    # Held by Bonkverse (login_attempts.py) before bonk.io saw it. Says why, so
    # it doesn't read as the site being broken.
    TOO_MANY_ATTEMPTS: (
        "Too many wrong passwords. Wait {wait} before trying again, so bonk.io "
        "doesn't block logins for everyone on Bonkverse."
    ),
    SITE_WAIT: (
        "A few wrong passwords were typed on Bonkverse just now. One more would make "
        "bonk.io pause logins for everyone, so new logins wait {wait}. This isn't "
        "your fault."
    ),
    BUSY: "Lots of logins right now. Try again in {wait}.",
    IN_PROGRESS: "Your last login is still going. Give it a few seconds.",
    BOT_CHECK: "Confirm you're not a bot, then log in again.",
    BonkError.REJECTED: "bonk.io didn't accept that login.",
    BonkError.UNAVAILABLE: "Network error talking to bonk.io. Try again in a minute.",
}

# Added to "Wrong password." when it used up the player's tries for now.
LAST_TRY_MESSAGE = (
    "That was your last try for now: wait {wait} before trying again, so bonk.io "
    "doesn't block logins for everyone on Bonkverse."
)


def login_failure_message(error: str | None, retry_after: int | None = None) -> str:
    """The user-facing sentence for a failed bonk.io login.

    `retry_after` is the seconds to wait, for the sentences that say how long
    ("a few minutes" when unknown).
    """
    message = LOGIN_FAILURE_MESSAGES.get(error, LOGIN_FAILURE_MESSAGES[BonkError.REJECTED])
    if error in COUNTED_FAILURES and retry_after:
        # That wrong try was the last one for now (login_attempts.py).
        message = f"{message} {LAST_TRY_MESSAGE}"
    if "{wait}" in message:
        wait = describe_wait(retry_after) if retry_after else "a few minutes"
        message = message.format(wait=wait)
    return message
