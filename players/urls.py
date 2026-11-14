from django.urls import path

from . import api, social_stats, views

# Usernames go in the path URL-encoded; bonk.io names can't contain "/".
# Names like "." and ".." get a "~" in front (players/converters.py).
# <username:…> is registered in PlayersConfig.ready().

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
    path("player/<username:username>/friends/", views.friends, name="player_friends"),
    path("player/<username:username>/skins/", views.skins, name="player_skins"),
    # The player's worn skin as their avatar (see selectors.SKIN_AVATAR_FILES).
    path(
        "player/<username:username>/skin.png",
        views.skin_avatar,
        {"kind": "png"},
        name="player_skin_avatar",
    ),
    path(
        "player/<username:username>/skin-thumb.png",
        views.skin_avatar,
        {"kind": "thumbnail"},
        name="player_skin_avatar_thumb",
    ),
    path("settings/profile/", views.profile_settings, name="profile_settings"),
    path("tools/xp/", views.xp_calculator, name="xp_calculator"),
    path("tools/xp/player.json", views.xp_calculator_player, name="xp_calculator_player"),
    path("tools/xp/levels.json", views.xp_calculator_levels, name="xp_calculator_levels"),
    path("social-stats/", social_stats.social_stats, name="social_stats"),
    # JSON for the player search pages and the post-login friend sync toast.
    path("api/players/search/", api.search_players_view, name="players_search"),
    path(
        "api/flash-friends/search/",
        api.search_flash_friends_view,
        name="flash_friends_search",
    ),
    path("api/friends-sync-status/", api.friends_sync_status, name="friends_sync_status"),
]
