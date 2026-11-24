"""Reading a bonk.io session token's own expiry.

A bonk.io session token is a JWT. Its payload is readable without any key
(docs/bonk/accounts.md, "Token format"): `uid`, `un`, `lv`, `ev`, `uip`,
`exp` and `g`. Bonkverse only reads `exp`, the Unix time bonk.io stops
accepting the token. Measured on 2026-11-10: about 24 hours after login.

Nothing here verifies the token: bonk.io does that. A token we can't read is
treated as having no known expiry, and bonk.io's own answer ("token") still
decides.

Free of Django, like the rest of core.bonk.
"""

from __future__ import annotations

import base64
import binascii
import json


def token_expiry(token: str | None) -> float | None:
    """The Unix time `token` expires (its `exp`), or None if it can't be read."""
    if not token or not isinstance(token, str):
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    payload = parts[1]
    try:
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        data = json.loads(raw)
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    exp = data.get("exp")
    if isinstance(exp, bool) or not isinstance(exp, (int, float)):
        return None
    return float(exp)
