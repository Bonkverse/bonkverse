# from django.shortcuts import render, redirect
# from django.http import JsonResponse
# from django.db.models import Q
# from django.core.paginator import Paginator
# from django.conf import settings
# from django.urls import reverse  # ✅ Import reverse
# from skins.models import Skin
# from skins.utils.fetch_and_crop_skin_image import fetch_and_crop_skin_image  # ✅ Correct
# import re
# from django.contrib import messages  # Import Django's messages framework


# bonk_url_pattern = r"^https://bonkleagues\.io/s/([A-Za-z0-9]{7})$"
# skin_name_pattern = r"^[A-Za-z0-9_ ]+$"

# def upload_skin(request):
#     if request.method == "POST":
#         skin_name = request.POST.get("skin_name").strip()
#         creator = request.POST.get("creator").strip()
#         bonkleagues_link = request.POST.get("bonkleagues_link").strip()

#         # Validation: Ensure all fields are filled
#         if not skin_name or not creator or not bonkleagues_link:
#             messages.error(request, "❌ All fields are required.")
#             return render(request, "skins/upload.html", {
#                 "error": "All fields are required."
#             })
        
#          # Validate skin name format
#         if not re.match(skin_name_pattern, skin_name):
#             messages.error(request, "❌ Skin name can only contain letters, numbers, spaces, and underscores.")
#             return render(request, "skins/upload.html", {"error": "Skin name can only contain letters, numbers, spaces, and underscores."})

#         # Validation: Check Bonkleagues link format
#         if not re.match(bonk_url_pattern, bonkleagues_link):
#             messages.error(request, "❌ Invalid Bonkleagues link format.")
#             return render(request, "skins/upload.html", {
#                 "error": "Invalid Bonkleagues Skin URL format."
#             })
        
#         # ✅ Check if Bonkleagues link already exists
#         if Skin.objects.filter(link=bonkleagues_link).exists():
#             messages.error(request, "❌ This Bonkleagues link has already been submitted!")
#             return redirect("upload_skin")

#         # Validation: Check max length constraints
#         if len(skin_name) > 1000 or len(creator) > 1000:
#             messages.error(request, "❌ Invalid skin or creator name length. Must be less than 1000 characters.")
#             return render(request, "skins/upload.html", {
#                 "error": "Skin name and creator must be under 1000 characters."
#             })

#         messages.info(request, "⏳ Uploading and processing your skin... Please wait!")
#         # Call function to fetch image from Bonkleagues and crop it
#         cropped_image_url = fetch_and_crop_skin_image(bonkleagues_link)

#         if not cropped_image_url:
#             messages.error(request, "❌ Could not retrieve the skin image. Please check your Bonkleagues link.")
#             return render(request, "skins/upload.html", {
#                 "error": "Could not retrieve the skin image. Please check your Bonkleagues link."
#             })

#         # Save new skin to the database
#         Skin.objects.create(
#             name=skin_name,
#             creator=creator,
#             link=bonkleagues_link,
#             image_url=cropped_image_url
#         )

#         # Set success message
#         messages.success(request, "✅ Skin uploaded successfully!")

#         return redirect(reverse("search_skins") + f"?q={skin_name}")

#     return render(request, "skins/upload.html")

# def autocomplete_creator(request):
#     query = request.GET.get("q", "").strip()
#     if query:
#         matching_creators = Skin.objects.filter(creator__icontains=query).values_list("creator",