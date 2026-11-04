from django.apps import AppConfig


class SkinsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "skins"

    def ready(self):
        from core import lookups

        lookups.register()
