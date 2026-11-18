"""Signing in and out, and BonxBot's Discord-link lookup (docs/apps/accounts.md). Paths and names are pinned by
tests/test_url_snapshot.py."""

from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("api/me/", views.me, name="api_me"),
    path("logout/", views.logout_view, name="logout"),
    path(
        "api/bot/discord-links/<int:discord_user_id>/",
        views.bot_discord_links,
        name="api_bot_discord_links",
    ),
]
