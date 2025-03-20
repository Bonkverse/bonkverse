import os
import logging
from django.core.management.base import BaseCommand
from skins.models import Skin

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

CROPPED_IMAGE_DIR = "cropped"  # Directory where cropped images are stored

class Command(BaseCommand):
    help = "Updates the skin_url field in the database with cropped images"

    def handle(self, *args, **kwargs):
        logging.info("🔄 Starting database update with cropped images...")

        # Fetch all skins
        skins = list(Skin.objects.all())
        total_skins = len(skins)

        if total_skins == 0:
            logging.info("✅ No skins found in the database. Nothing to update.")
            return

        updated_count = 0

        for index, skin in enumerate(skins, start=1):
            # Construct the expected image filename (e.g., skinUrl1.png, skinUrl2.png, ...)
            image_filename = f"skinUrl{index}.png"
            image_path = os.path.join(CROPPED_IMAGE_DIR, image_filename)

            # Check if the image exists
            if os.path.exists(image_path):
                # Update the skin_url field with the new image path
                skin.image_url = image_path
                skin.save()
                updated_count += 1
                logging.info(f"✅ Updated {skin.name} with {image_filename}")
            else:
                logging.warning(f"⚠️ Image not found for {skin.name}. Keeping previous skin_url.")

        logging.info(f"✅ Done! Updated {updated_count}/{total_skins} skins with new images.")
