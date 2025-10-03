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
from django.http import HttpResponse
from django.urls import path
from skins.search import search_skins
from skins.upload import upload_skin
from skins.upload import upload_skin
from django.conf import settings
from django.conf.urls.static import static
from skins.login import login_view, logout_view
from skins.my_profile import my_profile, edit_skin, delete_skin
from skins.bonkbot import matchmaking_page, join_matchmaking
from skins.skin_detail import skin_detail
from skins.skin_votes import vote_skin_api, toggle_favorite_api
from skins.wear_skin import wear_skin, bonk_login_for_wear
from skins.players import search_players_view, players_page
from skins.create_changelog import add_changelog
from skins.changelog import changelog_view
from skins import flash_friends
from skins import leaderboards
from skins import players
from skins import home
from skins import api
from skins import win_leaderboards
from skins import loss_leaderboards
from skins import winrate_leaderboards
from django.views.static import serve





urlpatterns = [
    path('admin/', admin.site.urls),
    path("search/", search_skins, name="search_skins"),
    path("", home.home, name='home'),
    # path("", search_skins, name="home"),  # Home page is now the search page
    path('upload/', upload_skin, name="upload_skin"),  # New Upload Page
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('my-profile/', my_profile, name='my_profile'),
    path('skin/<int:skin_id>/delete/', delete_skin, name='delete_skin'),
    path('skin/<int:skin_id>/edit/', edit_skin, name='edit_skin'),
    path('matchmaking/', matchmaking_page, name='matchmaking'),
    # path('skins/<int:skin_id>/', skin_detail, name='skin_detail'),
    path("skins/<int:skin_id>/<uuid:uuid>/", skin_detail, name="skin_detail"),
    path("changelog/", changelog_view, name="changelog"),


    # NEW: AJAX/JSON endpoints used by search cards
    path('api/skins/<int:skin_id>/vote/', vote_skin_api, name='api_vote_skin'),
    path('api/skins/<int:skin_id>/favorite/', toggle_favorite_api, name='api_toggle_favorite'),
    path("api/skins/<int:skin_id>/wear/", wear_skin, name="wear_skin"),
    path("api/bonk/login/", bonk_login_for_wear, name="bonk_login_for_wear"),
    path("api/players/search/", players.search_players_view, name="players_search"),
    path("api/flash-friends/search/", flash_friends.search_flash_friends_view, name="flash_friends_search"),
    path('api/join-matchmaking/', join_matchmaking),


    # Leaderboards
    path("leaderboards/upvoted/", leaderboards.most_upvoted_skins, name="leaderboards_upvoted"),
    path("leaderboards/downvoted/", leaderboards.most_downvoted_skins, name="leaderboards_downvoted"),
    path("leaderboards/favorited/", leaderboards.most_favorited_skins, name="leaderboards_favorited"),

    # Players Search navigation
    path("players_search/players/", players_page, name="players_page"),
    path("players_search/flash-friends/", flash_friends.flash_friends_page, name="flash_friends_page"),

    path("changelog/add/", add_changelog, name="add_changelog"),

    path("api/wins/", api.record_win, name="api_record_win"),
    path("api/losses/", api.record_loss, name="api_record_loss"),
    path("api/leaderboard/<str:period>/", api.leaderboard, name="api_leaderboard"),
    path("api/loss-leaderboard/<str:period>/", api.loss_leaderboard, name="api_loss_leaderboard"),
    path("api/heartbeat/", api.heartbeat, name="heartbeat"),
    path("api/stop_tracking/", api.stop_tracking, name="stop_tracking"),

    # Verification
    path("api/request_verification/", api.request_verification, name="request_verification"),
    path("api/complete_verification/", api.complete_verification, name="complete_verification"),



    path("leaderboards/wins/<str:period>/", win_leaderboards.wins_hub, name="wins_hub"),
    path("leaderboards/wins/", win_leaderboards.wins_hub, {"period": "today"}),  # default
    path("leaderboards/losses/<str:period>/", loss_leaderboards.losses_hub, name="losses_hub"),
    path("leaderboards/losses/", loss_leaderboards.losses_hub, {"period": "today"}),  # default
    path("leaderboards/winrate/<str:period>/", winrate_leaderboards.winrate_hub, name="winrate_hub"),
    path("leaderboards/winrate/", winrate_leaderboards.winrate_hub, {"period": "today"}),


] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Static files (always safe)
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Media files (needed for your volume-stored images)
urlpatterns += [
    path("media/<path:path>", serve, {"document_root": settings.MEDIA_ROOT}),
]
