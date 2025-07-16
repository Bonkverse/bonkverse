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
            search=SearchVector("name", "creator", "description")
        ).filter(search=query).order_by("creator", "name")
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

   # Get user's local time by adjusting from UTC
    now_utc = timezone.now()
    try:
        tz_offset_minutes = int(request.GET.get("tz_offset", "0"))
    except ValueError:
        tz_offset_minutes = 0

    # Convert UTC now to user's local time
    user_now = now_utc - timedelta(minutes=tz_offset_minutes)

    # Get the start and end of the user's local "today"
    user_today_start = user_now.replace(hour=0, minute=0, second=0, microsecond=0)
    user_today_end = user_today_start + timedelta(days=1)

    # Convert local start/end times back to UTC (to match DB storage)
    user_today_start_utc = user_today_start + timedelta(minutes=tz_offset_minutes)
    user_today_end_utc = user_today_end + timedelta(minutes=tz_offset_minutes)

    # Count skins created within that range
    daily_skin_count = Skin.objects.filter(
        created_at__range=(user_today_start_utc, user_today_end_utc)
    ).count()

    # Total skins overall
    total_skin_count = Skin.objects.count()

    return render(request, "skins/search.html", {
        "skins": page_obj,
        "query": query,
        'daily_skin_count': daily_skin_count,
        'total_skin_count': total_skin_count,
    })