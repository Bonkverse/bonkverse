from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
import uuid
from django.urls import reverse

import re
from django.core.exceptions import ValidationError

# Create your models here.

class Skin(models.Model):
    name = models.CharField(max_length=1000, default="UnnamedSkin")
    link = models.URLField(unique=True)
    creator = models.CharField(max_length=1000, blank=True, null=True, default="UnknownSkinCreator")
    image_url = models.URLField(max_length=4000, blank=True, null=True, default="https://bonkleagues.io/api/avatar.svg?skinCode=CgcDYQACCQkBCgcFYWwAAQBNPlt5PUI19d8%2FGMUDPsJvGgAAAAAAAAoFAAEATT5beT1CNfXfvvn8kL80i70BAAAAAAAKBQABAEs%2BgkonQjVq%2FL2vivk9L4r5AAAAzxsPCgUAAQANP1yl2D9VbKUAAAAAAAAAAAAAAM8bDwAAAAA%3D")  # Store the extracted image URL
    skin_code = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    description = models.TextField(blank=True, null=True)
    labels = models.JSONField(blank=True, null=True)  # Django 3.1+ uses this instead of `from contrib.postgres`
    labeled_at = models.DateTimeField(blank=True, null=True)
    upvotes = models.PositiveIntegerField(default=0)
    downvotes = models.PositiveIntegerField(default=0)
    favorited_by = models.ManyToManyField("BonkUser", related_name="favorite_skins", blank=True)
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    def __str__(self):
        return f"{self.name} ({self.link})"
    
    def get_absolute_url(self):
        return reverse("skin_detail", kwargs={"skin_id": self.id, "uuid": self.uuid})


class BonkUserManager(BaseUserManager):
    def create_user(self, username):
        if not username:
            raise ValueError("Bonk.io username is required")
        user = self.model(username=username)
        user.set_unusable_password()  # don't store Bonk.io passwords
        user.save(using=self._db)
        return user

class BonkUser(AbstractBaseUser):
    username = models.CharField(max_length=100, unique=True)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = BonkUserManager()

    USERNAME_FIELD = 'username'

    def __str__(self):
        return self.username

class SkinVote(models.Model):
    VOTE_CHOICES = [
        ('up', 'Upvote'),
        ('down', 'Downvote'),
    ]
    user = models.ForeignKey("BonkUser", on_delete=models.CASCADE)
    skin = models.ForeignKey(Skin, on_delete=models.CASCADE)
    vote = models.CharField(max_length=4, choices=VOTE_CHOICES)

    class Meta:
        unique_together = ('user', 'skin')

    def __str__(self):
        return f"{self.user.username} voted {self.vote} on {self.skin.name}"

class BonkPlayer(models.Model):
    """
    Any Bonk account we discover (friends, map authors, etc.).
    This is NOT your Bonkverse login user (BonkUser) — it’s the in-game identity.
    """
    bonk_id = models.BigIntegerField(unique=True, db_index=True)
    username = models.CharField(max_length=255, db_index=True)
    last_seen = models.DateTimeField(default=timezone.now)
    last_friend_count = models.IntegerField(default=0)  # snapshot at last sync

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["bonk_id"]),
            models.Index(fields=["username"]),
        ]

    def __str__(self):
        return f"{self.username} ({self.bonk_id})"


class Friendship(models.Model):
    """
    Undirected friendship edge between two BonkPlayers.
    Store once using ordered endpoints (player_low < player_high) to avoid duplicates.
    """
    player_low  = models.ForeignKey(BonkPlayer, on_delete=models.CASCADE, related_name="edges_low")
    player_high = models.ForeignKey(BonkPlayer, on_delete=models.CASCADE, related_name="edges_high")
    created_at = models.DateTimeField(auto_now_add=True)
    last_confirmed_at = models.DateTimeField(default=timezone.now)  # updated each sync we see it

    class Meta:
        constraints = [
            # Enforce undirected uniqueness and no self-edges
            models.UniqueConstraint(fields=["player_low", "player_high"], name="uniq_undirected_friendship"),
            models.CheckConstraint(check=~models.Q(player_low=models.F("player_high")), name="no_self_friendship"),
        ]
        indexes = [
            models.Index(fields=["player_low", "player_high"]),
            models.Index(fields=["player_high", "player_low"]),
        ]

    def __str__(self):
        return f"{self.player_low.bonk_id} ↔ {self.player_high.bonk_id}"

