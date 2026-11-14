"""Encrypting bonk.io tokens at rest (ADR 0016).

A bonk.io session token lets whoever holds it act as that player on bonk.io
until it expires, so Bonkverse never stores one readable. Every stored copy
(BonkAccountLink.token_encrypted, and the site session through BonkSession)
is encrypted with Fernet under `BONK_TOKEN_KEYS`: keys kept outside the
database and separate from SECRET_KEY, so a copy of the database alone (or
of SECRET_KEY alone) reveals nothing.

`BONK_TOKEN_KEYS` is a comma-separated list, newest first. New values are
encrypted with the first key; any listed key can decrypt. To rotate: put a
new key first, deploy, run `manage.py reencrypt_bonk_tokens --run`, then
drop the old key (docs/operations/runbook.md).

Never log a token, a stored value or a key.
"""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from core.bonk import BonkSession

# Outside production, when no key is set: a fixed key derived from this
# label, so local runs and tests work without setup. It's public by design;
# production refuses to start without its own keys (settings.py).
_DEV_ONLY_LABEL = b"bonkverse local development only, never production"


class TokenKeyError(ValueError):
    """BONK_TOKEN_KEYS is missing or holds something that isn't a Fernet key."""


def dev_key() -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(_DEV_ONLY_LABEL).digest()).decode("ascii")


def parse_keys(raw: str | None, *, required: bool) -> list[str]:
    """The keys in a BONK_TOKEN_KEYS value, newest first.

    Raises TokenKeyError (naming the key's position, never its value) for a key
    Fernet can't use, or when `required` and none is set. Without keys and
    not required, returns the development key.
    """
    keys = [key.strip() for key in (raw or "").split(",") if key.strip()]
    if not keys:
        if required:
            raise TokenKeyError("BONK_TOKEN_KEYS is not set")
        return [dev_key()]
    for position, key in enumerate(keys, start=1):
        try:
            Fernet(key)
        except (ValueError, TypeError):
            raise TokenKeyError(f"BONK_TOKEN_KEYS: key {position} is not a Fernet key") from None
    return keys


def encrypt(token: str) -> str:
    """The stored form of `token`, encrypted with the newest key."""
    return _box(_keys()).encrypt(token.encode("utf-8")).decode("ascii")


def decrypt(value: str | None) -> str | None:
    """The token in a stored value, or None if no listed key opens it.

    None also covers values that were never encrypted (older signed or plain
    values); callers that still accept those check them separately.
    """
    if not value:
        return None
    try:
        return _box(_keys()).decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError, TypeError):
        return None


def is_current(value: str | None) -> bool:
    """Whether `value` is encrypted with the newest key (nothing to redo)."""
    if not value:
        return False
    try:
        Fernet(_keys()[0]).decrypt(value.encode("ascii"))
    except (InvalidToken, UnicodeError, ValueError, TypeError):
        return False
    return True


def bonk_session(request):
    """The request's BonkSession, storing its token encrypted.

    The one way views and guards open the bonk.io part of a site session.
    """
    return BonkSession(request.session, encrypt=encrypt, decrypt=decrypt)


def _keys() -> tuple[str, ...]:
    from django.conf import settings

    return tuple(settings.BONK_TOKEN_KEYS)


@lru_cache(maxsize=4)
def _box(keys: tuple[str, ...]) -> MultiFernet:
    return MultiFernet([Fernet(key) for key in keys])
