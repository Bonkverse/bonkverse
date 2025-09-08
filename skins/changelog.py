from django.shortcuts import render
from .models import Changelog

def changelog_view(request):
    updates = Changelog.objects.order_by("-created_at")
    return render(request, "skins/changelog.html", {"updates": updates})