class FriendCountHistory(models.Model):
    player = models.ForeignKey(BonkPlayer, on_delete=models.CASCADE, related_name="friend_count_history")
    count = models.IntegerField()
    captured_at = models.DateTimeField(auto_now_add=True)


class BonkAccountLink(models.Model):
    """
    Links a Bonkverse site user (BonkUser) to an in-game BonkPlayer.
    Optionally stores an encrypted token for server-side Bonk API calls.
    """
    user = models.ForeignKey("BonkUser", on_delete=models.CASCADE, related_name="bonk_accounts")
    bonk_player = models.ForeignKey(BonkPlayer, on_delete=models.CASCADE, related_name="linked_site_users")
    token_encrypted = models.TextField(blank=True, null=True)  # store your encrypted session token, not password
    token_expires_at = models.DateTimeField(blank=True, null=True)
    scopes = models.JSONField(blank=True, null=True)  # e.g., {"friends": true}
    active = models.BooleanField(default=True)
    connected_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "bonk_player")

class FlashFriend(models.Model):
    """
    Represents a legacy Flash friend (Bonk1/TinyTanks import).
    Name-only unless we resolve to a BonkPlayer later.
    """
    name = models.TextField(db_index=True)
    bonk_player = models.ForeignKey(
        BonkPlayer, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="as_flash_friend"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("name", "bonk_player")  # prevent dupes

    def __str__(self):
        return f"{self.name} (linked to {self.bonk_player_id or '—'})"


class FlashFriendship(models.Model):
    """
    Links a Bonkverse site user to their imported flash friends.
    """
    user = models.ForeignKey("BonkUser", on_delete=models.CASCADE, related_name="flash_friendships")
    flash_friend = models.ForeignKey(FlashFriend, on_delete=models.CASCADE, related_name="friend_of")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "flash_friend")

    def __str__(self):
        return f"{self.user.username} ↔ {self.flash_friend.name}"

class Changelog(models.Model):
    title = models.CharField(max_length=200)
    content = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)
    version = models.CharField(max_length=20, blank=True, null=True)  # optional

    def __str__(self):
        return f"{self.version or ''} - {self.title}"

class SkinImage(models.Model):
    skin = models.ForeignKey("skins.Skin", on_delete=models.CASCADE, related_name="images")
    kind = models.CharField(max_length=50, default="original")
    path = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.kind} image for {self.skin.name}"
    

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9 _]+$")

def validate_username(value: str):
    if not value:
        raise ValidationError("Username is required.")
    if len(value) < 3:
        raise ValidationError("Username must be at least 3 characters long.")
    if len(value) > 35:
        raise ValidationError("Username must be at most 35 characters long.")
    if not USERNAME_PATTERN.match(value):
        raise ValidationError("Username can only contain letters, numbers, spaces, and underscores.")
    if value.lower().startswith("guest") or value.lower().startswith("new player"):
        raise ValidationError("Guest accounts are not allowed.")

class PlayerWin(models.Model):
    username = models.CharField(
        max_length=35,
        db_index=True,
        validators=[validate_username]
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.username} win at {self.created_at}"

class PlayerSession(models.Model):
    username = models.CharField(
        max_length=35,
        unique=True,
        db_index=True,
        validators=[validate_username]
    )
    token = models.CharField(max_length=255, unique=True, db_index=True)
    client_id = models.UUIDField(default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()

    def is_active(self):
        now = timezone.now()
        return self.expires_at > now and (now - self.last_seen) < timedelta(seconds=60)

    def __str__(self):
        return f"Session for {self.username} (active={self.is_active()})"

class PlayerLoss(models.Model):
    username = models.CharField(
        max_length=35,
        db_index=True,
        validators=[validate_username]
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.username} loss at {self.created_at}"

class DiscordTag(models.Model):
    name = models.CharField(max_length=64, unique=True)
    category = models.CharField(max_length=64, blank=True, default="")

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

    # Permanent invite requirement
    expires_at = models.DateTimeField(null=True, blank=True)  # should stay null for “permanent”

    # Discovery
    tags = models.ManyToManyField(DiscordTag, blank=True)

    status = models.CharField(max_length=32, choices=Status.choices, default=Status.ACTIVE)
    last_fetched_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.guild_id})"


class DiscordServerSnapshot(models.Model):
    server = models.ForeignKey(DiscordServer, on_delete=models.CASCADE, related_name="snapshots")
    recorded_at = models.DateTimeField(default=timezone.now, db_index=True)

    member_count = models.IntegerField()
    online_count = models.IntegerField()

    class Meta:
        indexes = [
            models.Index(fields=["server", "recorded_at"]),
        ]