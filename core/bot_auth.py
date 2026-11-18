"""BonxBot's shared secret: the `Authorization: Bearer <BONXBOT_API_TOKEN>`
header every /api/bot/ endpoint checks.

Owns: comparing the header with settings.BONXBOT_API_TOKEN in constant time.
An empty setting turns the bot API off (nothing matches).
Does not own: what any endpoint does once the bot is let in.
"""

import hmac

from django.conf import settings


def bot_authorized(request) -> bool:
    expected = settings.BONXBOT_API_TOKEN
    given = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    return bool(expected) and hmac.compare_digest(given.encode(), expected.encode())
