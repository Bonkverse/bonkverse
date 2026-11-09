"""Developer portal rules: who may create an API key, how many, and revoking.

Owns: the API terms version and recording that someone agreed to it, the
per-account limit on active keys, and creating or revoking a key for its own
owner.
Does not own: the key format and hashing (keys.py), checking keys on API
requests (auth.py), or the portal pages (views/portal.py).

Keys made here are always the standard tier. Partner keys (higher limits)
are issued by staff with `manage.py create_api_key --tier partner`.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .keys import create_key
from .models import ApiKey, ApiTermsAcceptance

logger = logging.getLogger(__name__)

# Bump when the terms on /developers/terms/ change in a way people must
# agree to again. Their existing keys keep working.
TERMS_VERSION = "2026-11-08"
MAX_KEY_NAME_LENGTH = 100


class PortalError(Exception):
    """A key request that breaks a rule. `code` is stable; the portal turns
    it into a message."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def has_accepted_terms(user) -> bool:
    """True if this account agreed to the current terms."""
    return ApiTermsAcceptance.objects.filter(user=user, version=TERMS_VERSION).exists()


def accept_terms(user) -> None:
    """Record that `user` agreed to the current terms (idempotent)."""
    ApiTermsAcceptance.objects.update_or_create(
        user=user, defaults={"version": TERMS_VERSION, "accepted_at": timezone.now()}
    )


def active_key_count(user) -> int:
    return ApiKey.objects.filter(owner=user, is_active=True).count()


@transaction.atomic
def create_own_key(user, *, name: str, agree_to_terms: bool = False) -> tuple[ApiKey, str]:
    """Create a standard-tier key owned by `user`.

    Args:
        user: The signed-in account; becomes the key's owner.
        name: What the key is for, shown in their key list (1-100 chars).
        agree_to_terms: The "I agree" box was ticked. Needed when they
            haven't agreed to the current terms yet.

    Returns:
        (ApiKey, raw key). The raw key is shown once and never stored.

    Raises:
        PortalError: "terms_not_accepted", "name_required", "name_too_long"
            or "too_many_keys".
    """
    if agree_to_terms:
        accept_terms(user)
    elif not has_accepted_terms(user):
        raise PortalError("terms_not_accepted")

    name = (name or "").strip()
    if not name:
        raise PortalError("name_required")
    if len(name) > MAX_KEY_NAME_LENGTH:
        raise PortalError("name_too_long")

    # Lock the owner's active keys so two quick submits can't both pass the
    # limit check.
    active = list(ApiKey.objects.select_for_update().filter(owner=user, is_active=True))
    if len(active) >= settings.PUBLIC_API_MAX_KEYS_PER_USER:
        raise PortalError("too_many_keys")

    api_key, raw = create_key(
        name=name, tier=ApiKey.TIER_STANDARD, owner=user, contact=user.username
    )
    logger.info("developer portal: key bvk_%s created by user=%s", api_key.prefix, user.pk)
    return api_key, raw


def revoke_own_key(user, prefix: str) -> ApiKey:
    """Revoke one of `user`'s active keys, found by its public prefix.

    Raises:
        PortalError: "key_not_found" if they have no active key with that
            prefix (someone else's key looks the same as a missing one).
    """
    api_key = ApiKey.objects.filter(owner=user, prefix=prefix, is_active=True).first()
    if api_key is None:
        raise PortalError("key_not_found")
    api_key.revoke()
    logger.info("developer portal: key bvk_%s revoked by user=%s", api_key.prefix, user.pk)
    return api_key
