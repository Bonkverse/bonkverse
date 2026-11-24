"""Accounts' models.

BonkAccountLink moved here from skins/ in RFC-0001 Phase 5.5 without moving
any data: it keeps its table (`skins_bonkaccountlink`), and its constraint and
index names come from that table, so they're unchanged too. BonkUser, the
site account (`AUTH_USER_MODEL`), followed in 5.5c the same way, keeping
`skins_bonkuser` (ADR 0017), and UserEvent (the event log) in 5.6c, keeping
`skins_userevent` and its index names.
"""

import time
from datetime import datetime
from datetime import timezone as dt_timezone

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone

from core import token_crypto
from core.bonk.session import EXPIRY_MARGIN_SECONDS
from core.bonk.tokens import token_expiry


class BonkUserManager(BaseUserManager):
    def create_user(self, username, **extra_fields):
        """Create a site account for a bonk.io username.

        Accounts never have a usable password: people sign in through bonk.io,
        and we never store bonk.io passwords.
        """
        if not username:
            raise ValueError("Bonk.io username is required")
        user = self.model(username=username, **extra_fields)
        user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra_fields):
        """Used by `manage.py createsuperuser --noinput --username X`.

        The password is ignored: admins sign in through bonk.io like everyone
        else. To promote an existing account, use `manage.py grant_admin`.
        """
        extra_fields.update(is_staff=True, is_superuser=True)
        return self.create_user(username, **extra_fields)


class AccountGroup(models.Model):
    """The bonk.io accounts one person plays as (RFC-0003 phase 5, ADR 0023).

    Each bonk.io account keeps its own site account (BonkUser) with its own
    profile, favorites, votes and uploads; the group only ties them together
    so the person can switch between them without a password and share one
    appearance. A site account belongs to at most one group. Groups are made
    by "Add account" (accounts/groups.py) and never hold a single member: the
    last two splitting up deletes the group.
    """

    # The account the group started from, or the one its owner picked.
    # Never null while the group has members (groups.py keeps it set).
    main = models.ForeignKey(
        "accounts.BonkUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # "Also plays as…": every account's public profile lists the group's
    # other accounts. Off by default (RFC-0003: grouping is private).
    show_on_profiles = models.BooleanField(default=False)

    def __str__(self):
        return f"group {self.pk} (main: {self.main_id})"


class BonkUser(AbstractBaseUser, PermissionsMixin):
    """A Bonkverse site account, identified by its bonk.io username.

    One per bonk.io account. A person with several bonk.io accounts has
    several site accounts in one AccountGroup.

    PermissionsMixin adds is_superuser, groups and user_permissions, which the
    Django admin needs (has_perm / has_module_perms). Those "groups" are
    Django's permission groups, unrelated to `account_group`.
    """

    username = models.CharField(max_length=100, unique=True)
    date_joined = models.DateTimeField(auto_now_add=True)
    is_staff = models.BooleanField(default=False)

    # The person's other bonk.io accounts (accounts/groups.py). Null for most
    # players: one account, no group.
    account_group = models.ForeignKey(
        AccountGroup,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="members",
    )
    joined_group_at = models.DateTimeField(null=True, blank=True)

    # Appearance, saved to the account so it follows them to other devices
    # (accounts/appearance.py). Blank until they first pick something.
    THEMES = ["bonkverse", "light", "dark"]
    theme = models.CharField(
        max_length=12,
        blank=True,
        choices=[(t, t) for t in THEMES],
        help_text="Bonkverse/ui theme; blank means the site default.",
    )
    seasonal = models.BooleanField(default=True, help_text="Show seasonal themes in season.")
    appearance_at = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="When they last chose (ms since 1970, the bv-appearance-at cookie).",
    )

    objects = BonkUserManager()

    USERNAME_FIELD = "username"

    class Meta:
        # Its table from when it lived in skins/ (RFC-0001 5.5c): keeping it
        # means no data moves. Its groups and permissions tables are named
        # from it (skins_bonkuser_groups, skins_bonkuser_user_permissions).
        db_table = "skins_bonkuser"

    def __str__(self):
        return self.username


