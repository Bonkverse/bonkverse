"""Accounts' models.

BonkAccountLink moved here from skins/ in RFC-0001 Phase 5.5 without moving
any data: it keeps its table (`skins_bonkaccountlink`), and its constraint and
index names come from that table, so they're unchanged too. The site account
model (BonkUser, `AUTH_USER_MODEL`) still lives in skins/ until step 5.5c.
"""

from django.conf import settings
from django.db import models

from core import token_crypto


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
