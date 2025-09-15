import re
import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from skins.models import Skin
from urllib.parse import urlparse, parse_qs, unquote


class Command(BaseCommand):
    help = "Backfill the skin_code column for all skins by scraping Bonkleagues links"

    def handle(self, *args, **options):
        skins = Skin.objects.filter(skin_code__isnull=True)  # only backfill missing ones
        self.stdout.write(f"Found {skins.count()} skins missing skin_code")

        for skin in skins:
            try:
                # --- Fetch page ---
                resp = requests.get(skin.link, timeout=15)
                resp.raise_for_status()

                # --- Parse DOM ---
                soup = BeautifulSoup(resp.text, "html.parser")
                img = soup.find("img", id="sharedimg")
                if not img:
                    self.stdout.write(self.style.WARNING(f"No sharedimg found for {skin.link}"))
                    continue

                src = img.get("src", "")
                if "skinCode=" not in src:
                    self.stdout.write(self.style.WARNING(f"No skinCode param in src for {skin.link}"))
                    continue

                # --- Extract skinCode ---
                parsed_url = urlparse(src)
                query = parse_qs(parsed_url.query)
                skin_code_raw = query.get("skinCode", [None])[0]

                if skin_code_raw:
                    skin_code = unquote(skin_code_raw)  # decode %2F etc
                    skin.skin_code = skin_code
                    skin.save(update_fields=["skin_code"])
                    self.stdout.write(self.style.SUCCESS(f"Updated {skin.id} with skin_code"))
                else:
                    self.stdout.write(self.style.WARNING(f"Could not parse skinCode for {skin.link}"))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error processing {skin.link}: {e}"))
