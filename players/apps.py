from django.apps import AppConfig


class PlayersConfig(AppConfig):
    """Player profiles: a page for every registered bonk.io player, built from
    the replay archive, plus skins and privacy settings for Bonkverse users."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "players"
