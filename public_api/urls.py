from django.urls import path

import players.urls  # noqa: F401  registers the <username:…> converter

from . import views

# Mounted at /api/v1/. Usernames use the same <username:…> converter as
# profile pages: "." and ".." are written "~." and "~.." in the path.
urlpatterns = [
    path("me/", views.me, name="api_v1_me"),
    path("lookup/players/", views.lookup_players, name="api_v1_lookup_players"),
    path("players/<username:username>/", views.player, name="api_v1_player"),
    path(
        "players/<username:username>/level-history/",
        views.level_history,
        name="api_v1_player_level_history",
    ),
]
