"""Players as Bonkverse knows them: bonk.io accounts, the friend graph, Flash-era
friends, and each user's profile settings.

BonkPlayer, Friendship, FriendCountHistory, FlashFriend and FlashFriendship
moved here from skins/ in RFC-0001 Phase 5.4b without moving any data: each
keeps its original table (`db_table`) and index names. Changing either would
make Django rename the real table or index.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class ProfileVisibility(models.Model):
    """Which sections of a Bonkverse user's public profile other people see.

    Everything is public by default. The owner always sees every section of
    their own profile. Players without a Bonkverse account have no row and
    their profile is fully public (it is built from public bonk.io replays);
    signing up is how they get these switches.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile_visibility"
    )
    level_history = models.BooleanField(default=True)
    activity = models.BooleanField(default=True)
    maps_and_modes = models.BooleanField(default=True)
    play_partners = models.BooleanField(default=True)
    friends = models.BooleanField(default=True)
    skins = models.BooleanField(default=True)
    favorites = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    # (field, label, what it shows), in tab order. The settings form, the
    # profile tabs and the Overview cards all read this, so a new section is
    # one entry here plus its field above.
    SECTIONS = [
        ("level_history", "Level", "Your level over time and when you levelled up."),
        ("activity", "Activity", "When and how much you play: days, hours, streaks."),
        ("maps_and_modes", "Maps and modes", "The modes, rooms and maps you play."),
        ("play_partners", "People", "Who you play with, team with and play against."),
        (
            "friends",
            "Friends",
            "Your bonk.io and Flash friend lists. Hiding them also leaves you out of "
            "other players' friend lists.",
        ),
        ("skins", "Skins", "Skins you created on Bonkverse."),
        ("favorites", "Favorites", "Skins you favorited."),
    ]

    class Meta:
        verbose_name_plural = "profile visibility"

    def __str__(self):
        hidden = [field for field, _, _ in self.SECTIONS if not getattr(self, field)]
        return f"{self.user} (hidden: {', '.join(hidden) or 'none'})"

    def as_dict(self):
        return {field: getattr(self, field) for field, _, _ in self.SECTIONS}


class SyncCursor(models.Model):
    """Where a background sync got to (players/replay_sync.py), so the next
    run carries on from there instead of starting over."""

    name = models.CharField(max_length=64, primary_key=True)
    value = models.TextField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} = {self.value}"


class WornSkinSource(models.TextChoices):
    """Where a player's worn skin was seen."""

    LOGIN = "login", "bonk.io login"
    WEAR = "wear", "Worn from Bonkverse"
    REPLAY = "replay", "Seen in a replay"


class BonkPlayer(models.Model):
    """Any bonk.io account we know of (friends, replay players, map authors).

    Not the Bonkverse login user (`skins.BonkUser`): this is the in-game identity.
    """

    # The bonk.io account ID (DBID). Empty for a name only seen in replays
    # (players.replay_sync copies those in); filled in when a friend list or
    # login shows the real ID (players.friends_sync.adopt_replay_names).
    bonk_id = models.BigIntegerField(unique=True, db_index=True, null=True, blank=True)
    username = models.CharField(max_length=255, db_index=True)
    last_seen = models.DateTimeField(default=timezone.now)
    last_friend_count = models.IntegerField(default=0)  # snapshot at last sync
    # Total XP from the player's own bonk.io login (the only place XP is
    # shown); null until they sign in to Bonkverse. Level: core.bonk.levels.
    xp = models.BigIntegerField(null=True, blank=True)
    xp_seen_at = models.DateTimeField(null=True, blank=True)
    # The skin the player last wore in game, from the newest place we saw it
    # (players.services.record_worn_skin). Plain base64, checked with
    # core.bonk.SkinCode; null until first seen.
    worn_skin_code = models.TextField(null=True, blank=True)
    worn_skin_seen_at = models.DateTimeField(null=True, blank=True)
    worn_skin_source = models.CharField(
        max_length=16, blank=True, default="", choices=WornSkinSource.choices
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "skins_bonkplayer"
        indexes = [
            models.Index(fields=["bonk_id"], name="skins_bonkp_bonk_id_65d61a_idx"),
            models.Index(fields=["username"], name="skins_bonkp_usernam_420f86_idx"),
        ]

    def __str__(self):
        return f"{self.username} ({self.bonk_id})"


class Friendship(models.Model):
    """Undirected friendship edge between two BonkPlayers.

    Stored once, with ordered endpoints (player_low < player_high), so a pair
    can't appear twice.
    """

    player_low = models.ForeignKey(BonkPlayer, on_delete=models.CASCADE, related_name="edges_low")
    player_high = models.ForeignKey(BonkPlayer, on_delete=models.CASCADE, related_name="edges_high")
    created_at = models.DateTimeField(auto_now_add=True)
    last_confirmed_at = models.DateTimeField(default=timezone.now)  # updated each sync we see it

    class Meta:
        db_table = "skins_friendship"
        constraints = [
            models.UniqueConstraint(
                fields=["player_low", "player_high"], name="uniq_undirected_friendship"
            ),
            models.CheckConstraint(
                condition=~models.Q(player_low=models.F("player_high")),
                name="no_self_friendship",
            ),
        ]
        indexes = [
            models.Index(
                fields=["player_low", "player_high"], name="skins_frien_player__25ca38_idx"
            ),
            models.Index(
                fields=["player_high", "player_low"], name="skins_frien_player__7d8c94_idx"
            ),
        ]

    def __str__(self):
        return f"{self.player_low.bonk_id} ↔ {self.player_high.bonk_id}"


class FriendCountHistory(models.Model):
    player = models.ForeignKey(
        BonkPlayer, on_delete=models.CASCADE, related_name="friend_count_history"
    )
    count = models.IntegerField()
    captured_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "skins_friendcounthistory"


class FlashFriend(models.Model):
    """A friend from the Flash era (Bonk 1 / TinyTanks), imported at login.

    Name only, unless it's later matched to a BonkPlayer.
    """

    name = models.TextField(db_index=True)
    bonk_player = models.ForeignKey(
        BonkPlayer, on_delete=models.SET_NULL, null=True, blank=True, related_name="as_flash_friend"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "skins_flashfriend"
        constraints = [
            # The resolved case (bonk_player set): two rows can't share the
            # same (name, bonk_player) pair.
            models.UniqueConstraint(
                fields=["name", "bonk_player"],
                condition=models.Q(bonk_player__isnull=False),
                name="uniq_flashfriend_name_player_resolved",
            ),
            # The far more common unresolved case. Postgres treats every NULL
            # as distinct, so a plain unique (name, bonk_player) would allow
            # endless duplicate names while bonk_player is NULL. This partial
            # index allows one row per name while it's unresolved.
            models.UniqueConstraint(
                fields=["name"],
                condition=models.Q(bonk_player__isnull=True),
                name="uniq_flashfriend_name_unresolved",
            ),
        ]

    def __str__(self):
        return f"{self.name} (linked to {self.bonk_player_id or '—'})"


class FlashFriendship(models.Model):
    """A Bonkverse user's imported Flash friend."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="flash_friendships"
    )
    flash_friend = models.ForeignKey(
        FlashFriend, on_delete=models.CASCADE, related_name="friend_of"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "skins_flashfriendship"
        unique_together = ("user", "flash_friend")

    def __str__(self):
        return f"{self.user.username} ↔ {self.flash_friend.name}"
