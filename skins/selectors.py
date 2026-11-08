"""Read-only queries shaped for pages (RFC-0001: selectors).

decorate_skins_for_user: everything a skin card (skins/partials/_skin_card.html)
shows beyond the Skin row itself, for a whole page of cards in a fixed number
of queries. tests/test_query_budgets.py fails if a page starts asking per card.

skins_created_by / favorites_of / creator_stats: a player's skins for the
Skins tab of their profile (players/).

bonk_players_matching / flash_friends_matching / flash_friend_counts: the
player directory (players/ "Players" page).
"""

from django.db.models import Case, Count, Exists, IntegerField, OuterRef, Q, Sum, Value, When

from .models import BonkAccountLink, BonkPlayer, FlashFriend, FlashFriendship, Skin, SkinVote


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


# Sort orders for a player's skins (profile Skins tab): key -> order_by fields.
SKIN_SORTS = {
    "top": ("-upvotes", "-id"),
    "new": ("-created_at", "-id"),
    "az": ("name", "id"),
}


def skins_created_by(username, sort="top"):
    """Skins `username` created, as a queryset in one of SKIN_SORTS' orders."""
    order = SKIN_SORTS.get(sort, SKIN_SORTS["top"])
    return Skin.objects.filter(creator__iexact=username).order_by(*order)


def favorites_of(user, sort="new"):
    """Skins `user` favorited, as a queryset in one of SKIN_SORTS' orders."""
    order = SKIN_SORTS.get(sort, SKIN_SORTS["new"])
    return user.favorite_skins.all().order_by(*order)


def creator_stats(username):
    """How many skins `username` made, and the upvotes and favorites they got."""
    totals = Skin.objects.filter(creator__iexact=username).aggregate(
        skins=Count("id", distinct=True),
        upvotes=Sum("upvotes"),
    )
    favorited = Skin.favorited_by.through.objects.filter(skin__creator__iexact=username).count()
    return {
        "skins": totals["skins"] or 0,
        "upvotes": totals["upvotes"] or 0,
        "favorited": favorited,
    }


def bonk_players_matching(query):
    """BonkPlayers whose name contains `query` (or whose bonk.io ID is it):
    an exact name first, then players linked to a Bonkverse account, then
    by friend count. Each has `linked` (bool)."""
    qs = BonkPlayer.objects.annotate(
        linked=Exists(BonkAccountLink.objects.filter(bonk_player=OuterRef("pk"), active=True))
    )
    if query:
        match = Q(username__icontains=query)
        if query.isdigit():
            match |= Q(bonk_id=int(query))
        qs = qs.filter(match).annotate(
            exact=Case(
                When(username__iexact=query, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        return qs.order_by("exact", "-linked", "-last_friend_count", "username")
    return qs.order_by("-linked", "-last_friend_count", "username")


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


def flash_friends_matching(query):
    """Flash (Bonk 1 / TinyTanks) friend names containing `query`, most
    listed first. Each has `listed_by` (how many Bonkverse users have them)."""
    qs = FlashFriend.objects.select_related("bonk_player").annotate(listed_by=Count("friend_of"))
    if query:
        qs = qs.filter(name__icontains=query)
    return qs.order_by("-listed_by", "name")


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
