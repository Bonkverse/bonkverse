"""The Discord server directory's data: tags, servers and count snapshots.

Moved from skins/ in RFC-0001 Phase 5.2b without moving any data: each model
keeps its original table (`db_table`), the tags join table keeps its name,
and the snapshot index keeps its name. Renaming any of them would make
Django rename the real table or index.
"""

import uuid

from django.db import models
from django.utils import timezone


class DiscordTag(models.Model):
    name = models.CharField(max_length=64, unique=True)
    category = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        db_table = "skins_discordtag"

    def __str__(self):
        return self.name


class DiscordServer(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active"
        INVITE_EXPIRED = "invite_expired"
        DISABLED = "disabled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Identity (dedupe key)
    guild_id = models.CharField(max_length=32, unique=True, db_index=True)

    # Invite + basic info
    invite_code = models.CharField(max_length=32, db_index=True)
    invite_url = models.URLField(max_length=512)

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    icon_hash = models.CharField(max_length=128, blank=True, default="")
    splash_hash = models.CharField(max_length=128, blank=True, default="")

    # Stats (latest snapshot)
    member_count = models.IntegerField(default=0)
    online_count = models.IntegerField(default=0)

    # Permanent invites only, so this stays null.
    expires_at = models.DateTimeField(null=True, blank=True)

    # Discovery
    tags = models.ManyToManyField(DiscordTag, blank=True, db_table="skins_discordserver_tags")

    status = models.CharField(max_length=32, choices=Status.choices, default=Status.ACTIVE)
    last_fetched_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "skins_discordserver"

    def __str__(self):
        return f"{self.name} ({self.guild_id})"


class DiscordServerSnapshot(models.Model):
    server = models.ForeignKey(DiscordServer, on_delete=models.CASCADE, related_name="snapshots")
    recorded_at = models.DateTimeField(default=timezone.now, db_index=True)

    member_count = models.IntegerField()
    online_count = models.IntegerField()

    class Meta:
        db_table = "skins_discordserversnapshot"
        indexes = [
            models.Index(fields=["server", "recorded_at"], name="skins_disco_server__cb589f_idx"),
        ]
