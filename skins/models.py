from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector, SearchVectorField
from django.utils import timezone
import uuid
from django.urls import reverse

from core.bonk import BonkUsername, InvalidUsername

from django.core import signing
from django.core.exceptions import ValidationError

# SKIN_SEARCH_CONFIG: the text-search language Skin.search_vector is built
# with; every SearchQuery against it must use the same one.
from .querysets import SKIN_SEARCH_CONFIG, SkinQuerySet


class Skin(models.Model):
    name = models.CharField(max_length=1000, default="UnnamedSkin")
    link = models.URLField(
        blank=True,
        null=True,
        help_text="Legacy external source (e.g. Bonkleagues import)",
    )
    creator = models.CharField(max_length=1000, blank=True, null=True, default="UnknownSkinCreator")
    image_url = models.URLField(
        max_length=4000,
        blank=True,
        null=True,
        default="https://bonkleagues.io/api/avatar.svg?skinCode=CgcDYQACCQkBCgcFYWwAAQBNPlt5PUI19d8%2FGMUDPsJvGgAAAAAAAAoFAAEATT5beT1CNfXfvvn8kL80i70BAAAAAAAKBQABAEs%2BgkonQjVq%2FL2vivk9L4r5AAAAzxsPCgUAAQANP1yl2D9VbKUAAAAAAAAAAAAAAM8bDwAAAAA%3D",
    )  # Store the extracted image URL
    skin_code = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    description = models.TextField(blank=True, null=True)
    labels = models.JSONField(
        blank=True, null=True
    )  # Django 3.1+ uses this instead of `from contrib.postgres`
    labeled_at = models.DateTimeField(blank=True, null=True)
    upvotes = models.PositiveIntegerField(default=0)
    downvotes = models.PositiveIntegerField(default=0)
    favorited_by = models.ManyToManyField("BonkUser", related_name="favorite_skins", blank=True)
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    # Full-text search data, kept up to date by Postgres on every insert/update.
    # Same fields and weights the search page always used; storing it lets a GIN
    # index find matches instead of rebuilding this for every row on every search.
    search_vector = models.GeneratedField(
        expression=(
            SearchVector("labels", weight="A", config=SKIN_SEARCH_CONFIG)
            + SearchVector("description", weight="A", config=SKIN_SEARCH_CONFIG)
            + SearchVector("name", weight="B", config=SKIN_SEARCH_CONFIG)
            + SearchVector("creator", weight="C", config=SKIN_SEARCH_CONFIG)
        ),
        output_field=SearchVectorField(),
        db_persist=True,
    )

    objects = SkinQuerySet.as_manager()

    class Meta:
        indexes = [
            # Relevance search: full-text match.
            GinIndex(fields=["search_vector"], name="skin_search_vector_gin"),
            # Fuzzy name match (pg_trgm `%`) and name mode (`ilike_contains`).
            GinIndex(fields=["name"], opclasses=["gin_trgm_ops"], name="skin_name_trgm"),
            # name / creator / description modes (`ilike_contains`, core/lookups.py).
            GinIndex(fields=["creator"], opclasses=["gin_trgm_ops"], name="skin_creator_trgm"),
            GinIndex(
                fields=["description"], opclasses=["gin_trgm_ops"], name="skin_description_trgm"
            ),
            # Newest sort, New Releases, and the "added today" header count.
            models.Index(fields=["-created_at"], name="skin_created_at_desc"),
        ]

    def __str__(self):
        return f"{self.name} ({self.link})"

    def get_absolute_url(self):
        return reverse("skin_detail", kwargs={"skin_id": self.id})


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

    def __str__(self):
        return self.username


