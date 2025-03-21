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

s3 = boto3.client("s3")
AWS_BUCKET = settings.AWS_STORAGE_BUCKET_NAME
AWS_BASE_URL = "https://bonkverse-skins.s3.us-east-2.amazonaws.com/uploads/cropped"

def upload_skin(request):
    if request.method == "POST":
        skin_name = request.POST.get("skin_name").strip()
        creator = request.POST.get("creator").strip()
        bonkleagues_link = request.POST.get("bonkleagues_link").strip()

        if not skin_name or not creator or not bonkleagues_link:
            messages.error(request, "❌ All fields are required.")
            return render(request, "skins/upload.html", {"error": "All fields are required."})

        if not re.match(skin_name_pattern, skin_name):
            messages.error(request, "❌ Skin name can only contain letters, numbers, spaces, and underscores.")
            return render(request, "skins/upload.html", {"error": "Skin name can only contain letters, numbers, spaces, and underscores."})

        if not re.match(bonk_url_pattern, bonkleagues_link):
            messages.error(request, "❌ Invalid Bonkleagues link format.")
            return render(request, "skins/upload.html", {"error": "Invalid Bonkleagues Skin URL format."})

        if Skin.objects.filter(link=bonkleagues_link).exists():
            messages.error(request, "❌ This Bonkleagues link has already been submitted!")
            return redirect("upload_skin")

        if len(skin_name) > 1000 or len(creator) > 1000:
            messages.error(request, "❌ Invalid skin or creator name length. Must be less than 1000 characters.")
            return render(request, "skins/upload.html", {"error": "Skin name and creator must be under 1000 characters."})

        # Step 1: Save skin to DB to get ID
        skin = Skin.objects.create(
            name=skin_name,
            creator=creator,
            link=bonkleagues_link,
            image_url=""  # placeholder
        )

        # Step 2: Get skin image URL
        skin_image_url = fetch_skin_image_url(bonkleagues_link)
        if not skin_image_url:
            skin.delete()
            messages.error(request, "❌ Could not fetch image from Bonkleagues.")
            return render(request, "skins/upload.html", {"error": "Could not fetch image from Bonkleagues."})

        # Step 3: Download and crop image
        response = requests.get(skin_image_url)
        if response.status_code != 200:
            skin.delete()
            messages.error(request, "❌ Failed to download skin image.")
            return render(request, "skins/upload.html", {"error": "Failed to download skin image."})

        temp_path = f"/tmp/skin_{skin.id}.png"
        cropped_path = f"/tmp/skinUrl{skin.id}.png"

        with open(temp_path, "wb") as f:
            f.write(response.content)

        # Crop the image
        img = cv2.imread(temp_path)
        if img is None:
            skin.delete()
            messages.error(request, "❌ Failed to read downloaded image.")
            return render(request, "skins/upload.html", {"error": "Failed to read downloaded image."})

        x, y, w, h = 5, 5, 115, 110
        cropped = img[y:y+h, x:x+w]
        cv2.imwrite(cropped_path, cropped)

        # Upload to S3
        s3_key = f"uploads/cropped/skinUrl{skin.id}.png"
        try:
            s3.upload_file(cropped_path, AWS_BUCKET, s3_key)
            skin.image_url = f"{AWS_BASE_URL}/skinUrl{skin.id}.png"
            skin.save()
        except Exception as e:
            skin.delete()
            messages.error(request, f"❌ Failed to upload to AWS: {e}")
            return render(request, "skins/upload.html", {"error": "Failed to upload image to cloud."})

        # Clean up local temp files
        os.remove(temp_path)
        os.remove(cropped_path)

        messages.success(request, "✅ Skin uploaded successfully!")
        return redirect(reverse("search_skins") + f"?q={skin_name}")

    return render(request, "skins/upload.html")

def autocomplete_creator(request):
    query = request.GET.get("q", "").strip()
    if query:
        matching_creators = Skin.objects.filter(creator__icontains=query).values_list("creator", flat=True).distinct()[:10]
        return JsonResponse(list(matching_creators), safe=False)
    return JsonResponse([], safe=False)
