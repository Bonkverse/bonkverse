from django.urls import path

from . import views

urlpatterns = [
    # Usernames go in the path as-is (URL-encoded); bonk.io names can't contain "/".
    path("player/<str:username>/", views.player_profile, name="player_profile"),
    path("settings/profile/", views.profile_settings, name="profile_settings"),
    path(
        "my-profile/replays-partial/",
        views.my_replay_stats_partial,
        name="my_replay_stats_partial",
    ),
]
