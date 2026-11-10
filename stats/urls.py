"""One page per LEADERBOARDS entry: /leaderboards/<key>/ named leaderboards_<key>.
Paths and names are unchanged from when these lived in skins/ (pinned by
tests/test_url_snapshot.py)."""

from django.urls import path

from . import leaderboards, views

urlpatterns = [
    path(
        f"leaderboards/{board}/",
        views.leaderboard,
        {"board": board},
        name=leaderboards.url_name(board),
    )
    for board in leaderboards.LEADERBOARDS
]
