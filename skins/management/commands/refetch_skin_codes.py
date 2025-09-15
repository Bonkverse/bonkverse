import os
import re
import time
import random
import requests
from django.core.management.base import BaseCommand
from django.conf import settings
from skins.models import Skin


class Command(BaseCommand):
    help = "Backfill skin_code and regenerate SVGs for skins missing them"

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit", type=int, default=None,
            help="Max number of skins to process (default: all)"
        )
        parser.add_argument(
            "--offset", type=int, default=0,
            help="Skip this many skins before starting"
        )

    def fetch_with_retry(self, url, retries=3, backoff=5):
        """Fetch a page with retry and exponential backoff for 429s and errors"""
        for attempt in range(retries):
            try:
                r = requests.get(url, timeout=15)
                if r.status_code == 429:  # Too many requests
                    sleep_time = backoff * (attempt + 1)
                    self.stdout.write(self.style.WARNING(
                        f"⏳ Rate limited on {url}, sleeping {sleep_time}s..."
                    ))
                    time.sleep(sleep_time)
                    continue
                r.raise_for_status()
                return r
            except requests.exceptions.RequestException as e:
                sleep_time = backoff * (attempt + 1)
                self.stdout.write(self.style.WARNING(
                    f"⚠️ Error fetching {url}: {e}. Retry in {sleep_time}s..."
                ))
                time.sleep(sleep_time)
        return None

    def fetch_skin_code(self, bl_link: str) -> str | None:
        r = self.fetch_with_retry(bl_link)
        if not r:
            self.stdout.write(self.style.ERROR(f"❌ Failed {bl_link} after retries"))
            return None
        match = re.search(r'avatar\.svg\?skinCode=([A-Za-z0-9_\-%=]+)', r.text)
        return match.group(1) if match else None

    def save_svg(self, skin_id: int, skin_code: str) -> str | None:
        svg_url = f"https://bonkleagues.io/api/avatar.svg?skinCode={skin_code}"
        out_dir = os.path.join(settings.MEDIA_ROOT, "skins")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{skin_id}.svg")

        r = self.fetch_with_retry(svg_url)
        if not r:
            self.stdout.write(self.style.ERROR(f"❌ Failed saving SVG {skin_id}"))
            return None

        try:
            with open(out_path, "wb") as f:
                f.write(r.content)
            return f"/media/skins/{skin_id}.svg"
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ File save error for {skin_id}: {e}"))
            return None

    def handle(self, *args, **options):
        limit = options.get("limit")
        offset = options.get("offset", 0)

        skins = Skin.objects.filter(skin_code__isnull=True) | Skin.objects.filter(skin_code="")
        if offset:
            skins = skins[offset:]
        if limit:
            skins = skins[:limit]

        total = skins.count() if not isinstance(skins, list) else len(skins)
        self.stdout.write(self.style.WARNING(f"🔄 Processing {total} skins (offset={offset}, limit={limit})..."))

        for idx, skin in enumerate(skins.iterator() if not isinstance(skins, list) else skins, start=1):
            if not skin.link:
                continue

            code = self.fetch_skin_code(skin.link)
            if not code:
                continue

            svg_path = self.save_svg(skin.id, code)
            if svg_path:
                skin.skin_code = code
                skin.image_url = svg_path
                skin.save(update_fields=["skin_code", "image_url"])
                self.stdout.write(self.style.SUCCESS(f"✅ {idx}/{total}: {skin.id} updated with code {code}"))

            # Random sleep to ease load on Bonkleagues
            time.sleep(random.uniform(0.5, 1.5))
