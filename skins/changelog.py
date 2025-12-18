from django.shortcuts import render
from .models import Changelog
from django_ratelimit.decorators import ratelimit

# def changelog_view(request):
#     updates = Changelog.objects.order_by("-created_at")
#     return render(request, "skins/changelog.html", {"updates": updates})



@ratelimit(key="ip", rate="5/m", block=True)
def changelog_view(request):
    updates = list(Changelog.objects.all().order_by("-created_at"))  # force materialize
    return render(request, "skins/changelog.html", {"updates": updates})
