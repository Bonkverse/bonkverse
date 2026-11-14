"""The bonk.io session we keep for a signed-in player, inside the site session.

The token is stored encrypted when BonkSession is given `encrypt`/`decrypt`
(core.token_crypto.bonk_session does that for every request; ADR 0016). This
module stays free of Django and of the keys.
"""

from __future__ import annotations

import time
from collections.abc import MutableMapping

from core.bonk.slots import AvatarSlot

# bonk.io tokens are kept this long; every successful wear pushes expiry forward.
TOKEN_TTL_SECONDS = 14 * 24 * 60 * 60

# Session keys. Unchanged from before this module so existing sessions keep working.
TOKEN = "bonk_token"
TOKEN_EXPIRES = "bonk_token_expires"
ACTIVE_SLOT = "bonk_active_slot"
USERNAME = "bonk_username"
BONK_ID = "bonk_user_id"
ALL_KEYS = (TOKEN, TOKEN_EXPIRES, ACTIVE_SLOT, USERNAME, BONK_ID)


class BonkSession:
    """Read and write a player's bonk.io token, active slot and identity.

    Wraps any mutable mapping (Django's `request.session` in practice) so the
    session keys and the token lifetime are defined in exactly one place.

    Args:
        store: The mapping to keep values in. If it has a `modified`
            attribute (Django sessions), it is set on every write.
        clock: Returns the current Unix time; replace it in tests.
        encrypt, decrypt: Turn a token into its stored form and back
            (decrypt returns None for a value it can't open). Without them
            the token is stored as is.
    """

    def __init__(self, store: MutableMapping, *, clock=time.time, encrypt=None, decrypt=None):
        self._store = store
        self._clock = clock
        self._encrypt = encrypt
        self._decrypt = decrypt

    @property
    def token(self) -> str | None:
        """The bonk.io token, or None when missing, expired or unreadable."""
        stored = self._store.get(TOKEN)
        if not stored or self.is_expired:
            return None
        if self._decrypt is None:
            return stored
        token = self._decrypt(stored)
        if token is None and is_plain_token(stored):
            # Stored before tokens were encrypted (ADR 0016): still good, and
            # encrypted from now on. Remove once old sessions have expired.
            token = stored
            self._store[TOKEN] = self._encrypt(stored)
            self._touch()
        return token

    @property
    def is_expired(self) -> bool:
        return self._clock() >= self._store.get(TOKEN_EXPIRES, 0)

    @property
    def expires_in_seconds(self) -> int:
        """Seconds until the token expires (negative once it has)."""
        return round(self._store.get(TOKEN_EXPIRES, 0) - self._clock())

    def store_token(self, token: str) -> None:
        """Keep `token` for TOKEN_TTL_SECONDS from now. Also used to slide expiry."""
        self._store[TOKEN] = self._encrypt(token) if self._encrypt else token
        self._store[TOKEN_EXPIRES] = self._clock() + TOKEN_TTL_SECONDS
        self._touch()

    @property
    def active_slot(self) -> AvatarSlot | None:
        return AvatarSlot.parse(self._store.get(ACTIVE_SLOT))

    def store_active_slot(self, slot) -> None:
        """Remember the player's active slot. Invalid values are ignored."""
        parsed = AvatarSlot.parse(slot)
        if parsed:
            self._store[ACTIVE_SLOT] = parsed.number
            self._touch()

    @property
    def bonk_id(self) -> int | None:
        """The bonk_id of the account whose token this session holds, if known."""
        try:
            return int(self._store[BONK_ID])
        except (KeyError, TypeError, ValueError):
            return None

    def store_identity(self, bonk_username: str, bonk_id) -> None:
        self._store[USERNAME] = bonk_username
        self._store[BONK_ID] = bonk_id
        self._touch()

    def clear(self) -> None:
        """Forget everything bonk.io-related (logout)."""
        for key in ALL_KEYS:
            self._store.pop(key, None)
        self._touch()

    def _touch(self) -> None:
        if hasattr(self._store, "modified"):
            self._store.modified = True


def is_plain_token(value) -> bool:
    """A bonk.io token as bonk.io sends it: a JWT, three dot-separated parts
    starting with an encoded "{". Encrypted values never contain a dot."""
    return isinstance(value, str) and value.startswith("eyJ") and value.count(".") == 2