class SkinVote(models.Model):
    VOTE_CHOICES = [
        ("up", "Upvote"),
        ("down", "Downvote"),
    ]
    user = models.ForeignKey("BonkUser", on_delete=models.CASCADE)
    skin = models.ForeignKey(Skin, on_delete=models.CASCADE)
    vote = models.CharField(max_length=4, choices=VOTE_CHOICES)

    class Meta:
        unique_together = ("user", "skin")

    def __str__(self):
        return f"{self.user.username} voted {self.vote} on {self.skin.name}"


class BonkPlayer(models.Model):
    """
    Any Bonk account we discover (friends, map authors, etc.).
    This is NOT your Bonkverse login user (BonkUser) — it’s the in-game identity.
    """

    # The bonk.io account ID (DBID). Empty for a name only seen in replays
    # (players.replay_sync copies those in); filled in when a friend list or
    # login shows the real ID (skins.friends_sync.adopt_replay_names).
    bonk_id = models.BigIntegerField(unique=True, db_index=True, null=True, blank=True)
    username = models.CharField(max_length=255, db_index=True)
    last_seen = models.DateTimeField(default=timezone.now)
    last_friend_count = models.IntegerField(default=0)  # snapshot at last sync
    # Total XP from the player's own bonk.io login (the only place XP is
    # shown); null until they sign in to Bonkverse. Level: core.bonk.levels.
    xp = models.BigIntegerField(null=True, blank=True)
    xp_seen_at = models.DateTimeField(null=True, blank=True)

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

    player_low = models.ForeignKey(BonkPlayer, on_delete=models.CASCADE, related_name="edges_low")
    player_high = models.ForeignKey(BonkPlayer, on_delete=models.CASCADE, related_name="edges_high")
    created_at = models.DateTimeField(auto_now_add=True)
    last_confirmed_at = models.DateTimeField(default=timezone.now)  # updated each sync we see it

    class Meta:
        constraints = [
            # Enforce undirected uniqueness and no self-edges
            models.UniqueConstraint(
                fields=["player_low", "player_high"], name="uniq_undirected_friendship"
            ),
            models.CheckConstraint(
                check=~models.Q(player_low=models.F("player_high")), name="no_self_friendship"
            ),
        ]
        indexes = [
            models.Index(fields=["player_low", "player_high"]),
            models.Index(fields=["player_high", "player_low"]),
        ]

    def __str__(self):
        return f"{self.player_low.bonk_id} ↔ {self.player_high.bonk_id}"


class FriendCountHistory(models.Model):
    player = models.ForeignKey(
        BonkPlayer, on_delete=models.CASCADE, related_name="friend_count_history"
    )
    count = models.IntegerField()
    captured_at = models.DateTimeField(auto_now_add=True)


class BonkAccountLink(models.Model):
    """
    Links a Bonkverse site user (BonkUser) to an in-game BonkPlayer.
    Optionally stores an encrypted token for server-side Bonk API calls.
    """

    user = models.ForeignKey("BonkUser", on_delete=models.CASCADE, related_name="bonk_accounts")
    bonk_player = models.ForeignKey(
        BonkPlayer, on_delete=models.CASCADE, related_name="linked_site_users"
    )
    token_encrypted = models.TextField(
        blank=True, null=True
    )  # store your encrypted session token, not password
    token_expires_at = models.DateTimeField(blank=True, null=True)
    scopes = models.JSONField(blank=True, null=True)  # e.g., {"friends": true}
    active = models.BooleanField(default=True)
    connected_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "bonk_player")

    # Signed with SECRET_KEY, not encrypted: anyone who has both the database
    # and the key can read the token (an open item in the RFC-0001 progress doc).
    TOKEN_SALT = "bonk_token"

    @classmethod
    def sign_token(cls, bonk_token: str) -> str:
        """The value stored in `token_encrypted` for a bonk.io token."""
        return signing.dumps({"t": bonk_token}, salt=cls.TOKEN_SALT)

    def bonk_token(self) -> str | None:
        """The stored bonk.io token, or None if there is none or it doesn't verify."""
        if not self.token_encrypted:
            return None
        try:
            return signing.loads(self.token_encrypted, salt=self.TOKEN_SALT)["t"]
        except (signing.BadSignature, KeyError, TypeError):
            return None


