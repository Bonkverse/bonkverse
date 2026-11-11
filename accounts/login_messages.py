"""What a player reads when a bonk.io login is turned down.

Used by the /login/ page (views.py) and the in-page login on wear
(skins/wear_skin.py, through accounts.services).
"""

from core.ratelimits import describe_wait
from integrations.bonk_api import BonkError

from .login_attempts import COUNTED_FAILURES, TOO_MANY_ATTEMPTS

# What a player sees when bonk.io turns a login down, by BonkError code.
# Also used by the in-page bonk.io login on wear (wear_skin.py).
LOGIN_FAILURE_MESSAGES = {
    BonkError.WRONG_PASSWORD: "Wrong password.",
    BonkError.UNKNOWN_USERNAME: "No bonk.io account has that username.",
    BonkError.RATE_LIMITED: (
        "bonk.io is limiting logins from Bonkverse right now. Try again in {wait}."
    ),
    # Held by Bonkverse (login_attempts.py) before bonk.io saw it. Says why, so
    # it doesn't read as the site being broken.
    TOO_MANY_ATTEMPTS: (
        "Too many wrong passwords. Wait {wait} before trying again, so bonk.io "
        "doesn't block logins for everyone on Bonkverse."
    ),
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
