from django.shortcuts import render
from django.db.models import Q, Count, F
from django.core.paginator import Paginator
from skins.models import Skin, SkinVote   # import SkinVote
from django.utils import timezone
from datetime import timedelta
from django_ratelimit.decorators import ratelimit
from django.contrib.postgres.search import SearchVector, SearchQuery, SearchRank, TrigramSimilarity
import random

@ratelimit(key="ip", rate="10/m", block=True)
def search_skins(request):
    query = request.GET.get("q", "").strip()
    mode = request.GET.get("mode", "relevance")
    sort = request.GET.get("sort", "relevance")
    page_number = request.GET.get("page", 1)
    per_page = 50

    skins = Skin.objects.all()

    if query:
        vector = (
            SearchVector("labels", weight="A") +
            SearchVector("description", weight="A") +
            SearchVector("name", weight="B") +
            SearchVector("creator", weight="C")
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
                skins.annotate(
                    rank=SearchRank(vector, search_query),
                    similarity=TrigramSimilarity("name", query)
                )
                .filter(Q(rank__gte=0.1) | Q(similarity__gt=0.2))
            )
    else:
        skins = list(skins)
        random.shuffle(skins)
        skins = skins[:50]

    # Sorting
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
        else:
            pass

    # Pagination
    paginator = Paginator(skins, per_page)
    page_obj = paginator.get_page(page_number)

    # 🔹 Attach current user's vote if logged in
    if request.user.is_authenticated:
        user_votes = SkinVote.objects.filter(user=request.user, skin__in=page_obj)
        vote_map = {v.skin_id: v.vote for v in user_votes}
        for skin in page_obj:
            skin.current_vote = vote_map.get(skin.id)
    else:
        for skin in page_obj:
            skin.current_vote = None

    # Counts for header
    now_utc = timezone.now()
    try:
        tz_offset_minutes = int(request.GET.get("tz_offset", "0"))
    except ValueError:
        tz_offset_minutes = 0

    user_now = now_utc - timedelta(minutes=tz_offset_minutes)
    user_today_start = user_now.replace(hour=0, minute=0, second=0, microsecond=0)
    user_today_end = user_today_start + timedelta(days=1)
    user_today_start_utc = user_today_start + timedelta(minutes=tz_offset_minutes)
    user_today_end_utc = user_today_end + timedelta(minutes=tz_offset_minutes)

    daily_skin_count = Skin.objects.filter(
        created_at__range=(user_today_start_utc, user_today_end_utc)
    ).count()
    total_skin_count = Skin.objects.count()

    return render(request, "skins/search.html", {
        "skins": page_obj,
        "query": query,
        "mode": mode,
        "sort": sort,
        "daily_skin_count": daily_skin_count,
        "total_skin_count": total_skin_count,
    })

