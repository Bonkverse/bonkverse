"""API key format, creation and lookup.

Owns: what a key looks like ("bvk_<prefix>_<secret>"), making one, hashing
it, and finding the active ApiKey for a presented key in constant time.
Does not own: reading the key from a request or rate limiting (auth.py).

The secret is 32 random bytes, so a plain SHA-256 is enough to store it:
slow password hashes exist for guessable inputs, and these aren't.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from .models import ApiKey

KEY_PREFIX = "bvk_"
_KEY_RE = re.compile(r"^bvk_([a-z0-9]{8})_([A-Za-z0-9_-]{43})$")


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _new_prefix() -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


def create_key(*, name: str, tier: str = ApiKey.TIER_STANDARD, owner=None, contact="", notes=""):
    """(ApiKey, raw key). The raw key exists only in this return value."""
    while True:
        prefix = _new_prefix()
        if not ApiKey.objects.filter(prefix=prefix).exists():
            break
    raw = f"{KEY_PREFIX}{prefix}_{secrets.token_urlsafe(32)}"
    api_key = ApiKey.objects.create(
        name=name,
        tier=tier,
        owner=owner,
        contact=contact,
        notes=notes,
        prefix=prefix,
        key_hash=hash_key(raw),
    )
    return api_key, raw


def find_active_key(raw_key: str) -> ApiKey | None:
    """The active ApiKey for this exact key, or None (malformed, unknown,
    revoked). Looks the row up by its public prefix, then compares hashes
    in constant time."""
    match = _KEY_RE.match(raw_key or "")
    if not match:
        return None
    api_key = ApiKey.objects.filter(prefix=match.group(1), is_active=True).first()
    if api_key is None:
        return None
    if not hmac.compare_digest(api_key.key_hash, hash_key(raw_key)):
        return None
    return api_key
