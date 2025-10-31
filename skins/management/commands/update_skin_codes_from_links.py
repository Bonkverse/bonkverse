import pandas as pd
import re
from django.core.management.base import BaseCommand
from django.db import transaction
from skins.models import Skin
from tqdm import tqdm


class Command(BaseCommand):
    help = "Updates skins_skin table with extracted skin codes from a CSV containing BonkLeagues links."

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            type=str,
            default="backfilled_skincodes.csv",
            help="Path to the CSV file containing BonkLeagues links with embedded skin codes.",
        )

    def handle(self, *args, **options):
        csv_path = options["csv"]
        self.stdout.write(self.style.NOTICE(f"📂 Loading {csv_path}..."))

        # Load CSV — automatically detect relevant columns
        df = pd.read_csv(csv_path)
        self.stdout.write(self.style.NOTICE(f"Loaded {len(df)} rows."))

        # Try to find the link column
        possible_cols = [c for c in df.columns if "link" in c.lower()]
        if not possible_cols:
            self.stderr.write("❌ Could not find a column containing 'link' in the CSV.")
            return

        link_col = possible_cols[0]
        self.stdout.write(self.style.NOTICE(f"🔗 Using column '{link_col}' for parsing."))

        # Regex pattern for skin codes starting with 'Cgc'
        skin_pattern = re.compile(r"(Cgc[\w%]+)")

        updated, skipped = 0, 0
        examples = []

        # Loop through CSV rows
        with transaction.atomic():
            for _, row in tqdm(df.iterrows(), total=len(df), desc="Updating skins"):
                link = str(row[link_col])
                match = skin_pattern.search(link)
                if not match:
                    skipped += 1
                    continue

                skin_code = match.group(1)
                skin = Skin.objects.filter(link=link).first()

                if skin:
                    skin.skin_code = skin_code
                    skin.save(update_fields=["skin_code"])
                    updated += 1
                    if len(examples) < 5:
                        examples.append((skin.id, skin.name, skin_code))
                else:
                    skipped += 1

        # --- Summary ---
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"✅ Update complete!"))
        self.stdout.write(self.style.SUCCESS(f"✨ Updated: {updated} skins"))
        self.stdout.write(self.style.WARNING(f"⏩ Skipped: {skipped} (no matching row or invalid link)"))

        if examples:
            self.stdout.write("\nExample updates:")
            for sid, name, code in examples:
                self.stdout.write(f"  • ID {sid} | {name} → {code}")
