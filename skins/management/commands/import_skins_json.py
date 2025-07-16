import os
import json
import logging
from django.core.management.base import BaseCommand
from skins.models import Skin
from skins.utils.fetch_skin_image_url import fetch_skin_image_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

SKIN_DIR = "/Users/papijorge/Desktop/Projects/BonkDownloads/MrGrass55kSkins/SkinOutputs"
SKIP_FILE = "Bonk Links Batch 100.json"

class Command(BaseCommand):
    help = "Imports all JSON skin files from a directory into the database, including image URLs."

    def handle(self, *args, **options):
        logging.info(f"🔍 Scanning directory: {SKIN_DIR}")

        files = sorted([
            f for f in os.listdir(SKIN_DIR)
            if f.endswith(".json") and f != SKIP_FILE
        ])

        if not files:
            logging.info("❌ No files found to import.")
            return

        for file_name in files:
            path = os.path.join(SKIN_DIR, file_name)
            logging.info(f"📥 Importing from: {file_name}")

            with open(path, "r", encoding="utf-8") as file:
                try:
                    data = json.load(file)
                except json.JSONDecodeError:
                    logging.warning(f"⚠️ Skipping invalid JSON file: {file_name}")
                    continue

            count = 0
            for row in data:
                name = row.get("name", "").strip()
                link = row.get("short_url", "").strip()
                creator = row.get("author", "").strip()

                if not link:
                    logging.warning(f"⚠️ Skipping missing link for: {name}")
                    continue

                image_url = fetch_skin_image_url(link)
                if not image_url:
                    logging.warning(f"⚠️ Could not fetch image for: {link}")
                    continue

                skin, created = Skin.objects.get_or_create(
                    link=link,
                    defaults={"name": name, "creator": creator, "image_url": image_url}
                )

                updated = False
                if not skin.creator and creator:
                    skin.creator = creator
                    updated = True
                if not skin.image_url and image_url:
                    skin.image_url = image_url
                    updated = True

                if updated:
                    skin.save()
                    logging.info(f"🔄 Updated: {name}")

                if created:
                    logging.info(f"✅ Added: {name}")
                    count += 1

            logging.info(f"🎉 {file_name} done: {count} new skins added.\n")
