# skins/management/commands/backfill_skin_codes.py
import re
import requests
from django.core.management.base import BaseCommand
from skins.models import Skin
from urllib.parse import urlparse, parse_qs, unquote

# Regex to capture the src attribute from <img id="sharedimg">
IMG_RE = re.compile(
    r'<img[^>]+id=["\']sharedimg["\'][^>]+src=["\']([^"\']+)["\']',
    re.IGNORECASE,
)

def extract_skin_code(link_or_img_url: str) -> str | None:
    """
    Extract the skinCode query parameter from a Bonkleagues shared image URL.
    Example: https://sebweb.co.uk/blbackend/prevgen.php?...&skinCode=XYZ
    """
    if not link_or_img_url or "skinCode=" not in link_or_img_url:
        return None
    parsed_url = urlparse(link_or_img_url)
    query = parse_qs(parsed_url.query)
    raw_code = query.get("skinCode", [None])[0]
    if raw_code:
        return unquote(raw_code)  # decode %2F, etc.
    return None


class Command(BaseCommand):
    help = "Backfill the skin_code column for all skins by scraping Bonkleagues links"

    def handle(self, *args, **options):
        skins = Skin.objects.filter(skin_code__isnull=True)
        self.stdout.write(f"Found {skins.count()} skins missing skin_code")

        for skin in skins.iterator(chunk_size=100):
            try:
                # --- Fetch the Bonkleagues page ---
                resp = requests.get(skin.link, timeout=15)
                resp.raise_for_status()
                html = resp.text

                # --- Extract <img id="sharedimg"> ---
                match = IMG_RE.search(html)
                if not match:
                    self.stdout.write(self.style.WARNING(f"No sharedimg found for {skin.link}"))
                    continue

                img_src = match.group(1)

                # --- Extract skinCode directly ---
                code = extract_skin_code(img_src)
                if code:
                    skin.skin_code = code
                    skin.save(update_fields=["skin_code"])
                    self.stdout.write(self.style.SUCCESS(f"Updated skin {skin.id}"))
                else:
                    self.stdout.write(self.style.WARNING(f"Could not extract skin_code for {skin.link}"))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error processing {skin.link}: {e}"))
