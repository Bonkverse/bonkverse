"""Browse pages: New Releases, the category index and one category's skins.

What each category matches, and the base query, are in skins/categories.py.
"""

from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import render

from core.pagination import elided_page_range
from core.periods import PERIODS
from core.ratelimits import limit
from skins.categories import CATEGORIES, browsable_skins, category_tiles, keyword_q, sorted_skins
from skins.selectors import decorate_skins_for_user


@limit("browse")
def category_index(request):
    """Tiles for every category, with a cover image and count. Cached in Redis."""
    return render(request, "skins/category_index.html", {"categories": category_tiles()})


@limit("browse")
def category_detail(request, slug):
    meta = CATEGORIES.get(slug)
    if not meta:
        raise Http404("Unknown category")

    qs = browsable_skins().filter(keyword_q(meta["keywords"]))
    qs, sort = sorted_skins(qs, request.GET.get("sort", "favorites"))

    page_obj = Paginator(qs, 60).get_page(request.GET.get("page", 1))
    return render(
        request,
        "skins/skin_browse.html",
        {
            "page_obj": page_obj,
            "skins": decorate_skins_for_user(page_obj.object_list, request.user),
            "heading": meta["label"],
            "blurb": meta["blurb"],
            "sort": sort,
            "slug": slug,
            "base_qs": f"sort={sort}",
            "elided_range": elided_page_range(page_obj),
        },
    )


@limit("browse")
def new_releases(request):
    period = request.GET.get("period", "all")
    if period not in PERIODS:
        period = "all"
    qs = browsable_skins().created_in(period).order_by("-created_at")

    page_obj = Paginator(qs, 60).get_page(request.GET.get("page", 1))
    return render(
        request,
        "skins/skin_browse.html",
        {
            "page_obj": page_obj,
            "skins": decorate_skins_for_user(page_obj.object_list, request.user),
            "heading": "New Releases",
            "blurb": "Fresh uploads, newest first.",
            "period": period,
            "base_qs": f"period={period}",
            "elided_range": elided_page_range(page_obj),
        },
    )
