from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """Signing in to Bonkverse with bonk.io: the login and logout pages, the
    limit on wrong passwords, what a successful login does, `/api/me/`, and
    `grant_admin` (docs/apps/accounts.md), and BonkAccountLink. The site
    account model (BonkUser) still lives in skins/ until step 5.5c."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
