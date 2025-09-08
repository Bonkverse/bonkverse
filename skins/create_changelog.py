from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import Http404
from .models import Changelog

@login_required
def add_changelog(request):
    # ✅ Only allow "The Saucy Tulip" to access
    if request.user.username != "The Saucy Tulip":
        raise Http404("Page not found")

    if request.method == "POST":
        title = request.POST.get("title")
        content = request.POST.get("content")
        version = request.POST.get("version")

        Changelog.objects.create(
            title=title,
            content=content,
            version=version
        )
        return redirect("changelog")  # redirect to changelog list

    return render(request, "skins/create_changelog.html")
