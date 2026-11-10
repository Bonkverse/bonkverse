from django.apps import AppConfig


class SitePagesConfig(AppConfig):
    """The site's own pages: home, privacy, terms, the staff page and small
    tools (the map decoder). Skins, players and Discord servers have their own
    apps; this one only shows what they provide (docs/apps/site_pages.md)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "site_pages"
