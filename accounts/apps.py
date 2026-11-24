from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """Signing in to Bonkverse with bonk.io: the login and logout pages, the
    limit on wrong passwords, what a successful login does, `/api/me/`, and
    `grant_admin` (docs/apps/accounts.md), and the models: BonkUser (the
    site account, AUTH_USER_MODEL) and BonkAccountLink."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        from django.contrib.auth.signals import user_logged_in

        from .sessions import mark_renewed_on_login

        user_logged_in.connect(mark_renewed_on_login, dispatch_uid="accounts.session_renewal")
