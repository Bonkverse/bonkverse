import os
import requests
from django.core.management.base import BaseCommand
from django.conf import settings
from skins.models import Skin

IMAGE_DIR = os.path.join(settings.MEDIA_ROOT, "skins")

class Command(BaseCommand):
    help = "Download SVGs for all skins"

    def handle(self, *args, **options):
        os.makedirs(IMAGE_DIR, exist_ok=True)

        skins = Skin.objects.all()
        self.stdout.write(f"Found {skins.count()} skins to fetch...")

        for skin in skins:
            if not skin.image_url:
                self.stdout.write(self.style.WARNING(f"Skipping {skin.id}: no image_url"))
                continue

            svg_path = os.path.join(IMAGE_DIR, f"{skin.id}.svg")
            if os.path.exists(svg_path):
                self.stdout.write(self.style.WARNING(f"SVG already exists for {skin.id}, skipping"))
                continue

            try:
                resp = requests.get(skin.image_url, timeout=10)
                resp.raise_for_status()
                with open(svg_path, "wb") as f:
                    f.write(resp.content)
                self.stdout.write(self.style.SUCCESS(f"Saved SVG for {skin.id}"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Failed {skin.id}: {e}"))
