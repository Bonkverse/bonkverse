"""
URL configuration for bonk_skin_search project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import include, path
from skins.rerender import rerender_skin
from skins.media import serve_media
from skins.search import search_skins
from skins.upload import upload_skin
from django.conf import settings
from django.conf.urls.static import static
from skins.login import login_view, logout_view
from skins.my_profile import my_profile, edit_skin, delete_skin, bulk_delete_skins, my_skins_partial
from skins.bonkbot import matchmaking_page, join_matchmaking
from skins.skin_detail import skin_detail
from skins.skin_votes import vote_skin_api, toggle_favorite_api
from skins.wear_skin import wear_skin, bonk_login_for_wear, wear_skin_code
from skins.create_changelog import add_changelog
from skins import flash_friends
from skins import leaderboards
from skins import players
from skins import home
from skins import api
from skins import staff
from skins import discord
from skins import discord_views
from skins.social_stats import social_stats
from skins.apis.index import index
from skins.apis.publish_skin import publish_skin
from skins.apis import bot_skins
from skins.share_skin import share_skin
from skins.apis.auth.who_am_i import me
from skins.report_skin import report_skin
from skins.utils.tools.map_decode import map_decode_page, api_map_decode
from skins.privacy import privacy
from skins.terms import terms
from skins import categories


urlpatterns = [
    path("admin/", admin.site.urls),
    path("search/", search_skins, name="search_skins"),
    path("", home.home, name="home"),
    path("api/publish-skin/", publish_skin, name="publish_skin"),
    path("api/bot/skins/", bot_skins.submit_skin, name="api_bot_submit_skin"),
    path("skins/share/<int:skin_id>/<uuid:uuid>/", share_skin, name="share_skin"),
    path("login/", login_view, name="login"),
    path("api/me/", me, name="api_me"),
    path("logout/", logout_view, name="logout"),
    path("my-profile/", my_profile, name="my_profile"),
    path("upload/", upload_skin, name="upload_skin"),
    path("skin/<int:skin_id>/delete/", delete_skin, name="delete_skin"),
    path("skins/bulk-delete/", bulk_delete_skins, name="bulk_delete_skins"),
    path("my-profile/skins-partial/", my_skins_partial, name="my_skins_partial"),
    path("skin/<int:skin_id>/edit/", edit_skin, name="edit_skin"),
    path("matchmaking/", matchmaking_page, name="matchmaking"),
    path("skins/detail/<int:skin_id>", skin_detail, name="skin_detail"),
    path("staff/", staff.staff_page, name="staff"),
    # Public, versioned API for other sites and bots (public_api/, ADR 0011).
    path("api/v1/", include("public_api.urls")),
    # Developer portal: API terms and your own API keys (public_api/, ADR 0012).
    path("developers/", include("public_api.portal_urls")),
    # NEW: AJAX/JSON endpoints used by search cards
    path("api/", index, name="api_index"),
    path("api/skins/<int:skin_id>/vote/", vote_skin_api, name="api_vote_skin"),
    path("api/skins/<int:skin_id>/favorite/", toggle_favorite_api, name="api_toggle_favorite"),
    path("api/skins/<int:skin_id>/wear/", wear_skin, name="wear_skin"),
    path("api/skins/wear-code/", wear_skin_code, name="wear_skin_code"),
    path("api/bonk/login/", bonk_login_for_wear, name="bonk_login_for_wear"),
    path("api/players/search/", players.search_players_view, name="players_search"),
    path(
        "api/flash-friends/search/",
        flash_friends.search_flash_friends_view,
        name="flash_friends_search",
    ),
    path("api/join-matchmaking/", join_matchmaking),
    path("new/", categories.new_releases, name="new_releases"),
    path("categories/", categories.category_index, name="category_index"),
    path("category/<slug:slug>/", categories.category_detail, name="category_detail"),
    # Leaderboards
    path("leaderboards/upvoted/", leaderboards.most_upvoted_skins, name="leaderboards_upvoted"),
    path(
        "leaderboards/downvoted/", leaderboards.most_downvoted_skins, name="leaderboards_downvoted"
    ),
    path(
        "leaderboards/favorited/", leaderboards.most_favorited_skins, name="leaderboards_favorited"
    ),
    # Players Search navigation
    path("changelog/add/", add_changelog, name="add_changelog"),
    path("api/friends-sync-status/", api.friends_sync_status, name="friends_sync_status"),
    path("serverlist/", discord.server_list, name="list"),
    path("<uuid:server_id>/", discord.server_detail, name="detail"),
    path("submit/", discord.submit_server_page, name="submit_server"),
    path("api/discords/submit/", discord_views.submit_server, name="api_submit_server"),
    path("tools/map-decode/", map_decode_page, name="map_decode_page"),
    path("api/tools/map-decode/", api_map_decode, name="api_map_decode"),
    path("api/skins/<int:skin_id>/report/", report_skin, name="report_skin"),
    path("social-stats/", social_stats, name="social_stats"),
    path("", include("players.urls")),
    path("skins/<int:skin_id>/rerender/", rerender_skin, name="rerender_skin"),
    path("privacy/", privacy, name="privacy"),
    path("terms/", terms, name="terms"),
] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Static files (always safe)
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Media files (needed for your volume-stored images)
urlpatterns += [
    path("media/<path:path>", serve_media),
]