class FlashFriend(models.Model):
    """
    Represents a legacy Flash friend (Bonk1/TinyTanks import).
    Name-only unless we resolve to a BonkPlayer later.
    """

    name = models.TextField(db_index=True)
    bonk_player = models.ForeignKey(
        BonkPlayer, on_delete=models.SET_NULL, null=True, blank=True, related_name="as_flash_friend"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # Covers the resolved case (bonk_player set): two rows can't
            # share the same (name, bonk_player) pair.
            models.UniqueConstraint(
                fields=["name", "bonk_player"],
                condition=models.Q(bonk_player__isnull=False),
                name="uniq_flashfriend_name_player_resolved",
            ),
            # Covers the far more common unresolved case. Postgres treats
            # every NULL as distinct from every other NULL, so a plain
            # unique_together on (name, bonk_player) silently allows
            # unlimited duplicate names as long as bonk_player is NULL —
            # which is true for almost every FlashFriend row. This partial
            # index enforces one row per name specifically when
            # bonk_player is unresolved.
            models.UniqueConstraint(
                fields=["name"],
                condition=models.Q(bonk_player__isnull=True),
                name="uniq_flashfriend_name_unresolved",
            ),
        ]

    def __str__(self):
        return f"{self.name} (linked to {self.bonk_player_id or '—'})"


class FlashFriendship(models.Model):
    """
    Links a Bonkverse site user to their imported flash friends.
    """

    user = models.ForeignKey("BonkUser", on_delete=models.CASCADE, related_name="flash_friendships")
    flash_friend = models.ForeignKey(
        FlashFriend, on_delete=models.CASCADE, related_name="friend_of"
    )
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


def validate_username(value: str):
    """Model-field validator for bonk.io usernames (rules in core/bonk/usernames.py).

    Only used by the archived PlayerWin/PlayerLoss tables; kept because their
    migrations import it by this path.
    """
    try:
        BonkUsername.validate(value)
    except InvalidUsername as error:
        raise ValidationError(str(error)) from None


class PlayerWin(models.Model):
    username = models.CharField(max_length=35, db_index=True, validators=[validate_username])
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.username} win at {self.created_at}"


class PlayerLoss(models.Model):
    username = models.CharField(max_length=35, db_index=True, validators=[validate_username])
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


class SkinReport(models.Model):
    REASON_CHOICES = [
        ("inappropriate", "Inappropriate content"),
        ("stolen", "Stolen / reposted without credit"),
        ("spam", "Spam or low-effort"),
        ("broken", "Broken / not loading"),
        ("other", "Other"),
    ]

    skin = models.ForeignKey(Skin, on_delete=models.CASCADE, related_name="reports")
    reporter = models.ForeignKey(
        "BonkUser", on_delete=models.SET_NULL, null=True, blank=True, related_name="skin_reports"
    )  # null = anonymous report
    reason = models.CharField(max_length=32, choices=REASON_CHOICES)
    details = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)

    class Meta:
        # One report per user per skin (authenticated users only)
        constraints = [
            models.UniqueConstraint(
                fields=["skin", "reporter"],
                condition=models.Q(reporter__isnull=False),
                name="one_report_per_user_per_skin",
            )
        ]

    def __str__(self):
        return f"Report on {self.skin.name} ({self.reason})"


class UserEvent(models.Model):
    user = models.ForeignKey(
        "BonkUser", on_delete=models.SET_NULL, null=True, blank=True, related_name="events"
    )
    event_type = models.CharField(max_length=50, db_index=True)
    skin = models.ForeignKey("Skin", on_delete=models.SET_NULL, null=True, blank=True)
    metadata = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["event_type", "created_at"])]

    def __str__(self):
        return f"{self.event_type} by {self.user_id} at {self.created_at}"
