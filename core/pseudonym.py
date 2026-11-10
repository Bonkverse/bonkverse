"""Stable, non-reversible stand-ins for names and IPs in logs and cache keys.

Owns: turning a username or IP into a short tag that is the same every time
for the same value, so log lines can be grouped by account or visitor
("these three wrong passwords and that rate limit were one person") without
writing the name or address itself into Railway's logs.
Does not own: which IP a request is from (core/client_ip.py).

The tag is an HMAC keyed with SECRET_KEY, so it can't be reversed by hashing
a list of known bonk.io names. Rotating SECRET_KEY changes every tag.
"""

import hashlib
import hmac

from django.conf import settings

TAG_LENGTH = 12  # hex characters: 48 bits, plenty to tell visitors apart in logs


def pseudonym(kind: str, value: str) -> str:
    """A short tag for `value`, e.g. pseudonym("account", "the saucy tulip").

    Args:
        kind: What `value` is ("account", "client"). Part of the key, so the
            same string as a name and as an IP gets different tags.
        value: The name or address. Callers normalize it first (bonk.io names
            are compared case-insensitively).

    Returns:
        TAG_LENGTH lowercase hex characters.
    """
    key = settings.SECRET_KEY.encode()
    message = f"{kind}:{value}".encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()[:TAG_LENGTH]
