from django.shortcuts import render
from django.http import JsonResponse
from django.db.models import Q
from django.core.paginator import Paginator
from skins.models import Skin
from django.conf import settings
import random
from django.contrib.postgres.search import SearchVector
from django.contrib.postgres.search import TrigramSimilarity


def search_skins(request):
    query = request.GET.get("q", "").strip()
    page_number = request.GET.get("page", 1)  # Get the current page number
    per_page = 50  # Limit skins per page

    if query:
        # ✅ Optimized search using PostgreSQL Full-Text Search
        skins = Skin.objects.annotate(
            search=SearchVector("name", "creator")
        ).filter(search=query).values("name", "creator", "image_url", "link")
    else:
        # Home page: Show 50 random skins
        skins = list(Skin.objects.all().values("name", "creator", "image_url", "link"))
        random.shuffle(skins)
        skins = skins[:50]  # Only show 50

    # Paginate the results
    paginator = Paginator(skins, per_page)
    page_obj = paginator.get_page(page_number)

    return render(request, "skins/search.html", {
        "skins": page_obj,
        "query": query,
        "MEDIA_URL": settings.MEDIA_URL
    })
