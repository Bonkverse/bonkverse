from django.shortcuts import render
from core.ratelimits import limit
from .models import Changelog

# def changelog_view(request):
#     updates = Changelog.objects.order_by("-created_at")
#     return render(request, "skins/changelog.html", {"updates": updates})


@limit("browse")
def changelog_view(request):
    updates = list(Changelog.objects.all().order_by("-created_at"))  # force materialize
    return render(request, "skins/changelog.html", {"updates": updates})
