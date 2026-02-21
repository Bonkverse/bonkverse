# skins/context_processors.py
from .models import Changelog
from django.conf import settings

def editor_urls(request):
    return {
        "BONKVERSE_EDITOR_URL": settings.BONKVERSE_EDITOR_URL
    }


def latest_update(request):
    try:
        return {"latest_update": Changelog.objects.order_by("-created_at").first()}
    except Exception:
        return {"latest_update": None}
