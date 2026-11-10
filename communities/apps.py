from django.apps import AppConfig


class CommunitiesConfig(AppConfig):
    """The Discord server directory: listing, tags, submitting a server and
    the hourly member-count refresh (docs/apps/communities.md). The models
    still live in skins/ until their move step."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "communities"