class BonkAccountLink(models.Model):
    """Links a Bonkverse site account to a bonk.io player (BonkPlayer).

    Holds the bonk.io session token from the latest login, for calls the
    server makes on the player's behalf (the friend sync). Never the password.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bonk_accounts"
    )
    bonk_player = models.ForeignKey(
        "players.BonkPlayer", on_delete=models.CASCADE, related_name="linked_site_users"
    )
    # Encrypted with BONK_TOKEN_KEYS (core/token_crypto.py, ADR 0016). Read
    # and written only through encrypt_token() and bonk_token().
    token_encrypted = models.TextField(blank=True, null=True)
    # The token's own expiry (its `exp`, about a day after login), less a
    # minute's margin (core.bonk.session.EXPIRY_MARGIN_SECONDS). Null for
    # links saved before RFC-0003 phase 2; bonk_token() then reads `exp`.
    token_expires_at = models.DateTimeField(blank=True, null=True)
    # The account's active avatar slot (1-5) at its latest login: the slot
    # the player wears in game. Null before RFC-0003 phase 2.
    active_slot = models.PositiveSmallIntegerField(blank=True, null=True)

    # Remember-me (RFC-0003 Part 2): a bonk.io remember-me token, kept only
    # when the player ticks "Keep me connected for Wear". It works like the
    # password until bonk.io revokes it, so it's encrypted like the session
    # token and read only by accounts/bonk_tokens.py (the token broker).
    REMEMBER_NONE = "none"
    REMEMBER_ACTIVE = "active"
    REMEMBER_REVOKED = "revoked"  # bonk.io refused it (login_auto.php: not_found)
    REMEMBER_STATUSES = [
        (REMEMBER_NONE, "None"),
        (REMEMBER_ACTIVE, "Active"),
        (REMEMBER_REVOKED, "Revoked"),
    ]
    remember_token_encrypted = models.TextField(blank=True, null=True)
    remember_status = models.CharField(
        max_length=10, choices=REMEMBER_STATUSES, default=REMEMBER_NONE
    )
    # Last successful refresh through login_auto.php.
    last_refreshed_at = models.DateTimeField(blank=True, null=True)
    scopes = models.JSONField(blank=True, null=True)  # e.g. {"friends": true}
    active = models.BooleanField(default=True)
    connected_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "skins_bonkaccountlink"
        unique_together = ("user", "bonk_player")

    @classmethod
    def encrypt_token(cls, bonk_token: str) -> str:
        """The value stored in `token_encrypted` for a bonk.io token."""
        return token_crypto.encrypt(bonk_token)

    def bonk_token(self) -> str | None:
        """The stored bonk.io token, or None if there is none, no key opens
        it, or it has expired (so nothing spends a bonk.io call to find out)."""
        if self.token_expires_at is not None and self.token_expires_at <= timezone.now():
            return None
        token = token_crypto.decrypt(self.token_encrypted)
        if token is None:
            return None
        exp = token_expiry(token)
        if exp is not None and time.time() >= exp - EXPIRY_MARGIN_SECONDS:
            return None
        return token

    def remember_token(self) -> str | None:
        """The stored remember-me token, or None. Only accounts/bonk_tokens.py
        should call this."""
        if self.remember_status != self.REMEMBER_ACTIVE:
            return None
        return token_crypto.decrypt(self.remember_token_encrypted)

    @staticmethod
    def expiry_for(bonk_token: str):
        """When a stored `bonk_token` stops being usable, as a datetime, or
        None when its `exp` can't be read."""
        exp = token_expiry(bonk_token)
        if exp is None:
            return None
        return datetime.fromtimestamp(exp - EXPIRY_MARGIN_SECONDS, tz=dt_timezone.utc)


class UserEvent(models.Model):
    """One entry in the event log: something a person (or the site for them) did.

    Written only through accounts.services.log_event (events.py).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )
    event_type = models.CharField(max_length=50, db_index=True)
    skin = models.ForeignKey("skins.Skin", on_delete=models.SET_NULL, null=True, blank=True)
    metadata = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        # Its table and index from when it lived in skins/ (RFC-0001 5.6c).
        db_table = "skins_userevent"
        indexes = [
            models.Index(fields=["event_type", "created_at"], name="skins_usere_event_t_2396a8_idx")
        ]

    def __str__(self):
        return f"{self.event_type} by {self.user_id} at {self.created_at}"
