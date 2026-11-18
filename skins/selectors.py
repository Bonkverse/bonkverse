"""Read-only queries shaped for pages (RFC-0001: selectors).

decorate_skins_for_user: everything a skin card (skins/partials/_skin_card.html)
shows beyond the Skin row itself, for a whole page of cards in a fixed number
of queries. tests/test_query_budgets.py fails if a page starts asking per card.

skins_created_by / favorites_of / creator_stats: a player's skins for the
Skins tab of their profile (players/).

bonk_players_matching / flash_friends_matching / flash_friend_counts: the
player directory (players/ "Players" page).

best_matches / random_skin: BonxBot's /skin commands (public_api/views/bot.py).
"""

import random

from django.conf import settings
from django.db.models import Count, F, Max, Min, Q, Sum

from core.db import time_limited_queries

from .models import Skin, SkinVote
from .querysets import MIN_NAME_SIMILARITY
from accounts.models import BonkAccountLink
from players.models import BonkPlayer, FlashFriendship


def decorate_skins_for_user(skins, user=None):
    """Set card fields on each skin, in place, and return the list.

    Every skin gets `fav_count_val` (how many users favorited it). With a
    signed-in `user`, each also gets `current_vote` ("up", "down" or None)
    and `is_favorited`; without one (anonymous visitors, or pages whose cards
    don't show the visitor's own state) those are None and False.

    Queries: 1 for the counts, plus 2 with a signed-in user, however many
    skins there are.
    """
    skins = list(skins)
    ids = [s.id for s in skins]
    if not ids:
        return skins

    fav_counts = dict(
        Skin.objects.filter(id__in=ids).with_favorite_count().values_list("id", "fav_count")
    )

    votes, favorited = {}, set()
    if user is not None and user.is_authenticated:
        votes = dict(
            SkinVote.objects.filter(user=user, skin_id__in=ids).values_list("skin_id", "vote")
        )
        favorited = set(user.favorite_skins.filter(id__in=ids).values_list("id", flat=True))

    for skin in skins:
        skin.fav_count_val = fav_counts.get(skin.id, 0)
        skin.current_vote = votes.get(skin.id)
        skin.is_favorited = skin.id in favorited
    return skins


def home_strips(size=24):
    """The home page's four skin strips: newest, random, most favorited and
    trending (upvotes minus downvotes). Skins with an open report are left out."""
    skins = Skin.objects.without_open_reports()
    return {
        "recent": skins.order_by("-created_at")[:size],
        "top_favs": skins.with_favorite_count().order_by("-fav_count", "-upvotes")[:size],
        "trending": skins.with_score().order_by("-score", "-created_at")[:size],
        "random_strip": skins.order_by("?")[:size],
    }


def best_matches(query: str, limit: int) -> list:
    """The `limit` most relevant skins for `query`, favorite counts included.

    Same rules and time limit as the search page; raises OperationalError if
    the search takes too long."""
    skins = (
        Skin.objects.search(query, "relevance")
        .with_favorite_count()
        .order_by("-rank", "-similarity", "name")
    )
    with time_limited_queries(
        settings.SEARCH_STATEMENT_TIMEOUT_MS,
        pg_trgm__similarity_threshold=MIN_NAME_SIMILARITY,
    ):
        return list(skins[:limit])


def random_skin():
    """One random skin, picked through the primary key index (never ORDER BY
    random() over the whole table), or None if there are no skins."""
    bounds = Skin.objects.aggregate(lo=Min("id"), hi=Max("id"))
    if bounds["lo"] is None:
        return None
    for _ in range(5):  # ids can have gaps where skins were deleted
        pick = random.randint(bounds["lo"], bounds["hi"])
        skin = Skin.objects.with_favorite_count().filter(id__gte=pick).order_by("id").first()
        if skin is not None:
            return skin
    return Skin.objects.with_favorite_count().order_by("id").first()


# How skins can be ranked for a leaderboard: metric -> annotate `value`, order
# by it. Ties have no defined order.
SKIN_RANKINGS = {
    "upvotes": lambda skins: skins.annotate(value=F("upvotes")).order_by("-upvotes"),
    "favorites": lambda skins: (
        skins.with_favorite_count().annotate(value=F("fav_count")).order_by("-fav_count")
    ),
}


def top_skins(metric: str, limit: int):
    """The `limit` skins ranked highest by `metric` (a SKIN_RANKINGS key), each
    with its count as `value`. Skins with an open report are left out."""
    return SKIN_RANKINGS[metric](Skin.objects.without_open_reports())[:limit]


# Sort orders for a player's skins (profile Skins tab): key -> order_by fields.
SKIN_SORTS = {
    "top": ("-upvotes", "-id"),
    "new": ("-created_at", "-id"),
    "az": ("name", "id"),
}


def skins_created_by(username, sort="top"):
    """Skins `username` created, as a queryset in one of SKIN_SORTS' orders."""
    order = SKIN_SORTS.get(sort, SKIN_SORTS["top"])
    return Skin.objects.made_by(username).order_by(*order)


def favorites_of(user, sort="new"):
    """Skins `user` favorited, as a queryset in one of SKIN_SORTS' orders."""
    order = SKIN_SORTS.get(sort, SKIN_SORTS["new"])
    return user.favorite_skins.all().order_by(*order)


def creator_stats(username):
    """How many skins `username` made, and the upvotes and favorites they got."""
    totals = Skin.objects.made_by(username).aggregate(
        skins=Count("id", distinct=True),
        upvotes=Sum("upvotes"),
    )
    favorited = Skin.favorited_by.through.objects.filter(skin__creator__iexact=username).count()
    return {
        "skins": totals["skins"] or 0,
        "upvotes": totals["upvotes"] or 0,
        "favorited": favorited,
    }


def bonk_players_named(names):
    """{lower name: BonkPlayer} for exact (case-insensitive) names."""
    lowered = {n.lower() for n in names}
    found = {}
    q = Q()
    for n in lowered:
        q |= Q(username__iexact=n)
    if not lowered:
        return found
    for p in BonkPlayer.objects.filter(q).order_by("-last_seen"):
        found.setdefault(p.username.lower(), p)
    return found


def flash_friend_counts(user_ids):
    """{user id: number of flash friends they imported}."""
    return dict(
        FlashFriendship.objects.filter(user_id__in=list(user_ids))
        .values("user_id")
        .annotate(c=Count("id"))
        .values_list("user_id", "c")
    )


def account_links_for(players):
    """{BonkPlayer id: BonkUser id} for players linked to a Bonkverse account."""
    return dict(
        BonkAccountLink.objects.filter(bonk_player__in=list(players), active=True).values_list(
            "bonk_player_id", "user_id"
        )
    )
