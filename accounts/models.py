"""Accounts' models.

BonkAccountLink moved here from skins/ in RFC-0001 Phase 5.5 without moving
any data: it keeps its table (`skins_bonkaccountlink`), and its constraint and
index names come from that table, so they're unchanged too. BonkUser, the
site account (`AUTH_USER_MODEL`), followed in 5.5c the same way, keeping
`skins_bonkuser` (ADR 0017).
"""

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models

from core import token_crypto


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


class BonkUser(AbstractBaseUser, PermissionsMixin):
    """A Bonkverse site account, identified by its bonk.io username.

    PermissionsMixin adds is_superuser, groups and user_permissions, which the
    Django admin needs (has_perm / has_module_perms).
    """

    username = models.CharField(max_length=100, unique=True)
    date_joined = models.DateTimeField(auto_now_add=True)
    is_staff = models.BooleanField(default=False)

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
    # Assumed 14 days from login; bonk.io tokens really last about a day
    # (RFC-0003 reads the token's own expiry instead).
    token_expires_at = models.DateTimeField(blank=True, null=True)
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
        """The stored bonk.io token, or None if there is none or no key opens it."""
        return token_crypto.decrypt(self.token_encrypted)
