from django.shortcuts import render
from django.db.models import Q, Count, F
from django.core.paginator import Paginator
from skins.models import Skin, SkinVote
from django.utils import timezone
from datetime import timedelta
from django_ratelimit.decorators import ratelimit
from django.contrib.postgres.search import SearchVector, SearchQuery, SearchRank, TrigramSimilarity

@ratelimit(key="ip", rate="10/m", block=True)
def search_skins(request):
    query         = request.GET.get("q", "").strip()
    mode          = request.GET.get("mode", "relevance")
    sort          = request.GET.get("sort", "relevance")
    page_number   = request.GET.get("page", 1)
    per_page      = 50

    skins = Skin.objects.all()

    if query:
        vector = (
            SearchVector("labels",      weight="A") +
            SearchVector("description", weight="A") +
            SearchVector("name",        weight="B") +
            SearchVector("creator",     weight="C")
        )
        search_query = SearchQuery(query)

        if mode == "name":
            skins = skins.filter(name__icontains=query)
        elif mode == "creator":
            skins = skins.filter(creator__icontains=query)
        elif mode == "tags":
            skins = skins.filter(labels__icontains=[query.lower()])
        elif mode == "description":
            skins = skins.filter(description__icontains=query)
        else:  # relevance
            skins = (
                skins
                .annotate(
                    rank=SearchRank(vector, search_query),
                    similarity=TrigramSimilarity("name", query),
                )
                .filter(Q(rank__gte=0.1) | Q(similarity__gt=0.2))
            )
    else:
        # DB-level random sample — never pulls the whole table into Python
        skins = Skin.objects.order_by("?")[:50]

    # ── Sorting ───────────────────────────────────────────────────
    if sort == "newest":
        skins = skins.order_by("-created_at")
    elif sort == "favorites":
        skins = skins.annotate(fav_count=Count("favorited_by")).order_by("-fav_count")
    elif sort == "upvotes":
        skins = skins.annotate(score=F("upvotes") - F("downvotes")).order_by("-score")
    else:  # relevance (default)
        if query and mode == "relevance":
            skins = skins.order_by("-rank", "-similarity", "name")
        elif query:
            skins = skins.order_by("name")
        # else: random order already applied above

    # ── Pagination ────────────────────────────────────────────────
    paginator    = Paginator(skins, per_page)
    page_obj     = paginator.get_page(page_number)
    skins_on_page = list(page_obj)  # evaluate once; reused below
    skin_ids      = [s.id for s in skins_on_page]

    # ── Prefetch votes + favorites in bulk (3 queries total) ──────
    #
    # Before this fix, the template called skin.favorited_by.all and
    # skin.favorited_by.count PER CARD — 100+ extra queries for 50 cards.
    # Now we do it all here in 2–3 queries regardless of page size.

    # Favorite counts — one query, all cards
    fav_counts = {
        row["id"]: row["fav_count"]
        for row in (
            Skin.objects
            .filter(id__in=skin_ids)
            .annotate(fav_count=Count("favorited_by"))
            .values("id", "fav_count")
        )
    }

    if request.user.is_authenticated:
        # Which of this page's skins has the user voted on?
        vote_map = {
            v.skin_id: v.vote
            for v in SkinVote.objects.filter(
                user=request.user, skin__in=skin_ids
            )
        }

        # Which of this page's skins has the user favorited?
        fav_ids = set(
            request.user.favorite_skins
            .filter(id__in=skin_ids)
            .values_list("id", flat=True)
        )

        for skin in skins_on_page:
            skin.current_vote  = vote_map.get(skin.id)
            skin.is_favorited  = skin.id in fav_ids
            skin.fav_count_val = fav_counts.get(skin.id, 0)
    else:
        for skin in skins_on_page:
            skin.current_vote  = None
            skin.is_favorited  = False
            skin.fav_count_val = fav_counts.get(skin.id, 0)

    # ── Daily / total counts for the header ───────────────────────
    now_utc = timezone.now()
    try:
        tz_offset_minutes = int(request.GET.get("tz_offset", "0"))
    except ValueError:
        tz_offset_minutes = 0

    user_now             = now_utc - timedelta(minutes=tz_offset_minutes)
    user_today_start     = user_now.replace(hour=0, minute=0, second=0, microsecond=0)
    user_today_end       = user_today_start + timedelta(days=1)
    user_today_start_utc = user_today_start + timedelta(minutes=tz_offset_minutes)
    user_today_end_utc   = user_today_end   + timedelta(minutes=tz_offset_minutes)

    daily_skin_count = Skin.objects.filter(
        created_at__range=(user_today_start_utc, user_today_end_utc)
    ).count()
    total_skin_count = Skin.objects.count()

    return render(request, "skins/search.html", {
        "skins":            page_obj,
        "skins_on_page":    skins_on_page,   # pre-evaluated list used in template
        "query":            query,
        "mode":             mode,
        "sort":             sort,
        "daily_skin_count": daily_skin_count,
        "total_skin_count": total_skin_count,
    })