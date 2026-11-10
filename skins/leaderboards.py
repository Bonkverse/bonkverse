"""Skin leaderboards: /leaderboards/<board>/ (most upvoted, most favorited, most downvoted).

Owns: which boards exist (LEADERBOARDS), how each ranks skins, and the one
view and template that show any of them.
Does not own: the counts themselves (Skin fields and Skin.objects
annotations, skins/querysets.py).

Adding a board is one LEADERBOARDS entry: bonk_skin_search/urls.py makes a
page for each, at /leaderboards/<key>/ named leaderboards_<key>.
"""

from collections.abc import Callable
from dataclasses import dataclass

from django.db.models import F, QuerySet
from django.http import Http404
from django.shortcuts import render

from core.ratelimits import limit
from skins.models import Skin

TOP_N = 50


@dataclass(frozen=True)
class Leaderboard:
    title: str  # page heading
    column: str  # heading of the count column
    tab: str | None  # label in the tab bar; None keeps the board out of it
    rank: Callable[[QuerySet], QuerySet]  # annotates `value` and orders by it


# Order matters: it is the tab order.
LEADERBOARDS = {
    "upvoted": Leaderboard(
        title="Most Upvoted Skins",
        column="Upvotes",
        tab="Most upvoted",
        rank=lambda skins: skins.annotate(value=F("upvotes")).order_by("-upvotes"),
    ),
    "favorited": Leaderboard(
        title="Most Favorited Skins",
        column="Favorites",
        tab="Most favorited",
        rank=lambda skins: (
            skins.with_favorite_count().annotate(value=F("fav_count")).order_by("-fav_count")
        ),
    ),
    # Reachable by URL only; not shown in the tabs.
    "downvoted": Leaderboard(
        title="Most Downvoted Skins",
        column="Downvotes",
        tab=None,
        rank=lambda skins: skins.annotate(value=F("downvotes")).order_by("-downvotes"),
    ),
}


def url_name(board: str) -> str:
    """The URL name of a board's page (kept from the three old views)."""
    return f"leaderboards_{board}"


@limit("browse")
def leaderboard(request, board: str):
    config = LEADERBOARDS.get(board)
    if config is None:
        raise Http404("Unknown leaderboard")

    return render(
        request,
        "leaderboards/leaderboard.html",
        {
            "board": config,
            "skins": config.rank(Skin.objects.all())[:TOP_N],
            "tabs": [
                {"url_name": url_name(slug), "label": b.tab, "current": slug == board}
                for slug, b in LEADERBOARDS.items()
                if b.tab
            ],
        },
    )
