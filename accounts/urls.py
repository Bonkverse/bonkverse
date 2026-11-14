"""Signing in and out (docs/apps/accounts.md). Paths and names are pinned by
tests/test_url_snapshot.py."""

from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("api/me/", views.me, name="api_me"),
    path("logout/", views.logout_view, name="logout"),
]
