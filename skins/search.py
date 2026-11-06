"""Skin search page (/search/).

Every query narrows the table with an index first, then applies the relevance
rules to the few rows left, so a search costs milliseconds instead of reading
every skin. Indexes are declared on Skin.Meta (skins/models.py).
"""

import logging
import random
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.postgres.search import SearchQuery, SearchRank, TrigramSimilarity
from django.core.paginator import Paginator
from django.db import OperationalError
from django.db.models import Count, F, Max, Min, Q
from django.shortcuts import render
from django.utils import timezone

from core.db import time_limited_queries
from core.ratelimits import limit
from skins.models import SKIN_SEARCH_CONFIG, Skin
from skins.selectors import decorate_skins_for_user

from .pagination_utils import elided_page_range

logger = logging.getLogger(__name__)

PER_PAGE = 50
# Relevance thresholds. Unchanged from the original search; the index prefilter
# below only skips rows that could never pass them.
MIN_RANK = 0.1
MIN_NAME_SIMILARITY = 0.2


def _relevance(skins, query: str):
    """Full-text + fuzzy-name matches, ranked. Index-backed (search_vector, name trigram)."""
    search_query = SearchQuery(query, config=SKIN_SEARCH_CONFIG)
    return (
        # Narrow with the GIN indexes: full-text hit OR name similar enough. With
        # pg_trgm.similarity_threshold = MIN_NAME_SIMILARITY this keeps every row
        # the rule below can accept.
        skins.filter(Q(search_vector=search_query) | Q(name__trigram_similar=query))
        .annotate(
            rank=SearchRank(F("search_vector"), search_query),
            similarity=TrigramSimilarity("name", query),
        )
        .filter(Q(rank__gte=MIN_RANK) | Q(similarity__gt=MIN_NAME_SIMILARITY))
    )


def _random_sample(size: int):
    """About `size` random skins via the primary key index, not ORDER BY random().

    Returns an unsliced queryset, so any sort can still be applied to it.
    """
    bounds = Skin.objects.aggregate(lo=Min("id"), hi=Max("id"))
    if bounds["lo"] is None:
        return Skin.objects.none()
    span = range(bounds["lo"], bounds["hi"] + 1)
    # Oversample to make up for deleted ids, then keep `size` that exist.
    candidates = random.sample(span, min(len(span), size * 3))
    ids = list(Skin.objects.filter(id__in=candidates).values_list("id", flat=True)[:size])
    return Skin.objects.filter(id__in=ids)


@limit("search")
def search_skins(request):
    query = request.GET.get("q", "").strip()
    mode = request.GET.get("mode", "relevance")
    sort = request.GET.get("sort", "relevance")
    page_number = request.GET.get("page", 1)

    if query:
        if mode == "name":
            skins = Skin.objects.filter(name__ilike_contains=query)
        elif mode == "creator":
            skins = Skin.objects.filter(creator__ilike_contains=query)
        elif mode == "tags":
            skins = Skin.objects.filter(labels__icontains=[query.lower()])
        elif mode == "description":
            skins = Skin.objects.filter(description__ilike_contains=query)
        else:  # relevance
            skins = _relevance(Skin.objects.all(), query)
    else:
        skins = _random_sample(PER_PAGE)

    # ── Sorting ───────────────────────────────────────────────────
    if sort == "newest":
        skins = skins.order_by("-created_at")
    elif sort == "favorites":
        skins = skins.annotate(fav_count=Count("favorited_by")).order_by("-fav_count")
    elif sort == "upvotes":
        skins = skins.annotate(score=F("upvotes") - F("downvotes")).order_by("-score")
    elif query and mode == "relevance":
        skins = skins.order_by("-rank", "-similarity", "name")
    elif query:
        skins = skins.order_by("name")
    else:
        skins = skins.order_by("?")  # shuffle the sample (at most PER_PAGE rows)

    # ── Run it, under a time limit ────────────────────────────────
    # A pathological query is cancelled instead of tying up a worker for everyone.
    search_error = None
    try:
        with time_limited_queries(
            settings.SEARCH_STATEMENT_TIMEOUT_MS,
            pg_trgm__similarity_threshold=MIN_NAME_SIMILARITY,
        ):
            page_obj = Paginator(skins, PER_PAGE).get_page(page_number)
            skins_on_page = list(page_obj)  # evaluate once; reused below
    except OperationalError:
        logger.warning("search timed out: q=%r mode=%s sort=%s", query[:100], mode, sort)
        search_error = "That search took too long. Try a more specific search term."
        page_obj = Paginator([], PER_PAGE).get_page(1)
        skins_on_page = []
    # Favorite counts, and the visitor's own votes and favorites, for the
    # whole page in a fixed number of queries (skins/selectors.py).
    decorate_skins_for_user(skins_on_page, request.user)

    # ── Daily / total counts for the header ───────────────────────
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

    # ── Pagination querystring ─────────────────────────────────────
    # Preserves q/mode/sort/tz_offset across page links so navigating
    # to page 2 doesn't silently reset the user's search or filters.
    base_qs = urlencode(
        {
            k: v
            for k, v in {
                "q": query,
                "mode": mode if query else None,  # mode/sort are only meaningful with a query
                "sort": sort,
                "tz_offset": request.GET.get("tz_offset"),
            }.items()
            if v
        }
    )

    return render(
        request,
        "skins/search.html",
        {
            "skins": page_obj,
            "skins_on_page": skins_on_page,  # pre-evaluated list used in template
            "query": query,
            "mode": mode,
            "sort": sort,
            "daily_skin_count": daily_skin_count,
            "total_skin_count": total_skin_count,
            "base_qs": base_qs,
            "elided_range": elided_page_range(page_obj),
            "search_error": search_error,
        },
    )
