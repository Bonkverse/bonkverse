import os
import requests
import cv2
import numpy as np
from io import BytesIO
from django.conf import settings
from playwright.sync_api import sync_playwright
from skins.models import Skin


def fetch_and_crop_skin_image(bonkleagues_link):
    """
    Fetches the Bonkleagues skin image URL, downloads, crops, and saves it.
    Returns the relative path of the cropped image.
    """
    try:
        # Get the next skin ID from the database
        next_skin_id = Skin.objects.count() + 1  # Get total skins and add 1

        # Start Playwright to extract skin image URL
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # Open the skin link
            page.goto(bonkleagues_link, wait_until="domcontentloaded")

            # Locate the Bonkleagues skin image
            image_element = page.locator("//img[@id='sharedimg']")
            skin_image_url = image_element.get_attribute("src") if image_element.count() > 0 else None
            browser.close()

        if not skin_image_url:
            print(f"⚠️ No skin image found at {bonkleagues_link}")
            return None

        # Download the skin image
        response = requests.get(skin_image_url, stream=True)
        if response.status_code != 200:
            print(f"❌ Failed to download image from {skin_image_url}")
            return None

        # Define image save paths
        os.makedirs(os.path.join(settings.MEDIA_ROOT, "cropped"), exist_ok=True)
        temp_path = os.path.join(settings.MEDIA_ROOT, "temp", f"skin_{next_skin_id}.png")
        cropped_filename = f"skinUrl{next_skin_id}.png"  # ✅ Use correct format
        cropped_path = os.path.join(settings.MEDIA_ROOT, "cropped", cropped_filename)

        # Save temporary image
        with open(temp_path, "wb") as f:
            f.write(response.content)

        # Crop the image
        if crop_skin_image(temp_path, cropped_path):
            return f"cropped/{cropped_filename}"  # ✅ Correctly formatted path for DB

        return None

    except Exception as e:
        print(f"❌ Error fetching or cropping skin: {e}")
        return None


def crop_skin_image(image_path, output_path):
    """
    Crops the circular portion of the skin and saves it.
    """
    img = cv2.imread(image_path)

    if img is None:
        print(f"❌ Error: Image not found at {image_path}")
        return False

    # Define cropping region (adjust if needed)
    x, y, width, height = 5, 5, 115, 110
    cropped = img[y:y + height, x:x + width]

    # Save the cropped image
    cv2.imwrite(output_path, cropped)
    print(f"✅ Cropped skin saved: {output_path}")
    return True
