import pandas as pd
from urllib.parse import urlparse, parse_qs
from django.core.management.base import BaseCommand
from django.db import transaction, connection
from django.utils.dateparse import parse_datetime
from skins.models import Skin
from tqdm import tqdm
import uuid


class Command(BaseCommand):
    help = "Restores Skin objects from CSV while preserving original IDs (for media sync)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            type=str,
            default="skins_skin_backup.csv",
            help="Path to CSV backup file",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Run without committing to the database",
        )

    def handle(self, *args, **options):
        csv_path = options["csv"]
        dry_run = options["dry_run"]

        self.stdout.write(self.style.NOTICE(f"📂 Loading CSV: {csv_path}"))

        df = pd.read_csv(csv_path, dtype=str, low_memory=False)

        def extract_skin_code(url):
            if not isinstance(url, str):
                return None
            query = urlparse(url).query
            return parse_qs(query).get("skinCode", [None])[0]

        created = 0
        missing_code = 0

        with transaction.atomic():
            for _, row in tqdm(df.iterrows(), total=len(df), desc="Restoring skins"):
                skin_id = int(row["id"])
                skin_code = extract_skin_code(row.get("image_url"))

                if not skin_code:
                    missing_code += 1
                    continue

                skin_uuid = uuid.uuid4()

                skin = Skin(
                    id=skin_id,  # 🔑 CRITICAL
                    uuid=skin_uuid,
                    name=row.get("name") or "UnnamedSkin",
                    creator=row.get("creator") or "UnknownSkinCreator",
                    skin_code=skin_code,
                    image_url=f"https://bonkverse.io/media/skins/{skin_id}.png",  # 🔑 synced to filesystem
                    link=row.get("link"),
                )

                created_at = parse_datetime(row.get("created_at") or "")
                if created_at:
                    skin.created_at = created_at

                if not dry_run:
                    skin.save(force_insert=True)

                created += 1

            if dry_run:
                self.stdout.write(self.style.WARNING("🧪 DRY RUN — rolling back"))
                raise Exception("Dry run complete")

        # 🔧 Reset Postgres sequence so future inserts don’t collide
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT setval(
                    pg_get_serial_sequence('skins_skin', 'id'),
                    (SELECT MAX(id) FROM skins_skin)
                );
                """
            )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("✅ Restore complete"))
        self.stdout.write(self.style.SUCCESS(f"🆕 Restored skins: {created}"))
        self.stdout.write(self.style.WARNING(f"⚠️ Skipped (missing skinCode): {missing_code}"))
