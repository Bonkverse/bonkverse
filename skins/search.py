from django.shortcuts import render
from django.http import JsonResponse
from django.db.models import Q
from django.core.paginator import Paginator
from skins.models import Skin
from django.conf import settings
import random
from django.contrib.postgres.search import SearchVector
from django.contrib.postgres.search import TrigramSimilarity

AWS_BASE_URL = "https://bonkverse-skins.s3.us-east-2.amazonaws.com/uploads/cropped"

def search_skins(request):
    query = request.GET.get("q", "").strip()
    page_number = request.GET.get("page", 1)
    per_page = 50

    if query:
        skins = Skin.objects.annotate(
            search=SearchVector("name", "creator")
        ).filter(search=query)
    else:
        skins = list(Skin.objects.all())
        random.shuffle(skins)
        skins = skins[:50]

    # Convert skin list to include full AWS URLs
    skins_data = [
        {
            "name": skin.name,
            "creator": skin.creator,
            "link": skin.link,
            "image_url": f"{AWS_BASE_URL}/skinUrl{skin.id}.png"
        }
        for skin in skins
    ]

    paginator = Paginator(skins_data, per_page)
    page_obj = paginator.get_page(page_number)

    return render(request, "skins/search.html", {
        "skins": page_obj,
        "query": query
    })
