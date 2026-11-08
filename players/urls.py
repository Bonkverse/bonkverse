from django.urls import path

from . import views

# Usernames go in the path as-is (URL-encoded); bonk.io names can't contain "/".
urlpatterns = [
    path("players/", views.directory, name="players_directory"),
    # The two old search pages, kept so old links and bookmarks still work.
    path("players_search/players/", views.legacy_players_page, name="players_page"),
    path(
        "players_search/flash-friends/",
        views.legacy_flash_friends_page,
        name="flash_friends_page",
    ),
    path("player/<str:username>/", views.overview, name="player_profile"),
    path("player/<str:username>/activity/", views.activity, name="player_activity"),
    path("player/<str:username>/level/", views.level, name="player_level"),
    path("player/<str:username>/maps/", views.maps, name="player_maps"),
    path("player/<str:username>/people/", views.people, name="player_people"),
    path("player/<str:username>/skins/", views.skins, name="player_skins"),
    path("settings/profile/", views.profile_settings, name="profile_settings"),
]
