from django.conf import settings
from django.db import models
from django.utils import timezone


class ApiKey(models.Model):
    """One key for one consumer of the public API (a partner site, a bot).

    Only a SHA-256 hash of the secret is stored. The full key is shown once,
    when it's created (`manage.py create_api_key`), and can't be recovered;
    a lost key is revoked and replaced. `prefix` is the public part of the
    key ("bvk_<prefix>_<secret>"), used to find the row and safe to show in
    logs, the admin and support conversations.
    """

    TIER_STANDARD = "standard"
    TIER_PARTNER = "partner"
    TIERS = [
        (TIER_STANDARD, "Standard"),
        (TIER_PARTNER, "Partner"),
    ]

    name = models.CharField(
        max_length=100, help_text="What it's for, e.g. 'Luna comp leaderboard'."
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="api_keys",
        help_text="The Bonkverse account responsible for this key, if any.",
    )
    contact = models.CharField(
        max_length=200, blank=True, help_text="How to reach them, e.g. a Discord username."
    )
    prefix = models.CharField(max_length=16, unique=True)
    key_hash = models.CharField(max_length=64, unique=True)
    tier = models.CharField(max_length=20, choices=TIERS, default=TIER_STANDARD)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "API key"
        ordering = ["-created_at"]

    def __str__(self):
        state = "" if self.is_active else " (revoked)"
        return f"{self.name} [bvk_{self.prefix}]{state}"

    def revoke(self):
        self.is_active = False
        self.revoked_at = timezone.now()
        self.save(update_fields=["is_active", "revoked_at"])
