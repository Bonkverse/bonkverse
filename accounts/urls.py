"""Signing in and out (docs/apps/accounts.md). Paths and names are pinned by
tests/test_url_snapshot.py."""

from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("api/me/", views.me, name="api_me"),
    path("logout/", views.logout_view, name="logout"),
    # A person's bonk.io accounts (RFC-0003 phase 5, accounts/groups.py).
    path("accounts/switch/", views.switch_account, name="switch_account"),
    path("accounts/remove/", views.remove_account, name="remove_account"),
    path("accounts/main/", views.make_main_account, name="make_main_account"),
    path("api/me/switch/", views.api_switch_account, name="api_switch_account"),
]
