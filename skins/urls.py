"""skins' routes: search, skin pages, browsing, your skins, upload, the JSON
endpoints skin cards use (vote, favorite, wear, report), and the staff report
queue (moderation). Paths and names are pinned by tests/test_url_snapshot.py.
"""

from django.urls import path

from skins.views import (
    api_index,
    bot_skins,
    browse,
    matchmaking,
    media,
    moderation,
    my_skins,
    publish,
    report,
    rerender,
    search,
    share,
    skin_detail,
    upload,
    votes,
    wear,
)

app_name = "skins"

urlpatterns = [
    path("search/", search.search_skins, name="search_skins"),
    path("skins/detail/<int:skin_id>", skin_detail.skin_detail, name="skin_detail"),
    path("skins/share/<int:skin_id>/<uuid:uuid>/", share.share_skin, name="share_skin"),
    # Browse
    path("new/", browse.new_releases, name="new_releases"),
    path("categories/", browse.category_index, name="category_index"),
    path("category/<slug:slug>/", browse.category_detail, name="category_detail"),
    # Your skins
    path("my-profile/", my_skins.my_profile, name="my_profile"),  # redirect to your profile
    path("upload/", upload.upload_skin, name="upload_skin"),
    path("skin/<int:skin_id>/edit/", my_skins.edit_skin, name="edit_skin"),
    path("skin/<int:skin_id>/delete/", my_skins.delete_skin, name="delete_skin"),
    path("skins/bulk-delete/", my_skins.bulk_delete_skins, name="bulk_delete_skins"),
    # Staff
    path("skins/<int:skin_id>/rerender/", rerender.rerender_skin, name="rerender_skin"),
    path("moderation/", moderation.queue, name="moderation"),
    path("moderation/skins/<int:skin_id>/decide/", moderation.decide, name="moderation_decide"),
    # JSON for skin cards and pages (core/js/bv-api.js)
    path("api/", api_index.index, name="api_index"),
    path("api/skins/<int:skin_id>/vote/", votes.vote_skin_api, name="api_vote_skin"),
    path(
        "api/skins/<int:skin_id>/favorite/", votes.toggle_favorite_api, name="api_toggle_favorite"
    ),
    path("api/skins/<int:skin_id>/wear/", wear.wear_skin, name="wear_skin"),
    path("api/skins/wear-code/", wear.wear_skin_code, name="wear_skin_code"),
    path("api/bonk/login/", wear.bonk_login_for_wear, name="bonk_login_for_wear"),
    path("api/skins/<int:skin_id>/report/", report.report_skin, name="report_skin"),
    # From the skin editor and BonxBot
    path("api/publish-skin/", publish.publish_skin, name="publish_skin"),
    path("api/bot/skins/", bot_skins.submit_skin, name="api_bot_submit_skin"),
    # Matchmaking ("coming soon" page and the BonkBot pass-through)
    path("matchmaking/", matchmaking.matchmaking_page, name="matchmaking"),
    path("api/join-matchmaking/", matchmaking.join_matchmaking),
    # Skin images on the media volume (rate limit + cache headers)
    path("media/<path:path>", media.serve_media),
]
