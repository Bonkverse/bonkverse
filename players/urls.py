from django.urls import path, register_converter

from . import views
from .converters import UsernameConverter

# Usernames go in the path URL-encoded; bonk.io names can't contain "/".
# Names like "." and ".." get a "~" in front (players/converters.py).
register_converter(UsernameConverter, "username")

urlpatterns = [
    path("players/", views.directory, name="players_directory"),
    # The two old search pages, kept so old links and bookmarks still work.
    path("players_search/players/", views.legacy_players_page, name="players_page"),
    path(
        "players_search/flash-friends/",
        views.legacy_flash_friends_page,
        name="flash_friends_page",
    ),
    path("player/<username:username>/", views.overview, name="player_profile"),
    path("player/<username:username>/activity/", views.activity, name="player_activity"),
    path("player/<username:username>/level/", views.level, name="player_level"),
    path("player/<username:username>/maps/", views.maps, name="player_maps"),
    path("player/<username:username>/people/", views.people, name="player_people"),
    path("player/<username:username>/skins/", views.skins, name="player_skins"),
    path("settings/profile/", views.profile_settings, name="profile_settings"),
    path("tools/xp/", views.xp_calculator, name="xp_calculator"),
    path("tools/xp/player.json", views.xp_calculator_player, name="xp_calculator_player"),
    path("tools/xp/levels.json", views.xp_calculator_levels, name="xp_calculator_levels"),
]
