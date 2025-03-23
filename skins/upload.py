from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.db.models import Q
from django.core.paginator import Paginator
from django.conf import settings
from django.urls import reverse
from django.contrib import messages
from skins.models import Skin
from skins.utils.fetch_skin_image_url import fetch_skin_image_url  # You should have this as a separate utility
import boto3
import os
import requests
import cv2
import re

bonk_url_pattern = r"^https://bonkleagues\.io/s/([A-Za-z0-9]{7})$"
skin_name_pattern = r"^[A-Za-z0-9_ ]+$"

def upload_skin(request):
    if request.method == "POST":
        skin_name = request.POST.get("skin_name").strip()
        creator = request.POST.get("creator").strip()
        bonkleagues_link = request.POST.get("bonkleagues_link").strip()

        if not skin_name or not creator or not bonkleagues_link:
            messages.error(request, "❌ All fields are required.")
            return render(request, "skins/upload.html")

        if not re.match(skin_name_pattern, skin_name):
            messages.error(request, "❌ Skin name can only contain letters, numbers, spaces, and underscores.")
            return render(request, "skins/upload.html")

        if not re.match(bonk_url_pattern, bonkleagues_link):
            messages.error(request, "❌ Invalid Bonkleagues link format.")
            return render(request, "skins/upload.html")

        if Skin.objects.filter(link=bonkleagues_link).exists():
            messages.error(request, "❌ This Bonkleagues link has already been submitted!")
            return redirect("upload_skin")

        if len(skin_name) > 1000 or len(creator) > 1000:
            messages.error(request, "❌ Skin name and creator must be under 1000 characters.")
            return render(request, "skins/upload.html")

        # Step 1: Fetch the image URL from the Bonkleagues API
        skin_image_url = fetch_skin_image_url(bonkleagues_link)
        if not skin_image_url:
            messages.error(request, "❌ Could not fetch skin image from Bonkleagues.")
            return render(request, "skins/upload.html")

        # Step 2: Save to DB
        Skin.objects.create(
            name=skin_name,
            creator=creator,
            link=bonkleagues_link,
            image_url=skin_image_url
        )

        messages.success(request, "✅ Skin uploaded successfully!")
        return redirect(reverse("search_skins") + f"?q={skin_name}")

    return render(request, "skins/upload.html")


def autocomplete_creator(request):
    query = request.GET.get("q", "").strip()
    if query:
        matching_creators = Skin.objects.filter(creator__icontains=query).values_list("creator", flat=True).distinct()[:10]
        return JsonResponse(list(matching_creators), safe=False)
    return JsonResponse([], safe=False)
