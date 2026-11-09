from django.apps import AppConfig


class PublicApiConfig(AppConfig):
    """The public, versioned Bonkverse API (/api/v1/) for other sites and bots:
    API keys, per-key rate limits, and read-only player data that respects
    each player's profile privacy settings."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "public_api"
    verbose_name = "Public API"
