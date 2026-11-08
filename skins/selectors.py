"""Read-only queries shaped for pages (RFC-0001: selectors).

decorate_skins_for_user: everything a skin card (skins/partials/_skin_card.html)
shows beyond the Skin row itself, for a whole page of cards in a fixed number
of queries. tests/test_query_budgets.py fails if a page starts asking per card.

skins_created_by / favorites_of: a player's skins for their profile page
(players/), most upvoted and most recently favorited first.
"""

from django.db.models import Count

from .models import Skin, SkinVote


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
        Skin.objects.filter(id__in=ids)
        .annotate(fav_count=Count("favorited_by"))
        .values_list("id", "fav_count")
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


def skins_created_by(username, limit):
    """(up to `limit` skins `username` created, most upvoted first; how many in all)."""
    qs = Skin.objects.filter(creator__iexact=username)
    return list(qs.order_by("-upvotes", "-id")[:limit]), qs.count()


def favorites_of(user, limit):
    """(up to `limit` skins `user` favorited, newest skins first; how many in all)."""
    qs = user.favorite_skins.all()
    return list(qs.order_by("-created_at")[:limit]), qs.count()
