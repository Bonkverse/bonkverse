from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.db.models import Q
from django.core.paginator import Paginator
from django.conf import settings
from django.urls import reverse  # ✅ Import reverse
from skins.models import Skin
from skins.utils.fetch_and_crop_skin_image import fetch_and_crop_skin_image  # ✅ Correct
import re
from django.contrib import messages  # Import Django's messages framework


bonk_url_pattern = r"^https://bonkleagues\.io/s/([A-Za-z0-9]{7})$"
skin_name_pattern = r"^[A-Za-z0-9_ ]+$"

def upload_skin(request):
    if request.method == "POST":
        skin_name = request.POST.get("skin_name").strip()
        creator = request.POST.get("creator").strip()
        bonkleagues_link = request.POST.get("bonkleagues_link").strip()

        # Validation: Ensure all fields are filled
        if not skin_name or not creator or not bonkleagues_link:
            messages.error(request, "❌ All fields are required.")
            return render(request, "skins/upload.html", {
                "error": "All fields are required."
            })
        
         # Validate skin name format
        if not re.match(skin_name_pattern, skin_name):
            messages.error(request, "❌ Skin name can only con