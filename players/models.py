from django.conf import settings
from django.db import models


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
