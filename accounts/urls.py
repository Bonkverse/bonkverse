"""Signing in and out (docs/apps/accounts.md). Paths and names are pinned by
tests/test_url_snapshot.py."""

from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("api/me/", views.me, name="api_me"),
    path("logout/", views.logout_view, name="logout"),
    path("login/forget/", views.forget_known_account, name="forget_known_account"),
    path("login/choose/", views.one_click_sign_in, name="one_click_sign_in"),
    # Sign in or add an account with a friend request (RFC-0003 phase 6).
    path("login/friend/", views.friend_request_login, name="friend_request_login"),
    # Sign in or add an account with a code typed in a bonk.io room (ADR 0026, experimental).
    path("login/room/", views.room_code_login, name="room_code_login"),
    path("login/room/<int:claim_id>/", views.room_code_wait, name="room_code_wait"),
    path("login/room/<int:claim_id>/status/", views.room_code_status, name="room_code_status"),
    path("login/friend/<int:claim_id>/", views.friend_request_wait, name="friend_request_wait"),
    path(
        "login/friend/<int:claim_id>/status/",
        views.friend_request_status,
        name="friend_request_status",
    ),
    # A person's bonk.io accounts (RFC-0003 phase 5, accounts/groups.py).
    path("accounts/switch/", views.switch_account, name="switch_account"),
    path("accounts/remove/", views.remove_account, name="remove_account"),
    path("accounts/main/", views.make_main_account, name="make_main_account"),
    path("accounts/show-on-profiles/", views.show_on_profiles_view, name="show_on_profiles"),
    path("accounts/browsers/remove/", views.remove_trusted_browser, name="remove_trusted_browser"),
    path("accounts/add-used-here/", views.add_used_here, name="add_used_here"),
    path(
        "accounts/one-click/remove/",
        views.remove_one_click_browser,
        name="remove_one_click_browser",
    ),
    path("api/me/switch/", views.api_switch_account, name="api_switch_account"),
]
