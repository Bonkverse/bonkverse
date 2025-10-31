import pandas as pd
from urllib.parse import urlparse, parse_qs
from django.core.management.base import BaseCommand
from django.db import transaction
from skins.models import Skin

# Optional: tqdm for progress bar
from tqdm import tqdm


class Command(BaseCommand):
    help = "Backfills missing skin_code values from a CSV file containing image URLs with ?skinCode= params."

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            type=str,
            default="skins_skin_backup.csv",
            help="Path to the CSV file containing backup data (default: skins_skin_backup.csv)",
        )

    def handle(self, *args, **options):
        csv_path = options["csv"]
        self.stdout.write(self.style.NOTICE(f"📂 Loading backup CSV from {csv_path}..."))

        # --- Load CSV efficiently ---
        df = pd.read_csv(
            csv_path,
            usecols=["id", "image_url"],  # only what we need
            dtype={"id": "int64", "image_url": "string"},
            low_memory=False,
        )

        # --- Extract skinCode from image_url ---
        def extract_skin_code(url):
            if not isinstance(url, str):
                return None
            query = urlparse(url).query
            if not query:
                return None
            return parse_qs(query).get("skinCode", [None])[0]

        df["skin_code"] = df["image_url"].apply(extract_skin_code)

        updated, skipped, missing = 0, 0, 0
        updated_examples = []

        self.stdout.write(self.style.NOTICE(f"🔄 Starting database update for {len(df)} skins..."))

        # --- Atomic transaction for safety ---
        with transaction.atomic():
            for _, row in tqdm(df.iterrows(), total=len(df), desc="Backfilling"):
                skin_code = row.get("skin_code")
                if not skin_code:
                    missing += 1
                    continue

                skin = Skin.objects.filter(id=row["id"]).first()
                if not skin:
                    skipped += 1
                    continue

                if not skin.skin_code:
                    skin.skin_code = skin_code
                    skin.save(update_fields=["skin_code"])
                    updated += 1
                    if len(updated_examples) < 5:
                        updated_examples.append((skin.id, skin.name, skin.skin_code))
                else:
                    skipped += 1

        # --- Summary ---
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("✅ Backfill complete!"))
        self.stdout.write(self.style.SUCCESS(f"✨ Updated: {updated} skins"))
        self.stdout.write(self.style.WARNING(f"⏩ Skipped: {skipped} (already filled or not found)"))
        self.stdout.write(self.style.ERROR(f"❌ Missing: {missing} (no skinCode in CSV)"))

        # --- Example output ---
        if updated_examples:
            self.stdout.write("\nExample updates:")
            for sid, name, code in updated_examples:
                self.stdout.write(f"  • ID {sid} | {name} → {code}")
