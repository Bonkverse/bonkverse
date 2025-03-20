import csv
import logging
from django.core.management.base import BaseCommand
from skins.models import Skin

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

class Command(BaseCommand):
    help = "Imports skins from a CSV file into the database."

    def add_arguments(self, parser):
        parser.add_argument("csv_file", type=str, help="Path to the CSV file")

    def handle(self, *args, **options):
        csv_file = options["csv_file"]
        logging.info(f"Importing skins from {csv_file}...")

        with open(csv_file, newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            for row in reader:
                name = row["Skin Name"]
                link = row["Link"]
                creator = row.get("Creator (if known)", "").strip()

                # Check if skin exists
                skin, created = Skin.objects.get_or_create(link=link, defaults={"name": name, "creator": creator})

                # Update creator if it's missing or an empty string
                if not skin.creator or skin.creator.strip() == "" and creator:
                    skin.creator = creator
                    skin.save()
                    logging.info(f"🔄 Updated creator for: {name}")

                if created:
                    logging.info(f"✅ Added: {name}")

        logging.info("Import complete.")
