from django.apps import AppConfig


class PlayersConfig(AppConfig):
    """Player profiles: a page for every registered bonk.io player, built from
    the replay archive, plus skins and privacy settings for Bonkverse users."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "players"

    def ready(self):
        # Register <username:…> once at startup, so any app's URL conf can use
        # it without importing players.urls for the side effect.
        from django.urls import register_converter

        from .converters import UsernameConverter

        register_converter(UsernameConverter, "username")
