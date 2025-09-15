import os
import re
import requests
from django.core.management.base import BaseCommand
from django.conf import settings
from skins.models import Skin

class Command(BaseCommand):
    help = "Backfill skin_code and regenerate SVGs for skins missing them"

    def fetch_skin_code(self, bl_link: str) -> str | None:
        try:
            r = requests.get(bl_link, timeout=10)
            r.raise_for_status()
            html = r.text
            match = re.search(r'avatar\.svg\?skinCode=([A-Za-z0-9_\-%=]+)', html)
            return match.group(1) if match else None
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Failed {bl_link}: {e}"))
            return None

    def save_svg(self, skin_id: int, skin_code: str) -> str:
        svg_url = f"https://bonkleagues.io/api/avatar.svg?skinCode={skin_code}"
        out_dir = os.path.join(settings.MEDIA_ROOT, "skins")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{skin_id}.svg")

        try:
            r = requests.get(svg_url, timeout=10)
            r.raise_for_status()
            with open(out_path, "wb") as f:
                f.write(r.content)
            return f"/media/skins/{skin_id}.svg"
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Failed saving SVG {skin_id}: {e}"))
            return None

    def handle(self, *args, **options):
        skins = Skin.objects.filter(skin_code__isnull=True) | Skin.objects.filter(skin_code="")
        total = skins.count()
        self.stdout.write(self.style.WARNING(f"🔄 Processing {total} skins..."))

        for skin in skins.iterator():
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
                self.stdout.write(self.style.SUCCESS(f"✅ {skin.id} updated with code {code}"))
