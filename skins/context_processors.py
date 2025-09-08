from .models import Changelog

def latest_update(request):
    try:
        return {"latest_update": Changelog.objects.order_by("-created_at").first()}
    except Exception:
        return {"latest_update": None}
