"""Root URL conf: mounts each app's routes.

RFC-0001 Phase 5 moves routes out of this file into each app's own `urls.py`,
included here, one app per step. Every path is pinned by
`tests/test_url_snapshot.py`, so a move can't change one.

Order matters: Django answers with the first pattern that matches.
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
from skins.apis.index import index
from skins.apis.publish_skin import publish_skin
from skins.apis import bot_skins
from skins.share_skin import share_skin
from skins.apis.auth.who_am_i import me
from skins.report_skin import report_skin
from skins import categories


urlpatterns = [
    path("admin/", admin.site.urls),
    path("search/", search_skins, name="search_skins"),
    # Home, privacy, terms, staff, map decoder (site_pages/, docs/apps/site_pages.md).
    path("", include("site_pages.urls")),
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
    # Public, versioned API for other sites and bots (public_api/, ADR 0011).
    path("api/v1/", include("public_api.urls")),
    # Developer portal: API terms and your own API keys (public_api/, ADR 0012).
    path("developers/", include("public_api.portal_urls")),
    # JSON endpoints used by skin cards and pages (core/js/bv-api.js).
    path("api/", index, name="api_index"),
    path("api/skins/<int:skin_id>/vote/", vote_skin_api, name="api_vote_skin"),
    path("api/skins/<int:skin_id>/favorite/", toggle_favorite_api, name="api_toggle_favorite"),
    path("api/skins/<int:skin_id>/wear/", wear_skin, name="wear_skin"),
    path("api/skins/wear-code/", wear_skin_code, name="wear_skin_code"),
    path("api/bonk/login/", bonk_login_for_wear, name="bonk_login_for_wear"),
    path("api/join-matchmaking/", join_matchmaking),
    path("new/", categories.new_releases, name="new_releases"),
    path("categories/", categories.category_index, name="category_index"),
    path("category/<slug:slug>/", categories.category_detail, name="category_detail"),
    # Leaderboards: one page per stats/leaderboards.py entry (stats/, docs/apps/stats.md).
    path("", include("stats.urls")),
    # Discord server directory (communities/, docs/apps/communities.md).
    path("", include("communities.urls")),
    path("api/skins/<int:skin_id>/report/", report_skin, name="report_skin"),
    # Player profiles, directory, search APIs, social stats, XP calculator (players/).
    path("", include("players.urls")),
    path("skins/<int:skin_id>/rerender/", rerender_skin, name="rerender_skin"),
]

# Static files (WhiteNoise serves them in production; this covers DEBUG).
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Skin images on the media volume (skins/media.py adds cache headers + limits).
urlpatterns += [
    path("media/<path:path>", serve_media),
]
