from django.shortcuts import render
from django.http import JsonResponse
from django.db.models import Q
from django.core.paginator import Paginator
from skins.models import Skin
from django.conf import settings
import random
from django.utils import timezone
from datetime import timedelta
from django.contrib.postgres.search import SearchVector
from django.contrib.postgres.search import TrigramSimilarity

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
            "image_url": skin.image_url
        }
        for skin in skins
    ]

    paginator = Paginator(skins_data, per_page)
    page_obj = paginator.get_page(page_number)

    # Get the user's timezone offset from the query string (in minutes)
    try:
        tz_offset_minutes = int(request.GET.get("tz_offset", "0"))
    except ValueError:
        tz_offset_minutes = 0

    # Get user's local time by adjusting from UTC
    now_utc = timezone.now()
    user_now = now_utc - timedelta(minutes=tz_offset_minutes)
    user_today = user_now.date()

    # Count skins created on the user's local "today"
    daily_skin_count = Skin.objects.filter(created_at__date=user_today).count()
    total_skin_count = Skin.objects.all().count()

    return render(request, "skins/search.html", {
        "skins": page_obj,
        "query": query,
        'daily_skin_count': daily_skin_count,
        'total_skin_count': total_skin_count,
    })
