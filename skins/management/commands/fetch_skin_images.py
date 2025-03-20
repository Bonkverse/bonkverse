import logging
import os
import time
import json
import requests
import cv2
import numpy as np
from django.core.management.base import BaseCommand
from playwright.sync_api import sync_playwright
from skins.models import Skin

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

DEFAULT_IMAGE_PATH = "default_skin_url.png"  # Default fallback image

class Command(BaseCommand):
    help = "Fetches, crops, and updates Bonkleagues skin images."

    def handle(self, *args, **kwargs):
        logging.info("Starting Playwright...")

        skins = list(Skin.objects.all())  # Fetch skins from the database
        total_skins = len(skins)
        logging.info(f"Total skins to process: {total_skins}")

        if total_skins == 0:
            logging.info("✅ All skins already have images! Nothing to do.")
            return

        # Ensure directories exist
        os.makedirs("temp", exist_ok=True)
        os.makedirs("cropped", exist_ok=True)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            for index, skin in enumerate(skins, start=1):
                logging.info(f"Processing ({index}/{total_skins}): {skin.name} ({skin.link})")

                try:
                    # Open the skin page
                    page.goto(skin.link, wait_until="domcontentloaded")
                    logging.info(f"📌 Opened {skin.link}")

                    # Locate the `sharedimg` element (Bonkleagues skin image URL)
                    image_element = page.locator("//img[@id='sharedimg']")
                    image_url = image_element.get_attribute("src") if image_element.count() > 0 else None

                    if not image_url:
                        logging.warning(f"⚠️ No image found for {skin.name}. Using default skin image.")
                        final_image_path = DEFAULT_IMAGE_PATH
                    else:
                        logging.info(f"✅ Found Bonkleagues image URL: {image_url}")
                        final_image_path = self.process_skin_image(image_url, index)

                    # Update the database with the new image URL
                    skin.image_url = final_image_path
                    skin.save()

                    logging.info(f"🎉 Saved skin image for {skin.name}: {final_image_path}")

                except Exception as e:
                    logging.error(f"❌ Error processing {skin.name}: {e}")
                    continue

            browser.close()
            logging.info("✅ Done processing skin images.")

    def process_skin_image(self, image_url, index):
        """Downloads, crops, and saves the Bonkleagues skin image."""
        try:
            # Download the image
            response = requests.get(image_url, stream=True)
            if response.status_code != 200:
                logging.warning(f"⚠️ Failed to download image from {image_url}, using default skin image.")
                return DEFAULT_IMAGE_PATH

            # Define paths
            input_path = f"temp/skin_{index}.png"
            output_path = f"cropped/skinUrl{index}.png"

            # Save original image
            with open(input_path, "wb") as f:
                f.write(response.content)

            # Crop and save the image
            if self.crop_skin_image(input_path, output_path):
                return output_path
            return DEFAULT_IMAGE_PATH

        except Exception as e:
            logging.error(f"❌ Error processing image {image_url}: {e}")
            return DEFAULT_IMAGE_PATH

    def crop_skin_image(self, image_path, output_path):
        """Crop the circular portion of the skin from a fixed region."""
        img = cv2.imread(image_path)

        if img is None:
            logging.error("❌ Error: Image not found! Using default skin image.")
            return False

        # Cropping coordinates for the circular skin area
        x, y, width, height = 5, 5, 115, 110  # Adjust as needed
        cropped = img[y:y + height, x:x + width]

        # Save cropped image
        cv2.imwrite(output_path, cropped)
        logging.info(f"✅ Cropped circular skin saved: {output_path}")
        return True
